// Enhanced MongoDB initialization script for AI Stock News Database
// This script is safe to run multiple times: it checks for existing
// collections/indexes and inserts sample documents only when collections
// are empty.

(function() {
  const TARGET_DB = 'aistock_news';
  const aistock = db.getSiblingDB(TARGET_DB);

  try {
    // Create collections if they don't exist
    const cols = [
      'news_articles',
      'stock_news_archive',
      'news_sources',
      'search_cache',
      'duplicate_detection',
      'news_analytics',
      'stock_mentions'
    ];

    cols.forEach(name => {
      if (!aistock.getCollectionNames().includes(name)) {
        aistock.createCollection(name);
        print(`created collection: ${name}`);
      }
    });

    // Seed news_sources if empty
    if (aistock.news_sources.countDocuments({}) === 0) {
      aistock.news_sources.insertMany([
        { name: 'Reuters', domain: 'reuters.com', category: 'international_finance', reliability_score: 0.9, language: 'en', enabled: true },
        { name: 'Bloomberg', domain: 'bloomberg.com', category: 'international_finance', reliability_score: 0.9, language: 'en', enabled: true },
        { name: 'MarketWatch', domain: 'marketwatch.com', category: 'international_finance', reliability_score: 0.8, language: 'en', enabled: true }
      ]);
      print('inserted sample news_sources');
    }

    // Insert sample documents for testing if collections empty
    if (aistock.stock_news_archive.countDocuments({}) === 0) {
      aistock.stock_news_archive.insertOne({
        _id: 'AAPL_sample_article_001',
        stock_symbol: 'AAPL',
        article_id: 'sample_article_001',
        date: '2024-01-15',
        relevance_score: 0.95,
        sentiment_score: 0.75,
        article_summary: {
          title: 'Apple发布新产品线，市场反应积极',
          summary: '苹果公司今日发布了新的产品线，市场反应普遍积极...',
          keywords: ['Apple', '新产品', '市场', '股价'],
          entities: ['Apple Inc.', 'iPhone', 'Mac']
        },
        created_at: new Date()
      });
      print('inserted sample stock_news_archive document');
    }

    if (aistock.duplicate_detection.countDocuments({}) === 0) {
      aistock.duplicate_detection.insertOne({
        url_hash: 'sample_hash_001',
        content_hash: 'content_hash_001',
        fingerprint: 'fingerprint_001',
        url: 'https://example.com/news/sample',
        created_at: new Date()
      });
      print('inserted sample duplicate_detection document');
    }

    if (aistock.news_analytics.countDocuments({}) === 0) {
      aistock.news_analytics.insertOne({
        _id: 'sample_article_001_sentiment',
        article_id: 'sample_article_001',
        analysis_type: 'sentiment',
        analysis_result: { sentiment: 'positive', confidence: 0.85, emotions: { positive: 0.75, negative: 0.15, neutral: 0.10 } },
        confidence_score: 0.85,
        created_at: new Date()
      });
      print('inserted sample news_analytics document');
    }

    if (aistock.stock_mentions.countDocuments({}) === 0) {
      aistock.stock_mentions.insertOne({ stock_symbol: 'AAPL', date: '2024-01-15', mention_count: 25, created_at: new Date(), updated_at: new Date() });
      print('inserted sample stock_mentions document');
    }

    // Create indexes (idempotent) with graceful error handling
    function ensureIndex(coll, spec, opts) {
      try {
        if (opts) coll.createIndex(spec, opts);
        else coll.createIndex(spec);
      } catch (e) {
        print('warning: index create ignored for ' + JSON.stringify(spec) + ' -> ' + e);
      }
    }

    ensureIndex(aistock.news_articles, { url: 1 }, { unique: true });
    ensureIndex(aistock.news_articles, { published_at: -1 });
    ensureIndex(aistock.news_articles, { related_stocks: 1 });
    ensureIndex(aistock.news_articles, { sentiment_score: 1 });
    ensureIndex(aistock.news_articles, { keywords: 1 });
    ensureIndex(aistock.news_articles, { source: 1 });
    ensureIndex(aistock.news_articles, { created_at: -1 });
    ensureIndex(aistock.news_articles, { title: 'text', content: 'text', summary: 'text' });

    ensureIndex(aistock.stock_news_archive, { stock_symbol: 1, date: -1 });
    ensureIndex(aistock.stock_news_archive, { stock_symbol: 1, relevance_score: -1 });
    ensureIndex(aistock.stock_news_archive, { date: -1 });
    ensureIndex(aistock.stock_news_archive, { sentiment_score: 1 });
    ensureIndex(aistock.stock_news_archive, { article_id: 1 }, { unique: true });

    ensureIndex(aistock.duplicate_detection, { url_hash: 1 }, { unique: true });
    ensureIndex(aistock.duplicate_detection, { content_hash: 1 });
    ensureIndex(aistock.duplicate_detection, { created_at: 1 }, { expireAfterSeconds: 7776000 }); // 90 days

    ensureIndex(aistock.search_cache, { query_hash: 1 }, { unique: true });
    ensureIndex(aistock.search_cache, { created_at: 1 }, { expireAfterSeconds: 3600 }); // 1 hour

    ensureIndex(aistock.news_analytics, { article_id: 1 });
    ensureIndex(aistock.news_analytics, { analysis_type: 1 });

    ensureIndex(aistock.stock_mentions, { stock_symbol: 1, date: -1 });

    print('✓ Enhanced AI Stock News Database initialization complete');
  } catch (err) {
    print('ERROR during init-news-db.js: ' + err);
    throw err;
  }

})();

