import feedparser

FEEDS = {
    "caixin": "https://rsshub.app/caixin/article/latest",
    "yicai": "https://rsshub.app/yicai/brief",
    "cls": "https://rsshub.app/cls/telegraph",
    "wallstreetcn": "https://rsshub.app/wallstreetcn/live/global",
    "eastmoney_report": "https://rsshub.app/eastmoney/report",
    "xueqiu_hot": "https://rsshub.app/xueqiu/hots",
    "sina_finance": "https://feedx.net/rss/sinafinance.xml",
}

def check():
    for name, url in FEEDS.items():
        try:
            f = feedparser.parse(url)
            print(f"{name}: entries={len(f.entries)} status={getattr(f, 'status', 'N/A')}")
            if f.entries:
                print("  first:", f.entries[0].get('title'))
        except Exception as e:
            print(f"{name}: error: {e}")

if __name__ == '__main__':
    check()
