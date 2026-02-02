
# 🚀 AIStock 专业舆情与事件驱动分析系统（v2 设计文档）

## 0. 背景与现状

你当前系统已经具备：

* 每日涨跌幅 `Top20` 股票分析（抓行情 + 新闻 + LLM 综合分析）
* 观察列表 `watchlist`（自动+手动）作为长期跟踪股票池
* FastAPI + React 的可视化平台
* PostgreSQL / MongoDB / Redis（以及你实际还有 MinIO）
* LLM 已接入（Azure OpenAI/GPT-4/5 系列）

当前痛点与升级目标：

* 从“每日一次分析报告”升级为“**长期跟踪**：新闻→事件→解释→简报→问答”
* 强化“专业可信信源”（不做全网UGC，但扩充官方/机构/行业层信源）
* 简报需要系统化（日报/周报/风险提醒）
* 东方财富存在连接问题，需要工程级“可运营抓取”（限速/熔断/回放）

---

## 1. 目标与非目标

### 1.1 目标（Goals）

1. **观察池驱动**：自动入池（Top20）+ 手动入池；支持定期清洗与生命周期管理
2. **专业舆情扩展**：保留东财/新浪新闻为媒体层，同时纳入权威公共渠道
3. **事件中心化**：把“新闻文章”提升为“事件（Event）”作为核心分析单位
4. **LLM 快速落地**：尽快实现舆情解释、事件归因、每日/每周简报生成
5. **RAG 问答**：围绕“公司/事件/时间窗”的证据检索与可追溯回答
6. **可运营**：失败归因、限速熔断、补抓回放、数据质量闸门

### 1.2 非目标（Non-goals）

* 不做全网舆情（微博/贴吧/雪球等UGC不纳入）
* 不采购商业付费数据服务（Wind/Choice等）
* 不追求“100%抓取稳定不变”，追求“可修复、可回放、可解释”

---

## 2. 关键业务概念

### 2.1 股票池（Pool）与观察列表（Watchlist）

* `Top20Pool`：每日从涨跌幅Top20自动生成候选
* `Watchlist`：长期观察池（自动入池 + 手动入池）
* `WatchlistLifecycle`：支持清洗与状态迁移（Active / Cooling / Archived）

### 2.2 信息资产层级（Professional Signal Levels）

为了“更多专业信源”但不走全网UGC，信源分级如下：

* **L1 法定/监管披露（硬事实）**：公告、交易所问询/监管函、处罚、立案等
* **L2 专业财经媒体（传播层）**：东方财富、新浪财经（你强约束必须保留）
* **L3 官方/行业机构（宏观行业信号）**：证监会/交易所新闻、部委、行业协会、权威统计/政策发布
* **L4 研究与机构观点（解释层）**：公开研究报告/白皮书摘要（只存摘要+链接）

> 系统的事件置信度、RAG排序、简报权重都基于 `source_level` 加权。

---

## 3. 总体架构（从“日报”到“事件驱动”）

```text
Frontend (React)
  ├─ 情报监控：观察池舆情流 / 风险提醒
  ├─ 个股详情：事件时间线 / 简报 / RAG问答
  ├─ 每日复盘：Top20扫描 + 市场情绪
  └─ 设置：抓取频率 / 清洗规则 / 模型参数

Backend (FastAPI)
  ├─ API: /watchlist /news /events /briefings /rag /agent
  ├─ Services:
  │    ├─ CollectorService   (抓取与归档)
  │    ├─ NormalizeService   (清洗/去重/结构化)
  │    ├─ EntityLinkService  (公司映射/消歧)
  │    ├─ EventService       (事件抽取/合并/评分)
  │    ├─ BriefingService    (日报/周报/风险卡片)
  │    └─ RagService         (召回/重排/问答生成)
  └─ Scheduler/Workers:
       ├─ Top20入池任务
       ├─ 观察池舆情刷新任务
       ├─ 事件抽取任务
       ├─ 日报/周报生成任务
       └─ 回放补抓任务

Storage
  ├─ MinIO     : raw HTML/JSON/PDF 快照、失败页快照
  ├─ MongoDB   : articles、fetch_failures、parse_failures（半结构化运行态）
  ├─ PostgreSQL: companies、watchlist、events、briefings、analysis（强一致业务事实）
  └─ Redis     : queue、rate-limit、circuit-breaker、dedup、hot cache
```

---

## 4. 与现有项目结构的“增量整合方案”

你现有结构不动主干，只新增/重构以下目录模块：

### 4.1 推荐的新目录结构（backend/app）

