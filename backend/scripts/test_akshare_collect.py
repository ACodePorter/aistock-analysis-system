import asyncio
import json
from backend.app.news.akshare_collector import AKShareCollector

async def main():
    collector = AKShareCollector(max_concurrent=2, min_interval_seconds=0.2, retry=1)
    symbols = ["600519.SH", "000001.SZ"]
    print("Fetching announcements batch for:", symbols)
    ann = await collector.batch_get_announcements(symbols, per_symbol=3)
    print(json.dumps(ann, ensure_ascii=False, indent=2))

    print("Fetching stock news batch for:", symbols)
    news = await collector.batch_get_stock_news(symbols, per_symbol=3)
    print(json.dumps(news, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
