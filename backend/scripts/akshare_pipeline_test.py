import asyncio
import json
from backend.app.news.akshare_collector import AKShareCollector
from backend.app.news.news_service import NewsProcessor

async def main():
    collector = AKShareCollector(max_concurrent=2, min_interval_seconds=0.2, retry=1)
    symbol = "000001.SZ"
    news = await collector.get_stock_news(symbol, limit=10)
    print(f"Collected {len(news)} items for {symbol}")
    # normalize to search-result like dicts expected by NewsProcessor
    formatted = []
    for item in news:
        formatted.append({
            'title': item.get('title') or '',
            'url': item.get('url') or '',
            'summary': item.get('summary') or '',
            'published': item.get('published') or None,
            'source': item.get('source') or 'akshare',
        })
    print(json.dumps(formatted, ensure_ascii=False, indent=2)[:2000])

    processor = NewsProcessor()
    processed = await processor.process_search_results(formatted, related_symbol=symbol)
    print(f"Processed -> articles returned: {len(processed)}")

if __name__ == '__main__':
    asyncio.run(main())
