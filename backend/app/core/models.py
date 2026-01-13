"""
数据库 ORM 模型定义（SQLAlchemy 2.0 风格，带中文注释）

说明：
- 统一使用 SQLAlchemy 2.0 的类型注解写法（Mapped/mapped_column）
- 保持后端其他模块所依赖的表名/字段名不变（例如 prices_daily、forecasts、fundflow_daily 等）
- 明确字段单位与语义：金额一律为“元”，数量一律为“股”；前端展示“万/亿”请自行换算
- 为高频查询添加必要索引（如 symbol+trade_date 组合索引）
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    String, Integer, Boolean, Date, BigInteger, Numeric, TIMESTAMP, Text, Index, Float, ForeignKey, JSON, func
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# =========================
# 枚举类型
# =========================

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    GENERATE_REPORT = "generate_report"
    FETCH_DATA = "fetch_data"
    TRAIN_MODEL = "train_model"
    FETCH_NEWS = "fetch_news"
    ANALYZE_NEWS = "analyze_news"


class NewsCategory(str, Enum):
    FINANCE = "finance"
    POLICY = "policy"
    INDUSTRY = "industry"
    COMPANY = "company"
    MARKET = "market"
    ECONOMIC = "economic"


class SentimentType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


# =========================
# Base
# =========================


class Base(DeclarativeBase):
    """SQLAlchemy Declarative Base"""
    pass


# =========================
# 核心业务表
# =========================


class Watchlist(Base):
    """自选股票表

    - symbol: 股票代码（如 600519.SH）唯一
    - enabled: 是否启用监控
    - sector/name: 行业与名称（用于展示和新闻关键词）
    - last_updated_at: 最后一次更新完成时间（表示资讯更新状态）
    """

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )
    last_updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP, nullable=True, comment="最后一次资讯更新完成时间"
    )


class Stock(Base):
    """股票基础信息（可选，当前仅少量使用，保留最小字段集）"""

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class PriceDaily(Base):
    """日线行情（单位：价格=元，成交量=股，成交额=元）"""

    __tablename__ = "prices_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_chg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 涨跌幅（%）
    vol: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)   # 成交量（股）
    amount: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)  # 成交额（元）

    __table_args__ = (
        Index("idx_prices_daily_symbol_date", "symbol", "trade_date"),
    )


class IngestStateDaily(Base):
    """EOD 全市场日线行情摄取状态表

    设计目的：
    - 记录每日批量行情抓取（全量 A 股）的执行与覆盖情况
    - 支持幂等：同一 trade_date 多次执行只更新同一行
    - 便于 API 返回 coverage / provider / 耗时等诊断信息

    字段：
    - trade_date: 交易日（主键之一）
    - status: pending/running/success/failed
    - provider_primary / provider_fallback: 使用的主、备数据源
    - total_symbols: 解析的原始标的数量
    - inserted_rows: 实际写入/更新的行数
    - started_at / finished_at: 过程时间
    - error_message: 失败详情（若 status=failed）
    - meta_json: 额外诊断（JSON 字符串）
    """

    __tablename__ = "ingest_state_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trade_date: Mapped[datetime.date] = mapped_column(Date, index=True, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    provider_primary: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    provider_fallback: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    total_symbols: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    inserted_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_ingest_state_daily_trade_date", "trade_date"),
        Index("idx_ingest_state_daily_status", "status"),
    )


class Signal(Base):
    """技术指标信号（按日）"""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[datetime.date] = mapped_column(Date, index=True)

    ma_short: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    ma_long: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    rsi: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    macd: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    signal_score: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    action: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # buy/sell/hold

    __table_args__ = (
        Index("idx_signal_symbol_date", "symbol", "trade_date"),
    )


class Forecast(Base):
    """预测结果（多模型多日期）"""

    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    run_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, index=True)
    target_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    model: Mapped[str] = mapped_column(String(32))
    yhat: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    yhat_lower: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    yhat_upper: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)

    __table_args__ = (
        Index("idx_forecast_symbol_target", "symbol", "target_date"),
    )


class FundFlowDaily(Base):
    """个股资金流向（EOD，仅存收盘后数据；单位：元/百分比）"""

    __tablename__ = "fundflow_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[datetime.date] = mapped_column(Date, index=True)

    main_net: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)    # 主力净流入（元）
    main_ratio: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)  # 主力净占比（%）
    super_net: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    super_ratio: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    large_net: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    large_ratio: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    medium_net: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    medium_ratio: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    small_net: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    small_ratio: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)

    __table_args__ = (
        Index("idx_fundflow_symbol_date", "symbol", "trade_date"),
    )


class Task(Base):
    """任务队列表（异步报告/数据/训练等）"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(50))  # TaskType
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PENDING.value)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1-10, 1最高
    task_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 字符串

    __table_args__ = (
        Index("idx_task_status_priority", "status", "priority"),
        Index("idx_task_symbol_type", "symbol", "task_type"),
    )


