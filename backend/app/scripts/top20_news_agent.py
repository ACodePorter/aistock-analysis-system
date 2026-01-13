import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import time

# 可选：接入 Bing Web Search API 或用 requests+BeautifulSoup 爬取百度/Google/Bing
# 这里只做通用演示，实际生产建议用官方API

SEARCH_ENGINES = {
    'bing': 'https://www.bing.com/search?q={query}',
    'baidu': 'https://www.baidu.com/s?wd={query}',
    'google': 'https://www.google.com/search?q={query}'
}

# 获取Top20榜单（可替换为实际API）
def fetch_top20():
    url = 'http://localhost:8000/api/movers/live_insight?limit=20'
    resp = requests.get(url)
    data = resp.json()
    top20 = data.get('gainers', []) + data.get('losers', [])
    return top20[:20]

# 搜索新闻

def search_news(stock_name: str, engine: str = 'bing', max_results: int = 5) -> List[Dict]:
    url = SEARCH_ENGINES[engine].format(query=stock_name + ' 新闻')
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    results = []
    # Bing新闻结果
    for item in soup.select('li.b_algo'):
        title = item.select_one('h2')
        link = item.select_one('a')
        snippet = item.select_one('p')
        if title and link:
            results.append({
                'title': title.text.strip(),
                'url': link['href'],
                'snippet': snippet.text.strip() if snippet else ''
            })
        if len(results) >= max_results:
            break
    return results

# 简单情感分析（可替换为更强NLP模型）
def sentiment(text: str) -> str:
    pos_words = ['上涨', '利好', '增持', '创新高', '业绩增长', '收购', '扩产', '政策支持']
    neg_words = ['下跌', '利空', '减持', '亏损', '处罚', '停牌', '业绩下滑', '负面']
    score = 0
    for w in pos_words:
        if w in text:
            score += 1
    for w in neg_words:
        if w in text:
            score -= 1
    if score > 0:
        return '正面'
    elif score < 0:
        return '负面'
    else:
        return '中性'

# agent主流程
def analyze_top20_news():
    top20 = fetch_top20()
    report = []
    for stock in top20:
        name = stock.get('name')
        symbol = stock.get('symbol')
        pct_chg = stock.get('pct_chg')
        print(f'分析: {name} ({symbol}) 涨跌幅: {pct_chg}')
        news_list = search_news(name)
        factors = []
        for news in news_list:
            senti = sentiment(news['title'] + news['snippet'])
            factors.append({
                'title': news['title'],
                'url': news['url'],
                'snippet': news['snippet'],
                'sentiment': senti
            })
        report.append({
            'name': name,
            'symbol': symbol,
            'pct_chg': pct_chg,
            'news_analysis': factors
        })
        time.sleep(1)  # 防止被封
    return report

if __name__ == '__main__':
    result = analyze_top20_news()
    for stock in result:
        print(f"\n股票: {stock['name']} ({stock['symbol']}) 涨跌幅: {stock['pct_chg']}")
        for news in stock['news_analysis']:
            print(f"  - {news['title']} [{news['sentiment']}]\n    {news['url']}\n    {news['snippet']}")
