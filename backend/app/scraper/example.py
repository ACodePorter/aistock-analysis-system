"""
Scraper 使用示例

演示如何使用完整的爬虫系统
"""

import asyncio
from backend.app.scraper import ScraperOrchestrator, run_scraper_sync


def example_1_sync_basic():
    """示例1: 基础同步用法"""
    print("=" * 50)
    print("Example 1: Basic Sync Usage")
    print("=" * 50)
    
    urls = [
        'https://en.wikipedia.org/wiki/Python_(programming_language)',
        'https://en.wikipedia.org/wiki/JavaScript',
    ]
    
    stats = run_scraper_sync(
        urls=urls,
        config_path='backend/scraper/config.yaml',
        max_concurrent=3,
        max_duration=60,
    )
    
    print(f"Stats: {stats}")


async def example_2_async_advanced():
    """示例2: 高级异步用法"""
    print("\n" + "=" * 50)
    print("Example 2: Advanced Async Usage")
    print("=" * 50)
    
    # 创建orchestrator
    orch = ScraperOrchestrator('backend/scraper/config.yaml')
    
    # 添加URLs
    urls = [
        'https://en.wikipedia.org/wiki/Python_(programming_language)',
        'https://en.wikipedia.org/wiki/Java_(programming_language)',
    ]
    
    task_ids = orch.add_urls(urls, priority=1)
    print(f"Added {len(task_ids)} tasks")
    
    # 处理队列
    await orch.process_queue(max_concurrent=3, max_duration=120)
    
    # 获取统计
    stats = orch.get_stats()
    print(f"Success: {stats['scraper']['success']}")
    print(f"Failed: {stats['scraper']['failed']}")
    print(f"Manual Review: {stats['scraper']['manual_review']}")
    
    # 查看失败的任务
    failed = orch.get_failed_tasks()
    if failed:
        print("\nFailed tasks:")
        for task in failed:
            print(f"  - {task['url']}: {task['last_error']}")
    
    await orch.close()


def example_3_queue_persistence():
    """示例3: 任务队列持久化（中断恢复）"""
    print("\n" + "=" * 50)
    print("Example 3: Queue Persistence")
    print("=" * 50)
    
    from backend.app.scraper import TaskQueue
    
    # 创建队列
    queue = TaskQueue('scraper_queue.db')
    
    # 添加任务
    urls = [
        'https://example.com/page1',
        'https://example.com/page2',
        'https://example.com/page3',
    ]
    
    for url in urls:
        queue.enqueue(url, domain='example.com', priority=1)
    
    # 获取统计
    stats = queue.get_stats()
    print(f"Queue stats: {stats}")
    
    # 获取一个待处理任务
    task = queue.dequeue()
    if task:
        print(f"Dequeued: {task}")
        
        # 模拟成功
        queue.mark_success(task['id'], {'content_length': 12345})
        
        # 或者模拟失败
        # queue.mark_failed(task['id'], 'Connection timeout')
    
    # 查看失败任务
    failed = queue.get_failed_tasks()
    print(f"Failed tasks: {len(failed)}")


def example_4_login_detection():
    """示例4: 登录检测"""
    print("\n" + "=" * 50)
    print("Example 4: Login Detection")
    print("=" * 50)
    
    from backend.app.scraper import is_login_page
    
    # 测试登录检测
    test_cases = [
        {
            'name': 'Login form page',
            'content': '<form><input type="password" name="pwd"></form>',
            'headers': {},
            'url': 'https://example.com',
            'status': 200,
        },
        {
            'name': '401 Unauthorized',
            'content': 'Unauthorized',
            'headers': {},
            'url': 'https://example.com',
            'status': 401,
        },
        {
            'name': 'Regular page',
            'content': '<h1>Welcome</h1><p>This is a regular page</p>',
            'headers': {},
            'url': 'https://example.com',
            'status': 200,
        },
    ]
    
    for case in test_cases:
        is_login, reason = is_login_page(
            case['content'],
            case['headers'],
            case['url'],
            case['status'],
        )
        print(f"{case['name']}: is_login={is_login}, reason={reason}")


def example_5_fetchers():
    """示例5: 直接使用不同的Fetcher"""
    print("\n" + "=" * 50)
    print("Example 5: Direct Fetcher Usage")
    print("=" * 50)
    
    from backend.app.scraper import WikipediaFetcher, RequestsFetcher
    
    # Wikipedia Fetcher (同步)
    print("\n1. Wikipedia Fetcher:")
    wiki_fetcher = WikipediaFetcher()
    result = wiki_fetcher.fetch('https://en.wikipedia.org/wiki/Python_(programming_language)')
    if result:
        print(f"   Title: {result.get('title')}")
        print(f"   Length: {result.get('extract_length')} chars")
    
    # Requests Fetcher
    print("\n2. Requests Fetcher:")
    req_fetcher = RequestsFetcher()
    result = req_fetcher.fetch('https://www.example.com')
    if result:
        print(f"   Status: {result.get('status_code')}")
        print(f"   Is login: {result.get('is_login_page')}")
        print(f"   Content length: {result.get('content_length')} bytes")


async def example_6_domain_routing():
    """示例6: 域名路由"""
    print("\n" + "=" * 50)
    print("Example 6: Domain Routing")
    print("=" * 50)
    
    from backend.app.scraper import DomainRouter
    
    config = {
        'domains': [
            {
                'name': 'wikipedia',
                'fetcher': 'wikipedia',
                'patterns': ['*.wikipedia.org', 'wikipedia.org'],
            },
            {
                'name': 'example',
                'fetcher': 'requests',
                'patterns': ['example.com', '*.example.com'],
            },
        ]
    }
    
    router = DomainRouter(config)
    
    urls = [
        'https://en.wikipedia.org/wiki/Python',
        'https://www.example.com',
        'https://api.example.com/data',
        'https://unknown.com/page',
    ]
    
    for url in urls:
        config = router.route(url)
        print(f"{url}")
        print(f"  -> Fetcher: {config['fetcher']}")
        print(f"  -> Domain: {config['domain']}")


def main():
    """运行所有示例"""
    print("\n" + "=" * 70)
    print("SCRAPER MODULE EXAMPLES")
    print("=" * 70)
    
    # 示例1: 基础同步
    # example_1_sync_basic()
    
    # 示例2: 高级异步
    # asyncio.run(example_2_async_advanced())
    
    # 示例3: 队列持久化
    example_3_queue_persistence()
    
    # 示例4: 登录检测
    example_4_login_detection()
    
    # 示例5: Fetchers
    # example_5_fetchers()
    
    # 示例6: 域名路由
    asyncio.run(example_6_domain_routing())
    
    print("\n" + "=" * 70)
    print("EXAMPLES COMPLETED")
    print("=" * 70)


if __name__ == '__main__':
    main()
