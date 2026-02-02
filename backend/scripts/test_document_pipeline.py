"""
测试文档管理流水线：PDF 下载 -> 对象存储 -> LLM 结构化提取 -> 入库
"""
import asyncio
import os
import sys
import json

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.news.document_manager import (
    UnifiedDocumentManager, UnifiedDocument, DocumentPipeline
)


async def test_pdf_pipeline():
    """测试 PDF 处理流水线"""
    print("=" * 60)
    print("统一文档管理流水线测试")
    print("=" * 60)
    
    # 使用今日有效的 PDF URL
    test_urls = [
        "https://static.cninfo.com.cn/finalpage/2026-01-24/1224949318.PDF",
        "https://static.cninfo.com.cn/finalpage/2026-01-24/1224949319.PDF",
    ]
    
    manager = UnifiedDocumentManager()
    
    try:
        # 1. 测试单个 PDF 处理
        print("\n[1] 测试单个 PDF 处理...")
        doc = UnifiedDocument(
            title="测试公告-科华生物",
            url=test_urls[0],
            source="cninfo",
            symbol="002022",
            is_pdf=True,
            content_type="pdf"
        )
        
        processed = await manager.pipeline.process_document(doc)
        
        print(f"  - 标题: {processed.title}")
        print(f"  - URL: {processed.url}")
        print(f"  - PDF 元数据:")
        if processed.pdf_meta:
            print(f"    - 存储路径: {processed.pdf_meta.storage_path}")
            print(f"    - 文件大小: {processed.pdf_meta.file_size:,} bytes")
            print(f"    - 页数: {processed.pdf_meta.page_count}")
            print(f"    - 提取状态: {processed.pdf_meta.extraction_status}")
        
        print(f"  - 提取文本长度: {len(processed.extracted_text):,} 字符")
        print(f"  - LLM 已分析: {processed.llm_analyzed}")
        
        if processed.tags:
            print(f"  - 结构化标签:")
            print(f"    - 文档类型: {processed.tags.document_type}")
            print(f"    - 行业: {processed.tags.industry}")
            print(f"    - 主题: {processed.tags.themes}")
            print(f"    - 关键词: {processed.tags.keywords[:5]}...")
            print(f"    - 情感: {processed.tags.sentiment} ({processed.tags.sentiment_score})")
            print(f"    - 重要性: {processed.tags.importance}")
            print(f"    - 摘要: {processed.tags.summary[:100]}..." if processed.tags.summary else "    - 摘要: (无)")
            print(f"    - 要点: {processed.tags.key_points[:3]}" if processed.tags.key_points else "    - 要点: (无)")
        
        # 2. 测试入库
        print("\n[2] 测试 MongoDB 入库...")
        success = await manager.ingester.ingest_document(processed)
        print(f"  - 入库结果: {'成功' if success else '失败'}")
        
        # 3. 测试批量处理
        print("\n[3] 测试批量处理...")
        documents = [
            {
                "title": f"测试公告 {i+1}",
                "url": url,
                "source": "cninfo",
                "symbol": "002022",
                "is_pdf": True,
            }
            for i, url in enumerate(test_urls)
        ]
        
        stats = await manager.process_and_ingest(documents)
        print(f"  - 处理统计:")
        print(f"    - 总数: {stats['total']}")
        print(f"    - 已处理: {stats['processed']}")
        print(f"    - PDF 下载: {stats['pdf_downloaded']}")
        print(f"    - LLM 分析: {stats['llm_analyzed']}")
        print(f"    - 已入库: {stats['ingested']}")
        print(f"    - 错误: {stats['errors']}")
        
        # 4. 检查对象存储
        print("\n[4] 检查对象存储...")
        storage_path = manager.pipeline.storage.base_path
        pdf_count = len([f for f in os.listdir(os.path.join(storage_path, 'pdf')) if f.endswith('.pdf')])
        text_count = len([f for f in os.listdir(os.path.join(storage_path, 'text')) if f.endswith('.txt')])
        meta_count = len([f for f in os.listdir(os.path.join(storage_path, 'meta')) if f.endswith('.json')])
        
        print(f"  - 存储路径: {storage_path}")
        print(f"  - PDF 文件数: {pdf_count}")
        print(f"  - 文本文件数: {text_count}")
        print(f"  - 元数据文件数: {meta_count}")
        
        # 5. 读取并显示一个元数据示例
        print("\n[5] 元数据示例:")
        meta = await manager.pipeline.storage.get_meta(test_urls[0])
        if meta:
            # 精简显示
            display_meta = {
                'title': meta.get('title'),
                'source': meta.get('source'),
                'symbol': meta.get('symbol'),
                'is_pdf': meta.get('is_pdf'),
                'llm_analyzed': meta.get('llm_analyzed'),
            }
            if meta.get('tags'):
                display_meta['tags'] = {
                    'document_type': meta['tags'].get('document_type'),
                    'sentiment': meta['tags'].get('sentiment'),
                    'importance': meta['tags'].get('importance'),
                }
            print(json.dumps(display_meta, ensure_ascii=False, indent=2))
        
        print("\n" + "=" * 60)
        print("测试完成!")
        print("=" * 60)
        
    finally:
        await manager.close()


async def test_without_llm():
    """不调用 LLM 的简化测试（仅测试下载和存储）"""
    print("=" * 60)
    print("简化测试（无 LLM）")
    print("=" * 60)
    
    # 使用今日有效的 PDF URL
    test_url = "https://static.cninfo.com.cn/finalpage/2026-01-24/1224949318.PDF"
    
    pipeline = DocumentPipeline()
    
    try:
        doc = UnifiedDocument(
            title="测试公告",
            url=test_url,
            source="cninfo",
            is_pdf=True,
            content_type="pdf"
        )
        
        # 只处理 PDF（不调用 LLM）
        doc = await pipeline._process_pdf(doc)
        
        print(f"PDF 处理结果:")
        print(f"  - 提取状态: {doc.pdf_meta.extraction_status if doc.pdf_meta else 'N/A'}")
        print(f"  - 文本长度: {len(doc.extracted_text):,} 字符")
        print(f"  - 存储路径: {doc.pdf_meta.storage_path if doc.pdf_meta else 'N/A'}")
        
        # 显示文本预览
        if doc.extracted_text:
            print(f"\n文本预览（前500字）:")
            print("-" * 40)
            print(doc.extracted_text[:500])
            print("-" * 40)
        
    finally:
        await pipeline.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 分析")
    args = parser.parse_args()
    
    if args.no_llm:
        asyncio.run(test_without_llm())
    else:
        asyncio.run(test_pdf_pipeline())
