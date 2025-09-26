// Enhanced MongoDB initialization script for AI Stock News Database
// 增强的MongoDB初始化脚本，支持按股票分类的新闻存档

// Switch to aistock_news database
use('aistock_news')

// Create collections with optimized schema
db.createCollection("news_articles")
db.createCollection("stock_news_archive")   // 核心：按股票分类的新闻存档
db.createCollection("news_sources")
db.createCollection("search_cache")
db.createCollection("duplicate_detection")  // 去重检测
db.createCollection("news_analytics")       // 新闻分析结果
db.createCollection("stock_mentions")       // 股票提及统计

// Create indexes for news_articles collection (主新闻文章集合)
db.news_articles.createIndex({"url": 1}, {"unique": true})
db.news_articles.createIndex({"published_at": -1})
db.news_articles.createIndex({"related_stocks": 1})
db.news_articles.createIndex({"sentiment_score": 1})
db.news_articles.createIndex({"keywords": 1})
db.news_articles.createIndex({"source": 1})
db.news_articles.createIndex({"created_at": -1})
db.news_articles.createIndex({"title": "text", "content": "text", "summary": "text"})

// Create indexes for stock_news_archive collection (核心优化)
db.stock_news_archive.createIndex({"stock_symbol": 1, "date": -1})
db.stock_news_archive.createIndex({"stock_symbol": 1, "relevance_score": -1})
db.stock_news_archive.createIndex({"date": -1})
db.stock_news_archive.createIndex({"sentiment_score": 1})
db.stock_news_archive.createIndex({"article_id": 1}, {"unique": true})

// Create indexes for duplicate_detection collection
db.duplicate_detection.createIndex({"url_hash": 1}, {"unique": true})
db.duplicate_detection.createIndex({"content_hash": 1})
db.duplicate_detection.createIndex({"created_at": 1}, {"expireAfterSeconds": 7776000})  // 90天过期

// Create indexes for search_cache collection
db.search_cache.createIndex({"query_hash": 1}, {"unique": true})
db.search_cache.createIndex({"created_at": 1}, {"expireAfterSeconds": 3600})  // 1小时过期

// Create indexes for news_analytics collection
db.news_analytics.createIndex({"article_id": 1}, {"unique": true})
db.news_analytics.createIndex({"analysis_type": 1})
db.news_analytics.createIndex({"confidence_score": -1})

// Create indexes for stock_mentions collection
db.stock_mentions.createIndex({"stock_symbol": 1, "date": -1})
db.stock_mentions.createIndex({"mention_count": -1})

// Insert enhanced news sources configuration
db.news_sources.insertMany([
  {
    "name": "新浪财经",
    "domain": "finance.sina.com.cn",
    "category": "finance",
    "reliability_score": 0.8,
    "language": "zh-CN",
    "enabled": true,
    "crawl_config": {
      "title_selector": "h1.title",
      "content_selector": ".article-content",
      "date_selector": ".date-time"
    }
  },
  {
    "name": "东方财富",
    "domain": "eastmoney.com",
    "category": "finance",
    "reliability_score": 0.85,
    "language": "zh-CN",
    "enabled": true,
    "crawl_config": {
      "title_selector": "h1",
      "content_selector": ".content",
      "date_selector": ".time"
    }
  },
  {
    "name": "雪球",
    "domain": "xueqiu.com",
    "category": "social_finance",
    "reliability_score": 0.7,
    "language": "zh-CN",
    "enabled": true,
    "crawl_config": {
      "title_selector": ".article-title",
      "content_selector": ".article-body",
      "date_selector": ".publish-time"
    }
  },
  {
    "name": "财联社",
    "domain": "cls.cn",
    "category": "finance",
    "reliability_score": 0.85,
    "language": "zh-CN",
    "enabled": true
  },
  {
    "name": "金融界",
    "domain": "jrj.com.cn",
    "category": "finance",
    "reliability_score": 0.75,
    "language": "zh-CN",
    "enabled": true
  },
  {
    "name": "Reuters",
    "domain": "reuters.com",
    "category": "international_finance",
    "reliability_score": 0.9,
    "language": "en",
    "enabled": true
  },
  {
    "name": "Bloomberg",
    "domain": "bloomberg.com",
    "category": "international_finance",
    "reliability_score": 0.9,
    "language": "en",
    "enabled": true
  },
  {
    "name": "MarketWatch",
    "domain": "marketwatch.com",
    "category": "international_finance",
    "reliability_score": 0.8,
    "language": "en",
    "enabled": true
  }
])

// Insert sample stock news archive document (示例文档结构)
db.stock_news_archive.insertOne({
  "_id": "AAPL_sample_article_001",
  "stock_symbol": "AAPL",
  "article_id": "sample_article_001",
  "date": "2024-01-15",
  "relevance_score": 0.95,
  "sentiment_score": 0.75,
  "article_summary": {
    "title": "Apple发布新产品线，市场反应积极",
    "summary": "苹果公司今日发布了新的产品线，市场反应普遍积极...",
    "keywords": ["Apple", "新产品", "市场", "股价"],
    "entities": ["Apple Inc.", "iPhone", "Mac"]
  },
  "created_at": new Date()
})

// Insert sample duplicate detection document
db.duplicate_detection.insertOne({
  "url_hash": "sample_hash_001",
  "content_hash": "content_hash_001",
  "fingerprint": "fingerprint_001",
  "url": "https://example.com/news/sample",
  "created_at": new Date()
})

// Insert sample news analytics document
db.news_analytics.insertOne({
  "_id": "sample_article_001_sentiment",
  "article_id": "sample_article_001",
  "analysis_type": "sentiment",
  "analysis_result": {
    "sentiment": "positive",
    "confidence": 0.85,
    "emotions": {
      "positive": 0.75,
      "negative": 0.15,
      "neutral": 0.10
    }
  },
  "confidence_score": 0.85,
  "created_at": new Date()
})

// Insert sample stock mentions document
db.stock_mentions.insertOne({
  "stock_symbol": "AAPL",
  "date": "2024-01-15",
  "mention_count": 25,
  "created_at": new Date(),
  "updated_at": new Date()
})

print("✓ Enhanced AI Stock News Database initialized successfully!")
print("✓ Collections created: news_articles, stock_news_archive, news_sources, search_cache, duplicate_detection, news_analytics, stock_mentions")
print("✓ Optimized indexes created for efficient stock-specific news retrieval")
print("✓ Sample documents inserted for testing")