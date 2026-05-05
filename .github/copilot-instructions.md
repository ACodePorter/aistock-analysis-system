# AIStock Copilot Instructions

使用中文与用户交流。

## Build, test, and lint commands

```bash
# Frontend (root scripts proxy into frontend/)
npm run dev
npm run build
npm run test

# Frontend single tests
cd frontend && npx vitest run src/ui/__tests__/SentimentBadge.test.tsx
cd frontend && npx vitest run src/ui/__tests__/DailyAnalysisPage.test.tsx

# Backend API
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload

# Backend test suites
cd backend && python tests/run_tests.py
cd backend && python tests/run_tests.py --data-only
cd backend && python tests/run_tests.py --api-url http://localhost:8090

# Backend single tests
cd backend && python -m pytest tests/unit/test_trading_calendar.py -v
cd backend && python -m pytest tests/unit/test_stock_pool_api.py -v
cd backend && python tests/integration/test_searxng.py

# Docker
docker-compose up -d
docker-compose -f docker-compose.local.yml up
```

当前仓库没有统一的 lint 脚本；根 `package.json` 和 `frontend/package.json` 都未定义 `lint`。前端 Vite 开发服务器端口是 `5174`，并通过 dev proxy 连到后端 `8090`。

## High-level architecture

- `frontend/src/main.tsx` 启动单页 React 应用并挂载 Ant Design 全局配置，真正的页面组合入口在 `frontend/src/ui/App.tsx`；观察池、日报、新闻、宏观、预测复盘等都从这里汇总。
- 前端 API 访问目前是双轨并存的：老页面常用 `frontend/src/config/api.ts` 里的 `buildApiUrl`/`API_ENDPOINTS`，新代码常用 `frontend/src/api/client.ts` 的 `apiFetch` 和 `src/api/*` typed wrapper。修改时沿用所在区域已有方式，不要再引入第三套调用路径。
- `frontend/vite.config.ts` 会把 `/api`、`/watchlist`、`/cache`、`/search_stock`、`/run`、`/report` 代理到 `http://127.0.0.1:8090`。部分后端文档和旧测试示例仍提到 `8081`，但前端本地联调默认目标是 `8090`。
- 前端常见链路是：`App.tsx` 这类页面容器发起请求，旧链路通过 `buildApiUrl` 直连 REST 端点，新链路通过 `src/api/*` wrapper 取 typed 数据；排查页面问题时通常要同时看页面组件、对应 API helper，以及 `backend/app/main.py` 或相关 router 的返回结构。
- `backend/app/main.py` 是后端集成枢纽：除了 FastAPI app 初始化，还集中挂载 routers、保留大量 legacy 端点、agent 任务接口、watchlist snapshot 缓存/流式接口，以及多处数据库/文件系统回退逻辑。要确认真实暴露的 API，优先看这里而不是只看某个 router 文件。
- `backend/app/tasks/scheduler.py` 是日常流水线编排器：它从 `stock_pool_members` 读取活跃股票，拉取近三年日线、计算技术信号、生成预测、更新资金流，再触发新闻采集、宏观流水线和 agent 日报作业。
- 调度器推荐独立于 API 进程运行；`backend/app/main.py` 已明确把 `ENABLE_SCHEDULER=1` 视为 legacy 单进程模式，正常联调或部署时应优先让 API 进程关闭调度器，由独立 worker 负责调度。
- `backend/app/main.py` 的观察池相关接口和 `scheduler.py` 的主流程不是同一张表：流水线核心读 `stock_pool_members`，而 `/api/watchlist/snapshot` 会把统一股票池与 `watchlist` 的置顶/展示状态拼起来。改股票池逻辑前先确认当前代码依赖的是统一池、旧 watchlist，还是 snapshot 聚合结果。
- `watchlist_snapshot` / `watchlist_snapshot_stream` 不只是简单查库：它们会从统一股票池取 symbol，再调用 `data_source.get_spot_snapshot()` 拼实时行情，并叠加缓存、刷新锁和 stale/fresh 双层回退。性能、空数据和展示不一致问题通常都在这条聚合链路里。
- `backend/app/data/data_source.py` 是行情与资金流的统一边界，负责股票代码标准化、金额/成交量单位统一，以及 AkShare / Tushare / 东方财富 / 新浪之间的多级回退与短期缓存。
- 数据存储是分层的：PostgreSQL（`backend/app/core/models.py`）存结构化业务事实，MongoDB 存新闻/事件类文档，Redis 提供缓存、锁与运行时状态。`README.md`/`CLAUDE.md` 还约定 MinIO 用于原始抓取快照。
- 新闻、宏观与部分检索能力并不完全落在 SQL 表里：`routers/news.py`、宏观报告链路和增强新闻调度器会通过 `utils.mongo_storage.get_storage()` 读写 MongoDB 文档，因此排查“接口有返回但数据库表里没有记录”时要同时检查 PostgreSQL 与 MongoDB。
- `prompts/` 是 LLM 提示词中心；新闻分析、公司画像、日报/周报摘要等模板都集中在这里，而不是内联在业务代码里。
- `backend/app/core/constants.py` 里的 `SOURCE_LEVEL_WEIGHTS` 和 `TOP20_POOL_RULES` 是跨模块领域规则：信源权重会影响事件置信度、检索排序和简报权重，Top20 规则会影响股票池生命周期与自动入池逻辑。
- `backend/app/routers/events.py` 和 `backend/app/routers/rag.py` 已挂载到主应用，但当前实现仍是明显的 TODO scaffold；动这些接口前先确认真实功能是否已经转移到别处，避免在空壳路由上重复造轮子。

## Key conventions

- 新的后端模型和 schema 工作延续 SQLAlchemy 2.0 typed ORM 风格：`Mapped[...]` + `mapped_column(...)`。
- 后端数据单位有明确约定：价格/金额按“元”，成交量按“股”；展示层再自行换算成“万/亿”。
- 跨模块传递股票代码时优先使用标准化后的后缀形式，如 `600519.SH`、`000001.SZ`；`data_source.py` 的兼容逻辑就是围绕这个契约展开的。
- 外部数据和新闻采集代码普遍采用“多级回退 + 节流日志 + 缓存兜底”策略，而不是失败即中断；调整这些链路时要保留韧性，不要把容灾路径删成硬失败。
- Prompt 不要内联到业务代码里。涉及 LLM 的新增或修改，优先落到 `prompts/` 目录，并按 `prompts/README.md` 的格式更新元数据头、`version` 和变更记录；模板变量使用 `str.format()` 风格占位符。
- 前端 API 接入层处于新旧并存状态：老页面通常沿用 `buildApiUrl` + `API_ENDPOINTS`，新页面优先查 `src/api/` 是否已有 typed client。局部保持一致比“全局统一重构”更符合当前仓库状态。
- watchlist 页面和日常流水线不是同一个数据源：调度器主读 `stock_pool_members`，而首页/观察池界面还会使用 `watchlist` 和 snapshot API。改股票池或观察池展示逻辑时先确认附近代码到底依赖哪张表、哪组接口。
- agent 日报接口优先读数据库持久化副本，但 `backend/app/main.py` 里保留了 `backend/agent_reports` 文件回退；排查“前端读不到日报”时要同时检查 DB 和文件落盘。
- 临时文件只放 `temp/`；若要新增依赖或调整仓库结构，应先得到明确确认。