class Report(Base):
    """报告版本表（存储最新/历史版本及摘要 JSON）"""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)

    # 补充：原 main.py 访问 report.latest_price_data / signal_data / forecast_data / analysis_summary
    # 以及 data_quality_score / prediction_confidence；之前遗漏定义导致 AttributeError。
    # 这些字段与 AgentJob 中的同名字段语义一致，用于缓存结构化 JSON 文本与质量指标。
    latest_price_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signal_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    forecast_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_quality_score: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    prediction_confidence: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)

    __table_args__ = (
        Index("idx_report_symbol_latest", "symbol", "is_latest"),
        Index("idx_report_symbol_version", "symbol", "version"),
    )


class AgentJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class AgentJob(Base):
    """Top20 智能分析 Agent 运行记录 / 队列持久化。

    字段:
    - job_id: 外部返回的 UUID
    - status: queued/running/finished/failed
    - strict_mode: 是否开启严格 JSON
    - created_at / started_at / finished_at: 关键时间点
    - return_code: 子进程退出码
    - stdout_tail / stderr_tail: 运行尾部日志（截断形式）
    - reports_json: 解析出的报告文件名列表（JSON 字符串）
    - error_message / traceback: 失败详情
    - duration_sec: 运行时长缓存，便于 metrics
    """
    __tablename__ = "agent_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=AgentJobStatus.QUEUED.value, index=True)
    strict_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    return_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stdout_tail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr_tail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reports_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("idx_agent_jobs_status", "status"),
        Index("idx_agent_jobs_created_at", "created_at"),
    )

    # JSON/文本内容（字符串存储，避免跨驱动 JSON 差异）
    latest_price_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signal_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    forecast_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 质量/置信度指标
    data_quality_score: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    prediction_confidence: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)

    # (Remove misplaced report indexes that previously caused symbol KeyError)


class AgentDailyReport(Base):
    """持久化的每日 Agent 综合分析报告。

    设计要点:
    - report_date: 交易日/自然日（UTC->本地可映射），保证每天一行，可覆盖更新。
    - job_id: 来源运行记录，便于追踪日志。
    - stock_reports_json / macro_json / analytics_json / diagnostics_json: 直接存储原始结构的 JSON 序列化字符串。
    - markdown: 生成的 md 文本（可选，用于前端直接展示）。
    - version: 兼容未来结构调整。
    """
    __tablename__ = "agent_daily_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    report_date: Mapped[datetime.date] = mapped_column(Date, unique=True, index=True)
    generated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow, index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    top20_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stock_reports_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    macro_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analytics_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnostics_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_daily_reports_date", "report_date"),
        Index("idx_agent_daily_reports_generated_at", "generated_at"),
    )


# =========================
# 新闻相关表
# =========================


class NewsSource(Base):
    """新闻来源表（域名白/黑名单、可信度等）"""

    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(255), unique=True)
    category: Mapped[str] = mapped_column(String(50))  # NewsCategory
    reliability_score: Mapped[float] = mapped_column(Float, default=0.5)
    language: Mapped[str] = mapped_column(String(10), default="zh-CN")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)

    # 关系
    articles = relationship("NewsArticle", back_populates="source")


class NewsArticle(Base):
    """新闻文章表（包含情感分析、关联股票等）"""

    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # 标记摘要是否由大语言模型生成（True 表示 LLM 生成；False 表示原生/规则/人工）
    summary_from_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    author: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # 元数据
    published_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    crawled_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)
    source_id: Mapped[int] = mapped_column(ForeignKey("news_sources.id"))
    
    # 统计字段 - 用于资讯页面显示
    start_date: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True, comment="最早发布时间")
    last_updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True, comment="最后更新时间")

    # 内容分析
    category: Mapped[str] = mapped_column(String(50))  # NewsCategory
    keywords: Mapped[Optional[JSON]] = mapped_column(JSON, nullable=True)  # 关键词列表
    entities: Mapped[Optional[JSON]] = mapped_column(JSON, nullable=True)  # 命名实体

    # 情感分析
    sentiment_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # SentimentType
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # -1 ~ 1
    sentiment_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 关联股票（JSONB 列表），使用 GIN 索引以支持包含查询
    related_stocks: Mapped[Optional[JSONB]] = mapped_column(JSONB, nullable=True)  # ["600519.SH", ...]
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0 ~ 1

    # 质量标记
    content_quality: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of: Mapped[Optional[int]] = mapped_column(ForeignKey("news_articles.id"), nullable=True)

    # 用户交互
    is_bookmarked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

    # 关系
    source = relationship("NewsSource", back_populates="articles")

    __table_args__ = (
        Index("idx_news_published_at", "published_at"),
        Index("idx_news_category", "category"),
        Index("idx_news_sentiment", "sentiment_type", "sentiment_score"),
        Index(
            "idx_news_stocks",
            "related_stocks",
            postgresql_using="gin",
            postgresql_ops={"related_stocks": "jsonb_path_ops"},
        ),
        Index("idx_news_source_published", "source_id", "published_at"),
        Index("idx_news_quality", "content_quality", "is_duplicate"),
    )


