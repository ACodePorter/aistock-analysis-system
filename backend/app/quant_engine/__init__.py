"""
AI 驱动量化分析与预测引擎（AI Quant Engine）

模块化架构：
- data_layer:           数据获取与存储（行情、新闻、宏观）
- factor_engine:        因子库系统（49+ 因子：技术/新闻/宏观/行为）
- feature_engineering:  特征工程管道（45+ 默认特征，z-score/minmax/rank 标准化）
- model_engine:         模型管理与训练（LightGBM/XGBoost，含跨股票分析）
- evaluation_engine:    回测与评估（Walk-Forward / Holdout / 预测回填）
- signal_engine:        交易信号生成与选股排名
- dashboard:            仪表板数据提供器（总览/单股分析/选股推荐）
- events:               事件驱动新闻集成（情绪突变/新闻异常检测）
- api:                  对外 REST 接口（/api/quant/*）

数据库表（qe_ 前缀）：
- qe_stock_models / qe_model_versions / qe_factor_metadata / qe_factor_values
- qe_predictions / qe_evaluation_runs / qe_evaluation_metrics
- qe_signals / qe_training_jobs
"""

__version__ = "0.1.0"
