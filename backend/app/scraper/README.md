# Scraper Module - 完整多域名爬虫系统

## 概述

这是一个生产级的Python爬虫系统，支持多个域名、多种抓取策略、自动登录检测、任务队列、中断恢复等企业级功能。

### 核心特性

✅ **多域名支持** - Wikipedia、Tianyancha、QCC、百度百科等
✅ **多种Fetcher** - Wikipedia API、Playwright（浏览器）、requests（HTTP）
✅ **登录检测** - 5层多策略自动检测登录页面
✅ **状态管理** - 浏览器登录状态自动轮转
✅ **任务队列** - SQLite持久化，支持中断恢复
✅ **结构化日志** - JSON格式便于监控和调试
✅ **健壮重试** - 指数退避+状态轮转+手动审核队列
✅ **静默运行** - 无需人工交互，支持后台服务

## 项目结构

```
backend/scraper/
├── config.yaml                    # 全局配置（域名、代理、速率、浏览器）
├── main.py                        # 主编排器 (ScraperOrchestrator)
├── domain_router.py               # URL → Fetcher 路由
├── __init__.py                    # 模块入口
│
├── fetchers/                      # Fetcher实现
│   ├── __init__.py
│   ├── wikipedia.py               # Wikipedia API fetcher
│   ├── requests_fetcher.py        # HTTP requests fetcher
│   └── playwright_fetcher.py      # 浏览器自动化 fetcher
│
├── storage/                       # 存储层
│   ├── __init__.py
│   ├── state_manager.py           # Playwright storage_state 管理
│   └── states/                    # 存放 storage_state.json 文件
│       ├── tianyancha_state_1.json
│       ├── tianyancha_state_2.json
│       └── ...
│
├── utils/                         # 工具函数
│   ├── __init__.py
│   ├── detect_login.py            # 登录页面检测
│   ├── http_utils.py              # User-Agent、速率限制、重试
│   └── logger.py                  # 结构化日志
│
└── queue/                         # 任务队列
    ├── __init__.py
    ├── task_queue.py              # SQLite任务队列
    └── scraper_queue.db           # 队列数据库（运行时生成）
```

## 配置文件

### config.yaml

```yaml
# 域名配置
domains:
  - name: wikipedia
    fetcher: wikipedia
    patterns: ['*.wikipedia.org']
    requires_login: false
    
  - name: tianyancha
    fetcher: playwright
    patterns: ['tianyancha.com']
    requires_login: true
    storage_states:
      - backend/scraper/storage/states/tianyancha_state_1.json
      - backend/scraper/storage/states/tianyancha_state_2.json

# User-Agent 列表
user_agents:
  - 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
  - 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
  - ...

# 代理列表（可选）
proxies: []

# 速率限制 (请求/秒)
rate_limits:
  wikipedia: 5
  default: 0.2

# 重试配置
retry:
  max_attempts: 5
  backoff_base: 2
  max_backoff: 60

# 浏览器配置
browser:
  headless: true
  timeout: 30000
  concurrent: 3

# 队列配置
queue:
  db_path: scraper_queue.db

# 日志配置
logging:
  file: scraper.log
  level: INFO
```

## 快速开始

### 1. 安装依赖

```bash
pip install playwright requests aiohttp pyyaml
playwright install chromium
```

### 2. 准备配置和状态文件

复制 `config.yaml.template` → `config.yaml`

对于需要登录的网站（Tianyancha、QCC），需要手动创建 `storage_state.json`：

```bash
# 使用Playwright Codegen生成登录态
python -m playwright codegen --save-storage https://www.tianyancha.com
# 保存到 backend/scraper/storage/states/tianyancha_state_1.json
```

### 3. 基础使用（同步）

```python
from backend.app.scraper import run_scraper_sync

urls = [
    'https://en.wikipedia.org/wiki/Python_(programming_language)',
    'https://www.baidu.com/s?wd=python',
]

stats = run_scraper_sync(
    urls=urls,
    config_path='backend/scraper/config.yaml',
    max_concurrent=5,
    max_duration=300,
)

print(stats)
# 输出:
# {
#   'scraper': {'total': 2, 'success': 1, 'failed': 0, 'manual_review': 0},
#   'queue': {'pending': 0, 'success': 1, 'failed': 0, 'manual_review': 0, 'total': 1}
# }
```

### 4. 异步使用