class NewsKeyword(Base):
    """新闻搜索关键词配置（与股票/行业等关联）"""

    __tablename__ = "news_keywords"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    keyword: Mapped[str] = mapped_column(String(100), unique=True)
    keyword_type: Mapped[str] = mapped_column(String(50))  # stock_symbol/company_name/industry/policy
    related_symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    search_priority: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_searched: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    search_frequency: Mapped[int] = mapped_column(Integer, default=24)  # 小时

    __table_args__ = (
        Index("idx_keyword_type_symbol", "keyword_type", "related_symbol"),
        Index("idx_keyword_priority", "search_priority", "enabled"),
    )


class SearchLog(Base):
    """新闻搜索日志（便于观测成功率和性能）"""

    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    query: Mapped[str] = mapped_column(String(500))
    query_type: Mapped[str] = mapped_column(String(50))  # manual/auto/scheduled/api
    source_engine: Mapped[str] = mapped_column(String(50))  # searxng/manual
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    processing_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index("idx_search_query_type", "query_type", "created_at"),
        Index("idx_search_success", "success", "created_at"),
    )


class NewsURLPattern(Base):
    """新闻 URL 匹配规则（用于过滤或允许特定来源/路径）"""

    __tablename__ = "news_url_patterns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # kind: block | allow
    kind: Mapped[str] = mapped_column(String(16), default="block")
    # scope: substring | regex（当前实现 substring 为主）
    scope: Mapped[str] = mapped_column(String(16), default="substring")
    # 可选主机限制（如 finance.sina.com.cn）
    host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # 匹配字符串
    pattern: Mapped[str] = mapped_column(String(1000))
    # 是否启用
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 维护者备注
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)

    __table_args__ = (
        Index("idx_news_url_patterns_kind_enabled", "kind", "enabled"),
        Index("idx_news_url_patterns_host", "host"),
    )

# =========================
# 新闻查询范式（模板）
# =========================

class NewsQueryTemplate(Base):
    """新闻搜索查询模板（范式）

    用于通过一组可配置模板统一管理新闻搜索关键字，支持作用域：
    - global：全局生效
    - symbol：针对具体股票（target=SYMBOL）
    - industry：针对行业（target=行业名或代码）

    模板中可使用占位符：
    - {symbol}：股票代码（如 600519.SH）
    - {name}：公司简称/名称（如 贵州茅台）
    - {industry}：行业名（可选）

    通过 priority 控制优先级（数值越大越优先），enabled 控制启用。
    """

    __tablename__ = "news_query_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), default="global", index=True)  # global|symbol|industry
    target: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    template: Mapped[str] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)

    __table_args__ = (
        Index("idx_nqt_scope_target", "scope", "target"),
        Index("idx_nqt_enabled_priority", "enabled", "priority"),
    )

# =========================
# 知识库扩展：日特征 / 事件 / 相关性 / 模型注册
# =========================

