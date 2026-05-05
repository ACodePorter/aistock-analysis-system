"""
常量定义 - v1.1 升级版本

系统级枚举、常数、规则、默认值等集中管理。
"""

from enum import Enum


# =========================
# 信源等级体系（核心）
# =========================

class SourceLevelEnum(str, Enum):
    """信源等级（按可信度和权重排序）"""
    L1 = "L1"  # 法定/监管披露（硬事实）：公告、交易所问询、处罚、立案
    L2 = "L2"  # 专业财经媒体（传播层）：东方财富、新浪财经、财经网
    L3 = "L3"  # 官方/行业机构（宏观行业信号）：证监会、交易所、行业协会、权威统计
    L4 = "L4"  # 研究与机构观点（解释层）：公开研究报告摘要、机构评论


SOURCE_LEVEL_WEIGHTS = {
    "L1": 1.0,
    "L2": 0.7,
    "L3": 0.9,
    "L4": 0.5,
}


# =========================
# 事件类型枚举
# =========================

class EventTypeEnum(str, Enum):
    """事件类型分类"""
    EARNINGS = "earnings"              # 业绩
    EARNINGS_ADJUSTMENT = "earnings_adjustment"  # 业绩调整/修正
    BUYBACK = "buyback"                # 回购
    ANNOUNCEMENT = "announcement"      # 通用公告
    PENALTY = "penalty"                # 监管处罚
    LITIGATION = "litigation"          # 诉讼/仲裁
    MERGER = "merger"                  # 并购/重组
    CONTRACT = "contract"              # 重大合同
    RISK_ALERT = "risk_alert"          # 风险提示
    POLICY_IMPACT = "policy_impact"    # 政策影响
    ASSET_SALE = "asset_sale"          # 资产出售
    DEBT_ISSUANCE = "debt_issuance"    # 债务发行
    EQUITY_ISSUANCE = "equity_issuance"  # 股权融资
    PRODUCT_LAUNCH = "product_launch"  # 产品发布
    STRATEGIC_PARTNERSHIP = "strategic_partnership"  # 战略合作


# =========================
# 观察列表生命周期
# =========================

class WatchlistStatusEnum(str, Enum):
    """观察列表股票状态"""
    ACTIVE = "active"              # 积极监控
    COOLING = "cooling"            # 冷却期（暂停监控）
    ARCHIVED = "archived"          # 归档


# =========================
# 简报周期
# =========================

class BriefingPeriodEnum(str, Enum):
    """简报周期"""
    DAILY = "daily"                # 日报
    WEEKLY = "weekly"              # 周报


# =========================
# 推荐与风险等级
# =========================

class RecommendationEnum(str, Enum):
    """投资建议"""
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    AVOID = "avoid"


