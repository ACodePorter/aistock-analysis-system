# Agent 使用说明

本文件说明 Top20 智能分析 Agent 的运行方式、API 触发、严格 JSON 模式以及诊断指标含义。

## 1. 功能概述

Agent 自动执行以下步骤：

1. 发现并调用涨跌幅榜 API，获取 Top20 (涨+跌)。
2. 并行检索每只股票相关新闻（SearXNG）。
3. 调用 LLM 进行个股情绪、因子、风险、宏观触发词结构化分析；失败时启用启发式回退。
4. 聚合宏观关键词并进行宏观/行业结构分析（含严格 JSON 重试逻辑）。
5. 生成 JSON + Markdown 报告写入 `agent_reports/` 目录。
6. 输出诊断 & 分析统计（情绪分布、因子频次、回退比例、严格模式重试统计等）。

## 2. 环境变量

| 变量 | 说明 | 默认 |
| ---- | ---- | ---- |
| MOVERS_API_URL | 涨跌榜接口 | <http://localhost:8081/api/movers/live_insight?limit=20> |
| SEARXNG_URL | SearXNG 入口 | <http://localhost:10000> |
| AGENT_STOCK_NEWS_LIMIT | 单股票新闻条数上限 | 10 |
| AGENT_PARALLEL_WORKERS | 并行抓取线程数 | 8 |
| AGENT_MAX_MACRO_KEYWORDS | 聚合宏观关键词去重后最大数 | 15 |
| AGENT_STRICT_JSON | 严格 JSON 模式（1=启用） | 0 |
| AGENT_REPORT_DIR | 报告输出目录 | ./agent_reports |
| LLM_API_URL | 通用 OpenAI Chat 兼容接口（可选） | - |
| AZURE_OPENAI_* | Azure OpenAI 相关配置 | - |

## 3. 严格 JSON 模式 (AGENT_STRICT_JSON=1)

启用后：

- Prompt 前加统一系统前缀，硬性要求仅输出 JSON。
- 首次解析失败会触发一次 Retry，并重新强调仅输出单个 JSON 对象。
- 记录重试计数：`strict_retry_stock`, `strict_retry_macro`。
- 成功解析统计：`parse_success_stock_first`, `parse_success_stock_retry` 等。

## 4. 诊断字段说明

在最终 JSON 报告 `diagnostics` 中：

| 字段 | 含义 |
| ---- | ---- |
| fallback_stock_count | 个股分析使用启发式回退次数 |
| fallback_macro_used | 宏观分析是否使用启发式回退 |
| strict_json_enabled | 是否启用严格模式 |
| strict_retry_stock / strict_retry_macro | 严格模式下触发的重试次数 |
| parse_success_* | 首次/重试成功解析的次数（stock/macro） |
| fallback_ratio | 回退股票数 / 总股票数 |
| azure_last_error | 最近一次 Azure 调用错误摘要（若有） |

## 5. 后端 API 触发

新增端点：

### POST /api/agent/run

参数：`strict_json` (bool, query) 是否临时启用严格模式（只影响该次运行）。

返回：`{"job_id": "...", "status": "running"}`

### GET /api/agent/status/{job_id}

返回：

```json
{
  "status": "running|finished|failed",
  "created_at": "...",
  "strict": true,
  "return_code": 0,
  "stdout_tail": ["..."],
  "stderr_tail": ["..."],
  "reports_detected": ["JSON: agent_reports/...", "Markdown: agent_reports/..."]
}
```

## 6. 本地测试脚本

`backend/app/scripts/test_agent_endpoint.py`：

```bash
python backend/app/scripts/test_agent_endpoint.py --strict
```

将轮询任务状态直至完成或超时。

### 新闻搜索（源过滤与增量）

- POST `/api/news/search` 支持以下可选字段：
  - `language`、`engines`：传递给 SearXNG
  - `include_domains`：仅包含这些域名的结果（host 或后缀，例：`["eastmoney.com","finance.sina.com.cn"]`）
  - `exclude_domains`：排除这些域名
  - `since`：仅返回发布时间 >= since 的结果（ISO 或 `YYYY-MM-DD`），便于增量拉取

