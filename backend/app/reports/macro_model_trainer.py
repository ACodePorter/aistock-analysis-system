"""Training and calibration helpers for macro news driven regression models."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from ..data import data_source
from ..utils.mongo_storage import StockNewsStorage, get_storage


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MacroTrainingRun:
    model_name: str
    run_date: datetime
    metrics: Dict[str, float]
    coefficients: Dict[str, float]
    calibration: Dict[str, Any]
    config: Dict[str, Any]
    feature_columns: List[str]
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["run_date"] = self.run_date.isoformat()
        payload.setdefault("created_at", datetime.now(UTC))
        payload.setdefault("updated_at", datetime.now(UTC))
        return payload


class MacroModelTrainer:
    """Orchestrates dataset preparation, model training and calibration."""

    def __init__(
        self,
        *,
        target_symbol: Optional[str] = None,
        lookback_days: Optional[int] = None,
        forecast_horizon: Optional[int] = None,
        storage: Optional[StockNewsStorage] = None,
    ) -> None:
        self.target_symbol = target_symbol or os.getenv("MACRO_TARGET_SYMBOL", "000300.SH")
        self.lookback_days = lookback_days or int(os.getenv("MACRO_LOOKBACK_DAYS", "180"))
        self.forecast_horizon = forecast_horizon or int(os.getenv("MACRO_FORECAST_HORIZON", "1"))
        self._storage = storage
        self.model_name = os.getenv("MACRO_MODEL_NAME", "macro_linear_regression")
        self.calibration_window = int(os.getenv("MACRO_CALIBRATION_WINDOW", "30"))
        self.use_ridge = os.getenv("MACRO_USE_RIDGE", "false").lower() in ("1", "true", "yes")
        self.ridge_alpha = float(os.getenv("MACRO_RIDGE_ALPHA", "0.8"))

    async def run(self) -> Optional[MacroTrainingRun]:
        storage = self._storage or await get_storage()
        if storage is None:
            logger.warning("Storage unavailable; training run will proceed without persistence")

        dataset = await self._load_training_frame(storage)
        if dataset is None or dataset.empty:
            logger.warning("Insufficient dataset for macro training")
            return None

        run = self._train_and_calibrate(dataset)

        if storage is not None:
            await storage.save_macro_model_run(run.to_dict())

        return run

    async def _load_training_frame(self, storage: Optional[StockNewsStorage]) -> Optional[pd.DataFrame]:
        if storage is None:
            logger.warning("Mongo storage not available; cannot load macro observations")
            return None

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.lookback_days * 2)
        observations = await storage.get_macro_observations(start_date=start_date, end_date=end_date, limit=10000)
        if not observations:
            logger.info("No macro observations available between %s and %s", start_date, end_date)
            return None

        obs_rows: List[Dict[str, Any]] = []
        for item in observations:
            topic = item.get("topic", "unknown")
            topic_display = item.get("topic_display", topic)
            date_str = item.get("observation_date")
            try:
                obs_date = pd.to_datetime(date_str).date()
            except Exception:  # noqa: BLE001
                continue
            features = item.get("features", {}) or {}
            row = {f"{topic}.{key}": value for key, value in features.items()}
            row["topic"] = topic
            row["topic_display"] = topic_display
            row["observation_date"] = obs_date
            obs_rows.append(row)

        if not obs_rows:
            return None

        df_obs = pd.DataFrame(obs_rows)
        df_obs.sort_values("observation_date", inplace=True)
        df_obs.reset_index(drop=True, inplace=True)
        df_obs.fillna(0.0, inplace=True)

        trading_df = self._load_target_series(start_date, end_date)
        if trading_df.empty:
            logger.warning("Target series empty for symbol %s", self.target_symbol)
            return None

        merged = df_obs.merge(
            trading_df[["trade_date", "target_return"]],
            left_on="observation_date",
            right_on="trade_date",
            how="inner",
        )
        merged.drop(columns=["trade_date"], inplace=True)

        return merged

    def _load_target_series(self, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        lookback_start = (start_date - timedelta(days=30)).strftime("%Y%m%d")
        df = data_source.fetch_daily(self.target_symbol, start_date=lookback_start)
        if df.empty:
            return pd.DataFrame()
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df.sort_values("trade_date", inplace=True)
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
        df["target_return"] = df["pct_chg"].shift(-self.forecast_horizon) / 100.0
        df = df[(df["trade_date"] >= pd.Timestamp(start_date.date())) & (df["trade_date"] <= pd.Timestamp(end_date.date()))]
        df.dropna(subset=["target_return"], inplace=True)
        return df

    def _train_and_calibrate(self, dataset: pd.DataFrame) -> MacroTrainingRun:
        feature_cols = [
            col
            for col in dataset.columns
            if col not in {"observation_date", "topic", "topic_display", "target_return"}
        ]
        if not feature_cols:
            raise ValueError("No feature columns available for training")

        X = dataset[feature_cols].values.astype(float)
        y = dataset["target_return"].values.astype(float)

        if len(dataset) < 20:
            logger.warning("Dataset too small (%d rows); model may overfit", len(dataset))

        split_idx = max(int(len(dataset) * 0.8), len(dataset) - 5)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        model = self._build_model()
        model.fit(X_train, y_train)

        train_pred = model.predict(X_train)
        val_pred = model.predict(X_val) if len(X_val) else np.array([])

        metrics = {
            "train_rmse": float(np.sqrt(mean_squared_error(y_train, train_pred)) if len(y_train) else 0.0),
            "train_mae": float(mean_absolute_error(y_train, train_pred) if len(y_train) else 0.0),
            "train_r2": float(r2_score(y_train, train_pred) if len(y_train) > 1 else 0.0),
        }

        if len(X_val):
            metrics.update(
                {
                    "val_rmse": float(np.sqrt(mean_squared_error(y_val, val_pred))),
                    "val_mae": float(mean_absolute_error(y_val, val_pred)),
                    "val_r2": float(r2_score(y_val, val_pred) if len(y_val) > 1 else 0.0),
                }
            )
        else:
            metrics.update({"val_rmse": 0.0, "val_mae": 0.0, "val_r2": 0.0})

        calibration = self._build_calibration(y_val, val_pred)
        coefficients = self._extract_coefficients(model, feature_cols)

        config = {
            "target_symbol": self.target_symbol,
            "forecast_horizon": self.forecast_horizon,
            "lookback_days": self.lookback_days,
            "use_ridge": self.use_ridge,
            "ridge_alpha": self.ridge_alpha,
        }

        notes: List[str] = []
        if len(dataset) < 60:
            notes.append("Dataset shorter than 60 samples; consider increasing lookback window")
        if metrics.get("val_r2", 0.0) < 0:
            notes.append("Validation R^2 is negative, indicating poor generalization")

        return MacroTrainingRun(
            model_name=self.model_name,
            run_date=datetime.now(UTC),
            metrics=metrics,
            coefficients=coefficients,
            calibration=calibration,
            config=config,
            feature_columns=feature_cols,
            notes=notes,
        )

    def _build_model(self):
        if self.use_ridge:
            return Ridge(alpha=self.ridge_alpha)
        return LinearRegression()

    def _extract_coefficients(self, model, feature_cols: Sequence[str]) -> Dict[str, float]:
        coefs: Dict[str, float] = {}
        if hasattr(model, "coef_"):
            for feature, value in zip(feature_cols, getattr(model, "coef_")):
                coefs[feature] = float(value)
        if hasattr(model, "intercept_"):
            coefs["intercept"] = float(getattr(model, "intercept_"))
        return coefs

    def _build_calibration(self, y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, Any]:
        if y_true.size == 0 or y_pred.size == 0:
            return {
                "bias": 0.0,
                "std": 0.0,
                "samples": 0,
                "updated_at": datetime.now(UTC).isoformat(),
                "strategy": "none",
            }

        residuals = y_true - y_pred
        bias = float(residuals.mean())
        std = float(residuals.std(ddof=1)) if residuals.size > 1 else 0.0
        adjustment = -bias

        return {
            "bias": bias,
            "std": std,
            "samples": int(residuals.size),
            "updated_at": datetime.now(UTC).isoformat(),
            "strategy": "offset",
            "offset": adjustment,
        }


async def run_training_job() -> Optional[MacroTrainingRun]:
    trainer = MacroModelTrainer()
    return await trainer.run()


def run_sync() -> None:
    result = asyncio.run(run_training_job())
    if result is None:
        logger.warning("Macro training job produced no result")
    else:
        logger.info("Macro training completed: %s", result.to_dict())


if __name__ == "__main__":
    run_sync()
