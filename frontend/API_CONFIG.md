# 前端 API 配置说明

## 配置文件说明

### `vite.config.ts` - Vite 构建工具配置

这是 Vite 构建工具的配置文件，主要作用：

1. **开发服务器配置**
   - 端口：5174
   - 主机绑定：允许外部访问

2. **代理配置**

```typescript
proxy: {
   '/api': {
      target: 'http://localhost:8080',
      changeOrigin: true,
      secure: false
   }
}
```

- 将所有 `/api/*` 请求代理到后端服务器 `http://localhost:8080`
- 解决开发环境的跨域问题

3. **插件配置**
   - React 插件支持

### `src/config/api.ts` - 应用 API 配置

这是应用级别的 API 配置文件，主要作用：

1. **智能环境检测**

   - 开发环境：使用相对路径（通过 `buildApiUrl` 统一拼接），依赖 Vite 代理到 8080
   - 生产环境：默认 `http://localhost:8080`，可通过运行时注入 `window.API_BASE` 覆盖

2. **API 端点管理**
   - 统一管理所有 API 端点
   - 提供类型安全的端点常量

3. **灵活配置支持**
   - 支持通过 `window.API_BASE` 动态配置
   - 支持不同环境的自动切换

## 工作原理

### 开发环境

```text
前端请求: /api/news/articles
↓ (Vite 代理)
后端请求: http://localhost:8080/api/news/articles
```

### 生产环境

```text
前端请求: http://localhost:8080/api/news/articles
↓ (直接请求)
后端请求: http://localhost:8080/api/news/articles
```

## 优势

1. **无缝切换**：开发和生产环境自动切换，无需手动修改
2. **跨域解决**：开发环境通过 Vite 代理解决跨域问题
3. **类型安全**：TypeScript 提供 API 端点的类型检查
4. **集中管理**：所有 API 配置集中在一个文件中
5. **灵活配置**：支持运行时动态配置 API 地址

## 使用方式

```typescript
import { buildApiUrl, API_ENDPOINTS } from '@/config/api';

// 推荐使用方式
const response = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.ARTICLES));

// 动态端点
const response = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.STOCK_NEWS('AAPL')));
```

## 注意事项

1. 确保 `vite.config.ts` 中的代理目标与后端服务器地址一致（当前使用 8080）
2. 生产环境部署时，需要确保 API 地址正确
3. 如需自定义 API 地址，可通过 `window.API_BASE` 设置

## 新增：行情异动 (MOVERS) 端点

Deep Market Insight / 深度每日行情 页面使用以下统一端点（位于 `API_ENDPOINTS.MOVERS`）：

| Key | 描述 | 方法 | 示例 |
| --- | ---- | ---- | ---- |
| DAILY | 当日涨跌榜数据（source=db 收盘日线 / source=live 实时快照） | GET | `/api/movers/daily?source=live&exchange=ALL` |
| DAILY_FLAT | 当日涨幅降序单列表（支持 source=live 或 db） | GET | `/api/movers/daily_flat?source=live` |
| WEEKLY | 周度动量榜 | GET | `/api/movers/weekly` |
| ANALYZE | 综合智能分析（行业热度 / 推荐 / 新闻摘要 / 主题） | GET | `/api/movers/analyze` |
| SERIES | 指定股票近 N 日价格序列（数据库版） | GET | `/api/movers/series/000001?days=30` |
| LIVE_INSIGHT | 纯实时全市场涨跌（akshare + 东方财富回退，无 DB 依赖） | GET | `/api/movers/live_insight?exchange=ALL&limit=20` |
| LIVE_SERIES | 指定股票近 N 日历史（日 K，akshare 直连） | GET | `/api/movers/live_series/000001.SZ?days=30` |
| FULL_DAILY | 最近一次成功摄取日的收盘全市场统计 | GET | `/api/movers/full/daily` |
| FULL_RANGE | 区间累计收益 Top/Bottom (period=1m 或 1y) | GET | `/api/movers/full/range?period=1m` |
| EXPAND | 关键词扩展 | GET | `/api/movers/expand_keywords` |

