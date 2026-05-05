"""
股票预测训练框架（Prediction Training Framework）

结构化、可复现的时间序列预测训练管道。

模块划分：
- data_loader:       数据加载 → 标签生成 → 时间序列 CV 分割
- factor_engine:     综合因子工程（技术/市场/情绪/宏观/衍生）
- feature_selector:  特征筛选（相关性/模型重要性/SHAP）+ Top-N 自动选择
- models:            可插拔模型（XGBoost / LightGBM / LSTM）
- trainer:           TimeSeriesCVTrainer — N 折 CV + loss 曲线 + best checkpoint
- evaluator:         指标计算 + 训练报告
- auto_optimizer:    收敛检测 + 自动调参 + 发散回滚

快速使用（基础）：
    from app.prediction.framework import train_and_evaluate
    report = train_and_evaluate(df, model_name="lightgbm", task_type="classification")

进阶使用（全因子 + 自动筛选）：
    from app.prediction.framework import train_advanced
    report, selection, tracker = train_advanced(
        df, model_name="lightgbm", task_type="classification",
        news_df=news_df, macro_df=macro_df, top_n_features=40,
    )

终极使用（自动调参 + 收敛检测）：
    from app.prediction.framework import train_with_optimization
    result = train_with_optimization(
        df, model_name="lightgbm", task_type="classification",
        min_rounds=50, max_rounds=80,
    )
"""

from .data_loader import TimeSeriesDataLoader, TimeSeriesDataset, build_features
from .factor_engine import FactorEngine, compute_technical_factors
from .feature_selector import FeatureSelector, SelectionResult, ImportanceTracker
from .event_alpha import (
    EventDetector, EventFeatureBuilder, compute_event_factors,
    extract_events_from_db, build_event_features_for_symbol,
)
from .event_model import EventDrivenModel, blend_predictions, EventPrediction
from .event_validator import EventValidator, validate_events_from_db, ValidationReport
from .evaluator import ModelEvaluator, TrainingReport, FoldReport
from .trainer import (
    TimeSeriesCVTrainer, train_and_evaluate, train_advanced, train_with_optimization,
)
from .auto_optimizer import (
    AutoOptimizer, OptimizationResult, ConvergenceDetector, auto_optimize,
)
from .models import get_model, list_models, BaseModel

__all__ = [
    # Data
    "TimeSeriesDataLoader",
    "TimeSeriesDataset",
    "build_features",
    # Factor Engine
    "FactorEngine",
    "compute_technical_factors",
    # Feature Selection
    "FeatureSelector",
    "SelectionResult",
    "ImportanceTracker",
    # Event Alpha
    "EventDetector",
    "EventFeatureBuilder",
    "compute_event_factors",
    "extract_events_from_db",
    "build_event_features_for_symbol",
    # Event Model
    "EventDrivenModel",
    "blend_predictions",
    "EventPrediction",
    # Event Validation
    "EventValidator",
    "validate_events_from_db",
    "ValidationReport",
    # Evaluation
    "ModelEvaluator",
    "TrainingReport",
    "FoldReport",
    # Training
    "TimeSeriesCVTrainer",
    "train_and_evaluate",
    "train_advanced",
    # Auto-Optimization
    "AutoOptimizer",
    "OptimizationResult",
    "ConvergenceDetector",
    "auto_optimize",
    "train_with_optimization",
    # Models
    "get_model",
    "list_models",
    "BaseModel",
]