- POST `/api/news/search_incremental`：在上述基础上，返回字段包含 `latest_published`，建议下次作为 since 起点。

请求示例：

```json
POST /api/news/search_incremental
{
  "query": "贵州茅台 公司 新闻",
  "category": "general",
  "time_range": "month",
  "max_results": 20,
  "language": "zh-CN",
  "include_domains": ["eastmoney.com","yicai.com"],
  "since": "2025-10-01"
}
```

返回示例（裁剪）：

```json
{
  "query": "贵州茅台 公司 新闻",
  "total_count": 12,
  "latest_published": "2025-10-13T10:22:03",
  "articles": [ {"title":"...","url":"...","content":"..."} ]
}
```

Agent 增量开关与配置：

- `AGENT_USE_MEDIA_INCREMENTAL=1` 启用（默认1）
- `AGENT_MEDIA_INCREMENTAL_DOMAINS` 覆盖站点列表（逗号分隔，不设则复用 `SEARXNG_CN_SITES`）
- `AGENT_MEDIA_INCREMENTAL_MAX` 每轮增量拉取条数（默认 `max(3, limit/2)`）
- `AGENT_MEDIA_INCREMENTAL_MAX_SITES` 每轮站点上限（默认 8）
- `AGENT_MEDIA_SINCE_FILE` 增量状态文件路径（默认 `agent_reports/agent_media_since.json`）

### 保底兜底：后端富集接口（避免0新闻）

当多轮 SearXNG 与 DB 回退后仍不足最小阈值，Agent 会调用后端富集接口作为最终兜底，必要时允许“占位”以消除“信息不足”。

- 触发路径：`GET /api/news/company_enriched/{symbol}`
- 关键查询参数：
  - `ensure_min`: 至少返回 N 条
  - `trigger_topup=1` + `wait_seconds=3~5`: 触发即时补齐并短暂等待
  - `allow_placeholder=1`: 允许占位条目用于保底
  - `include_content=1` + `min_content`: 控制正文最小长度

Agent 相关环境变量：

- `AGENT_ENSURE_MIN_NEWS=5` 建议设置为 5 及以上
- `AGENT_USE_BACKEND_ENRICHED_FALLBACK=1` 开启后端富集兜底（默认1）
- `AGENT_BACKEND_FALLBACK_WAIT_SECONDS=3` 兜底等待秒数
- `AGENT_ENRICHED_DAYS=7`、`AGENT_ENRICHED_FALLBACK_DAYS=120` 控制富集查询窗口
- `AGENT_ENRICHED_MIN_CONTENT=0` 兜底时的最小正文过滤

该兜底与“媒体增量”共同工作，基本可杜绝“新闻数 0/信息不足”的情况。

## 7. 校验逻辑

- 个股 & 宏观 JSON 解析后使用 `validate_stock_json` / `validate_macro_json` 清洗：
  - 归一化权重、clamp 数值范围。
  - 缺失字段填默认值，防止前端或下游处理异常。

## 8. 常见问题

| 问题 | 可能原因 | 解决 |
| ---- | -------- | ---- |
| 所有股票 fallback | LLM 不可用或输出非 JSON | 检查 Azure/OpenAI 配置；查看 stdout tail |
| strict 重试仍失败 | 模型输出被截断或指令未生效 | 减少 prompt 冗余，降低 tokens；手动观察 raw 片段 |
| 宏观 industry_heat 为空 | 新闻稀少或模型输出精简 | 启用回退启发式（自动） |
| 报告文件未检测到 | stdout 抽取失败 | 手动查看 `agent_reports` 目录 |

## 9. 后续可扩展建议

- 增加持久化任务表（数据库）取代内存 job store。
- 将回退启发式拆分为策略模块（便于 A/B）。
- 增加对多模型链路（政策→情绪→宏观）分段缓存。
- 增加压力测试与新闻检索失败重试统计。

## 10. 变更记录

2025-10-06: 初版文档；加入严格 JSON 模式、端点与校验。
2025-10-13: 新增媒体增量搜索与 API 源过滤。
2025-10-13: 增加后端富集接口兜底文档，给出避免0新闻的推荐环境变量。

---

如需进一步增强（多模型协同、指标订阅、回测接口），请提出具体需求。
