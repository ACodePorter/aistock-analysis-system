# Web Data Providers 配置指南

本模块提供统一的互联网数据查询能力，支持天气、股票、百科、新闻、通用搜索等多种数据类型。

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    WebDataManager                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    缓存层 (SimpleCache)               │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐   │
│  │  天气    │   股票   │   百科   │   新闻   │   搜索   │   │
│  │ Provider │ Provider │ Provider │ Provider │ Provider │   │
│  └──────────┴──────────┴──────────┴──────────┴──────────┘   │
│       │          │          │          │          │         │
│  ┌────┴────┐ ┌───┴───┐ ┌───┴───┐ ┌───┴───┐ ┌────┴────┐    │
│  │wttr.in  │ │Yahoo  │ │Wiki   │ │NewsAPI│ │SearXNG  │    │
│  │OpenWM   │ │Sina   │ │百度   │ │Google │ │DDG      │    │
│  └─────────┘ └───────┘ └───────┘ └───────┘ └─────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## 环境变量配置

### 基础配置

```bash
# 请求超时时间（秒）
WEB_DATA_TIMEOUT=15

# 缓存 TTL（秒）
WEB_DATA_CACHE_TTL=300

# 是否启用 Redis 缓存（如可用）
WEB_DATA_ENABLE_REDIS=1

# 并发查询线程数
WEB_DATA_MAX_WORKERS=5
```

### 天气服务

```bash
# OpenWeatherMap API Key（可选，免费账户可用）
# 申请地址：https://openweathermap.org/api
OPENWEATHERMAP_API_KEY=2007ef2bf8a0ecb1892221c0f2b05ddc
```

### 新闻服务

```bash
# NewsAPI Key（可选，免费账户每天100次请求）
# 申请地址：https://newsapi.org/
NEWSAPI_KEY=70d1f3b77ebc48fc9e65234d533eac89
```

### 搜索服务

```bash
# SearXNG 实例地址（默认本地）
SEARXNG_URL=http://localhost:10000

# 多实例负载均衡（逗号分隔）
SEARXNG_INSTANCE_POOL=http://searx1:8081,http://searx2:8081,http://searx3:8081

# SearXNG 代理池（可选）
SEARXNG_PROXY_POOL=http://proxy1:8081,http://proxy2:8081
```

## API 端点

### 天气查询

```bash
GET /api/webdata/weather?location=Beijing&lang=zh

# 响应示例
{
  "success": true,
  "source": "wttr.in",
  "latency_ms": 523,
  "data": {
    "location": "Beijing",
    "temperature_c": 0,
    "feels_like_c": -3,
    "humidity": 64,
    "weather_desc": "Haze",
    "wind_speed_kmph": 8,
    "wind_direction": "SSW"
  }
}
```

### 股票查询

```bash
# A股
GET /api/webdata/stock?symbol=002594.SZ

# 港股
GET /api/webdata/stock?symbol=1211.HK

# 美股
GET /api/webdata/stock?symbol=AAPL

# 批量查询
GET /api/webdata/stock/batch?symbols=002594.SZ,1211.HK,AAPL

# 响应示例
{
  "success": true,
  "source": "sina_finance",
  "latency_ms": 234,
  "data": {
    "symbol": "002594.SZ",
    "name": "比亚迪",
    "price": 90.91,
    "change": -1.31,
    "change_percent": -1.42,
    "currency": "CNY"
  }
}
```

### 百科查询

```bash
GET /api/webdata/encyclopedia?keyword=比亚迪&lang=zh

# 响应示例
{
  "success": true,
  "source": "wikipedia",
  "latency_ms": 856,
  "data": {
    "title": "比亚迪",
    "summary": "比亚迪股份有限公司（简称BYD）是一家总部位于中国广东省深圳市的上市跨国制造企业...",
    "url": "https://zh.wikipedia.org/wiki/比亚迪"
  }
}
```

### 新闻查询

```bash
GET /api/webdata/news?keyword=A股&limit=10&language=zh-CN

# 响应示例
{
  "success": true,
  "source": "google_news_rss",
  "latency_ms": 1234,
  "data": {
    "keyword": "A股",
    "articles": [
      {
        "title": "A股三大指数集体收涨",
        "url": "https://...",
        "source": "新浪财经",
        "published_at": "2026-01-30T10:30:00Z"
      }
    ]
  }
}
```

### 通用搜索

```bash
GET /api/webdata/search?q=关键词&categories=general&limit=10

# 响应示例
{
  "success": true,
  "source": "searxng_enhanced",
  "latency_ms": 567,
  "data": {
    "keyword": "关键词",
    "results": [
      {
        "title": "...",
        "url": "...",
        "content": "...",
        "engine": "google"
      }
    ]
  }
}
```

### 智能查询

```bash
# 自动识别查询类型
GET /api/webdata/smart?q=北京天气
GET /api/webdata/smart?q=比亚迪股价
GET /api/webdata/smart?q=特斯拉是什么公司
GET /api/webdata/smart?q=A股最新新闻
```

### 批量查询

```bash
POST /api/webdata/multi
Content-Type: application/json

{
  "queries": [
    {"type": "weather", "location": "Beijing"},
    {"type": "stock", "symbol": "002594.SZ"},
    {"type": "encyclopedia", "keyword": "比亚迪"}
  ]
}
```

