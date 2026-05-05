# 🚀 AI股票分析系统（全中文说明）

一个面向中国A股市场的智能分析与新闻监控平台，集成 AI 预测、技术指标、智能新闻收集与情感分析、任务调度与可视化前端，支持本地与 Docker 一键部署。

---

## ✨ 核心功能

- 🤖 AI预测与报告：神经网络多步预测（含置信区间）、自动生成分析报告
- 📊 技术指标与信号：RSI/MACD/均线/布林带等指标与多维评分
- 📰 新闻管理中心：多源聚合、情感分析、去重、按股票归档与批量操作
- 🌐 宏观新闻观测：跨主题采集、情绪聚合、特征生成与每日回归训练
- 🔄 自动化调度：每日/小时级采集与预测，任务状态与仪表盘
- 💾 混合存储：PostgreSQL + MongoDB + Redis（可选）
- 💻 现代前端：React + TypeScript + Vite + TailwindCSS

> 🔍 新增：Top20 涨跌+新闻+宏观 智能分析 Agent（严格 JSON 模式 + 回退 + REST 触发），详见 `AGENT_USAGE.md`。

---

## 🧱 技术栈

- 后端：FastAPI、SQLAlchemy、PostgreSQL、Redis、MongoDB（可选）
- AI/数据：scikit-learn、pandas、NumPy
- 前端：React 18、TypeScript、Vite、Recharts、TailwindCSS
- 部署：Docker Compose、Nginx

---

## ⚡ 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/mxmore/aistock-analysis-system.git
cd aistock-analysis-system
```

### 2. 配置环境

```bash
cp .env.example .env
# 按需修改数据库、SearXNG、OpenAI等配置
```

### 3. 使用 Docker 一键启动（推荐）

```bash
docker compose up -d --build
```

访问：

- 前端：[http://localhost:3000](http://localhost:3000)（或 [http://localhost:8081](http://localhost:8081)）
- 后端API：[http://localhost:8081](http://localhost:8081)
- API文档：[http://localhost:8081/docs](http://localhost:8081/docs)
- SearXNG（新闻搜索）：[http://localhost:10000](http://localhost:10000)（如已启用）

### 本地开发（可选）

后端：

```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Windows PowerShell
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8081
```

前端：

```bash
cd frontend
npm install
npm run dev
```

### 在 Conda 环境中编译/启动前端（Windows）

如果你使用 Conda 并已创建 `node1817_env`（包含 Node.js 18.x）：

```powershell
# 激活 Conda 环境（在 Anaconda Prompt 或 PowerShell 中）
conda activate node1817_env

# 进入前端目录并安装依赖
cd frontend
npm ci ; if ($LASTEXITCODE -ne 0) { npm install }

# 开发启动（默认端口 5173）
npm run dev

# 生产构建
npm run build

# 本地预览已构建产物（http://localhost:5173）
npm run preview
```

注意：如果后端不在同一端口，请在浏览器控制台执行或在 HTML 模板里设置 `window.API_BASE` 指向后端，例如：

```html
<script>
  window.API_BASE = 'http://localhost:8081';