```
backend/app/
├── core/
│   ├── models.py                # Pydantic/SQLAlchemy模型
│   ├── settings.py              # 配置
│   └── constants.py             # 信源等级、事件类型枚举
├── routers/
│   ├── watchlist.py
│   ├── news.py
│   ├── events.py                # 新增
│   ├── briefings.py             # 新增
│   ├── rag.py                   # 新增
│   └── agent.py
├── services/
│   ├── collector_service.py     # 新增：统一采集入口（东财/新浪/公告/监管）
│   ├── normalize_service.py     # 新增：清洗/去重/质量闸门
│   ├── entity_link_service.py   # 新增：公司识别/消歧
│   ├── event_service.py         # 新增：事件抽取/合并/置信度
│   ├── briefing_service.py      # 新增：日报/周报/风险提醒
│   └── rag_service.py           # 新增：混合检索+生成
├── workers/
│   ├── top20_job.py             # 从 temp 脚本迁移进来
│   ├── crawl_job.py             # 抓取任务
│   ├── event_job.py             # 事件抽取任务
│   ├── briefing_job.py          # 简报任务
│   └── replay_job.py            # 补抓/回放
├── news/                        # 你现有的新闻模块保留
├── scripts/
│   └── top20_llm_agent_full.py  # 保留，但拆出“可复用分析器”
└── utils/
    ├── enhanced_news_fetch.py
    ├── direct_news_api.py
    └── ...
```

### 4.2 “temp 脚本”迁移策略

* `temp/fetch_stocks_sina.py` → `workers/top20_job.py`（作为可调度任务）
* `temp/comprehensive_analysis.py` → 分拆为：

  * `services/briefing_service.py`（简报生成）
  * `services/event_service.py`（事件抽取）
  * `scripts/top20_llm_agent_full.py` 保留“Top20 日报分析”模式

---

## 5. 数据模型升级（重点：事件中心化）

### 5.1 PostgreSQL 业务事实库（新增/调整）

#### watchlist（扩展）

新增字段建议：

* `source`: `top20|manual`
* `status`: `active|cooling|archived`
* `added_at`, `last_active_at`
* `clean_rule_tag`（用于记录清洗策略）

#### events（新增核心表）

> **events 成为系统的“长期记忆”与分析核心。**

* `event_id` (uuid)
* `symbol`
* `event_type`（枚举：业绩/回购/处罚/并购/重大合同/风险提示…）
* `event_date`（披露/发生）
* `summary`（结构化摘要）
* `entities`（jsonb：主体、对手方、金额、产品、地区等）
* `confidence`（0~1）
* `source_level`（L1/L2/L3/L4）
* `evidence`（jsonb：article_ids, urls, raw_keys）
* `created_at`

#### briefings（新增）

* `briefing_id`
* `symbol`
* `period`: `daily|weekly`
* `period_start`, `period_end`
* `risk_summary`
* `opportunity_summary`
* `key_events`（jsonb：event_id列表）
* `llm_meta`（jsonb：模型、prompt版本、token统计）
* `generated_at`

### 5.2 MongoDB 运行态库（articles/failures）

* `articles`：存文章解析结果（标题/正文/发布时间/公司命中/情绪等）
* `fetch_failures`：记录 HTTP/解析失败，支持回放
* `parse_failures`：选择器变更/正文为空等

### 5.3 MinIO（必做：为“可运营”）

* 存储原始 HTML/JSON/PDF
* 存储失败页快照（用于排查东财连不上原因）
* Key 规范：`raw/{source}/{yyyy}/{mm}/{dd}/{sha256(url)}.*`

---

## Consolidated root docs

The repository previously contained several root-level Markdown files (upgrade notes, checklists and reports). To keep documentation centralized, these items have been consolidated into this `README.md` as summaries and the original root files have been removed. The following list explains what was consolidated:

- `README_v1.md` — Older design notes for v2; its architecture and design content was merged (kept the authoritative version above).
- `DELIVERY_CHECKLIST.md` — Delivery checklist (moved summarized items into release/operational notes section).
- `FINAL_ACCEPTANCE_REPORT.md` — Acceptance test summary and pass/fail notes (archived, key PASS indicators included in verification section).
- `FINAL_TEST_REPORT.md` — Test run summaries and critical test outcomes (key results summarized in Verification and QA notes).
- `QUICKSTART_v1_1.md` — Quickstart steps condensed into the `Quick Start` and `Run` sections of this README.
- `UPGRADE_CHECKLIST*.md`, `UPGRADE_*.md`, `UPGRADE_REPORT_v1_1.md` — Various upgrade artifacts and checklists; critical migration notes and DB instructions have been integrated into the Migration & Upgrade notes section.

If you need the full original content for any removed file, it has been preserved in the repository history (git). If you want the full text reinserted into `README.md`, tell me which file(s) and I'll paste their contents under a dedicated archive subsection.

---

<!-- End of consolidated root docs -->

---

## 6. 核心 Pipeline（观察池长期跟踪）

### 6.1 每日 Top20 → 入池流程

1. 抓行情（你已有）得到 Top20
2. 计算入池评分（如波动幅度、成交额、连续异动）
3. 符合规则的自动加入 watchlist（status=active, source=top20）
4. 生成“Top20 日报”（保留你已有 agent 输出）

### 6.2 观察池舆情刷新（循环任务）

对 watchlist.active 股票：

1. 采集：东财/新浪 + L1/L3 公共权威源
2. 解析：正文抽取、发布时间、来源等级
3. 去重：URL规范化+内容hash
4. 公司识别：symbol/别名命中
5. 落库：articles（Mongo），raw（MinIO）
6. 触发事件抽取任务（event_job）