### 健康检查

```bash
GET /api/webdata/health

# 响应示例
{
  "status": "healthy",
  "providers": {
    "weather": [
      {"name": "wttr.in", "status": "healthy", "error_count": 0, "success_count": 5}
    ],
    "stock": [
      {"name": "yahoo_finance", "status": "degraded", "error_count": 1},
      {"name": "sina_finance", "status": "healthy", "error_count": 0}
    ]
  }
}
```

## Python 代码使用

```python
from app.utils.web_data_providers import (
    get_web_data_manager,
    query_weather,
    query_stock,
    query_encyclopedia,
    query_news,
    query_search,
)

# 方式1：使用便捷函数
result = query_weather("Beijing")
if result.success:
    print(f"温度: {result.data['temperature_c']}°C")

# 方式2：使用管理器
manager = get_web_data_manager()
result = manager.query_stock("002594.SZ")
print(f"来源: {result.source}, 延迟: {result.latency_ms}ms")

# 并发查询
from app.utils.web_data_providers import DataCategory
results = manager.query_parallel(DataCategory.STOCK, symbol="1211.HK", timeout=5)

# 健康状态
status = manager.get_health_status()
```

## 数据源优先级

每种数据类型都有多个数据源，按优先级自动降级：

| 类别 | 优先级1 | 优先级2 | 优先级3 | 优先级4+ |
|------|---------|---------|---------|----------|
| 天气 | wttr.in | OpenWeatherMap | - | - |
| 股票 | Yahoo Finance | Sina Finance | - | - |
| 百科 | Wikipedia | 百度百科 | - | - |
| 新闻 | NewsAPI | 财联社 | 华尔街见闻 | 金十/东方财富/新浪/腾讯 |
| 搜索 | SearXNG | DuckDuckGo | - | - |

### 新闻数据源详情

系统集成了 **9个** 新闻数据源，支持聚合查询获取20-50条高质量新闻：

| 名称 | 提供器名 | 特点 | 是否需要API Key |
|------|----------|------|-----------------|
| NewsAPI | newsapi | 国际新闻，100+来源 | ✅ (免费100次/天) |
| Google News | google_news_rss | 国际新闻，RSS免费 | ❌ |
| 财联社 | cls_news | 中国财经快讯，时效性强 | ❌ |
| 华尔街见闻 | wallstreetcn | 深度财经分析 | ❌ |
| 金十数据 | jin10 | 实时财经快讯 | ❌ |
| 东方财富 | eastmoney_news | A股相关新闻丰富 | ❌ |
| 新浪财经 | sina_finance_news | 综合财经新闻 | ❌ |
| 腾讯财经 | tencent_finance_news | 综合财经新闻 | ❌ |
| RSSHub聚合 | rsshub_finance | 需自建RSSHub实例 | ❌ |

### 聚合新闻查询 API

专门为深度分析场景设计，从多源并发获取并去重：

```bash
GET /api/webdata/news/aggregated?keyword=比亚迪&min_articles=20&max_articles=50

# 响应示例
{
  "success": true,
  "source": "aggregated:jin10,wallstreetcn,sina_finance_news...",
  "latency_ms": 1673,
  "data": {
    "keyword": "比亚迪",
    "articles": [...],
    "total_results": 50,
    "sources_used": ["jin10", "wallstreetcn", "sina_finance_news", "newsapi", "google_news_rss"],
    "aggregation_stats": {
      "total_raw": 120,
      "after_dedup": 85,
      "final_count": 50,
      "elapsed_ms": 1673
    }
  }
}
```

## 缓存策略

| 数据类型 | 默认 TTL | 说明 |
|----------|----------|------|
| 天气 | 10分钟 | 天气变化不频繁 |
| 股票 | 1分钟 | 盘中实时性要求高 |
| 百科 | 1小时 | 内容相对稳定 |
| 新闻 | 5分钟 | 新闻时效性要求 |
| 搜索 | 5分钟 | 一般时效性 |

## 扩展新数据源

```python
from app.utils.web_data_providers import BaseDataProvider, DataCategory, ProviderResult

class MyCustomProvider(BaseDataProvider):
    name = "my_provider"
    category = DataCategory.NEWS
    priority = 3
    
    def query(self, keyword: str, **kwargs) -> ProviderResult:
        # 实现查询逻辑
        try:
            data = self._fetch_data(keyword)
            return ProviderResult(success=True, data=data, source=self.name)
        except Exception as e:
            return ProviderResult(success=False, error=str(e), source=self.name)

# 注册到管理器
manager = get_web_data_manager()
manager.register_provider(MyCustomProvider())
```

## 常见问题

### Q: SearXNG 不可用怎么办？
A: 系统会自动降级到 DuckDuckGo Instant Answer API。

### Q: 如何提高股票数据的稳定性？
A: 
1. 确保新浪财经可访问（国内网络）
2. 配置代理池用于 Yahoo Finance
3. 考虑添加东方财富 API 作为备选

### Q: 如何减少 API 调用次数？
A:
1. 增加缓存 TTL：`WEB_DATA_CACHE_TTL=600`
2. 使用批量查询端点
3. 在前端实现请求去重和节流

### Q: 如何监控数据源健康状态？
A: 调用 `/api/webdata/health` 端点，可集成到监控系统（Prometheus/Grafana）。
