import asyncio
import os
from backend.app.news.akshare_collector import AKShareCollector


async def main():
    col = AKShareCollector()
    symbols = ['600519', '000001', 'sh600519', 'sz000001']
    for s in symbols:
        print('Testing get_stock_news for', s)
        res = await col.get_stock_news(s, limit=5)
        print(' -> items:', len(res))
        print('Testing get_announcements for', s)
        res2 = await col.get_announcements(s, limit=5)
        print(' -> announcements:', len(res2))

if __name__ == '__main__':
    asyncio.run(main())
