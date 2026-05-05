# 📊 AI Stock Analysis System - Backend Module Documentation

> 后端项目完整模块功能说明文档  
> 提供股票数据收集、技术分析、AI驱动的新闻处理、预测与调度等核心功能

---

## 📑 目录

- [项目概述](#项目概述)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [核心模块说明](#核心模块说明)
  - [数据库与存储](#数据库与存储)
  - [数据获取](#数据获取)
  - [技术分析](#技术分析)
  - [预测与模型](#预测与模型)
  - [新闻处理](#新闻处理)
  - [任务与调度](#任务与调度)
  - [AI与LLM](#ai与llm)
  - [宏观与策略](#宏观与策略)
  - [路由与API](#路由与api)
- [快速开始](#快速开始)
- [环境配置](#环境配置)
- [常用命令](#常用命令)

---

## 项目概述

本后端系统是一个基于FastAPI的完整股票分析平台，整合了以下核心功能：

- **📈 实时行情获取**：多源数据（AkShare/Tushare/东方财富/新浪）聚合
- **🔍 技术指标计算**：RSI、MACD、均线等常用技术信号
- **🤖 AI驱动预测**：深度学习、随机森林、SARIMAX等多模型集成
- **📰 智能新闻处理**：网页爬虫、LLM分析、去重、情感分析、关联股票提取
- **⏰ 自动调度系统**：定时数据拉取、指标计算、预测更新、新闻采集
- **📊 报告生成**：基于技术面+AI的自动分析报告
- **🗄️ 数据存储**：PostgreSQL关系型数据库 + MongoDB文档存储

---

## 技术栈

### 后端框架与库
- **FastAPI** - 高性能异步Web框架
- **SQLAlchemy 2.0** - ORM与数据库管理
- **APScheduler** - 任务调度器
- **Pandas & NumPy** - 数据处理与分析
- **scikit-learn** - 机器学习模型
- **statsmodels** - 时间序列分析(SARIMAX)
- **asyncio** - 异步编程

### 数据源
- **AkShare** - A股免费数据源（默认）
- **Tushare** - 专业级数据接口
- **东方财富** - 行情与资金流数据
- **新浪财经** - 实时L1行情补充

### 数据库
- **PostgreSQL** - 关系型数据存储（核心）
- **MongoDB** - 文档存储（新闻与分析结果）
- **Redis** - 缓存与消息队列（可选）

---

## 项目结构

```
backend/
├── app/                              # 主应用程序包
│   ├── main.py                       # FastAPI 主应用与所有路由定义
│   ├── models.py                     # SQLAlchemy ORM 模型定义
│   ├── db.py                         # 数据库连接与会话管理
│   │
│   ├── 📊 数据获取模块
│   ├── data_source.py                # 多源数据聚合（股票信息、日线、资金流等）
│   │
│   ├── 🔧 技术分析模块
│   ├── signals.py                    # 技术指标计算（RSI、MACD、均线等）
│   ├── stock_manager.py              # 自选股列表管理
│   │
│   ├── 🤖 预测模块
│   ├── forecast.py                   # 基础预测方法（SARIMAX、特征回归）
│   ├── forecast_enhanced.py          # 增强预测（神经网络、随机森林）
│   ├── model_inference.py            # 模型推理工具
│   │
│   ├── 📰 新闻处理模块（核心子系统）
│   ├── news_service.py               # 新闻搜索、抓取、正文提取、LLM分析
│   ├── news_crawler.py               # 异步网页爬虫、内容清洗、NLP处理
│   ├── news_strategy.py              # 新闻处理策略与流程编排
│   ├── llm_processor.py              # LLM驱动的新闻分析（实体、情感、分类）
│   ├── news_deduplication.py         # 新闻去重检测
│   ├── enhanced_news_scheduler.py    # 增强新闻调度器（并发爬取、LLM分析）
│   │
│   ├── ⏰ 调度与任务模块
│   ├── scheduler.py                  # 定时任务调度器（日常管道、新闻采集）
│   ├── task_manager.py               # 异步任务管理与队列
│   ├── task_scheduler.py             # 任务调度工具
│   │
│   ├── 📊 报告与宏观模块
│   ├── report.py                     # 报告生成与文本摘要
│   ├── macro_pipeline.py             # 宏观新闻观测与特征提取
│   ├── macro_report.py               # 宏观报告生成
│   ├── macro_reporter.py             # 宏观数据报告器
│   ├── macro_model_trainer.py        # 宏观预测模型训练
│   │
│   ├── 🔧 工具与辅助模块
│   ├── mongo_storage.py              # MongoDB 存储与查询
│   ├── stock_profile_enrichment.py   # 股票信息增强
│   ├── stock_profile_validator.py    # 数据质量验证
│   ├── profile_updater.py            # 个股信息更新
│   ├── background_task_queue.py      # 后台任务队列
│   ├── agent_persistence.py          # Agent任务持久化
│   ├── metrics.py                    # 监控指标
│   ├── logging_config.py             # 日志配置
│   │
│   ├── routers/                      # 路由分解（模块化）
│   │   ├── news.py                   # 新闻相关API路由
│   │   └── movers.py                 # 涨跌停等实时行情路由
│   │
│   ├── agents/                       # AI Agent模块（可选扩展）
│   └── __init__.py                   # 包初始化
│
├── scripts/                          # 开发与运维脚本
│   ├── manage.py                     # 项目管理脚本（测试、服务检查等）
│   ├── dev_server.py                 # 开发服务器启动脚本
│   ├── test_real_api.py              # 真实数据API测试
│   ├── diagnose_api.py               # API诊断工具
│   ├── audit_and_fix_articles.py     # 新闻文章审计与修复
│   ├── backfill_*.py                 # 数据回填脚本集合
│   ├── fix_*.py                      # 数据修复脚本集合
│   ├── check_*.py                    # 数据检查脚本集合
│   ├── build_*.py                    # 数据构建脚本集合
│   ├── run_macro_pipeline.py         # 宏观管道执行脚本
│   └── [更多数据治理脚本...]         # 其他数据处理脚本
│
├── tests/                            # 测试模块
│   ├── run_tests.py                  # 测试执行主入口
│   ├── integration/                  # 集成测试
│   │   └── test_api.py               # API集成测试
│   └── [其他测试文件...]
│
├── migrations/                       # 数据库迁移（可选）
├── requirements.txt                  # 依赖声明
├── Dockerfile                        # Docker配置
└── README.md                         # 本文档

```

---

## 核心模块说明

### 数据库与存储

#### `db.py` - 数据库与缓存连接管理
**功能描述**：
- 构建PostgreSQL SQLAlchemy Engine与会话工厂(SessionLocal)
- 提供FastAPI依赖(get_session)用于按请求获取/释放会话
- 提供可选的Redis客户端用于轻量级缓存与节流
- 初始化数据库表结构

**主要函数**：
- `get_db_url()` - 拼接PostgreSQL连接URL
- `get_session()` - FastAPI依赖，获取数据库会话
- `init_database()` - 初始化数据库schema与表
- `get_redis_client()` - 获取Redis连接（可选）

**环境变量**：
```
POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_PORT / POSTGRES_DB
REDIS_HOST / REDIS_PORT / REDIS_DB / REDIS_PASSWORD（可选）
```

#### `models.py` - SQLAlchemy ORM数据模型
**功能描述**：
- 定义所有数据库表的ORM模型
- 包含Stock/Watchlist/PriceDaily/Signal/Forecast/Report等30+表
- 使用SQLAlchemy 2.0风格的类型注解与Mapped字段

**主要模型**：
- `Stock` - 股票基础信息
- `Watchlist` - 用户自选股列表
- `PriceDaily` - 日线行情数据
- `FundFlowDaily` - 资金流向数据
- `Signal` - 技术指标信号
- `Forecast` - 价格预测结果
- `Report` - 分析报告
- `NewsArticle` - 新闻文章
- `Task` - 异步任务
- `StockProfile` - 个股详细信息
- 等等...

#### `mongo_storage.py` - MongoDB文档存储
**功能描述**：
- 异步MongoDB存储客户端
- 支持新闻文章的文档存储与查询
- 支持分析结果存档与历史追踪

**主要方法**：
- `save_article()` - 保存新闻文章到MongoDB
- `archive_analysis()` - 存档LLM分析结果
- `query_articles()` - 查询文章集合
- `get_storage()` - 获取或初始化存储实例

---

### 数据获取

#### `data_source.py` - 多源数据聚合与获取
**功能描述**：
- 统一的数据源抽象层，支持多重回退策略
- 聚合AkShare、Tushare、东方财富、新浪等数据源
- 实现数据标准化、缓存与质量清洗

**主要函数**：
| 函数名 | 功能 |
|--------|------|
| `normalize_symbol()` | 标准化股票代码（加后缀.SH/.SZ） |
| `fetch_daily()` | 获取单只股票日线数据（优先Tushare，回退Akshare） |
| `fetch_fund_flow_daily()` | 获取资金流向数据 |
| `search_stocks()` | 基于代码/名称搜索股票 |
| `get_stock_info()` | 获取股票基础信息 |
| `get_realtime_stock()` | 获取实时L1行情 |
| `get_spot_snapshot()` | 批量获取A股实时快照 |

**返回数据格式**：
- 统一采用标准列：symbol, trade_date, open, high, low, close, pct_chg, vol, amount
- 金额统一为"元"，成交量统一为"股"
- 缺失数据通过多层回退策略补充

---

### 技术分析

#### `signals.py` - 技术指标计算
**功能描述**：
- 计算常用技术指标（RSI、MACD、均线等）
- 生成交易信号与打分

**主要函数**：
| 函数名 | 功能 |
|--------|------|
| `rsi()` | 相对强弱指数（RSI），值域0~100 |
| `macd()` | MACD指标（MACD线、信号线、柱体） |
| `compute_signals()` | 综合信号计算 |

**信号评分**：
- 均线金叉：+20 / 死叉：-20
- RSI偏离50：±15
- MACD金叉：+10
- **交易建议**：
  - score >= 15: "BUY"
  - score <= -15: "TRIM"
  - 其他: "HOLD"

#### `stock_manager.py` - 自选股列表管理
**功能描述**：
- 管理Watchlist与相关的新闻关键词
- 支持批量操作与统计

**主要方法**：
| 方法 | 功能 |
|------|------|
| `add_stock()` | 添加股票到自选列表 |
| `remove_stock()` | 删除自选股 |
| `update_stock()` | 更新股票信息 |
| `list_stocks()` | 列表查询（支持分页、过滤） |
| `batch_add_stocks()` | 批量添加 |
| `get_stock_statistics()` | 统计信息 |
| `create_news_collection_task()` | 为股票创建新闻采集任务 |

---

### 预测与模型

#### `forecast.py` - 基础预测方法
**功能描述**：
- 实现多种基础时间序列预测方法
- 集成SARIMAX与特征回归预测

**主要方法**：
| 方法 | 说明 |
|------|------|
| `sarimax_forecast()` | SARIMAX时间序列预测 |
| `feature_regression_forecast()` | 基于特征的回归预测 |
| `predict_stock_price()` | 统一入口（优先使用增强预测） |

**输出**：
- 预测价格序列
- 置信上下界
- 置信度评分

#### `forecast_enhanced.py` - 增强预测模型
**功能描述**：
- 高级时间序列特征工程
- 多种ML模型集成（神经网络、随机森林、SARIMAX、线性趋势）
- 自动降级与容错机制

**主要方法**：
| 方法 | 说明 |
|------|------|
| `create_sequence_features()` | 构造时间序列特征 |
| `neural_network_forecast()` | 基于MLP的多步预测 |
| `enhanced_feature_regression_forecast()` | 随机森林预测 |
| `predict_stock_price_enhanced()` | 高层API（自动选择最优方法） |

**特征工程**：
- 滞后特征（1-5天）
- 移动平均（MA5/10/20）
- 指数加权平均（EMA）
- 波动率与成交量特征
- RSI风格指标、布林带等

**置信区间计算**：
- 基于历史预测误差
- 支持多种区间宽度（80%、95%等）

#### `model_inference.py` - 模型推理工具
**功能描述**：
- 模型加载与推理管理
- 支持模型版本控制与更新

---

### 新闻处理（核心子系统）

#### `news_service.py` - 新闻搜索与处理服务
**功能描述**：
- 完整的新闻处理管道：搜索→抓取→提取→分析→入库
- 多源新闻搜索（SearXNG等）
- 智能正文提取（readability + CSS选择器 + 域名定制解析）
- 去重检测与数据质量控制

**核心类**：

**NewsSearchService** - 新闻搜索
- `search_news()` - 通用搜索
- `search_stock_news()` - 股票相关新闻
- `search_industry_news()` - 行业新闻

**NewsProcessor** - 新闻处理流程
- URL合法性判别
- HTML/PDF内容抓取与解码
- 正文提取（多种策略回退）
- 编码修复与文本清洗
- 发布时间解析
- 去重检测
- LLM分析集成
- 摘要生成

**主要特性**：
- ✅ 支持PDF文件抓取（pdfminer / pypdf）
- ✅ 多层正文提取策略（readability → CSS → body）
- ✅ 编码检测与修复（mojibake处理）
- ✅ 域名定制解析（如新浪VIP处理）
- ✅ 动态URL过滤规则（TTL缓存）
- ✅ SSL/TLS兼容性回退
- ✅ User-Agent轮换与请求重试

**配置（环境变量）**：
```
SEARXNG_URL                      # SearXNG服务地址
SEARXNG_TIMEOUT                  # 请求超时
WEB_RETRIEVAL_MODE              # legacy | openclaw（Agentic Retrieval）
WEB_RETRIEVAL_FALLBACK_TO_LEGACY # openclaw失败时是否回退旧模式
WEB_AGENT_MAX_URLS              # URL选择上限
WEB_AGENT_SEARCH_TOP_K          # 初始检索候选数
WEB_AGENT_FETCH_CONCURRENCY     # 并发抓取数
WEB_AGENT_USE_LLM_SELECTOR      # 是否用LLM筛URL
WEB_AGENT_USE_LLM_REASONER      # 是否用LLM做阅读推理摘要
WEB_CACHE_DIR                   # search/pages/articles缓存目录
NEWS_HTTP_PROXY                  # HTTP代理（可选）
NEWS_FETCH_RETRIES               # 重试次数
NEWS_FETCH_BACKOFF               # 重试退避间隔
NEWS_USE_LLM                      # 是否启用LLM分析
NEWS_URL_ALLOWLIST/BLOCKLIST     # 白/黑名单
NEWS_URL_FILTER_TTL              # 规则缓存TTL
NEWS_MIN_CN_RATIO                # 中文比例要求
NEWS_SSL_*                       # SSL/TLS回退选项
```

#### `news_crawler.py` - 异步网页爬虫
**功能描述**：
- 异步HTTP请求与内容爬取
- 去重检测（URL + 内容哈希）
- 智能正文提取
- NLP处理（关键词、实体识别、质量评分）

**核心功能**：
| 功能 | 说明 |
|------|------|
| 异步爬取 | 基于httpx.AsyncClient，支持超时/重试/退避 |
| 并发控制 | 限制最大并发数，防止资源耗尽 |
| 去重检测 | URL规范化 + MD5哈希 + 数据库查询 |
| 正文提取 | 预定义CSS选择器 → readability → 段落合并 |
| 内容清洗 | 移除注释/脚本/样式/广告/评论等 |
| 编码检测 | 使用chardet自动推断编码 |
| NLP处理 | 摘要生成、关键词提取、实体识别 |
| 时间解析 | 多种时间格式支持 |

**返回结构**（crawl_article/batch_crawl_articles）：
```json
{
  "status": "success",
  "url": "https://example.com/news/123",
  "url_hash": "md5_hash",
  "crawled_at": "2024-10-24T10:30:00Z",
  "title": "标题",
  "content": "正文纯文本",
  "summary": "摘要",
  "author": "作者",
  "published_date": "2024-10-24T10:00:00Z",
  "keywords": ["关键词1", "关键词2"],
  "entities": ["实体1", "实体2"],
  "content_quality": 0.85,
  "word_count": 1200,
  "domain": "example.com"
}
```

#### `llm_processor.py` - LLM驱动的新闻分析
**功能描述**：
- 使用大语言模型进行高级新闻分析
- 实体识别、情感分析、分类、关键词提取
- 与Azure OpenAI集成（Responses API）

**核心类**：

**NewsAnalysisResult** - 分析结果数据类：
- 基本信息：summary、category
- 实体信息：companies、people、locations、stock_symbols
- 情感分析：sentiment_type、sentiment_score、sentiment_confidence
- 主题与关键词：main_topics、keywords
- 财经特定：financial_metrics、market_impact、relevance_score
- 时间与质量：time_references、content_quality、reliability_assessment

**LLMNewsProcessor** - 处理器类：
| 方法 | 功能 |
|------|------|
| `analyze_news()` | 分析单篇新闻 |
| `batch_analyze()` | 批量分析 |
| `extract_companies()` | 提取公司信息 |
| `extract_sentiment()` | 情感分析 |
| `classify_article()` | 文章分类 |

**配置（环境变量）**：
```
AZURE_OPENAI_ENDPOINT            # Azure端点
AZURE_OPENAI_KEY                 # API密钥
AZURE_OPENAI_DEPLOYMENT          # 部署名
AZURE_OPENAI_API_VERSION         # API版本（默认2025-04-01-preview）
AZURE_OPENAI_MODEL               # 模型名
AZURE_OPENAI_MAX_COMPLETION_TOKENS  # 最大token数
AZURE_OPENAI_TIMEOUT             # 超时时间（秒）
```

**特性**：
- ✅ 并发控制与速率限制
- ✅ 冷却机制与退避策略
- ✅ 多模型支持（gpt-4, gpt-5等）
- ✅ Responses API兼容性

#### `news_deduplication.py` - 新闻去重
**功能描述**：
- 多层去重策略（URL、内容哈希、相似度）
- 检测并标记重复文章
- 支持增量去重

**去重方法**：
- URL规范化 + 哈希匹配
- 内容指纹生成
- 语义相似度计算（可选）

#### `news_strategy.py` - 新闻处理策略
**功能描述**：
- 定义新闻处理的策略与流程
- 支持自定义处理管道

#### `enhanced_news_scheduler.py` - 增强新闻调度
**功能描述**：
- 高并发新闻采集系统
- 支持批量爬取、LLM分析、去重、保存
- 自动容错与降级

**核心方法**：
| 方法 | 功能 |
|------|------|
| `run_daily_news_collection()` | 每日新闻采集流程 |
| `_collect_news_for_stock()` | 单股新闻完整流程 |
| `_crawl_articles_batch()` | 批量爬取文章 |
| `_process_and_save_articles()` | 处理与保存 |
| `run_intelligent_news_collection()` | 智能新闻采集 |
| `get_collection_status()` | 获取统计信息 |

**配置参数**：
- `max_concurrent_crawls` - 最大并发爬取数
- `max_articles_per_stock` - 单股最大文章数
- `crawl_batch_size` - 爬取批大小
- `rate_limit_delay` - 请求延迟

---

### 任务与调度

#### `task_manager.py` - 异步任务管理
**功能描述**：
- 统一管理异步任务创建、调度与执行
- 任务状态生命周期管理（PENDING → RUNNING → COMPLETED/FAILED）
- 并发控制与数据库持久化

**核心类**：

**TaskManager** - 任务管理器：
| 方法 | 功能 |
|------|------|
| `create_task()` | 创建通用任务 |
| `create_report_task()` | 创建报告生成任务 |
| `check_and_create_missing_report_tasks()` | 检查并为缺失报告的股票创建任务 |
| `execute_report_task()` | 执行报告生成 |
| `execute_news_task()` | 执行新闻收集 |
| `process_tasks()` | 分派待处理任务到异步执行 |
| `get_pending_tasks()` | 列取待处理任务 |

**属性**：
- `running_tasks` - 正在执行的任务集合
- `max_concurrent_tasks` - 最大并发限制（默认3）

**任务类型**：
- `REPORT_GENERATION` - 报告生成
- `FETCH_NEWS` - 新闻采集
- 等...

**任务状态**：
- `PENDING` - 等待中
- `RUNNING` - 运行中
- `COMPLETED` - 完成
- `FAILED` - 失败

#### `scheduler.py` - 定时任务调度器
**功能描述**：
- 使用APScheduler的AsyncIOScheduler实现定时调度
- 编排每日数据管道（行情、信号、预测、资金流等）
- 触发新闻采集流程

**核心方法**：
| 方法 | 功能 |
|------|------|
| `run_daily_pipeline()` | 执行完整日常管道 |
| `run_enhanced_daily_news_collection()` | 触发增强新闻采集 |
| `run_intelligent_news_collection()` | 智能新闻采集 |
| `attach_scheduler()` | 将调度器挂载到FastAPI应用 |

**日常管道流程**：
1. 遍历启用的自选股（Watchlist）
2. 拉取近三年日线数据 → UPSERT到prices_daily
3. 计算技术信号 → 写入signals（去重）
4. 使用增强预测模型 → 结果写入forecasts
5. 拉取资金流向 → UPSERT到fund_flow_daily
6. 触发增强新闻采集

**注册的作业**：
| 作业名 | CRON时间 | 功能 |
|--------|---------|------|
| daily_pipeline | CRON_HOUR:CRON_MINUTE（默认16:10） | 主管道 |
| daily_pipeline_post_close | CRON_HOUR2:CRON_MINUTE2（默认16:30） | 收盘后保障 |
| intelligent_news_collection | 每4小时 | 智能新闻采集 |
| legacy_news_collection | 每12小时 | 传统新闻采集（备份） |

**配置（环境变量）**：
```
TZ                              # 调度器时区（默认Asia/Taipei）
FORECAST_AHEAD_DAYS            # 预测天数（默认5）
CRON_HOUR / CRON_MINUTE        # 主管道运行时间
CRON_HOUR2 / CRON_MINUTE2      # 收盘后保障运行时间
```

#### `task_scheduler.py` - 任务调度工具
**功能描述**：
- 支持性的任务调度工具函数
- 补充TaskManager功能

---

### 报告与宏观

#### `report.py` - 报告生成与LLM摘要
**功能描述**：
- 基于价格、信号、预测数据生成分析报告
- 可选的LLM驱动摘要简化

**核心函数**：
| 函数 | 功能 |
|------|------|
| `plain_summary()` | 生成纯文本技术面摘要 |
| `llm_summarize()` | 异步调用Azure OpenAI简化摘要 |
| `generate_report_data()` | 构造结构化报告字典 |

**报告内容**：
- 数据质量评分
- 技术面要点
- 信号建议
- 预测与置信度
- 资金面分析

#### `macro_pipeline.py` - 宏观新闻观测与特征提取
**功能描述**：
- 宏观层面新闻收集与分析
- 特征向量构造
- 长期观测记录

**核心类**：

**MacroTopic** - 宏观主题：
- name、queries、weight、description、related_indices

**MacroObservation** - 宏观观测数据：
- topic、observation_date、article_count
- features、top_keywords、top_entities
- summaries、references

**宏观管道流程**：
1. 定义宏观主题与关键词集
2. 搜索与爬取相关新闻
3. LLM分析与特征提取
4. 聚合生成观测记录
5. 保存到数据库与MongoDB

#### `macro_report.py` 与 `macro_reporter.py` - 宏观报告
**功能描述**：
- 生成宏观经济分析报告
- 支持周期性报告汇总

#### `macro_model_trainer.py` - 宏观预测模型训练
**功能描述**：
- 使用宏观特征训练预测模型
- 支持回测与模型评估

---

### AI与LLM

#### `llm_processor.py` - 新闻LLM分析（已详述上文）

---

### 宏观与策略

#### `mongo_storage.py` - MongoDB存储（已详述上文）

#### `stock_profile_enrichment.py` - 股票信息增强
**功能描述**：
- 增强股票基础信息（融合多源数据）
- 补充行业、概念、历史等信息

#### `stock_profile_validator.py` - 数据质量验证
**功能描述**：
- 验证股票数据的完整性
- 检测异常值与脏数据

#### `profile_updater.py` - 个股信息更新
**功能描述**：
- 定期更新个股基础信息
- 保持数据最新

#### `background_task_queue.py` - 后台任务队列
**功能描述**：
- 异步任务队列管理
- 支持任务优先级与重试

#### `agent_persistence.py` - Agent任务持久化
**功能描述**：
- Agent任务的数据库持久化
- 支持任务恢复与追踪

#### `metrics.py` - 监控指标
**功能描述**：
- 系统运行指标收集
- 性能监控与告警

#### `logging_config.py` - 日志配置
**功能描述**：
- 统一的日志管理
- 支持多级别日志输出

---

### 路由与API

#### `main.py` - FastAPI主应用与路由
**功能描述**：
- FastAPI应用初始化
- 所有HTTP路由定义
- CORS、中间件配置
- 数据库与调度器初始化

**主要路由分类**：

**股票信息相关** (`/api/stocks/*`)：
- GET `/api/stocks` - 列表查询
- GET `/api/stocks/{symbol}` - 单只股票详情
- GET `/api/stocks/{symbol}/profile` - 个股档案
- POST `/api/stocks/search` - 搜索股票

**自选股相关** (`/api/watchlist/*`)：
- GET `/api/watchlist` - 自选股列表
- POST `/api/watchlist` - 添加自选股
- DELETE `/api/watchlist/{symbol}` - 移除自选股
- GET `/api/watchlist/snapshot` - 自选股快照

**行情数据相关** (`/api/prices/*`)：
- GET `/api/prices/{symbol}` - 日线数据
- GET `/api/realtime` - 实时行情

**技术指标相关** (`/api/signals/*`)：
- GET `/api/signals/{symbol}` - 技术信号
- GET `/api/signals/{symbol}/current` - 最新信号

**预测相关** (`/api/forecast/*`)：
- GET `/api/forecast/{symbol}` - 价格预测
- GET `/api/forecast/{symbol}/confidence` - 预测置信度

**报告相关** (`/api/reports/*`)：
- GET `/api/reports/{symbol}` - 股票报告
- GET `/api/reports/{symbol}/history` - 报告历史
- POST `/api/reports/generate` - 生成报告

**新闻相关** (`/api/news/*`)：
- GET `/api/news` - 新闻列表
- GET `/api/news/{article_id}` - 新闻详情
- GET `/api/news/stock/{symbol}` - 个股相关新闻
- POST `/api/news/search` - 搜索新闻
- GET `/api/news/analysis/{article_id}` - 新闻分析结果

**任务相关** (`/api/tasks/*`)：
- GET `/api/tasks` - 任务列表
- POST `/api/tasks` - 创建任务
- GET `/api/tasks/{task_id}` - 任务详情
- POST `/api/tasks/{task_id}/cancel` - 取消任务

**管理员相关** (`/admin/*`)：
- GET `/admin/health` - 健康检查
- GET `/admin/db/init` - 初始化数据库
- GET `/admin/scheduler/status` - 调度器状态
- POST `/admin/scheduler/run-now` - 立即运行任务
- GET `/admin/scheduler/task-stats` - 任务统计

#### `routers/news.py` - 新闻模块路由
**功能描述**：
- 新闻相关的API路由分解
- 减少main.py复杂度

#### `routers/movers.py` - 实时行情与涨跌停
**功能描述**：
- 获取涨跌停个股
- 实时行情缓存与预热

**主要路由**：
- GET `/api/movers/gainers` - 上涨排行
- GET `/api/movers/losers` - 下跌排行
- GET `/api/movers/limit-up` - 涨停个股
- GET `/api/movers/limit-down` - 跌停个股

---

## 快速开始

### 前置要求
- Python 3.9+
- PostgreSQL 12+
- MongoDB 4.4+（可选）
- Redis 6.0+（可选，用于缓存）

### 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 初始化数据库

```bash
# 使用管理脚本初始化
python scripts/manage.py info

# 或直接调用API初始化
curl http://localhost:8081/admin/db/init
```

### 启动服务

**开发环境**：
```bash
# 启动主API服务器（带热重载）
python scripts/dev_server.py --mode main --port 8081

# 或使用项目管理脚本
python scripts/manage.py server --mode main --port 8081
```

**生产环境**：
```bash
# 使用uvicorn启动
uvicorn app.main:app --host 0.0.0.0 --port 8081 --workers 4
```

---

## 环境配置

### 核心配置（必需）

```bash
# PostgreSQL
export POSTGRES_USER=aistock
export POSTGRES_PASSWORD=your_password
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=aistock

# 数据源（默认akshare，可选tushare）
export DATA_SOURCE=akshare
export TUSHARE_TOKEN=your_token  # 若使用tushare

# 调度器
export TZ=Asia/Shanghai
export FORECAST_AHEAD_DAYS=5
export CRON_HOUR=16
export CRON_MINUTE=10
```

### 新闻处理配置（可选，但推荐）

```bash
# SearXNG搜索引擎
export SEARXNG_URL=http://localhost:10000
export SEARXNG_TIMEOUT=30

# 新闻处理
export NEWS_USE_LLM=true
export NEWS_FETCH_RETRIES=3
export NEWS_FETCH_BACKOFF=2
export NEWS_URL_FILTER_TTL=3600
```

### LLM配置（可选，用于AI分析）

```bash
# Azure OpenAI
export AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com
export AZURE_OPENAI_KEY=your_api_key
export AZURE_OPENAI_DEPLOYMENT=gpt-4
export AZURE_OPENAI_API_VERSION=2025-04-01-preview
export AZURE_OPENAI_MAX_COMPLETION_TOKENS=1024
export AZURE_OPENAI_TIMEOUT=30
```

### MongoDB配置（可选，用于文档存储）

```bash
export MONGODB_URL=mongodb://localhost:27017
export MONGODB_DB=aistock
```

### Redis配置（可选，用于缓存）

```bash
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
export REDIS_PASSWORD=  # 若有密码
```

---

## 常用命令

### 管理脚本

```bash
# 显示项目信息
python scripts/manage.py info

# 运行单元测试
python scripts/manage.py test --type unit

# 运行集成测试
python scripts/manage.py test --type integration

# 检查服务状态
python scripts/manage.py check

# 启动开发服务器
python scripts/manage.py server --mode main --port 8081
```

### 数据检查脚本

```bash
# 检查股票价格数据
python scripts/check_prices.py

# 检查资金流向数据
python scripts/check_fundflow.py

# 检查报告数据
python scripts/check_reports.py

# 检查数据库连接
python scripts/test_db_connection.py

# 诊断API问题
python scripts/diagnose_api.py
```

### 数据治理脚本

```bash
# 回填价格数据
python scripts/backfill_prices.py

# 回填资金流向
python scripts/backfill_fundflow.py

# 修复股票信息
python scripts/fix_watchlist_names.py

# 构建股票档案
python scripts/build_stock_profiles.py

# 清理无效数据
python scripts/cleanup_invalid_formats.py
```

### 宏观与预测

```bash
# 执行宏观管道
python scripts/run_macro_pipeline.py

# 训练宏观模型
python scripts/train_macro_model.py

# 训练信号模型
python scripts/train_signal_models.py
```

### 新闻处理

```bash
# 刷新新闻
python scripts/refresh_news.py

# 审计并修复文章
python scripts/audit_and_fix_articles.py

# 检查MongoDB
python scripts/check_mongo_agent_reports.py
```

---

## 文件关键字快速查询

| 功能需求 | 核心文件 |
|---------|--------|
| 数据库连接与ORM | `db.py`、`models.py` |
| 获取行情数据 | `data_source.py` |
| 计算技术指标 | `signals.py` |
| 生成预测 | `forecast.py`、`forecast_enhanced.py` |
| 新闻搜索与爬虫 | `news_service.py`、`news_crawler.py` |
| LLM新闻分析 | `llm_processor.py` |
| 任务管理 | `task_manager.py` |
| 定时调度 | `scheduler.py` |
| 报告生成 | `report.py` |
| MongoDB存储 | `mongo_storage.py` |
| 自选股管理 | `stock_manager.py` |
| 宏观分析 | `macro_pipeline.py`、`macro_report.py` |
| 路由与API | `main.py`、`routers/` |
| 开发测试 | `scripts/dev_server.py`、`scripts/manage.py` |

---

## 常见问题与故障排查

### Q: 如何添加新的数据源？
**A**: 在 `data_source.py` 中扩展 `fetch_daily()` 与 `fetch_fund_flow_daily()` 函数，添加新的数据源回退逻辑。

### Q: 如何自定义技术指标？
**A**: 在 `signals.py` 中定义新函数，并在 `compute_signals()` 中调用。

### Q: 如何集成新的预测模型？
**A**: 在 `forecast_enhanced.py` 中实现新的预测方法，并在 `predict_stock_price_enhanced()` 中添加回退逻辑。

### Q: 如何添加新的新闻源？
**A**: 修改 `news_service.py` 中的 `NewsSearchService`，或在 `news_crawler.py` 中添加域名定制解析器。

### Q: 如何禁用LLM分析？
**A**: 设置环境变量 `NEWS_USE_LLM=false`，系统会自动回退到本地分析。

### Q: 如何监控任务执行状态？
**A**: 调用 `/admin/scheduler/status` 与 `/admin/scheduler/task-stats` 获取实时状态。

---

## 性能优化建议

1. **数据库索引**：在 `PriceDaily(symbol, trade_date)` 等高频查询列上添加组合索引
2. **缓存策略**：使用Redis缓存股票基础信息与实时快照
3. **异步处理**：对长时间任务（如批量报告生成）使用后台队列
4. **并发控制**：调整 `EnhancedNewsScheduler` 的 `max_concurrent_crawls` 参数
5. **日志级别**：生产环境设置为 `WARNING` 级别减少I/O开销

---

## 许可与免责

本项目提供股票数据处理与分析工具，不构成投资建议。使用者需自行承担使用本系统产生的一切后果。

---

## 相关文档

- [前端README](../frontend/README.md)
- [项目总README](../README.md)
- [API文档](./docs/API.md)（若存在）
- [贡献指南](../CONTRIBUTING.md)（若存在）

---

**最后更新**: 2024年10月24日  
**维护者**: AI Stock Analysis Team  
**版本**: 1.0.0