class RiskLevelEnum(str, Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# =========================
# 新闻分类
# =========================

class NewsCategory(str, Enum):
    """新闻分类"""
    FINANCE = "finance"
    POLICY = "policy"
    INDUSTRY = "industry"
    COMPANY = "company"
    MARKET = "market"
    ECONOMIC = "economic"


# =========================
# 情感分析
# =========================

class SentimentEnum(str, Enum):
    """情感倾向"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


# =========================
# 采集配置（可运营参数）
# =========================

COLLECTOR_CONFIG = {
    # 限速策略（域名级）
    "rate_limit": {
        "eastmoney.com": {
            "requests_per_minute": 10,
            "burst_size": 5,
        },
        "sina.com.cn": {
            "requests_per_minute": 15,
            "burst_size": 8,
        },
        "default": {
            "requests_per_minute": 20,
            "burst_size": 10,
        },
    },
    # 断路器策略
    "circuit_breaker": {
        "failure_threshold": 5,  # 连续失败次数
        "timeout_minutes": 30,    # 熔断时长
        "half_open_requests": 2,  # 半开状态尝试请求数
    },
    # 重试策略
    "retry": {
        "max_retries": 3,
        "backoff_base": 2,  # 指数退避基数
        "jitter_factor": 0.1,  # 抖动系数
    },
    # 超时
    "timeout_seconds": 30,
}


# =========================
# 去重策略
# =========================

DEDUP_CONFIG = {
    "url_normalization": {
        "remove_fragment": True,
        "lowercase": True,
        "remove_query_params": False,
    },
    "content_hash": {
        "algorithm": "sha256",
        "minimum_length": 100,  # 最小字数（字符）
    },
    "similarity_threshold": 0.85,  # 相似度阈值（0-1）
}


# =========================
# 事件合并规则
# =========================

EVENT_MERGE_RULES = {
    "same_symbol_and_type": {
        "time_window_days": 3,  # 同股票同事件类型，3天内合并
        "confidence_boost": 0.1,  # 合并后置信度提升
    },
    "multi_source_consistency": {
        "min_sources_for_merge": 2,  # 最少多少个信源可确认合并
    },
}


# =========================
# 简报配置
# =========================

BRIEFING_CONFIG = {
    "max_events_in_summary": 5,   # 简报中最多显示的事件数
    "min_confidence_threshold": 0.5,  # 简报中事件最低置信度
    "daily_generation_hour": 18,  # 日报生成时间（北京时间18点）
    "weekly_generation_day": 5,   # 周报生成日（周五）
}


# =========================
# 简报生成提示词版本
# =========================

BRIEFING_PROMPTS = {
    "daily": {
        "version": "v1.0",
        "system": """你是专业的股票分析师。根据提供的事件、新闻和行情数据，生成高质量的日报。
        
要求：
1. 必须基于证据回答（不凭空生成）
2. 列举关键事件时必须标注事件ID和信源等级
3. 风险/机会总结必须引用具体新闻标题或数据
4. 输出JSON格式，包含risk_summary、opportunity_summary、key_events、confidence等字段""",
        "temperature": 0.7,
        "max_tokens": 2000,
    },
    "weekly": {
        "version": "v1.0",
        "system": """你是专业的股票分析师。根据提供的一周事件汇总，生成周报。
        
要求：
1. 识别关键趋势和转折点
2. 对标的风险/机会做出中期展望（1-4周）
3. 输出JSON格式，包含weekly_trend、key_turning_points、mid_term_outlook、confidence等字段""",
        "temperature": 0.7,
        "max_tokens": 3000,
    },
}


# =========================
# RAG 检索策略
# =========================

RAG_CONFIG = {
    "retrieval": {
        "keyword_weight": 0.3,
        "semantic_weight": 0.5,
        "recency_weight": 0.2,  # 时间衰减
        "source_level_boost": {
            "L1": 1.5,
            "L2": 1.0,
            "L3": 1.2,
            "L4": 0.8,
        },
    },
    "reranking": {
        "strategy": "evidence_relevance",  # keyword_match | source_level | semantic_distance
        "top_k": 10,  # 最终返回Top K
    },
    "hallucination_prevention": {
        "require_evidence": True,
        "evidence_min_count": 1,  # 至少引用N条证据
        "confidence_threshold": 0.7,  # 低于该阈值输出"不足以判断"
    },
}


# =========================
# 清洗规则
# =========================

CLEANING_RULES = {
    "article_quality": {
        "min_content_length": 200,  # 最小字数
        "min_publish_date": "2020-01-01",  # 最早发布日期
        "required_fields": ["title", "content", "published_at"],
    },
    "dedup_duplicate_threshold": 0.90,  # 内容相似度>90%判定为重复
    "spam_keywords": [
        "广告",
        "投资咨询",
        "免责声明",  # 如果全是免责声明则过滤
    ],
}


# =========================
# Top20 自动入池规则
# =========================

TOP20_POOL_RULES = {
    "min_consecutive_days": 3,  # 连续出现3天以上才入池
    "min_volatility_pct": 5.0,   # 最小波动幅度
    "max_pool_size": 200,         # 观察池最大容纳股票数
    "cooling_threshold_days": 30,  # 30天未出现Top20则进入Cooling
    "archive_threshold_days": 90,  # 90天未活跃则Archive
}


# =========================
# 预测模型再训练触发规则
# =========================

RETRAIN_TRIGGER_RULES = {
    "consecutive_failures": 3,
    "direction_accuracy_threshold": 0.45,
    "mape_threshold_pct": 8.0,
    "interval_hit_rate_threshold": 0.50,
    "cooldown_hours": 24,
    "min_evaluations": 5,
    "min_interval_evaluations": 3,
    "auto_retrain_enabled": True,
    "min_score_improvement_ratio": 1.02,
    "retrain_lock_ttl_seconds": 7200,
}


# =========================
# 默认参数
# =========================

DEFAULT_CONFIDENCE_SCORE = 0.5
DEFAULT_SENTIMENT_NEUTRAL = 0.0
EVENT_ID_PREFIX = "evt_"
BRIEFING_ID_PREFIX = "brf_"