### 实时接口说明

`/api/movers/live_insight` 特性：

- 不访问本地数据库；失败时自动从 akshare 切换到 东方财富分页 API。

返回字段：

- gainers / losers: `[ { symbol, name, pct_chg, change, price } ]`
- provider: akshare 或 eastmoney
- universe_size / parsed_rows / valid_rows: 诊断计数
- error / ak_error: 若主源失败时的错误信息

参数：

- `limit` (<=100)
- `exchange` (ALL|SH|SZ)
- `provider` (auto|akshare|eastmoney) 强制数据源或自动选择

### 日终全量端点 (FULL_*)

这些端点依赖每日批量摄取脚本 `backend/app/scripts/ingest_daily_prices.py` 将全市场 EOD 数据写入 `prices_daily` 并记录状态表 `ingest_state_daily`。

1. `GET /api/movers/full/daily`
   - 自动定位最近 `status=success` 的交易日
   - 返回：trade_date, universe_size, gainers, losers, stats(avg_pct_chg, median_pct_chg)
2. `GET /api/movers/full/range?period=1m|1y`
   - 以最近成功交易日为区间末，向前近 1 个月(≈35 天) / 1 年(≈380 天) 取首末收盘计算累计涨跌幅
   - 返回：gainers / losers / universe_size / start_date / end_date

摄取脚本（初版）：

```bash
python -m backend.app.scripts.ingest_daily_prices --date 2025-10-04
```

当前脚本为最小可用版本：串行抓取 + akshare 主源；尚未添加 (symbol, trade_date) 唯一约束与并发优化。

### source 参数行为总结

| 端点 | source 参数 | 说明 |
|------|-------------|------|
| /api/movers/daily | db / live | db=最近日线表 (prices_daily)；live=实时快照缓存 (15s) |
| /api/movers/daily_flat | db / live | 同上 |
| /api/movers/live_insight | 无需 | 固定实时，不读 DB |
| /api/movers/series/{symbol} | (无) | 读取数据库价格表 |
| /api/movers/live_series/{symbol} | (无) | 直接 akshare 历史接口 |
| /api/movers/full/daily | (无) | 使用 ingest_state_daily 定位最近成功日期 |
| /api/movers/full/range | period 控制 | 区间基于最近成功日期 |

### 诊断与覆盖率（后续规划）

- ingest_state_daily 将记录 total_symbols / inserted_rows / provider / error_message
- 后续可在 full/daily 响应中添加 coverage_ratio = inserted_rows / total_symbols
- 可扩展多数据源回退：tushare -> eastmoney -> akshare。

示例：

```ts
import { API_ENDPOINTS, buildApiUrl } from '@/config/api'

async function loadDaily(){
   const r = await fetch(buildApiUrl(API_ENDPOINTS.MOVERS.DAILY))
   if(!r.ok) throw new Error('Failed load daily movers')
   return r.json()
}
```

## 统一调用规范更新

1. 已移除自定义 `src/api/client.ts` 封装，避免重复配置源。
2. 所有请求统一：`fetch(buildApiUrl(API_ENDPOINTS.*))`。
3. 禁止直接写死 `fetch('/api/...')`；必须通过常量，方便批量重构与运行时基地址切换。
4. 运行时替换基地址：

   ```html
   <script>window.API_BASE='https://your-domain.example';</script>
   ```

5. 可搜索以下关键字做自检：`fetch('/api/`、`apiFetch(`、`API_BASE +`。

## 迁移检查清单

| 检查项 | 状态 |
| ------ | ---- |
| 自定义 apiFetch 已移除 | ✅ |
| MOVERS 端点加入 `API_ENDPOINTS` | ✅ |
| Vite 代理端口更新为 8080 | ✅ |
| 文档端口统一 | ✅ |

完成以上后，如仍出现 500 错误，请查看浏览器网络面板对应请求的 Response / 后端日志堆栈，定位后端逻辑或数据层异常。