```python
import asyncio
from backend.app.scraper import run_scraper

async def main():
    urls = [
        'https://en.wikipedia.org/wiki/Python',
        'https://www.baidu.com/s?wd=python',
    ]
    
    stats = await run_scraper(
        urls=urls,
        config_path='backend/scraper/config.yaml',
        max_concurrent=10,
        max_duration=600,
    )
    print(stats)

asyncio.run(main())
```

### 5. 高级用法 - 使用Orchestrator

```python
import asyncio
from backend.app.scraper import ScraperOrchestrator

async def main():
    orch = ScraperOrchestrator('backend/scraper/config.yaml')
    
    # 添加单个URL
    task_id = orch.add_url('https://en.wikipedia.org/wiki/Python')
    
    # 添加多个URLs
    task_ids = orch.add_urls([
        'https://www.baidu.com/s?wd=python',
        'https://www.baidu.com/s?wd=java',
    ], priority=1)
    
    # 处理队列
    await orch.process_queue(max_concurrent=5, max_duration=300)
    
    # 获取统计
    stats = orch.get_stats()
    print(f"Success: {stats['scraper']['success']}")
    
    # 获取失败任务
    failed = orch.get_failed_tasks()
    for task in failed:
        print(f"Failed: {task['url']} - {task['last_error']}")
    
    await orch.close()

asyncio.run(main())
```

## 工作流程

### 1. URL入队

```
User → add_url(url) → 解析域名 → 入队到TaskQueue
```

### 2. 任务处理

```
Dequeue → 获取Fetcher → 调用Fetcher.fetch()
    ↓
检查登录页?
    ├─ YES → 轮转State → 重试
    └─ NO → 返回结果
```

### 3. 失败处理

```
Fetch失败 → 检查重试次数
    ├─ 还有重试次数 → 返回PENDING（入队重试）
    └─ 无重试次数 → 移至MANUAL_REVIEW
```

### 4. 日志和监控

所有事件记录为JSON格式：

```json
{
  "timestamp": "2024-01-01T12:00:00",
  "event_type": "fetch_success",
  "url": "https://example.com",
  "domain": "example.com",
  "fetcher": "playwright",
  "content_length": 12345,
  "elapsed_time": 2.5
}
```

## Fetcher详解

### Wikipedia Fetcher

- **用途**: Wikipedia页面内容提取
- **方法**: Wikimedia API调用
- **优势**: 无需登录、速度快、无反爬虫
- **返回**: {title, content, url, language, pageid}

```python
from backend.app.scraper import WikipediaFetcher

fetcher = WikipediaFetcher()
result = await fetcher.fetch_async('https://en.wikipedia.org/wiki/Python')
```

### Requests Fetcher

- **用途**: 普通HTTP页面抓取
- **方法**: requests库
- **优势**: 简单、快速、支持cookies
- **返回**: {content, headers, status_code, is_login_page}

```python
from backend.app.scraper import RequestsFetcher

fetcher = RequestsFetcher()
result = fetcher.fetch('https://www.baidu.com/s?wd=python')
```

### Playwright Fetcher

- **用途**: 登录保护网站、JavaScript渲染
- **方法**: Chromium浏览器自动化
- **优势**: 支持登录状态、JavaScript、复杂交互
- **返回**: {content, status_code, is_login_page, user_agent}

```python
from backend.app.scraper import PlaywrightFetcher, StateManager

state_mgr = StateManager(['state1.json', 'state2.json'])
fetcher = PlaywrightFetcher(state_manager=state_mgr)
result = await fetcher.fetch('https://www.tianyancha.com')
```

## 登录检测逻辑

系统通过5层多策略检测登录页面：

```
1. HTTP状态码 (401, 403)
    ↓
2. 重定向URL (包含login关键字)
    ↓
3. 响应体关键字 (login, 登录, 请登录等20+)
    ↓
4. 登录表单字段 (password, captcha等)
    ↓
5. Content-Type分析
```

自动处理：
- ✅ 检测到登录页 → 轮转登录状态
- ✅ 状态耗尽 → 移至手动审核
- ✅ 网络错误 → 指数退避重试

## 状态管理（Storage State）

### 什么是Storage State

Playwright的`storage_state.json`包含：
- Cookies
- LocalStorage
- SessionStorage
- 登录令牌

### 如何生成

```bash
# 1. 打开浏览器代码生成器
python -m playwright codegen --save-storage https://www.tianyancha.com

# 2. 手动登录
# 3. 访问目标页面
# 4. 关闭浏览器 → 保存storage_state.json

# 5. 复制到 backend/scraper/storage/states/
cp storage_state.json backend/scraper/storage/states/tianyancha_state_1.json
```

