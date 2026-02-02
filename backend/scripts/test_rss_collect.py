import asyncio
import sys
sys.path.insert(0, '..')
from backend.app.news.rss_collector import RSSNewsCollector

async def main():
    collector = RSSNewsCollector()
    articles = await collector.collect_all()
    print(f"Fetched {len(articles)} articles")
    # print first 3 titles
    for a in articles[:3]:
        print(a.get('title'), a.get('url'))

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        print('Error:', e)
        sys.exit(1)
