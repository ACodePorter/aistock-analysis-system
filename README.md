# 🚀 AI股票分析系统（全中文说明）

一个面向中国A股市场的智能分析与新闻监控平台，集成 AI 预测、技术指标、智能新闻收集与情感分析、任务调度与可视化前端，支持本地与 Docker 一键部署。

---

## ✨ 核心功能

- 🤖 AI预测与报告：神经网络多步预测（含置信区间）、自动生成分析报告
- 📊 技术指标与信号：RSI/MACD/均线/布林带等指标与多维评分
- 📰 新闻管理中心：多源聚合、情感分析、去重、按股票归档与批量操作
- 🔄 自动化调度：每日/小时级采集与预测，任务状态与仪表盘
- 💾 混合存储：PostgreSQL + MongoDB + Redis（可选）
- 💻 现代前端：React + TypeScript + Vite + TailwindCSS

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
- 后端API：[http://localhost:8080](http://localhost:8080)
- API文档：[http://localhost:8080/docs](http://localhost:8080/docs)
- SearXNG（新闻搜索）：[http://localhost:10000](http://localhost:10000)（如已启用）

### 本地开发（可选）

后端：

```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Windows PowerShell
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
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
  window.API_BASE = 'http://localhost:8080';
</script>
```

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
├── searxng/                        # SearXNG配置（可选）
├── initdb/                         # PostgreSQL初始化脚本
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

## 🔌 API 概览（节选）

- 报告与价格：
  - `GET /api/report/{symbol}`、`GET /api/report/{symbol}/full`、`GET /prices/{symbol}`
- 任务与仪表盘：
  - `GET /api/tasks/status`、`GET /api/dashboard/reports`、`GET /api/dashboard/tasks`
- 新闻：见“新闻管理中心（前端）→ API映射”

完整接口请参见后端 [http://localhost:8080/docs](http://localhost:8080/docs)。

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
3. 结构化与特征变更需给出字段定义与兼容策略，避免线上断裂。
4. 严格避免信息泄露：只用当时可得信息构造特征与样本。
5. 关注成本：缓存优先、分层分流、小模型/规则优先，LLM 调用可观测、可限流。
6. 合规第一：来源标注、版权遵循、隐私保护与审计留痕。

> 后续开发应严格遵循以上路线图与守则，所有 PR/改动需说明与目标的对齐点（覆盖率/质量/结构化/特征/评估/成本/合规）。
