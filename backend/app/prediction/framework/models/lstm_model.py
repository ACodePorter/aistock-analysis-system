"""
LSTM 可插拔模型（基于 PyTorch）

依赖：torch（可选）
若未安装 PyTorch，导入时会抛出 ImportError 并在模型注册中心跳过。

特性：
- 双层 LSTM + Dropout + 全连接输出
- 支持 classification（CrossEntropy）和 regression（MSE）
- 逐 epoch 记录 train/val loss
- 自动序列化输入（2D → 3D sliding window）
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np

from .base_model import BaseModel, IterationLog, TrainResult

logger = logging.getLogger(__name__)

# 延迟检测 PyTorch 可用性
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


# ---------------------------------------------------------------------------
# PyTorch 模型定义
# ---------------------------------------------------------------------------

if TORCH_AVAILABLE:

    class _LSTMNet(nn.Module):
        def __init__(
            self,
            input_dim: int,
            hidden_dim: int = 64,
            num_layers: int = 2,
            dropout: float = 0.2,
            output_dim: int = 1,
        ):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=input_dim,
                hidden_size=hidden_dim,
                num_layers=num_layers,
                dropout=dropout if num_layers > 1 else 0.0,
                batch_first=True,
            )
            self.dropout = nn.Dropout(dropout)
            self.fc = nn.Linear(hidden_dim, output_dim)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (batch, seq_len, features)
            lstm_out, _ = self.lstm(x)
            last_hidden = lstm_out[:, -1, :]   # 取最后一个时间步
            out = self.dropout(last_hidden)
            return self.fc(out)


# ---------------------------------------------------------------------------
# LSTM 模型封装
# ---------------------------------------------------------------------------

class LSTMModel(BaseModel):
    """LSTM 模型

    需要 PyTorch >= 2.0。如未安装：
        pip install torch --index-url https://download.pytorch.org/whl/cpu
    """

    def __init__(self, task_type: str = "regression", params: Optional[Dict] = None):
        if not TORCH_AVAILABLE:
            raise ImportError(
                "PyTorch is required for LSTM model. "
                "Install: pip install torch --index-url https://download.pytorch.org/whl/cpu"
            )
        super().__init__(task_type=task_type, params=params)
        self._net: Optional[nn.Module] = None
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._feature_names: List[str] = []
        self._mean: Optional[np.ndarray] = None
        self._std: Optional[np.ndarray] = None

    @property
    def name(self) -> str:
        return "lstm"

    def get_default_params(self) -> Dict[str, Any]:
        return {
            "seq_len": 20,
            "hidden_dim": 64,
            "num_layers": 2,
            "dropout": 0.2,
            "epochs": 80,
            "batch_size": 32,
            "lr": 1e-3,
            "weight_decay": 1e-5,
            "patience": 15,
        }

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
    ) -> TrainResult:
        p = self._merge_params()
        self._feature_names = feature_names or []
        seq_len = p["seq_len"]

        # 标准化
        self._mean = X_train.mean(axis=0)
        self._std = X_train.std(axis=0) + 1e-8
        X_train_n = (X_train - self._mean) / self._std
        X_val_n = (X_val - self._mean) / self._std if X_val is not None else None

        # 2D → 3D 序列
        X_tr_seq, y_tr_seq = self._to_sequences(X_train_n, y_train, seq_len)
        if len(X_tr_seq) < 10:
            raise ValueError(f"序列化后训练样本不足: {len(X_tr_seq)}")

        X_va_seq, y_va_seq = None, None
        if X_val_n is not None:
            X_va_seq, y_va_seq = self._to_sequences(X_val_n, y_val, seq_len)

        # 构建网络
        input_dim = X_tr_seq.shape[2]
        output_dim = 2 if self.task_type == "classification" else 1
        self._net = _LSTMNet(
            input_dim=input_dim,
            hidden_dim=p["hidden_dim"],
            num_layers=p["num_layers"],
            dropout=p["dropout"],
            output_dim=output_dim,
        ).to(self._device)

        # 训练设置
        if self.task_type == "classification":
            criterion = nn.CrossEntropyLoss()
        else:
            criterion = nn.MSELoss()

        optimizer = torch.optim.Adam(
            self._net.parameters(), lr=p["lr"], weight_decay=p["weight_decay"]
        )
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=5
        )

        train_loader = self._make_loader(X_tr_seq, y_tr_seq, p["batch_size"], shuffle=True)
        val_loader = (
            self._make_loader(X_va_seq, y_va_seq, p["batch_size"], shuffle=False)
            if X_va_seq is not None else None
        )

        # 训练循环
        iteration_logs: List[IterationLog] = []
        best_val_loss = float("inf")
        best_state = None
        patience_counter = 0

        for epoch in range(p["epochs"]):
            train_loss = self._train_epoch(train_loader, criterion, optimizer)
            val_loss = (
                self._eval_epoch(val_loader, criterion) if val_loader else None
            )
            scheduler.step(val_loss if val_loss is not None else train_loss)

            iteration_logs.append(IterationLog(
                iteration=epoch,
                train_loss=train_loss,
                val_loss=val_loss,
            ))

            if val_loss is not None and val_loss < best_val_loss:
                best_val_loss = val_loss
                best_state = {k: v.cpu().clone() for k, v in self._net.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= p["patience"]:
                    logger.info("Early stopping at epoch %d", epoch)
                    break

        # 恢复最优权重
        if best_state is not None:
            self._net.load_state_dict(best_state)

        self._is_fitted = True
        best_epoch = min(
            (l for l in iteration_logs if l.val_loss is not None),
            key=lambda l: l.val_loss,
            default=iteration_logs[-1],
        ).iteration if iteration_logs else 0

        return TrainResult(
            model_name=self.name,
            task_type=self.task_type,
            iteration_logs=iteration_logs,
            best_iteration=best_epoch,
            best_val_loss=best_val_loss,
            train_samples=len(X_tr_seq),
            val_samples=len(X_va_seq) if X_va_seq is not None else 0,
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._is_fitted or self._net is None:
            raise RuntimeError("模型未训练")
        p = self._merge_params()
        X_n = (X - self._mean) / self._std
        X_seq, _ = self._to_sequences(X_n, np.zeros(len(X_n)), p["seq_len"])

        self._net.eval()
        with torch.no_grad():
            t = torch.FloatTensor(X_seq).to(self._device)
            out = self._net(t).cpu().numpy()

        if self.task_type == "classification":
            return np.argmax(out, axis=1)
        return out.flatten()

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self._is_fitted or self._net is None:
            raise RuntimeError("模型未训练")
        p = self._merge_params()
        X_n = (X - self._mean) / self._std
        X_seq, _ = self._to_sequences(X_n, np.zeros(len(X_n)), p["seq_len"])

        self._net.eval()
        with torch.no_grad():
            t = torch.FloatTensor(X_seq).to(self._device)
            out = self._net(t)
            if self.task_type == "classification":
                proba = torch.softmax(out, dim=1).cpu().numpy()
            else:
                proba = out.cpu().numpy()
        return proba

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        artifact = {
            "state_dict": self._net.state_dict() if self._net else None,
            "task_type": self.task_type,
            "params": self.params,
            "feature_names": self._feature_names,
            "mean": self._mean,
            "std": self._std,
            "net_config": {
                "input_dim": self._net.lstm.input_size if self._net else 0,
                "hidden_dim": self._net.lstm.hidden_size if self._net else 64,
                "num_layers": self._net.lstm.num_layers if self._net else 2,
            },
        }
        torch.save(artifact, path)
        logger.info("LSTM model saved: %s", path)
        return path

    def load(self, path: str) -> None:
        artifact = torch.load(path, map_location=self._device, weights_only=False)
        self.task_type = artifact.get("task_type", self.task_type)
        self.params = artifact.get("params", {})
        self._feature_names = artifact.get("feature_names", [])
        self._mean = artifact.get("mean")
        self._std = artifact.get("std")

        cfg = artifact.get("net_config", {})
        p = self._merge_params()
        output_dim = 2 if self.task_type == "classification" else 1
        self._net = _LSTMNet(
            input_dim=cfg.get("input_dim", 1),
            hidden_dim=cfg.get("hidden_dim", p["hidden_dim"]),
            num_layers=cfg.get("num_layers", p["num_layers"]),
            output_dim=output_dim,
        ).to(self._device)
        self._net.load_state_dict(artifact["state_dict"])
        self._is_fitted = True
        logger.info("LSTM model loaded: %s", path)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _to_sequences(
        X: np.ndarray, y: np.ndarray, seq_len: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        seqs, targets = [], []
        for i in range(seq_len, len(X)):
            seqs.append(X[i - seq_len : i])
            targets.append(y[i])
        if not seqs:
            return np.empty((0, seq_len, X.shape[1])), np.empty(0)
        return np.array(seqs), np.array(targets)

    def _make_loader(
        self, X: np.ndarray, y: np.ndarray, batch_size: int, shuffle: bool,
    ) -> DataLoader:
        t_x = torch.FloatTensor(X).to(self._device)
        if self.task_type == "classification":
            t_y = torch.LongTensor(y.astype(int)).to(self._device)
        else:
            t_y = torch.FloatTensor(y).to(self._device)
        ds = TensorDataset(t_x, t_y)
        return DataLoader(ds, batch_size=batch_size, shuffle=shuffle)

    def _train_epoch(self, loader: DataLoader, criterion, optimizer) -> float:
        self._net.train()
        total_loss, n = 0.0, 0
        for x_batch, y_batch in loader:
            optimizer.zero_grad()
            out = self._net(x_batch)
            if self.task_type == "regression":
                out = out.squeeze(-1)
            loss = criterion(out, y_batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self._net.parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item() * len(y_batch)
            n += len(y_batch)
        return total_loss / max(n, 1)

    def _eval_epoch(self, loader: DataLoader, criterion) -> float:
        self._net.eval()
        total_loss, n = 0.0, 0
        with torch.no_grad():
            for x_batch, y_batch in loader:
                out = self._net(x_batch)
                if self.task_type == "regression":
                    out = out.squeeze(-1)
                loss = criterion(out, y_batch)
                total_loss += loss.item() * len(y_batch)
                n += len(y_batch)
        return total_loss / max(n, 1)
