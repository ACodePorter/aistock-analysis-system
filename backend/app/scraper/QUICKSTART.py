"""
快速开始指南 (Quick Start Guide)
"""

# ============================================================================
# 1. 最简单的用法 - 5行代码爬取多个网站
# ============================================================================

from backend.app.scraper import run_scraper_sync

urls = [
    'https://en.wikipedia.org/wiki/Python_(programming_language)',
    'https://en.wikipedia.org/wiki/JavaScript',
]

stats = run_scraper_sync(urls)
print(f"成功: {stats['scraper']['success']}, 失败: {stats['scraper']['failed']}")


# ============================================================================
# 2. 异步用法 - 更高效的并发爬取
# ============================================================================

import asyncio
from backend.app.scraper import run_scraper

async def main():
    urls = ['https://en.wikipedia.org/wiki/Python', 'https://en.wikipedia.org/wiki/Java']
    stats = await run_scraper(urls, max_concurrent=10)
    print(stats)

asyncio.run(main())


# ============================================================================
# 3. 高级用法 - 完全控制
# ============================================================================

import asyncio
from backend.app.scraper import ScraperOrchestrator

async def main():
    # 创建爬虫
    scraper = ScraperOrchestrator()
    
    # 添加URLs
    scraper.add_urls([
        'https://en.wikipedia.org/wiki/Python',
        'https://en.wikipedia.org/wiki/JavaScript',
    ], priority=1)
    
    # 处理队列
    await scraper.process_queue(max_concurrent=5)
    
    # 查看结果
    stats = scraper.get_stats()
    failed = scraper.get_failed_tasks()
    
    print(f"✅ 成功: {stats['scraper']['success']}")
    print(f"❌ 失败: {len(failed)}")
    
    await scraper.close()

asyncio.run(main())


# ============================================================================
# 4. 登录网站爬取 (需要先生成 storage_state.json)
# ============================================================================

import asyncio
from backend.app.scraper import PlaywrightFetcher, StateManager

async def main():
    # 1. 生成登录态
    # python -m playwright codegen --save-storage https://www.tianyancha.com
    # 保存到 backend/scraper/storage/states/tianyancha_state_1.json
    
    # 2. 使用带登录态的Fetcher
    state_mgr = StateManager(['backend/scraper/storage/states/tianyancha_state_1.json'])
    fetcher = PlaywrightFetcher(state_manager=state_mgr)
    
    # 3. 爬取
    result = await fetcher.fetch('https://www.tianyancha.com/company/...')
    print(f"登录状态: {not result['is_login_page']}")
    print(f"内容长度: {result['content_length']}")

asyncio.run(main())


# ============================================================================
# 5. 监控队列状态
# ============================================================================

from backend.app.scraper import TaskQueue

queue = TaskQueue()

# 查看统计
stats = queue.get_stats()
print(f"待处理: {stats['pending']}")
print(f"成功: {stats['success']}")
print(f"需要人工审核: {stats['manual_review']}")

# 查看失败的任务
failed = queue.get_failed_tasks(limit=10)
for task in failed:
    print(f"失败: {task['url']} - {task['last_error']}")


# ============================================================================
# 6. 配置调优
# ============================================================================

# config.yaml 中的关键配置:

"""
# 速率限制 (避免反爬虫)
rate_limits:
  wikipedia: 5        # Wikipedia允许5req/s
  default: 0.2        # 其他网站0.2req/s

# 浏览器配置 (登录网站)
browser:
  headless: true      # 无头模式（更快、更稳定）
  timeout: 30000      # 30秒超时
  concurrent: 3       # 最多3个浏览器进程

# 重试配置
retry:
  max_attempts: 5     # 最多重试5次
  backoff_base: 2     # 指数退避：1s, 2s, 4s, 8s, 16s
  max_backoff: 60     # 最大等待60秒
"""


# ============================================================================
# 7. 常用模式
# ============================================================================

# 模式1: 单一域名快速爬取
from backend.app.scraper import WikipediaFetcher

fetcher = WikipediaFetcher()
result = fetcher.fetch('https://en.wikipedia.org/wiki/Python')
content = result['content']


# 模式2: 多域名智能路由
from backend.app.scraper import run_scraper_sync

urls = [
    'https://en.wikipedia.org/wiki/Python',      # 自动使用Wikipedia Fetcher
    'https://www.baidu.com/s?wd=python',         # 自动使用Requests Fetcher
    'https://www.tianyancha.com/company/...',    # 自动使用Playwright Fetcher
]
stats = run_scraper_sync(urls)


# 模式3: 中断恢复
# Session 1: 爬取100个URL
stats1 = run_scraper_sync(urls[:100])

# Session 2: 重新启动，自动继续处理未完成的
stats2 = run_scraper_sync(urls[:100])


# ============================================================================
# 8. 故障排查
# ============================================================================

# 查看日志
import subprocess
subprocess.run('tail -f scraper.log', shell=True)

# 重置卡住的任务
from backend.app.scraper import TaskQueue
queue = TaskQueue()
queue.reset_stuck_tasks(timeout_minutes=30)

# 清理旧记录
queue.clear_old_tasks(days=30)


# ============================================================================
# 架构概览
# ============================================================================

"""
用户 URL列表
  ↓
TaskQueue (SQLite持久化)
  ↓
ScraperOrchestrator (主编排)
  ├─ DomainRouter (URL → Fetcher)
  │  ├─ Wikipedia Fetcher
  │  ├─ Requests Fetcher
  │  └─ Playwright Fetcher
  │
  ├─ LoginDetector (登录页识别)
  ├─ StateManager (浏览器登录态轮转)
  └─ Logger (JSON结构化日志)

输出: {content, metadata}
"""


# ============================================================================
# 关键特性总结
# ============================================================================

"""
✅ 多域名支持
   - Wikipedia: API调用，快速，无需登录
   - Tianyancha: 浏览器自动化，支持登录
   - QCC: 浏览器自动化，支持登录
   - 百度百科: HTTP爬取

✅ 登录检测 (5层多策略)
   - HTTP状态码检查
   - 重定向检查
   - 响应体关键字检查
   - 登录表单检查
   - Content-Type分析

✅ 状态管理
   - 多个登录账号支持
   - 自动轮转
   - 失败计数

✅ 健壮重试
   - 指数退避
   - 状态轮转
   - 手动审核队列

✅ 中断恢复
   - SQLite队列持久化
   - 任务状态追踪
   - 自动恢复

✅ 结构化监控
   - JSON日志
   - 事件追踪
   - 统计分析
"""
