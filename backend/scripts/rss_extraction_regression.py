import asyncio
import json
import os
import sys
sys.path.insert(0, '..')

from backend.app.news.rss_collector import RSSNewsCollector
from backend.app.news.news_crawler import NewsContentCrawler


async def main():
    collector = RSSNewsCollector()
    articles = await collector.collect_all()
    print(f'Collected {len(articles)} RSS articles')
    urls = [a.get('url') for a in articles if a.get('url')]
    sample = urls[:10]
    print('Sampling', len(sample), 'urls for extraction')

    async with NewsContentCrawler() as crawler:
        results = await crawler.batch_crawl_articles(sample, max_concurrent=3)

    out = []
    for u, r in zip(sample, results):
        entry = {
            'url': u,
            'status': r.get('status'),
            'title': r.get('title'),
            'word_count': r.get('word_count', 0),
            'content_preview': (r.get('content') or '')[:200]
        }
        out.append(entry)

    os.makedirs('temp', exist_ok=True)
    path = os.path.join('temp', 'rss_extraction_results.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'sample_count': len(sample), 'results': out}, f, ensure_ascii=False, indent=2)

    print('Saved extraction results to', path)


if __name__ == '__main__':
    asyncio.run(main())