</script>
```

---

## 文档归档入口

- 历史阶段性总结与报告已归档到 `docs/archive/2025-Q4/`。
- 当前归档包含：
  - `API_OPTIMIZATION_SUMMARY.md`
  - `PROJECT_RESTRUCTURE_SUMMARY.md`
  - `QWEN3_INTEGRATION_SUMMARY.md`
  - `SYMBOL_IMPLEMENTATION_REPORT.md`
  - `SYMBOL_UPDATE_SUMMARY.md`
  - `SCRIPT_FIXES.md`
  - `QUICK_START_FIXED.md`
  - `UI_OPTIMIZATION_UPDATE.md`
  - `README_FRONTEND_OPTIMIZATION.md`
  - `STOCKS_PAGE_ON_DEMAND_LOADING.md`
  - `STOCK_UPDATE_DELIVERY.md`
- 后续新增阶段性总结文档，建议按季度归档到 `docs/archive/YYYY-QX/`。

---

## 📁 目录结构

```text
aistock-analysis-system/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI主应用（含新闻/任务/报告等API）
│   │   ├── models.py              # ORM模型
│   │   ├── news_service.py        # 新闻搜索与入库
│   │   ├── news_strategy.py       # 智能策略与调度
│   │   ├── enhanced_news_scheduler.py
│   │   ├── news_deduplication.py  # 去重逻辑
│   │   ├── llm_processor.py       # LLM分析
│   │   └── mongo_storage.py       # MongoDB增强存储（可选）
│   └── scripts/
├── frontend/
│   └── src/ui/                    # App.tsx、Dashboard.tsx、News组件等
├── infra/                          # 基础设施配置
│   ├── initdb/                     # PostgreSQL初始化脚本
│   ├── mongodb/                    # MongoDB初始化脚本
│   └── searxng/                    # SearXNG配置
├── docker-compose.yml              # 一键编排
└── README.md
```

---

## 📰 新闻管理中心（前端）

新闻的集中管理与分析界面，支持统计、筛选、列表与批量操作，并与智能采集协同工作。

### 功能

- 概览统计：总文章数、今日文章数、情感分布（积极/消极/中性）、热门来源与热门股票
- 列表筛选：关键字、时间、来源、类别、情感类型、关联股票，支持分页（limit/offset）
- 交互操作：收藏/取消收藏、标记已读/未读、批量操作、刷新/隐藏统计
- 智能采集：一键执行“智能采集/每日采集”，查看采集状态与任务进度

### API映射（后台）

- 统计/枚举：
  - `GET /api/news/stats`、`GET /api/news/sources`、`GET /api/news/categories`、`GET /api/news/sentiment-types`
- 列表/过滤：
  - `GET /api/news/articles?category&sentiment&symbol&limit&offset`
- 操作/批量：
  - `POST /api/news/{id}/bookmark`、`POST /api/news/{id}/read`、`POST /api/news/batch-update?action=...`、`DELETE /api/news/{id}`
- 采集/策略：
  - `POST /api/news/collect/intelligent`、`POST /api/news/collect/daily`、`GET /api/news/collection/status`、`GET /api/news/strategies`、`POST /api/news/strategies/execute/{name}`
- 个股情感：
  - `GET /api/news/sentiment/{symbol}?days=7`
- Mongo存档（可选）：
  - `GET /api/storage/stock-news/{stock_symbol}`、`GET /api/storage/stock-statistics/{stock_symbol}`、`POST /api/storage/cleanup?days_to_keep=90`

---

## 📈 宏观情绪仪表盘（前端）

仪表盘新增“宏观”视图，可视化展示跨主题的宏观新闻情绪与模型训练结果，帮助快速评估每日宏观信号。

### 功能亮点

- **情绪总览**：统计宏观主题覆盖数量、文章篇目、平均情绪以及最新模型运行次数，并标记存储连接状态。
- **主题洞察卡片**：为每个宏观主题展示情绪趋势、积极/中性/消极占比、关键词、关联实体、摘要要点与核心参考文章。
- **模型训练结果**：列出近期模型运行记录，突出关键指标、重要系数、校准信息与备注说明。
- **自动刷新**：宏观视图自动每 3 分钟刷新一次，可手动点击“刷新”即时获取最新数据。
- **每日宏观日报**：新增日报面板，可在前端选择历史快照或实时生成最新报告，快速查看亮点摘要、核心指标、热门/风险主题。

### 数据来源

- API：`
  GET /api/macro/overview`
  - `topics[]`：宏观主题观测摘要（情绪、关键词、参考链接等）
  - `model_runs[]`：模型训练结果（指标、系数、备注）
- API：`GET /api/macro/report`

### 使用提示

- 若后端未配置 MongoDB 或尚未运行宏观采集/训练任务，前端会提示“暂无宏观观测记录”。
- 请确保 `window.API_BASE` 指向包含 `/api/macro/overview` 的后端服务地址。
- 如需调整刷新频率，可修改 `useMacroOverview` Hook 中的 `autoRefreshMs` 参数。

---

## 🌐 宏观新闻观测与每日训练

宏观层面的新闻会通过 `backend/app/macro_pipeline.py` 组合 SearXNG 搜索、内容爬取与 LLM 分析，生成跨主题的情绪/关键词特征并落库（Mongo `macro_observations` 集合）。随后 `backend/app/macro_model_trainer.py` 会加载这些特征，结合指定大盘指数的收益率作回归训练与校准。

### 运行方式

- 每日采集与特征生成：

  ```powershell
  cd backend
  python -m scripts.run_macro_pipeline
  ```

- 模型训练与校准：

  ```powershell
  cd backend
  python -m scripts.train_macro_model
  ```

  两个脚本均可被调度器或 CI 任务调用，也可在 `APScheduler` 中按日程触发。
  默认情况下，调度器会在每日 **19:45** 运行宏观观测流水线、在 **20:15** 运行模型训练，可通过 `MACRO_CRON_HOUR/MACRO_CRON_MINUTE` 与 `MACRO_TRAIN_CRON_HOUR/MACRO_TRAIN_CRON_MINUTE` 覆写。

### 核心环境变量（按需覆写）

| 变量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `MACRO_NEWS_TIME_RANGE` | `day` | 搜索时间窗（SearXNG time_range 参数） |
| `MACRO_MAX_ARTICLES` | `20` | 每个主题保留的文章上限 |
| `MACRO_ANALYSIS_BATCH` | `5` | LLM 批量分析的大小 |
| `MACRO_CRAWL_CONCURRENCY` | `4` | 内容抓取的最大并发数量 |
| `MACRO_MIN_RELEVANCE` | `0.2` | 过滤文章时的最低相关性阈值 |
| `MACRO_MAX_KEYWORDS` | `10` | 聚合报告中保留的关键词数量 |
| `MACRO_MAX_REFERENCES` | `8` | 每日摘要中保留的参考新闻数 |
| `MACRO_TARGET_SYMBOL` | `000300.SH` | 训练时的目标指数（默认沪深300） |
| `MACRO_FORECAST_HORIZON` | `1` | 预测的提前步数（单位：交易日） |
| `MACRO_LOOKBACK_DAYS` | `180` | 训练样本回溯天数 |
| `MACRO_MODEL_NAME` | `macro_linear_regression` | 模型名称（用于记录与持久化） |
| `MACRO_USE_RIDGE` | `false` | 是否使用 Ridge 回归（否则为 LinearRegression） |
| `MACRO_SENTIMENT_FLOOR` | `-1` | 情绪得分的下限（截断噪声） |
| `MACRO_SENTIMENT_CAP` | `1` | 情绪得分的上限 |
| `MACRO_CRON_HOUR` | `19` | APScheduler 中宏观观测任务的小时 |
| `MACRO_CRON_MINUTE` | `45` | APScheduler 中宏观观测任务的分钟 |
| `MACRO_TRAIN_CRON_HOUR` | `20` | APScheduler 中宏观训练任务的小时 |
| `MACRO_TRAIN_CRON_MINUTE` | `15` | APScheduler 中宏观训练任务的分钟 |

训练结果会写入 `macro_model_runs` 集合，包含系数、验证指标、校准偏移等信息，可用于生成报告或前端可视化。

---

## 🔌 API 概览（节选）

- 报告与价格：
  - `GET /api/report/{symbol}`、`GET /api/report/{symbol}/full`、`GET /prices/{symbol}`
- 任务与仪表盘：
  - `GET /api/tasks/status`、`GET /api/dashboard/reports`、`GET /api/dashboard/tasks`
- 新闻：见“新闻管理中心（前端）→ API映射”

完整接口请参见后端 [http://localhost:8081/docs](http://localhost:8081/docs)。

### 🆕 每日分析（Daily Analysis Page）

前端新增“每日分析”模块（导航按钮：每日分析），聚合以下内容：

- 最新智能 Agent 结果（Top20 股票列表、简要摘要、生成时间、诊断信息）
- 动态股票池分页浏览（支持多选 Symbol）
- 批量在线预测（选择若干股票后点击“预测”触发 `/api/models/predict` 返回多个 horizon 结果）
- 预测结果表格（显示 horizon、预测值、上涨概率 prob_up（如后端提供））

相关新增/使用中的后端接口：

| 功能 | 方法 | 路径 | 说明 |
| ---- | ---- | ---- | ---- |
| 最新 Agent 报告 | GET | `/api/agent/latest` | 返回智能分析最新结构化/Markdown 内容与 Top20 列表 |
| Agent 运行（已存在） | POST | `/api/agent/run` | 手动触发一次 Agent 生成流程（如已开放） |
| 股票池分页 | GET | `/api/stock-pool?page=1&page_size=50&sort=days_active&order=desc` | 返回成员、首次/最近出现、活跃天数、行业 |
| 单个股票画像 | GET | `/api/stock-profile/{symbol}` | 返回已填充的行业/描述画像（如已存在） |
| 刷新股票画像 | POST | `/api/stock-profile/{symbol}/refresh` | 触发重新抓取/更新画像（可选） |
| 批量模型预测 | POST | `/api/models/predict` | Body: `{ "symbols": ["AAA"], "horizons": [1,5,10] }` |

前端实现要点：

- `frontend/src/config/api.ts` 新增 `AGENT` / `STOCK_POOL` / `MODELS` 端点常量
- `frontend/src/api/dailyAnalysis.ts` 封装 `fetchLatestAgentReport`、`fetchStockPoolPage`、`fetchModelPrediction`
- `frontend/src/ui/DailyAnalysisPage.tsx` 渲染概览、股票池表、预测表
- 采用轻量表格 + checkbox 多选；预测按钮在空选或加载中禁用
- 预测结果按 (symbol,horizon) 展开行，prob_up 用颜色提示（>55% 绿色，<45% 红色）

可扩展方向：

- 增加行业筛选（在调用 `fetchStockPoolPage` 时传递 industry 参数）
- 增加排序 UI（按 `days_active`、`first_seen`、`symbol` 等）
- 为预测结果添加误差区间、特征重要性（若后端返回）
- 添加“导出 CSV”按钮快速导出股票池或预测结果

> 注意：若后端暂未返回 `prob_up` 字段，前端会显示 `-`；返回后自动高亮。

#### 🔄 Agent 报告自动生成机制

当页面首次加载且 `GET /api/agent/latest` 无可用报告文件时，前端会自动：

1. 调用 `POST /api/agent/run` 触发一次生成（默认 `strict_json=false`）。
2. 每 2.5 秒轮询 `GET /api/agent/status/{job_id}`。
3. 状态进入 `succeeded` 或 `failed` 后，延迟 ~1.2 秒重新获取最新报告。

界面行为：

- “生成报告” 按钮可手动再次触发运行；进行中显示“生成中…”。
- 无报告时展示提示并自动启动一次生成。

排错建议：

- 长时间卡在“生成中…”：检查后端日志 `_run_agent_job` 是否异常。
- 轮询状态始终 `running`：查看是否超出并发限制（配置的最大运行数），可稍后重试。
- 生成成功仍无内容：确认 `agent_reports/` 目录下是否写入 `agent_report_*.json`，以及进程是否有写权限。

禁用自动生成（可选）：

- 在 `DailyAnalysisPage.tsx` 中找到 `autoRunRef` 使用处，直接提前 `return` 终止逻辑，或增加一个环境开关判断。

路径注意事项：

默认报告输出目录与后端扫描目录一致：仓库根目录下 `agent_reports/`。脚本 `backend/app/scripts/top20_llm_agent_full.py` 现已强制将 `AGENT_REPORT_DIR` 默认为仓库根目录（除非显式覆盖）。若你之前版本运行过并生成在 `backend/agent_reports/`，请将旧文件移动到根目录的 `agent_reports/` 以便 `/api/agent/latest` 可读取。


### ⏱ 前端时间区间裁剪逻辑（价格走势 & 预测区间）

报告接口 `/api/report/{symbol}/full?timeRange=` 会根据所选区间返回历史 + 预测数据。为保证稳定性，后端可能会在某些区间额外返回「缓冲」天数（用于指标计算或减少重复请求）。前端在渲染主图表前，会执行一次严格裁剪，确保展示的历史数据数量与用户选择一致：

| timeRange | 展示交易日数 | 说明 |
|-----------|--------------|------|
| 5d        | 5            | 最近 5 个交易日 |
| 1m        | 22           | 约 1 个月（22 个交易日）|
| 3m        | 66           | 约 3 个月 |
| 6m        | 132          | 约 6 个月 |
| 1y        | 250          | 约 1 年 |
| all       | 不裁剪       | 全部历史 |

实现细节：

1. 文件：`frontend/src/ui/utils/rangeSlice.ts` 暴露 `sliceByTimeRange()` 与映射常量。
2. 主页面 `App.tsx` 在合并历史与预测数据前调用该工具对 `price_data` 进行裁剪，然后再追加预测点。
3. 预测区间（未来点）总是完整显示，不受历史裁剪影响。
4. 单元测试：`rangeSlice.test.ts` 与 `rangeSliceAll.test.ts` 覆盖 5d 及全部范围、边界与不可变性。

这样做的好处：

* 后端可自由调整内部 buffer/预取长度，而不会影响最终 UI 呈现的“近 5 日 / 近 1 月”语义。
* 避免因回测或指标计算需要而无意扩展用户视图范围。
* 提高前端行为一致性（所有区间均使用统一的裁剪函数）。

如需修改某个区间的交易日数，只需调整 `TRADING_DAY_RANGE` 常量并更新（或新增）对应测试用例即可。

### 额外健康检查

- `GET /api/llm/health`：检查 LLM 集成（Azure Responses API）是否可用，返回服务类型（azure/local/none）、端点、API 版本、模型/部署名、令牌上限、是否可用、响应预览等。

### 新闻 URL 过滤配置

可通过环境变量控制新闻链接的过滤策略：

- `NEWS_URL_ALLOWLIST`：逗号分隔的子串；设置后，只有包含任一子串的 URL 才会被允许。例如：`tw.stock.yahoo.com/news/,finance.yahoo.com/news/`
- `NEWS_URL_BLOCKLIST`：逗号分隔的子串；任何包含任一子串的 URL 都会被阻止。例如：`/quote/,/keywords/,/tag/`

---

## 🚀 部署与配置

1) 复制并修改 `.env`：数据库、SearXNG、AI服务（Azure OpenAI 等）
2) 运行 `docker compose up -d --build`
3) 验证服务：访问前端/后端/API文档

注意：开发环境可选择 MongoDB 无鉴权运行；生产环境务必开启账号与数据保留策略。

---

## ❓ 常见问题（FAQ）

- `/api/news/stats` 返回 500？
  - 请确认数据库表结构一致；`related_stocks` 为 JSONB，统计查询使用 `jsonb_array_elements_text`。
- 新闻日期为 1970-01-01？
  - 多为 `published_at` 缺失导致，请在采集/解析阶段补充时间字段。
- 智能采集无结果？
  - 检查 SearXNG 服务与网络可用性，或查看 `/api/news/collection/status`。

---

## 📄 许可证与免责声明

- 本项目采用 MIT License，仅供学习与研究，不构成任何投资建议。
- 市场有风险，投资需谨慎；请结合自身情况理性决策。

---

Made for A股研究与学习 ✨

---

## 🎯 项目目标与架构路线图（面向A股趋势预测）

本项目的核心目标：持续、尽可能全面地采集与理解财经信息，通过 AI（含 LLM）将非结构化文本转为结构化、可量化的要素与事件，用于构建和训练面向 A 股个股的趋势预测模型，并在在线/批处理场景中稳健服务。

### 1) 端到端流程（从采集到上线）

- 采集层：多源抓取（交易所/公告、主流媒体、券商研报、公司IR、监管、宏观日历、社区UGC、替代数据），具备 RSS/站点地图/列表解析、反爬与限流、JS 渲染回退。
- 清洗与质量层：正文抽取、语言与编码识别、时间/来源规范化；非文章过滤（黑名单+轻量分类）；内容去重（哈希/相似度）；质量仪表板与告警。
- 结构化抽取层：LLM+规则混合抽取到统一 JSON Schema（实体、事件、指标、情绪、主题、引用与可信度），带约束验证与回退（重试/小模型/规则）。
- 特征与标签层：时序与图谱特征（事件计数与时衰、主题与情绪、跨文档共现、市场上下文），与目标标签（未来 t+N 收益、方向分类）构建与存储。
- 模型训练与评估：时间序列交叉验证/滚动回测，避免信息泄露；指标（IC、HitRate、PnL、回撤）与显著性检验；模型集成与稳健性分析。
- 上线与 MLOps：任务编排、特征仓与模型注册、在线推理与批处理、缓存与成本控制、全链路日志与合规。

成功标准（示例，可按阶段调整）

- 覆盖率：重点源覆盖 > 90%，公告类延迟 < 10 分钟，媒体类 < 30 分钟。
- 质量：正文抽取成功率 > 98%，非文章误收率 < 1%，重复率 < 2%。
- 结构化：关键字段（日期/金额/股票）准确率 > 95%，事件类型召回 > 85%。
- 预测：月度滚动 IC > 0.02、HitRate > 53%、信息比 > 0.4。

### 2) 数据源编目与优先级

- A 级（强信号/可交易）：上/深交所、巨潮资讯（公告、停复牌、问询函、回购、定增、质押、投资者关系活动等），证监会/央行/统计局/发改委等；公司 IR；权威媒体（每经、上证报、新华社、路透等）。
- B 级（广覆盖/补充）：门户财经频道（新浪/腾讯/网易/搜狐）、行业与区域媒体（36氪、界面、财新等）。
- C 级（UGC/替代数据，降权）：雪球、东方财富股吧、贴吧等；招聘、舆情、社交、电商榜单、卫星等（预算与合规允许时）。

抓取策略：优先 RSS/站点地图；否则稳态列表解析（CSS/XPath）+ 回退正文定位；限流与重试、指纹/UA 轮换与缓存；ETag/Last-Modified/正文哈希变更感知。

### 3) 稳健正文抽取与 JS 回退

- 规则 + readability-lxml + 站点适配；必要表格以 CSV 化附带关键数值；保留引用位置（offset）。
- 对 JS 门控站点（如报价/图表页），无法抽取正文时标记非文章并跳过，避免浪费 LLM 调用。
- 自动字符集与语言识别，必要时简繁转换。

### 4) 非文章与噪声过滤、去重

- 黑名单：域/路径级非文章 URL 家族预过滤（如 quote/概念/公司资料/列表页/日历页/UGC Hub 等）；采集前与入库前双重拦截。
- 轻量分类：基于标题/正文长度、DOM 密度、关键词（如“请启用 JavaScript”、“公司高管”、“行情中心”、“报价”等）判别；阈值可调。
- 去重：URL 规范化哈希；正文指纹（MinHash/SimHash）近重复聚类；保留最早或信息量更高版本。

### 5) LLM 结构化抽取（可验证/可回退）

统一 Schema（示意）：

```json
{
  "id": "...", "url": "...", "source": "...", "published_dt": "...",
  "entities": {"companies": [{"name": "...", "ticker": "..."}], "people": [], "locations": []},
  "events": [{"type": "投资/并购/回购/中标/产能/诉讼/...", "time": "...", "values": {"amount": 1.23e8, "pct": 0.12}, "counterparties": ["..."]}],
  "financial_metrics": {"revenue": {"value": 1.23e9, "yoy": 0.15}, "net_income": {"value": 2.3e8, "yoy": -0.05}},
  "sentiment": {"type": "positive|neutral|negative", "score": 0.62},
  "topics": ["AI", "新能源"],
  "confidence": {"extraction": 0.9, "source_rank": "A"},
  "quotes": [{"text": "...", "start": 120, "end": 180}],
  "tables": [{"name": "...", "csv": "..."}]
}
```

执行策略：JSON Schema 硬约束提示；第 1 次用中等模型，第 2 次回退小模型+规则抽取关键字段，第 3 次入人工/死信队列（可选）。
验证策略：数值/文本核对（金额/百分比回查原文）、实体对齐证券主表（歧义消解）、事件字典校验、时区与交易日口径对齐。
成本控制：正文哈希缓存、按源/主题分层缓存、热点源小模型优先。

### 6) 特征工程与标签

- 文本/情绪：文章级与公司级近 N 日情绪均值/极值、主题分布、关键词向量。
- 事件强度：事件计数与时衰、金额对数尺度、同业分位数。
- 共现图谱：公司-事件-主题三部图共现度与传播路径。
- 市场上下文：波动率、换手、指数/行业因素、宏观脉冲变量。

标签设计：

- 二分类方向（t+1/t+5/t+10 交易日收益正负，阈值 epsilon 可设）。
- 回归（未来收益百分比/alpha）。
- 事件窗口（公告用事件窗，媒体用自然日/交易日滑窗）。

注意：严格避免信息泄露（特征生成仅使用当时可得信息与滞后口径；滚动切片构造训练/验证集）。

### 7) 模型与评估

- 候选：LightGBM/XGBoost、时间卷积/Transformer、图模型（预算允许时）；多模型集成。
- 验证：时间序列交叉验证/滚动回测；IC/RankIC、HitRate、Precision@K、策略收益/回撤；组内（行业/市值）分层与显著性检验。
- 消融与漂移：特征消融评估贡献；特征分布漂移与 PSI 监控。

### 8) MLOps 与成本/合规

- 编排：抓取→清洗→结构化→入库→特征→训练/推理；失败重试与告警。
- 特征仓：离线（Parquet/Delta）+ 在线（Redis/特征服务）。
- 模型注册：版本、指标、A/B 与影子发布，可回滚。
- 日志与审计：采集/抽取/Prompt 记录；来源与版权标注；遵循 robots/许可条款。
- 成本：LLM 调用阈值与限额，缓存命中率与单文档成本监控。

### 9) 近期落地改造（与本仓库对齐）

- 后端默认黑名单：将已识别的非文章 URL 家族（报价/概念/公司资料/列表页/日历页/UGC Hub 等）加入后端持久黑名单，在采集前与入库前过滤。
- JS 门控判别：正文出现“请启用 JavaScript”等直接标记非文章并跳过。
- 内容哈希去重：对 `backend/app/news_service.py`/`data_source.py` 接入正文哈希与近重复检查。
- 结构化抽取任务化：抽取/验证/回退封装为可重试任务（含限流与死信队列）。
- 质量仪表板：每日源覆盖率、非文章拦截率、重复率、抽取成功率、LLM 失败与重试率、成本与延迟。
- 脚本对齐：`scripts/extended_news_cleanup.py` 已内置多类非文章模式；建议将关键模式同步为后端黑名单以源头治理。

### 10) 开发守则（持续对齐目标）

1. 任何新增数据源/接口，必须明确其“是否为正文内容”，避免引入纯列表/行情/资料页。
2. 提交新功能时，说明如何提升“覆盖率/可用率/结构化准确率/成本效率”四类指标之一。

---

## 📦 动态股票池与公司画像（Stock Pool & Profiles）

为支持对高信号标的的持续跟踪，系统内置“动态股票池”机制：

### 组成要素

- StockPoolMember：记录某标的首次进入 Top20 的日期、最近出现日期与退出日期（若长期未再出现可标记退出）。
- StockProfile：一次性/按需的公司基础与竞争画像（行业、子行业、产品、竞品、风险要点、业务概述等），可刷新。
- StockDailyFeature：新增列 `in_stock_pool`, `industry` 以供特征工程与模型使用。

### 生成流程

1. Agent 成功运行 → 触发脚本 `update_stock_pool.py`：
   - 解析最新 `agent_report_*.json` 提取当日 Top20 标的集合。
   - 新标的写入（first_seen_date=今日）；已在池中标的更新 last_seen_date。
   - 可扩展逻辑：连续 N 日未出现即设置 `exit_date`。
2. 新标的调用 `enrich_stock_profile.py` 生成占位 Profile（后续可替换为 LLM 或外部数据源增强）。
3. `build_daily_features.py` 在每日特征生成时联表：
   - 若标的仍活跃（exit_date IS NULL）→ `in_stock_pool=True`。
   - 若存在公司画像 → 填充 `industry` 字段。

### 使用 API

- 获取当前池：`GET /api/stock-pool?active=true&since=2025-01-01&limit=200`
- 获取单个公司画像：`GET /api/stock-profile/{symbol}`
- 刷新/创建画像：`POST /api/stock-profile/{symbol}/refresh`

增强参数（自 2025-10-08）：

| 参数 | 说明 |
| ---- | ---- |
| `offset` | 分页偏移（默认 0） |
| `sort` | 排序字段：`first_seen_date` | `last_seen_date` | `symbol` |
| `order` | `asc` / `desc` |
| `industry` | 精确行业过滤（与 `StockProfile.industry` 匹配） |

返回示例（/api/stock-pool）：
```json
{
  "count": 3,
  "rows": [
    {"symbol": "600519.SH", "first_seen_date": "2025-10-07", "last_seen_date": "2025-10-08", "exit_date": null, "industry": "白酒"},
    {"symbol": "000001.SZ", "first_seen_date": "2025-10-06", "last_seen_date": "2025-10-08", "exit_date": null, "industry": null}
  ]
}
```

### 特征工程对接

- 模型可直接使用 `in_stock_pool` 作为二元特征（表示近期高关注度/异常波动集中度）。
- `industry` 可用于分层、行业内归一化或构造行业哑变量。
- 后续可加入：行业内相对情绪强度、同池标的共振因子、交叉事件计数等衍生特征。

### 后续增强建议

- 画像 enrichment：调用企业年报 / 研报摘要 / LLM 总结（多源合并 + 去重）；加入可信度评分。
- 退出逻辑：设置阈值（如 15 个交易日未再入池）自动写入 exit_date，并支持 `/api/stock-pool?active=false` 查询历史成员。
- 质量监控：统计每日新增/存量/退出、画像覆盖率、行业分布变化。
- 增量同步：若行业或产品线在外部源更新，自动刷新 `StockProfile` 并写入变更日志。

---

### 🔄 升级与迁移指南（Stock Pool 功能）

1. 拉取最新代码后执行一次迁移（任选其一）：
  - Python 方式（推荐，可幂等）：
    ```bash
    python backend/scripts/migrate_stock_pool_schema.py
    ```
  - SQL 文件方式（PostgreSQL）：
    ```bash
    psql $DATABASE_URL -f infra/initdb/migrations/2025_10_08_stock_pool.sql
    ```
2. 重启后端服务（确保新表可用）。
3. 触发一次 Agent 运行：
  ```bash
  curl -X POST http://localhost:8081/api/agent/run
  ```
4. 待运行完成后验证：
  - `GET /api/stock-pool`
  - `GET /api/stock-profile/{symbol}`
5. （可选）重新构建当日特征：
  ```bash
  python backend/scripts/build_daily_features.py
  ```

回滚策略：
 - 删除新表：`DROP TABLE stock_pool_members; DROP TABLE stock_profiles;`
 - 移除列：`ALTER TABLE stock_daily_features DROP COLUMN in_stock_pool, DROP COLUMN industry;`
 - 不建议在生产直接回滚已使用的特征列，若模型依赖需同步更新特征选择。

监控建议：
 - 统计每日新增成员数 & 活跃成员总数
 - 画像覆盖率 = 有 `stock_profiles` / `stock_pool_members` 活跃数
 - 行业分布占比漂移（用于分析主题集中度）
3. 结构化与特征变更需给出字段定义与兼容策略，避免线上断裂。
4. 严格避免信息泄露：只用当时可得信息构造特征与样本。
5. 关注成本：缓存优先、分层分流、小模型/规则优先，LLM 调用可观测、可限流。
6. 合规第一：来源标注、版权遵循、隐私保护与审计留痕。

> 后续开发应严格遵循以上路线图与守则，所有 PR/改动需说明与目标的对齐点（覆盖率/质量/结构化/特征/评估/成本/合规）。

---

## 🧪 个股日特征与预测模型（知识库管线）

系统新增一套“日级特征 → 标签回填 → 相关性分析 → 模型训练 → 在线推理”流水：

### 1. 特征来源

| 类别 | 说明 | 代表字段 |
| ---- | ---- | -------- |
| 行情基础 | 当日 OHLCV 与涨跌幅 | `open, high, low, close, pct_chg, vol, amount` |
| 滞后收益/波动 | 前一日/5日收益、历史 5 日波动 | `ret_1d_prev, ret_5d_prev, vol_5d_prev` |
| Agent 因子聚合 | 智能分析中识别的要素数量与类别 | `agent_factor_count, agent_positive_factor_count, agent_negative_factor_count, agent_risk_factors_count` |
| 宏观共享 | 同一报告宏观情绪/风险指数 | `macro_sentiment_index, macro_risk_index` |
| 新闻聚合 | 文章数量与情绪均值（占位，可扩展） | `news_count, news_sentiment_score_avg` |
| 扩展技术结构 | K 线结构与换手强度 | `amplitude, candle_body, upper_shadow_ratio, lower_shadow_ratio` |
| 相对活跃度 | 20 日滚动均量/额对比 | `vol_ratio_20, amount_ratio_20` |
| 因子平衡与风险占比 | 正/负面净平衡 & 风险因子比例 | `factor_balance, risk_factor_ratio` |

计算脚本：`python backend/scripts/build_daily_features.py`（Agent 成功运行后会自动触发一次）。

### 2. 前瞻标签回填

脚本：

```powershell
python backend/scripts/backfill_forward_labels.py --start 2024-01-01 --end 2025-12-31 --limit 8000
```

填充：

- `fwd_ret_{1d,5d,10d,20d}`：未来 H 日收盘收益率
- `fwd_dir_{1d,5d}`：未来 1/5 日方向（>0 为 1，否则 0）
- `realized_vol_{5d,20d}`：未来窗口日收益波动（标准差）

缺失的未来收盘价会导致对应字段暂留 NULL，后续可重复运行脚本补齐。

### 3. 相关性 / 信息系数（可选）

示例：`python backend/scripts/analyze_feature_correlations.py`（会写入 `feature_correlations` 表，用于评估特征与未来收益/波动的 Pearson / IC）。

### 4. 模型训练

脚本：

```powershell
python backend/scripts/train_signal_models.py --activate
```

当前训练：

- 分类：`next_day_direction`（目标 `fwd_dir_1d`）
- 回归：`fwd_ret_{1d,5d,10d,20d}` 四个单任务模型

自动包含新增工程特征与分类/情绪类别的 One-Hot 编码；训练后会在 `models/` 目录生成：

```text
next_day_direction_v1.pkl
next_day_direction_v1_meta.json
fwd_ret_1d_reg_v1.pkl
fwd_ret_1d_reg_v1_meta.json
...
```

元数据（`*_meta.json`）包含特征顺序与分类映射，供在线推理重建特征向量。

### 5. 在线推理 API

端点：

```http
GET /api/models/predict?symbol=600519.SH&horizons=1d,5d,10d
```

返回示例：

```json
{
  "symbol": "600519.SH",
  "trade_date": "2025-10-08",
  "direction_prob_up_1d": 0.57,
  "expected_return_1d": 0.0042,
  "expected_return_5d": 0.0125,
  "expected_return_10d": 0.0211
}
```

说明：

- 若某 horizon 对应模型未激活，该字段缺省。
- `trade_date` 为用于推理的特征行日期（显式传入 `&trade_date=` 可回溯历史推理实验）。
- 模型更新需重新训练并 `--activate` 注册为激活版本。

### 6. 未来可扩展方向

- 增补行业 / 市值 / 因子暴露等横截面控制特征
- 引入分层时间序列交叉验证与滚动窗口回测
- 增加集成/加权与不确定性估计（分位数回归 / MC Dropout）
- 上线在线特征服务（Redis 缓存实时行情与增量新闻特征）
- 增设指标监控（模型漂移、特征漂移、预测概率分布）