class StockDailyFeature(Base):
    """逐日特征表：融合行情 / 新闻 / Agent 输出 / 宏观指标。

    说明：
    - 未来收益标签 (fwd_ret_*, fwd_dir_*) 在首次插入时可能为空，待未来日回填。
    - parse_mode / sentiment_label 等直接来自 agent 报告。
    - raw_factors_json 存储因子原始 JSON 便于后续再加工。
    """
    __tablename__ = "stock_daily_features"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[datetime.date] = mapped_column(Date, index=True)

    # 行情特征
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_chg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vol: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 滞后收益/波动 (构建阶段可空后续补)
    ret_1d_prev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ret_5d_prev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vol_5d_prev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 5日收盘收益波动

    # 未来标签（回填）
    fwd_ret_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fwd_ret_5d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fwd_ret_10d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fwd_ret_20d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fwd_dir_1d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1 up,0 down
    fwd_dir_5d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    realized_vol_5d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_vol_20d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 新闻聚合
    news_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    news_pos: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    news_neg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    news_neutral: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    news_sentiment_score_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Agent 输出特征
    agent_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    agent_sentiment_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    agent_sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    agent_factor_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_positive_factor_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_negative_factor_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_risk_factors_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_parse_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    agent_fallback_used: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    agent_macro_need_flag: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # 宏观共享指标
    macro_sentiment_index: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macro_risk_index: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 扩展技术/结构特征
    amplitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # (high-low)/close
    candle_body: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # (close-open)/open
    upper_shadow_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lower_shadow_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vol_ratio_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # vol / avg_vol_20
    amount_ratio_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    factor_balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # (pos-neg)/(pos+neg+eps)
    risk_factor_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # risk / total

    # 股票池 / 基础画像衔接
    in_stock_pool: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 来自 StockProfile

    # 原始 JSON 存档
    raw_factors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)

    __table_args__ = (
        Index("idx_sdf_symbol_date", "symbol", "trade_date", unique=True),
        Index("idx_sdf_fwd_dir_1d", "fwd_dir_1d"),
    )


class StockEvent(Base):
    """自动/半自动识别的事件标签。"""
    __tablename__ = "stock_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)  # volatility_spike, abnormal_volume, policy_thematic, risk_alert, macro_thematic
    severity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trigger_features: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 字符串
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # rule|agent|model
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index("idx_events_symbol_date", "symbol", "trade_date"),
        Index("idx_events_type", "event_type"),
    )


class FeatureCorrelation(Base):
    """特征与未来收益/波动的相关性或信息系数记录。"""
    __tablename__ = "feature_correlations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feature_name: Mapped[str] = mapped_column(String(100), index=True)
    horizon: Mapped[str] = mapped_column(String(10), index=True)  # 1d / 5d / 10d / 20d / vol5d etc.
    metric_type: Mapped[str] = mapped_column(String(30), index=True)  # pearson / spearman / ic / mutual_info
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rolling_window: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_fc_feature_metric", "feature_name", "metric_type", "horizon"),
    )


class ModelRegistry(Base):
    """模型注册信息（版本 / 特征集 / 评估指标 / 存储路径）。"""
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, index=True)
    task: Mapped[str] = mapped_column(String(50), index=True)  # next_day_direction / next_5d_return etc.
    algo: Mapped[str] = mapped_column(String(50))
    train_start: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    train_end: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    features_used: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 列表
    metrics_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON 指标
    artifact_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index("idx_model_task_active", "task", "is_active"),
    )

# =========================
# 股票池与公司基础画像
# =========================

class StockPoolMember(Base):
    """动态股票池成员表（来源：每日 Top20 聚合）。

    - 每日更新：若当日进入 Top20 且此前未入池，则插入。
    - exit_date：可选（规则：若连续 N 日未再出现，可标记退出；当前留空供后续扩展）。
    """
    __tablename__ = "stock_pool_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    first_seen_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    last_seen_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    exit_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_stock_pool_symbol", "symbol"),
        Index("idx_stock_pool_last_seen", "last_seen_date"),
    )


class StockProfile(Base):
    """公司基础与结构化画像（一次性/周期性增量采集）。

    字段示例：行业、主营、核心产品、竞争对手、行业地位、关键历史事件、风险点等。
    允许后续 LLM 生成结构化 JSON（以 text/json 字段存档）。
    """
    __tablename__ = "stock_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    market: Mapped[str] = mapped_column(String(16), default="A股", nullable=False, index=True, comment="市场标签：A股/港股/美股/新股等")
    company_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sub_industry: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    business_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    core_products: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 逗号或 JSON 化
    competitive_position: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    competitors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 或分隔
    strategic_keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_factors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    history_highlights: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    profile_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 结构化 JSON 全量
    last_refreshed: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, default=datetime.datetime.utcnow)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)

    # Profile 验证字段
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否有效，false表示公司已作废/停运/风险")
    validation_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="valid/invalid/suspended/delisted/risk_alert")
    validation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="作废原因说明")
    last_validated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True, comment="最后一次验证时间")

    __table_args__ = (
        Index("idx_stock_profile_symbol", "symbol"),
        Index("idx_stock_profile_industry", "industry"),
        Index("idx_stock_profile_is_valid", "is_valid"),
    )