### 多状态轮转

支持为同一域名配置多个状态文件（应对账号限制、IP检测等）：

```yaml
tianyancha:
  storage_states:
    - states/tianyancha_state_1.json   # 账号1
    - states/tianyancha_state_2.json   # 账号2
    - states/tianyancha_state_3.json   # 账号3
```

失败时自动轮转到下一个账号。

## 任务队列

### 工作原理

基于SQLite的持久化队列，支持中断恢复：

```
┌─────────────────────────────────┐
│   scraper_queue.db              │
├─────────────────────────────────┤
│ ID  URL  Domain  Status  Attempt│
├─────────────────────────────────┤
│ 1   url1 wiki   success  1      │
│ 2   url2 wiki   pending  0      │
│ 3   url3 tianya failed   3      │
│ 4   url4 baidu  manual   5      │
└─────────────────────────────────┘
```

### 任务状态

- **PENDING**: 待处理
- **PROCESSING**: 正在处理
- **SUCCESS**: 成功完成
- **FAILED**: 失败（且无重试机会）
- **MANUAL_REVIEW**: 需要人工审核

### 中断恢复

```python
# Session 1: 处理了5个任务，中途中断
stats1 = run_scraper_sync(urls[:100])

# Session 2: 重新启动，自动从pending恢复
stats2 = run_scraper_sync(urls[:100])  # 继续处理剩余任务
```

## 监控和故障排查

### 查看日志

```bash
tail -f scraper.log | grep error
```

### 检查队列状态

```python
from backend.app.scraper import TaskQueue

queue = TaskQueue()
stats = queue.get_stats()
print(f"Pending: {stats['pending']}")
print(f"Success: {stats['success']}")
print(f"Manual Review: {stats['manual_review']}")
```

### 查看失败任务

```python
failed = queue.get_failed_tasks(limit=20)
for task in failed:
    print(f"{task['url']}: {task['last_error']}")
```

### 重置卡住的任务

```python
queue.reset_stuck_tasks(timeout_minutes=30)
```

## 性能优化建议

1. **并发控制**: `max_concurrent` 根据机器资源调整
   - 普通硬件: 3-5
   - 高配置: 10-20

2. **速率限制**: 配置中`rate_limits`避免反爬虫
   - Wikipedia: 5 req/s（官方允许）
   - 其他: 0.2 req/s（安全）

3. **浏览器优化**:
   ```yaml
   browser:
     headless: true           # 无头模式更快
     timeout: 30000          # 30秒超时
     concurrent: 3           # 最多3个浏览器进程
   ```

4. **状态缓存**: 多次访问同一域名时复用context

## 扩展指南

### 添加新的Fetcher

```python
# my_fetcher.py
class CustomFetcher:
    async def fetch(self, url: str) -> Dict[str, Any]:
        # 实现获取逻辑
        return {
            'url': url,
            'status_code': 200,
            'content': 'page content',
            'is_login_page': False,
        }

# 在 main.py 中注册
# fetchers['custom'] = CustomFetcher()
```

### 添加新的域名

```yaml
domains:
  - name: mysite
    fetcher: requests
    patterns: ['mysite.com', '*.mysite.com']
    requires_login: false
```

### 自定义事件处理

```python
from backend.app.scraper import ScraperEventLogger

logger = ScraperEventLogger('my_scraper.log')
logger.log_event('custom_event', 'My message', {'key': 'value'})
```

## 常见问题

### Q: 如何处理需要JavaScript渲染的页面？
**A**: 使用Playwright fetcher，在config中配置该域名使用'playwright'。

### Q: 如何支持更多的登录网站？
**A**: 为新域名生成storage_state.json，添加到config.yaml中。

### Q: 如何限制同时打开的浏览器数量？
**A**: 在config中设置 `browser.concurrent` 值。

### Q: 如何在服务器上无界面运行？
**A**: 使用 `headless: true`（默认值）并在后台运行：
```bash
nohup python -c "from backend.app.scraper import run_scraper_sync; run_scraper_sync(...)" > scraper.log 2>&1 &
```

### Q: 支持代理吗？
**A**: 支持。在config.yaml中配置proxies列表，会自动轮转。

## 依赖安装

### 必需

```bash
pip install requests aiohttp pyyaml
```

### 可选（完整功能）

```bash
pip install playwright
python -m playwright install chromium
```

## 许可证

MIT

## 贡献

欢迎提交Issue和PR！
