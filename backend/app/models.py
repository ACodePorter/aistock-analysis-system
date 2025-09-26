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

    # JSON/文本内容（字符串存储，避免跨驱动 JSON 差异）
    latest_price_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signal_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    forecast_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 质量/置信度指标
    data_quality_score: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    prediction_confidence: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)

    __table_args__ = (
        Index("idx_report_symbol_latest", "symbol", "is_latest"),
        Index("idx_report_symbol_version", "symbol", "version"),
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