### 6.3 事件抽取与合并（event_job）

1. 规则抽取（关键词/模板）
2. LLM 精修（可选）：补全字段、生成结构化 summary
3. 事件合并：同公司+同类型+近似摘要合并为一个 event
4. 置信度计算：source_level + 多源一致性 + 文本质量

---

## 7. LLM 快速落地：舆情解释 & 简报生成

### 7.1 LLM 应用优先级（按落地速度排序）

1. **事件摘要生成**（输入：文章/公告 → 输出：结构化事件字段）
2. **每日简报**（输入：当天事件列表 → 输出：风险/机会/结论）
3. **每周简报**（输入：一周事件时间线 → 输出：趋势、关键转折、建议）
4. **RAG 问答**（输入：检索证据 → 输出：可引用回答）

### 7.2 简报生成契约（用于 vibe coding）

简报输出必须包含：

* `风险点（2~5条）`：必须引用 event_id
* `机会点（1~3条）`
* `关键事件时间线（Top N）`
* `结论与置信度`
* `引用证据链接（URL 或 raw_key）`

---

## 8. RAG 查询设计（公司/事件为中心）

### 8.1 召回策略（混合检索）

* 关键词：Postgres全文/pg_trgm（快速过滤）
* 语义：pgvector（按 chunk 检索）
* 重排策略：

  1. L1 > L2 > L3 > L4
  2. event 证据优先于 article
  3. 新近优先（可配置时间衰减）

### 8.2 问答边界（防幻觉）

* 必须基于证据回答
* 无证据 → 输出“不足以判断 + 建议补抓/查看公告”
* 回答必须给出引用列表（titles + urls）

---

## 9. 可运营抓取（解决东财连接问题的工程化要求）

**必须具备的能力：**

* 域名级限速（东财更严格）
* 重试策略（指数退避+抖动）
* 断路器（连续失败→熔断→恢复）
* 失败归因（403/429/timeout/parse_changed）
* 回放补抓（对 failures 的 url 批量重跑）

这些能力通过 Redis 维护状态（rate-limit / circuit-breaker / queue）。

---

## 10. 前端产品形态升级（面向长期观察）

新增页面/模块建议：

1. **观察池时间线**：按公司展示事件时间线（可筛选事件类型/等级）
2. **风险雷达**：按周统计监管/诉讼/减持/业绩下修等风险事件
3. **简报中心**：日报/周报列表 + 一键生成/重跑
4. **问答面板**：对公司提问并显示引用证据

---

## 11. Vibe Coding 任务拆解（Epic → Story）

### Epic A：观察池与生命周期

* A1 自动入池：Top20 → watchlist（规则可配）
* A2 手动入池：前端添加 → watchlist
* A3 定期清洗：Cooling/Archived（规则可配+人工确认）

### Epic B：专业信源采集扩展

* B1 东财/新浪采集器稳定化（限速/熔断/回放）
* B2 L1 公告采集器（巨潮/交易所）
* B3 L3 官方/行业机构采集器（证监会/协会）

### Epic C：文章标准化与去重

* C1 URL 规范化 + 内容 hash
* C2 质量闸门（正文长度/时间解析/可用性）
* C3 MinIO 快照与失败快照存档

### Epic D：事件中心化

* D1 事件类型体系与规则模板
* D2 LLM 事件结构化（schema 输出）
* D3 事件合并与置信度模型

### Epic E：简报生成

* E1 日报生成（按公司）
* E2 周报生成（按公司 + 市场）
* E3 简报存储与前端展示

### Epic F：RAG 问答

* F1 索引：全文 + pgvector
* F2 召回与重排
* F3 引用证据输出与防幻觉策略

### Epic G：运维与可观测

* G1 失败分类仪表盘
* G2 任务重放
* G3 指标：成功率、延迟、事件产出率、简报质量评分

---

## 12. 验收标准（DoD）

* 观察池股票可持续跟踪（≥30天）且清洗机制生效
* 每日自动生成：Top20日报 + 观察池个股日报
* 每周自动生成：观察池周报（含风险/机会/趋势）
* 事件抽取准确率可人工抽样验证（同一事件多新闻可合并）
* RAG 问答能返回明确引用证据，不凭空生成
* 抓取失败可归因并可回放补抓（东财最关键）

---

## 13. 你当前项目的最小升级路径（两周内见效）

**Week 1（快落地）**

* 事件表 + 简报表落地（Postgres）
* 把 `comprehensive_analysis.py` 拆成 `event_service + briefing_service`
* 做“日报生成”：观察池公司每日一页 markdown + json

**Week 2（质量提升）**

* 接入 L1 公告 + L3 官方渠道
* 上线 RAG（先关键词检索，再pgvector）
* 做失败回放与熔断机制，稳定东财/新浪抓取

---

如果你想把这份设计直接变成“vibe coding 的开发提示词包”，我可以在下一条回复里输出：

* **每个 Epic 的 Prompt 模板**（给 Copilot/Codex）
* **事件 Schema 的严格 JSON Schema**
* **简报 Prompt（日报/周报）版本化策略**
* **抓取稳定性策略参数默认值（东财/新浪分别）**
