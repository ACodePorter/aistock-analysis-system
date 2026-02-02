"""
端到端测试：文档处理流水线集成测试
验证完整流程：CNInfo 获取公告 -> PDF 下载 -> 对象存储 -> LLM 结构化提取 -> MongoDB 入库
"""
import asyncio
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.news.document_manager import UnifiedDocumentManager, UnifiedDocument
from app.news.multi_source_collector import MultiSourceCollector


async def test_e2e_pipeline():
    """端到端测试：从 CNInfo 获取公告并完整处理"""
    print("=" * 70)
    print("端到端流水线测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # 1. 准备测试公告数据
    print("\n[1/4] 准备测试公告数据...")
    # 直接使用今日有效的 PDF URL
    announcements = [
        {
            'title': '迪哲医药：关于向香港联交所递交境外上市外资股（H股）发行并上市的申请',
            'url': 'https://static.cninfo.com.cn/finalpage/2026-01-24/1224949359.PDF',
            'source': 'cninfo',
            'symbol': '688192',
            'is_pdf': True,
        },
        {
            'title': '恒丰纸业：发行股份购买资产暨关联交易报告书',
            'url': 'https://static.cninfo.com.cn/finalpage/2026-01-24/1224949319.PDF',
            'source': 'cninfo',
            'symbol': '600356',
            'is_pdf': True,
        },
        {
            'title': '恒丰纸业：关于发行股份购买资产暨关联交易事项获得中国证监会批复',
            'url': 'https://static.cninfo.com.cn/finalpage/2026-01-24/1224949318.PDF',
            'source': 'cninfo',
            'symbol': '600356',
            'is_pdf': True,
        },
    ]
    
    if not announcements:
        print("  ❌ 未获取到公告，测试终止")
        return
    
    print(f"  ✓ 获取到 {len(announcements)} 条公告:")
    for i, ann in enumerate(announcements):
        print(f"    {i+1}. {ann['title'][:50]}...")
        print(f"       URL: {ann['url'][:60]}...")
        print(f"       是否PDF: {ann.get('is_pdf', False)}")
    
    # 2. 通过统一文档管理器处理
    print("\n[2/4] 通过统一文档管理器处理...")
    manager = UnifiedDocumentManager()
    
    try:
        stats = await manager.process_and_ingest(announcements)
        
        print(f"  处理统计:")
        print(f"    - 总数: {stats['total']}")
        print(f"    - 已处理: {stats['processed']}")
        print(f"    - PDF 下载成功: {stats['pdf_downloaded']}")
        print(f"    - LLM 分析完成: {stats['llm_analyzed']}")
        print(f"    - 入库成功: {stats['ingested']}")
        print(f"    - 错误数: {stats['errors']}")
        
        # 3. 验证对象存储
        print("\n[3/4] 验证对象存储...")
        storage_path = manager.pipeline.storage.base_path
        
        pdf_files = [f for f in os.listdir(os.path.join(storage_path, 'pdf')) if f.endswith('.pdf')]
        text_files = [f for f in os.listdir(os.path.join(storage_path, 'text')) if f.endswith('.txt')]
        meta_files = [f for f in os.listdir(os.path.join(storage_path, 'meta')) if f.endswith('.json')]
        
        print(f"  存储路径: {storage_path}")
        print(f"  PDF 文件: {len(pdf_files)} 个")
        print(f"  文本文件: {len(text_files)} 个")
        print(f"  元数据文件: {len(meta_files)} 个")
        
        # 显示一个元数据示例
        if meta_files:
            sample_meta_path = os.path.join(storage_path, 'meta', meta_files[-1])
            with open(sample_meta_path, 'r', encoding='utf-8') as f:
                sample_meta = json.load(f)
            
            print(f"\n  元数据示例 ({meta_files[-1][:20]}...):")
            print(f"    - 标题: {sample_meta.get('title', '')[:40]}...")
            print(f"    - 来源: {sample_meta.get('source')}")
            print(f"    - LLM已分析: {sample_meta.get('llm_analyzed')}")
            if sample_meta.get('tags'):
                tags = sample_meta['tags']
                print(f"    - 文档类型: {tags.get('document_type')}")
                print(f"    - 行业: {tags.get('industry')}")
                print(f"    - 情感: {tags.get('sentiment')} ({tags.get('sentiment_score')})")
                print(f"    - 重要性: {tags.get('importance')}")
        
        # 4. 验证 MongoDB 入库
        print("\n[4/4] 验证 MongoDB 入库...")
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient('mongodb://localhost:27017')
        db = client['aistock_news']
        
        total_docs = await db['documents'].count_documents({})
        recent_docs = await db['documents'].count_documents({
            'processed_at': {'$exists': True}
        })
        
        print(f"  documents 集合总数: {total_docs}")
        print(f"  已处理文档数: {recent_docs}")
        
        # 显示最新入库的文档
        latest = await db['documents'].find_one(
            sort=[('updated_at', -1)]
        )
        if latest:
            print(f"\n  最新入库文档:")
            print(f"    - 标题: {latest.get('title', '')[:50]}...")
            print(f"    - 来源: {latest.get('source')}")
            print(f"    - 是否PDF: {latest.get('is_pdf')}")
            if latest.get('tags'):
                print(f"    - 文档类型: {latest['tags'].get('document_type')}")
                print(f"    - 主题: {latest['tags'].get('themes')}")
                print(f"    - 关键词: {latest['tags'].get('keywords', [])[:3]}...")
        
        print("\n" + "=" * 70)
        print("✓ 端到端测试完成!")
        print("=" * 70)
        
    finally:
        await manager.close()


async def test_scheduler_integration():
    """测试调度器集成（模拟单股票处理）"""
    print("\n" + "=" * 70)
    print("调度器集成测试")
    print("=" * 70)
    
    from app.news.enhanced_news_scheduler import EnhancedNewsScheduler
    
    scheduler = EnhancedNewsScheduler()
    
    # 获取一些测试数据
    collector = MultiSourceCollector()
    announcements = await collector.fetch_cninfo_announcements(symbol='000001', limit=2)
    
    if not announcements:
        print("  ❌ 未获取到公告")
        return
    
    print(f"\n获取到 {len(announcements)} 条公告，开始处理...")
    
    # 调用 _process_and_save_articles
    saved = await scheduler._process_and_save_articles(announcements, 'TEST001')
    
    print(f"\n处理结果:")
    print(f"  - 保存成功: {saved}")
    print(f"  - 统计: {scheduler.stats}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduler", action="store_true", help="测试调度器集成")
    args = parser.parse_args()
    
    if args.scheduler:
        asyncio.run(test_scheduler_integration())
    else:
        asyncio.run(test_e2e_pipeline())
