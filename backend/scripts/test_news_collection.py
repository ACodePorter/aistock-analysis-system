"""
测试改进后的新闻采集流程
"""
import asyncio
import logging
import sys
import os

# 设置项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_multi_source():
    """测试多源采集器"""
    from app.news.multi_source_collector import MultiSourceCollector
    
    print("=" * 60)
    print("测试 MultiSourceCollector")
    print("=" * 60)
    
    collector = MultiSourceCollector()
    try:
        # 测试单只股票
        results = await collector.collect_stock_news('000001.SZ', limit_per_source=5)
        print(f"\n获取到 {len(results)} 条新闻/公告:")
        
        for i, item in enumerate(results[:10], 1):
            print(f"\n{i}. [{item['source']}] {item['title'][:50]}")
            if item.get('url'):
                print(f"   URL: {item['url'][:70]}...")
            if item.get('published'):
                print(f"   发布: {item['published']}")
        
        # 按来源统计
        sources = {}
        for item in results:
            src = item.get('source', 'unknown')
            sources[src] = sources.get(src, 0) + 1
        
        print("\n\n来源统计:")
        for src, count in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"  {src}: {count} 条")
        
        return results
            
    finally:
        await collector.close()


async def test_scheduler_integration():
    """测试与调度器的整合"""
    print("\n" + "=" * 60)
    print("测试 EnhancedNewsScheduler 整合")
    print("=" * 60)
    
    try:
        from app.news.enhanced_news_scheduler import EnhancedNewsScheduler
        
        scheduler = EnhancedNewsScheduler()
        
        # 测试多源采集方法
        print("\n运行多源采集...")
        result = await scheduler.run_multi_source_collection(related_symbol='000001.SZ')
        print(f"调度器多源采集结果: {result}")
        
        # 显示统计
        print(f"统计信息: {scheduler.stats}")
        
        return result
        
    except Exception as e:
        print(f"整合测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_content_extraction(results):
    """测试内容提取"""
    print("\n" + "=" * 60)
    print("测试内容提取")
    print("=" * 60)
    
    from app.news.multi_source_collector import MultiSourceCollector
    
    collector = MultiSourceCollector()
    try:
        # 选取有 URL 的文章测试内容提取
        for item in results[:3]:
            url = item.get('url', '')
            if url and not url.endswith('.pdf'):
                print(f"\n提取: {item['title'][:40]}...")
                content = await collector.extract_content(url)
                if content:
                    print(f"  内容长度: {len(content)} 字符")
                    print(f"  预览: {content[:200]}...")
                else:
                    print("  未能提取内容")
                break
    finally:
        await collector.close()


async def main():
    print("开始测试改进后的新闻采集系统\n")
    
    # 1. 测试多源采集器
    results = await test_multi_source()
    
    # 2. 测试内容提取
    if results:
        await test_content_extraction(results)
    
    # 3. 测试调度器整合
    await test_scheduler_integration()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
