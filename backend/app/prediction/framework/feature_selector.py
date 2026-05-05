"""
特征筛选模块

三重筛选策略：
1. 相关性分析 — Pearson + Spearman，去除冗余共线特征
2. 模型重要性 — LightGBM feature importance（快速、稳定）
3. SHAP 分析 — 如可用，提供更精确的特征归因（可选依赖）

自动筛选流程：
  fit() → 计算全部指标 → 综合排名 → 选取 Top-N

输出：
  - 特征重要性排名 DataFrame
  - 相关性矩阵
  - 冗余特征列表
  - 筛选后的特征集
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False


# ===================================================================
# 数据容器
# ===================================================================

@dataclass
class SelectionResult:
    """特征筛选结果"""
    selected_features: List[str]
    importance_ranking: pd.DataFrame         # columns: feature, score, rank, category
    correlation_matrix: Optional[pd.DataFrame] = None
    redundant_features: List[str] = field(default_factory=list)
    shap_values: Optional[np.ndarray] = None
    method_scores: Dict[str, Dict[str, float]] = field(default_factory=dict)


# ===================================================================
# 相关性分析
# ===================================================================

def correlation_analysis(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: List[str],
    method: str = "spearman",
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """计算特征与目标的相关性 + 特征间相关性矩阵

    Returns:
        corr_matrix: 特征间相关性矩阵
        target_corr: {feature_name: correlation_with_target}
    """
    df = pd.DataFrame(X, columns=feature_names)
    df["_target_"] = y

    if method == "spearman":
        corr_full = df.rank().corr()
    else:
        corr_full = df.corr()

    target_corr = {}
    for col in feature_names:
        c = corr_full.loc[col, "_target_"] if col in corr_full.index else 0.0
        target_corr[col] = float(c) if np.isfinite(c) else 0.0

    corr_matrix = corr_full.loc[feature_names, feature_names]
    return corr_matrix, target_corr


def find_redundant_features(
    corr_matrix: pd.DataFrame,
    threshold: float = 0.95,
    target_corr: Optional[Dict[str, float]] = None,
) -> List[str]:
    """找出高度共线的冗余特征（保留与目标相关性更高的那个）"""
    cols = list(corr_matrix.columns)
    to_drop = set()

    for i in range(len(cols)):
        if cols[i] in to_drop:
            continue
        for j in range(i + 1, len(cols)):
            if cols[j] in to_drop:
                continue
            if abs(corr_matrix.iloc[i, j]) >= threshold:
                # 保留与目标相关性更大的那个
                if target_corr:
                    if abs(target_corr.get(cols[i], 0)) >= abs(target_corr.get(cols[j], 0)):
                        to_drop.add(cols[j])
                    else:
                        to_drop.add(cols[i])
                else:
                    to_drop.add(cols[j])

    return sorted(to_drop)


# ===================================================================
# 模型重要性
# ===================================================================

def tree_importance(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: List[str],
    task_type: str = "regression",
    n_estimators: int = 200,
) -> Dict[str, float]:
    """用 LightGBM 快速计算特征重要性（gain-based）"""
    try:
        import lightgbm as lgb
    except ImportError:
        return _sklearn_importance(X, y, feature_names, task_type)

    params = {
        "n_estimators": n_estimators,
        "learning_rate": 0.1,
        "max_depth": 5,
        "num_leaves": 31,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "verbose": -1,
        "n_jobs": -1,
    }

    if task_type == "classification":
        model = lgb.LGBMClassifier(**params)
    else:
        model = lgb.LGBMRegressor(**params)

    try:
        model.fit(X, y)
        imp = model.feature_importances_
        total = imp.sum() or 1.0
        return {name: float(v / total) for name, v in zip(feature_names, imp)}
    except Exception as e:
        logger.warning("LightGBM importance failed: %s", e)
        return {name: 0.0 for name in feature_names}


def _sklearn_importance(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: List[str],
    task_type: str,
) -> Dict[str, float]:
    """sklearn GradientBoosting 后备"""
    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor

    if task_type == "classification":
        model = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42)
    else:
        model = GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=42)

    try:
        model.fit(X, y)
        imp = model.feature_importances_
        total = imp.sum() or 1.0
        return {name: float(v / total) for name, v in zip(feature_names, imp)}
    except Exception:
        return {name: 0.0 for name in feature_names}


# ===================================================================
# SHAP 分析（可选）
# ===================================================================

def shap_importance(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: List[str],
    task_type: str = "regression",
    max_samples: int = 500,
) -> Tuple[Dict[str, float], Optional[np.ndarray]]:
    """用 SHAP 计算特征重要性

    Returns:
        importance_dict, shap_values_array
    """
    if not SHAP_AVAILABLE:
        logger.info("SHAP not installed, skipping. Install: pip install shap")
        return {name: 0.0 for name in feature_names}, None

    try:
        import lightgbm as lgb

        params = {
            "n_estimators": 200, "max_depth": 5, "verbose": -1,
            "random_state": 42, "n_jobs": -1,
        }
        if task_type == "classification":
            model = lgb.LGBMClassifier(**params)
        else:
            model = lgb.LGBMRegressor(**params)

        model.fit(X, y)

        sample_idx = np.random.choice(len(X), min(max_samples, len(X)), replace=False)
        X_sample = X[sample_idx]

        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_sample)

        if isinstance(shap_vals, list):
            shap_vals = shap_vals[1] if len(shap_vals) > 1 else shap_vals[0]

        mean_abs = np.mean(np.abs(shap_vals), axis=0)
        total = mean_abs.sum() or 1.0
        importance = {name: float(v / total) for name, v in zip(feature_names, mean_abs)}

        return importance, shap_vals

    except Exception as e:
        logger.warning("SHAP analysis failed: %s", e)
        return {name: 0.0 for name in feature_names}, None


# ===================================================================
# 综合特征筛选器
# ===================================================================

class FeatureSelector:
    """特征筛选器

    综合三重信号（相关性 + 模型重要性 + SHAP）自动筛选 Top-N 因子。

    用法：
        selector = FeatureSelector(top_n=40, redundancy_threshold=0.95)
        result = selector.fit(X, y, feature_names, task_type="classification")
        X_selected = selector.transform(X)
        print(result.importance_ranking)
    """

    def __init__(
        self,
        top_n: int = 40,
        redundancy_threshold: float = 0.95,
        use_shap: bool = True,
        corr_method: str = "spearman",
    ):
        self.top_n = top_n
        self.redundancy_threshold = redundancy_threshold
        self.use_shap = use_shap and SHAP_AVAILABLE
        self.corr_method = corr_method
        self._result: Optional[SelectionResult] = None
        self._selected_indices: Optional[np.ndarray] = None

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
        task_type: str = "regression",
        factor_groups: Optional[Dict] = None,
    ) -> SelectionResult:
        """执行完整的特征筛选

        Args:
            X:              特征矩阵
            y:              标签
            feature_names:  特征名列表
            task_type:      classification / regression
            factor_groups:  因子分组信息（来自 FactorEngine）

        Returns:
            SelectionResult
        """
        logger.info("开始特征筛选: %d 个候选特征, top_n=%d", len(feature_names), self.top_n)

        # 1. 相关性分析
        corr_matrix, target_corr = correlation_analysis(
            X, y, feature_names, method=self.corr_method,
        )
        redundant = find_redundant_features(
            corr_matrix, self.redundancy_threshold, target_corr,
        )
        logger.info("冗余特征: %d 个 (阈值=%.2f)", len(redundant), self.redundancy_threshold)

        # 去除冗余后的特征
        non_redundant = [f for f in feature_names if f not in redundant]
        non_redundant_idx = [feature_names.index(f) for f in non_redundant]
        X_nr = X[:, non_redundant_idx]

        # 2. 模型重要性
        model_imp = tree_importance(X_nr, y, non_redundant, task_type)

        # 3. SHAP（可选）
        shap_imp: Dict[str, float] = {}
        shap_vals = None
        if self.use_shap:
            shap_imp, shap_vals = shap_importance(
                X_nr, y, non_redundant, task_type,
            )

        # 4. 综合评分
        ranking_df = self._compute_combined_score(
            non_redundant, target_corr, model_imp, shap_imp, factor_groups,
        )

        # 5. 选取 Top-N
        top_features = ranking_df.head(self.top_n)["feature"].tolist()

        self._result = SelectionResult(
            selected_features=top_features,
            importance_ranking=ranking_df,
            correlation_matrix=corr_matrix,
            redundant_features=redundant,
            shap_values=shap_vals,
            method_scores={
                "target_correlation": target_corr,
                "model_importance": model_imp,
                "shap_importance": shap_imp,
            },
        )

        # 记住选中特征在原始 X 中的列索引
        self._all_feature_names = feature_names
        self._selected_indices = np.array([feature_names.index(f) for f in top_features])

        logger.info("特征筛选完成: %d → %d 个特征", len(feature_names), len(top_features))
        return self._result

    def transform(self, X: np.ndarray) -> np.ndarray:
        """根据 fit() 结果过滤特征列"""
        if self._selected_indices is None:
            raise RuntimeError("请先调用 fit()")
        return X[:, self._selected_indices]

    def fit_transform(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
        task_type: str = "regression",
        factor_groups: Optional[Dict] = None,
    ) -> Tuple[np.ndarray, List[str], SelectionResult]:
        """fit + transform 一步完成

        Returns:
            X_selected, selected_feature_names, result
        """
        result = self.fit(X, y, feature_names, task_type, factor_groups)
        X_selected = self.transform(X)
        return X_selected, result.selected_features, result

    @property
    def result(self) -> Optional[SelectionResult]:
        return self._result

    # ------------------------------------------------------------------
    # 综合评分
    # ------------------------------------------------------------------

    def _compute_combined_score(
        self,
        features: List[str],
        target_corr: Dict[str, float],
        model_imp: Dict[str, float],
        shap_imp: Dict[str, float],
        factor_groups: Optional[Dict] = None,
    ) -> pd.DataFrame:
        """综合评分：相关性 30% + 模型重要性 40% + SHAP 30%"""
        rows = []
        for feat in features:
            corr_score = abs(target_corr.get(feat, 0))
            mi_score = model_imp.get(feat, 0)
            shap_score = shap_imp.get(feat, 0) if shap_imp else 0

            if shap_imp and any(v > 0 for v in shap_imp.values()):
                combined = 0.3 * corr_score + 0.4 * mi_score + 0.3 * shap_score
            else:
                combined = 0.4 * corr_score + 0.6 * mi_score

            # 查找因子类别
            category = "unknown"
            if factor_groups:
                for grp_name, grp in factor_groups.items():
                    if hasattr(grp, "names") and feat in grp.names:
                        category = grp_name
                        break

            rows.append({
                "feature": feat,
                "combined_score": combined,
                "target_corr": target_corr.get(feat, 0),
                "abs_corr": corr_score,
                "model_importance": mi_score,
                "shap_importance": shap_score,
                "category": category,
            })

        df = pd.DataFrame(rows)
        df = df.sort_values("combined_score", ascending=False).reset_index(drop=True)
        df["rank"] = df.index + 1
        return df

    # ------------------------------------------------------------------
    # 报告输出
    # ------------------------------------------------------------------

    def print_ranking(self, top_n: int = 20) -> str:
        """打印特征重要性排名"""
        if self._result is None:
            return "未执行筛选"

        lines = ["=" * 70]
        lines.append(f"{'Rank':>4s}  {'Feature':<35s}  {'Score':>8s}  {'Corr':>8s}  {'MI':>8s}  {'Cat':<12s}")
        lines.append("-" * 70)

        df = self._result.importance_ranking.head(top_n)
        for _, row in df.iterrows():
            lines.append(
                f"{int(row['rank']):>4d}  {row['feature']:<35s}  "
                f"{row['combined_score']:>8.4f}  {row['target_corr']:>+8.4f}  "
                f"{row['model_importance']:>8.4f}  {row['category']:<12s}"
            )
        lines.append("=" * 70)
        report = "\n".join(lines)
        return report

    def save_report(self, path: str) -> None:
        """保存筛选报告为 JSON"""
        if self._result is None:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        report = {
            "selected_features": self._result.selected_features,
            "redundant_features": self._result.redundant_features,
            "ranking": self._result.importance_ranking.to_dict(orient="records"),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("Feature selection report saved: %s", path)


# ===================================================================
# 特征重要性趋势追踪
# ===================================================================

class ImportanceTracker:
    """跨训练轮次追踪特征重要性变化

    用法：
        tracker = ImportanceTracker()
        for fold in folds:
            model.train(...)
            tracker.record(fold_idx, model.feature_importance)
        trend_df = tracker.get_trend()
    """

    def __init__(self):
        self._records: List[Dict] = []

    def record(self, round_id: int, importance: Dict[str, float], extra: Optional[Dict] = None):
        row = {"round": round_id, **importance}
        if extra:
            row.update(extra)
        self._records.append(row)

    def get_trend(self) -> pd.DataFrame:
        """获取重要性趋势 DataFrame（行=轮次, 列=特征）"""
        if not self._records:
            return pd.DataFrame()
        df = pd.DataFrame(self._records).set_index("round")
        return df

    def get_stable_features(self, top_n: int = 20, min_rounds: int = 2) -> List[str]:
        """获取在多轮训练中稳定重要的特征"""
        trend = self.get_trend()
        if trend.empty or len(trend) < min_rounds:
            return []

        feature_cols = [c for c in trend.columns if not c.startswith("_")]
        avg_importance = trend[feature_cols].mean().sort_values(ascending=False)
        return avg_importance.head(top_n).index.tolist()

    def summary(self, top_n: int = 15) -> str:
        """输出重要性趋势摘要"""
        trend = self.get_trend()
        if trend.empty:
            return "无记录"

        feature_cols = [c for c in trend.columns if not c.startswith("_")]
        avg = trend[feature_cols].mean().sort_values(ascending=False)
        std = trend[feature_cols].std()

        lines = [
            "===== Feature Importance Trend =====",
            f"Rounds: {len(trend)}",
            "",
            f"{'Rank':>4s}  {'Feature':<35s}  {'Avg':>8s}  {'Std':>8s}  {'Stable':>6s}",
            "-" * 65,
        ]
        for i, (feat, score) in enumerate(avg.head(top_n).items()):
            s = std.get(feat, 0)
            is_stable = "✓" if s < score * 0.5 else ""
            lines.append(f"{i+1:>4d}  {feat:<35s}  {score:>8.4f}  {s:>8.4f}  {is_stable:>6s}")
        lines.append("=" * 65)
        return "\n".join(lines)

    def save(self, path: str) -> None:
        """保存趋势数据"""
        trend = self.get_trend()
        if trend.empty:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        trend.to_csv(path, index=True)
        logger.info("Importance trend saved: %s", path)
