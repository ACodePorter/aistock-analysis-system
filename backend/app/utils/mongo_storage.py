"""
用于异步管理与 MongoDB 的股票新闻存储模块。该模块提供面向股票新闻的完整生命周期支持，包括文章保存与检索、按股票归档、去重检测、搜索缓存、分析结果存储、提及统计、统计聚合与旧数据清理等功能。模块基于 motor/pymongo 实现异步操作，并在数据库驱动不可用时优雅降级（记录警告并禁用 MongoDB 功能）。同时在初始化阶段创建针对性能与查询场景优化的索引，并对重复键、认证失败和常见异常进行处理与日志记录。

主要集合（collections）：
- news_articles：主新闻文章集合（全文索引、按时间排序等）
- stock_news_archive：按股票组织的新闻归档（按相关性和日期优化）
- duplicate_detection：去重检测（URL/内容哈希、过期策略）
- search_cache：搜索缓存（短期过期）
- news_analytics：新闻分析结果存储
- stock_mentions：股票提及统计（每日聚合计数）
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import hashlib
import logging
import json

# 尝试导入MongoDB相关库
try:
    from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
    from pymongo import ASCENDING, DESCENDING, TEXT
    from pymongo.errors import DuplicateKeyError, OperationFailure
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False
    AsyncIOMotorClient = None
    AsyncIOMotorDatabase = None
    AsyncIOMotorCollection = None
    ASCENDING = 1
    DESCENDING = -1
    TEXT = "text"
    DuplicateKeyError = Exception
    OperationFailure = Exception

logger = logging.getLogger(__name__)

class StockNewsStorage:
    """
    Stock-specific news storage with optimized MongoDB architecture
    按股票分类的新闻存储，使用优化的MongoDB架构
    """
    
    def __init__(self, mongo_uri: str = "mongodb://localhost:27017", database_name: str = "aistock_news"):
        self.mongo_uri = mongo_uri
        self.database_name = database_name
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        
        # Collection names
        self.collections = {
            'news_articles': 'news_articles',           # 主新闻文章集合
            'stock_news_archive': 'stock_news_archive',  # 按股票分类的新闻存档
            'news_sources': 'news_sources',             # 新闻源配置
            'search_cache': 'search_cache',             # 搜索缓存
            'duplicate_detection': 'duplicate_detection', # 去重检测
            'news_analytics': 'news_analytics',          # 新闻分析结果
            'stock_mentions': 'stock_mentions',         # 股票提及统计
            'macro_observations': 'macro_observations',  # 宏观新闻观测快照
            'macro_model_runs': 'macro_model_runs',      # 模型训练与校准记录
            'macro_reports': 'macro_reports',            # 宏观日报快照
            # 新增：抓取/搜索错误日志集合
            'news_error_logs': 'news_error_logs',
            # 新增：单页 Agent 报告集合（PageCrawlAgent）
            'agent_page_reports': 'agent_page_reports'
        }
    
    async def initialize(self):
        """初始化MongoDB连接和索引"""
        if not MONGODB_AVAILABLE:
            logger.warning("⚠ MongoDB libraries not available, skipping MongoDB initialization")
            return False
            
        try:
            self.client = AsyncIOMotorClient(self.mongo_uri)
            self.db = self.client[self.database_name]
            
            # 验证连接
            await self.client.admin.command('ping')
            logger.info(f"✓ Connected to MongoDB: {self.database_name}")
            
            # 创建索引
            await self._create_indexes()
            logger.info("✓ MongoDB indexes created successfully")
            
            return True
            
        except Exception as e:
            logger.exception("⚠ MongoDB initialization failed (full traceback)")
            logger.warning(f"⚠ MongoDB initialization failed: {e}")
            logger.warning("⚠ System will continue without MongoDB support")
            # 尝试关闭客户端以清理资源
            try:
                if self.client:
                    await self.client.close()
            except Exception:
                pass
            # 清理连接对象，避免后续操作失败
            self.client = None
            self.db = None
            return False
    
    async def _create_indexes(self):
        """创建优化的索引结构"""
        try:
            # 1. 主新闻文章集合索引
            news_articles = self.db[self.collections['news_articles']]
            await news_articles.create_index([("url", ASCENDING)], unique=True)
            await news_articles.create_index([("published_at", DESCENDING)])
            await news_articles.create_index([("related_stocks", ASCENDING)])
            await news_articles.create_index([("sentiment_score", ASCENDING)])
            await news_articles.create_index([("source", ASCENDING)])
            await news_articles.create_index([("created_at", DESCENDING)])
            await news_articles.create_index([
                ("title", TEXT), 
                ("content", TEXT), 
                ("summary", TEXT)
            ])
            
            # 2. 股票新闻存档集合索引（核心优化）
            stock_archive = self.db[self.collections['stock_news_archive']]
            await stock_archive.create_index([("stock_symbol", ASCENDING), ("date", DESCENDING)])
            await stock_archive.create_index([("stock_symbol", ASCENDING), ("relevance_score", DESCENDING)])
            await stock_archive.create_index([("date", DESCENDING)])
            await stock_archive.create_index([("sentiment_score", ASCENDING)])
            await stock_archive.create_index([("article_id", ASCENDING)], unique=True)
            
            # 3. 去重检测集合索引
            duplicate_detection = self.db[self.collections['duplicate_detection']]
            await duplicate_detection.create_index([("url_hash", ASCENDING)], unique=True)
            await duplicate_detection.create_index([("content_hash", ASCENDING)])
            await duplicate_detection.create_index([("created_at", ASCENDING)], expireAfterSeconds=7776000)  # 90天过期
            
            # 4. 搜索缓存集合索引
            search_cache = self.db[self.collections['search_cache']]
            await search_cache.create_index([("query_hash", ASCENDING)], unique=True)
            await search_cache.create_index([("created_at", ASCENDING)], expireAfterSeconds=3600)  # 1小时过期
            
            # 5. 新闻分析结果集合索引
            news_analytics = self.db[self.collections['news_analytics']]
            await news_analytics.create_index([("article_id", ASCENDING)], unique=True)
            await news_analytics.create_index([("analysis_type", ASCENDING)])
            await news_analytics.create_index([("confidence_score", DESCENDING)])
            
            # 6. 股票提及统计集合索引
            stock_mentions = self.db[self.collections['stock_mentions']]
            await stock_mentions.create_index([("stock_symbol", ASCENDING), ("date", DESCENDING)])
            await stock_mentions.create_index([("mention_count", DESCENDING)])

            # 7. 宏观观测集合索引
            macro_observations = self.db[self.collections['macro_observations']]
            await macro_observations.create_index([("observation_date", DESCENDING)])
            await macro_observations.create_index([("topic", ASCENDING), ("observation_date", DESCENDING)])
            await macro_observations.create_index([("created_at", DESCENDING)])
            await macro_observations.create_index([("features.avg_sentiment", DESCENDING)])
            await macro_observations.create_index([("features.relevance_mean", DESCENDING)])

            # 8. 宏观模型训练记录
            macro_model_runs = self.db[self.collections['macro_model_runs']]
            await macro_model_runs.create_index([("run_date", DESCENDING)])
            await macro_model_runs.create_index([("model_name", ASCENDING), ("run_date", DESCENDING)])
            await macro_model_runs.create_index([("metrics.rmse", ASCENDING)])

            # 9. 宏观日报集合索引
            macro_reports = self.db[self.collections['macro_reports']]
            await macro_reports.create_index([("report_date", DESCENDING)], unique=True)
            await macro_reports.create_index([("generated_at", DESCENDING)])
            await macro_reports.create_index([("metrics.average_sentiment", DESCENDING)])

            # 10. 新闻错误日志集合索引
            news_error_logs = self.db[self.collections['news_error_logs']]
            await news_error_logs.create_index([("created_at", DESCENDING)])
            await news_error_logs.create_index([("kind", ASCENDING), ("domain", ASCENDING), ("created_at", DESCENDING)])
            await news_error_logs.create_index([("url_hash", ASCENDING)], unique=False)
            await news_error_logs.create_index([("created_at", ASCENDING)], expireAfterSeconds=1209600)  # 14 天过期

            # 11. 单页 Agent 报告集合索引
            page_reports = self.db[self.collections['agent_page_reports']]
            await page_reports.create_index([("created_at", DESCENDING)])
            await page_reports.create_index([("domain", ASCENDING), ("created_at", DESCENDING)])
            await page_reports.create_index([("symbol", ASCENDING), ("created_at", DESCENDING)])
            await page_reports.create_index([("url_hash", ASCENDING)], unique=False)
            
        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
                logger.warning(f"⚠ MongoDB authentication failed during index creation: {e}")
                logger.warning("⚠ Please check MONGO_USER and MONGO_PASSWORD in .env file")
                logger.warning("⚠ Disabling MongoDB features for this session")
                # 清理连接，避免后续操作失败
                if self.client:
                    await self.client.close()
                self.client = None
                self.db = None
            else:
                logger.warning(f"⚠ Failed to create MongoDB indexes: {e}")
                logger.warning("⚠ MongoDB functionality may be limited")
    
    async def save_news_article(self, article_data: Dict[str, Any]) -> Optional[str]:
        """
        保存新闻文章到主集合
        """
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping article save")
            return None
            
        try:
            collection = self.db[self.collections['news_articles']]
            
            # 添加创建时间
            article_data['created_at'] = datetime.utcnow()
            article_data['updated_at'] = datetime.utcnow()
            
            # 生成文章ID
            article_id = hashlib.md5(article_data['url'].encode()).hexdigest()
            article_data['_id'] = article_id
            
            result = await collection.insert_one(article_data)
            logger.info(f"✓ Saved news article: {article_id}")
            
            return str(result.inserted_id)
            
        except DuplicateKeyError:
            logger.warning(f"Article already exists: {article_data.get('url', 'unknown')}")
            return None
        except Exception as e:
            logger.error(f"✗ Failed to save article: {e}")
            return None
    
    async def archive_stock_news(self, stock_symbol: str, article_id: str, 
                               relevance_score: float, sentiment_score: float,
                               article_summary: Dict[str, Any]) -> bool:
        """
        将新闻归档到股票特定集合
        """
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping stock news archive")
            return False
            
        try:
            collection = self.db[self.collections['stock_news_archive']]
            
            archive_data = {
                '_id': f"{stock_symbol}_{article_id}",
                'stock_symbol': stock_symbol.upper(),
                'article_id': article_id,
                'date': datetime.utcnow().date().isoformat(),
                'relevance_score': relevance_score,
                'sentiment_score': sentiment_score,
                'article_summary': article_summary,
                'created_at': datetime.utcnow()
            }
            
            await collection.insert_one(archive_data)
            logger.info(f"✓ Archived news for {stock_symbol}: {article_id}")
            
            # 更新股票提及统计
            await self._update_stock_mentions(stock_symbol)
            
            return True
            
        except DuplicateKeyError:
            logger.warning(f"Archive entry already exists: {stock_symbol}_{article_id}")
            return False
        except Exception as e:
            logger.error(f"✗ Failed to archive stock news: {e}")
            return False
    
    async def get_stock_news(self, stock_symbol: str, 
                           start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None,
                           limit: int = 100,
                           min_relevance: float = 0.0) -> List[Dict[str, Any]]:
        """
        获取特定股票的新闻
        """
        try:
            collection = self.db[self.collections['stock_news_archive']]
            
            # 构建查询条件
            query = {
                'stock_symbol': stock_symbol.upper(),
                'relevance_score': {'$gte': min_relevance}
            }
            
            if start_date or end_date:
                date_filter = {}
                if start_date:
                    date_filter['$gte'] = start_date.date().isoformat()
                if end_date:
                    date_filter['$lte'] = end_date.date().isoformat()
                query['date'] = date_filter
            
            # 执行查询，按相关性和时间排序
            cursor = collection.find(query).sort([
                ('relevance_score', DESCENDING),
                ('created_at', DESCENDING)
            ]).limit(limit)
            
            results = await cursor.to_list(length=limit)
            
            # 获取完整文章内容
            for result in results:
                article_id = result['article_id']
                full_article = await self.get_article_by_id(article_id)
                if full_article:
                    result['full_article'] = full_article
            
            return results
            
        except Exception as e:
            logger.error(f"✗ Failed to get stock news: {e}")
            return []
    
    async def get_article_by_id(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        根据ID获取完整文章
        """
        try:
            collection = self.db[self.collections['news_articles']]
            result = await collection.find_one({'_id': article_id})
            return result
        except Exception as e:
            logger.error(f"✗ Failed to get article: {e}")
            return None

    # ---------------- Error Logs (Search/Crawl) -----------------
    async def log_news_error(self, kind: str, *, url: Optional[str] = None, domain: Optional[str] = None,
                              symbol: Optional[str] = None, message: Optional[str] = None, detail: Optional[Dict[str, Any]] = None) -> bool:
        """记录新闻相关错误：kind=search|crawl。
        存储字段：kind, url, url_hash, domain, symbol, message, detail, created_at。
        """
        if self.client is None or self.db is None:
            return False
        try:
            col = self.db[self.collections['news_error_logs']]
            data: Dict[str, Any] = {
                'kind': (kind or '').lower(),
                'url': url,
                'url_hash': hashlib.md5(url.encode('utf-8')).hexdigest() if url else None,
                'domain': domain,
                'symbol': (symbol or '').upper() if symbol else None,
                'message': message,
                'detail': detail or {},
                'created_at': datetime.utcnow()
            }
            await col.insert_one(data)
            return True
        except Exception as e:
            logger.warning(f"Failed to log news error: {e}")
            return False

    async def list_news_errors(self, kind: Optional[str] = None, *, domain: Optional[str] = None, symbol: Optional[str] = None,
                               since_minutes: int = 1440, limit: int = 200) -> List[Dict[str, Any]]:
        """查询错误日志，默认查最近 24 小时。
        支持按 kind/search/crawl、domain、symbol 过滤，并按时间倒序返回。
        """
        try:
            if self.client is None or self.db is None:
                return []
            col = self.db[self.collections['news_error_logs']]
            since_dt = datetime.utcnow() - timedelta(minutes=max(1, since_minutes))
            q: Dict[str, Any] = {'created_at': {'$gte': since_dt}}
            if kind:
                q['kind'] = kind.lower()
            if domain:
                q['domain'] = domain
            if symbol:
                q['symbol'] = symbol.upper()
            cur = col.find(q).sort([('created_at', DESCENDING)]).limit(max(1, min(limit, 1000)))
            return await cur.to_list(length=limit)
        except Exception as e:
            logger.warning(f"Failed to list news errors: {e}")
            return []
    
    async def save_duplicate_detection(self, url: str, content_hash: str, 
                                     fingerprint: str) -> bool:
        """
        保存去重检测信息
        """
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping duplicate detection save")
            return False
            
        try:
            collection = self.db[self.collections['duplicate_detection']]
            
            detection_data = {
                'url_hash': hashlib.md5(url.encode()).hexdigest(),
                'fingerprint': fingerprint,
                'url': url,
                'created_at': datetime.utcnow()
            }

            if content_hash:
                detection_data['content_hash'] = content_hash

            await collection.insert_one(detection_data)
            return True
            
        except DuplicateKeyError:
            return False
        except Exception as e:
            logger.error(f"✗ Failed to save duplicate detection: {e}")
            return False
    
    async def check_duplicate(self, url: str = None, content_hash: str = None) -> bool:
        """
        检查是否为重复内容
        """
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping duplicate check")
            return False
            
        try:
            collection = self.db[self.collections['duplicate_detection']]
            
            query = {}
            if url:
                query['url_hash'] = hashlib.md5(url.encode()).hexdigest()
            if content_hash:
                query['content_hash'] = content_hash
            
            if not query:
                return False
            
            result = await collection.find_one(query)
            return result is not None
            
        except Exception as e:
            logger.error(f"✗ Failed to check duplicate: {e}")
            return False

    # ---------------- Agent Page Reports (PageCrawlAgent) -----------------
    async def save_page_crawl_report(self, report: Dict[str, Any]) -> Optional[str]:
        """保存单页 Agent 爬取报告。

        期望字段（尽力而为）：
        - url, domain, crawled_at, symbol, company_name, title, summary, content,
          entities, keywords, links, top_candidates, images, charts_saved, probe_results, errors
        额外生成：url_hash, created_at
        """
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping page report save")
            return None
        try:
            col = self.db[self.collections['agent_page_reports']]
            payload = dict(report or {})
            url = payload.get('url') or ''
            payload['url_hash'] = hashlib.md5(url.encode('utf-8')).hexdigest() if url else None
            payload['created_at'] = datetime.utcnow()
            res = await col.insert_one(payload)
            return str(res.inserted_id)
        except Exception as exc:
            logger.error("✗ Failed to save page crawl report: %s", exc)
            return None

    async def list_page_crawl_reports(self, *, symbol: Optional[str] = None, domain: Optional[str] = None,
                                      since_minutes: int = 1440, limit: int = 100) -> List[Dict[str, Any]]:
        """列出最近的单页 Agent 报告，支持按 symbol/domain 过滤。"""
        if self.client is None or self.db is None:
            return []
        since_dt = datetime.utcnow() - timedelta(minutes=max(1, since_minutes))
        q: Dict[str, Any] = {"created_at": {"$gte": since_dt}}
        if symbol:
            q['symbol'] = (symbol or '').upper()
        if domain:
            q['domain'] = domain
        try:
            col = self.db[self.collections['agent_page_reports']]
            cur = col.find(q).sort([('created_at', DESCENDING)]).limit(max(1, min(limit, 500)))
            rows = await cur.to_list(length=limit)
            # stringify _id
            for r in rows:
                if r.get('_id') is not None:
                    r['_id'] = str(r['_id'])
            return rows
        except Exception as exc:
            logger.error("✗ Failed to list page crawl reports: %s", exc)
            return []

    async def get_page_crawl_report(self, *, report_id: Optional[str] = None, url_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """根据 Mongo _id（字符串化）或 url_hash 获取单页 Agent 报告。"""
        if self.client is None or self.db is None:
            return None
        if not report_id and not url_hash:
            return None
        try:
            col = self.db[self.collections['agent_page_reports']]
            if report_id:
                try:
                    from bson import ObjectId
                    doc = await col.find_one({'_id': ObjectId(report_id)})
                except Exception:
                    doc = await col.find_one({'_id': report_id})  # in case of string _id
            else:
                doc = await col.find_one({'url_hash': url_hash})
            if doc and doc.get('_id') is not None:
                doc['_id'] = str(doc['_id'])
            return doc
        except Exception as exc:
            logger.error("✗ Failed to get page crawl report: %s", exc)
            return None
    
    async def save_news_analytics(self, article_id: str, analysis_type: str,
                                analysis_result: Dict[str, Any], 
                                confidence_score: float) -> bool:
        """
        保存新闻分析结果
        """
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping analytics save")
            return False
            
        try:
            collection = self.db[self.collections['news_analytics']]
            
            analytics_data = {
                '_id': f"{article_id}_{analysis_type}",
                'article_id': article_id,
                'analysis_type': analysis_type,
                'analysis_result': analysis_result,
                'confidence_score': confidence_score,
                'created_at': datetime.utcnow()
            }
            
            await collection.insert_one(analytics_data)
            return True
            
        except DuplicateKeyError:
            # 更新现有分析结果
            await collection.replace_one(
                {'_id': f"{article_id}_{analysis_type}"},
                analytics_data
            )
            return True
        except Exception as e:
            logger.error(f"✗ Failed to save analytics: {e}")
            return False
    
    async def _update_stock_mentions(self, stock_symbol: str):
        """
        更新股票提及统计
        """
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping stock mentions update")
            return
            
        try:
            collection = self.db[self.collections['stock_mentions']]
            today = datetime.utcnow().date().isoformat()
            
            # 使用upsert更新计数
            await collection.update_one(
                {
                    'stock_symbol': stock_symbol.upper(),
                    'date': today
                },
                {
                    '$inc': {'mention_count': 1},
                    '$setOnInsert': {
                        'created_at': datetime.utcnow()
                    },
                    '$set': {
                        'updated_at': datetime.utcnow()
                    }
                },
                upsert=True
            )
            
        except Exception as e:
            logger.error(f"✗ Failed to update stock mentions: {e}")
    
    async def get_stock_statistics(self, stock_symbol: str, 
                                 days: int = 30) -> Dict[str, Any]:
        """
        获取股票新闻统计信息
        """
        try:
            # 计算日期范围
            end_date = datetime.utcnow().date()
            start_date = end_date - timedelta(days=days)
            
            # 获取新闻数量统计
            archive_collection = self.db[self.collections['stock_news_archive']]
            news_count = await archive_collection.count_documents({
                'stock_symbol': stock_symbol.upper(),
                'date': {
                    '$gte': start_date.isoformat(),
                    '$lte': end_date.isoformat()
                }
            })
            
            # 获取平均情感分数
            pipeline = [
                {
                    '$match': {
                        'stock_symbol': stock_symbol.upper(),
                        'date': {
                            '$gte': start_date.isoformat(),
                            '$lte': end_date.isoformat()
                        }
                    }
                },
                {
                    '$group': {
                        '_id': None,
                        'avg_sentiment': {'$avg': '$sentiment_score'},
                        'avg_relevance': {'$avg': '$relevance_score'}
                    }
                }
            ]
            
            avg_scores = await archive_collection.aggregate(pipeline).to_list(1)
            
            # 获取提及统计
            mentions_collection = self.db[self.collections['stock_mentions']]
            total_mentions = await mentions_collection.aggregate([
                {
                    '$match': {
                        'stock_symbol': stock_symbol.upper(),
                        'date': {
                            '$gte': start_date.isoformat(),
                            '$lte': end_date.isoformat()
                        }
                    }
                },
                {
                    '$group': {
                        '_id': None,
                        'total_mentions': {'$sum': '$mention_count'}
                    }
                }
            ]).to_list(1)
            
            return {
                'stock_symbol': stock_symbol.upper(),
                'period_days': days,
                'news_count': news_count,
                'avg_sentiment_score': avg_scores[0]['avg_sentiment'] if avg_scores else 0.0,
                'avg_relevance_score': avg_scores[0]['avg_relevance'] if avg_scores else 0.0,
                'total_mentions': total_mentions[0]['total_mentions'] if total_mentions else 0,
                'calculated_at': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"✗ Failed to get stock statistics: {e}")
            return {}
    
    async def cleanup_old_data(self, days_to_keep: int = 90):
        """
        清理旧数据
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
            
            # 清理旧的搜索缓存（自动过期）
            # 清理旧的去重检测数据（自动过期）
            
            # 清理旧的新闻分析结果
            analytics_collection = self.db[self.collections['news_analytics']]
            result = await analytics_collection.delete_many({
                'created_at': {'$lt': cutoff_date}
            })
            
            logger.info(f"✓ Cleaned up {result.deleted_count} old analytics records")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to cleanup old data: {e}")
            return False

    async def save_macro_observation(self, observation: Dict[str, Any]) -> Optional[str]:
        """保存宏观新闻观测快照"""
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping macro observation save")
            return None

        try:
            collection = self.db[self.collections['macro_observations']]

            observation_id = observation.get("_id")
            if not observation_id:
                topic = observation.get("topic", "unknown").lower()
                observation_date = observation.get("observation_date")
                if isinstance(observation_date, datetime):
                    date_str = observation_date.date().isoformat()
                else:
                    date_str = str(observation_date)
                observation_id = f"{topic}_{date_str}"
                observation["_id"] = observation_id

            observation.setdefault("created_at", datetime.utcnow())
            observation.setdefault("updated_at", datetime.utcnow())

            await collection.replace_one({"_id": observation_id}, observation, upsert=True)
            logger.info(f"✓ Saved macro observation: {observation_id}")
            return observation_id

        except Exception as e:
            logger.error(f"✗ Failed to save macro observation: {e}")
            return None

    async def get_macro_observations(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        topics: Optional[List[str]] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """查询宏观新闻观测记录"""
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping macro observation query")
            return []

        try:
            collection = self.db[self.collections['macro_observations']]

            query: Dict[str, Any] = {}

            if start_date or end_date:
                date_filter: Dict[str, Any] = {}
                if start_date:
                    date_filter['$gte'] = start_date.date().isoformat()
                if end_date:
                    date_filter['$lte'] = end_date.date().isoformat()
                query['observation_date'] = date_filter

            if topics:
                normalized_topics = [topic.lower() for topic in topics]
                query['topic'] = {'$in': normalized_topics}

            cursor = collection.find(query).sort([
                ('observation_date', DESCENDING),
                ('topic', ASCENDING)
            ]).limit(limit)

            results = await cursor.to_list(length=limit)
            return results

        except Exception as e:
            logger.error(f"✗ Failed to get macro observations: {e}")
            return []

    async def save_macro_model_run(self, run_payload: Dict[str, Any]) -> Optional[str]:
        """保存宏观模型训练与校准结果"""
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping macro model run save")
            return None

        try:
            collection = self.db[self.collections['macro_model_runs']]

            run_id = run_payload.get("_id")
            if not run_id:
                model_name = run_payload.get("model_name", "macro_regressor")
                run_date = run_payload.get("run_date")
                if isinstance(run_date, datetime):
                    date_str = run_date.isoformat()
                elif isinstance(run_date, str):
                    date_str = run_date
                else:
                    date_str = datetime.utcnow().isoformat()
                run_id = f"{model_name}_{date_str}"
                run_payload["_id"] = run_id

            run_payload.setdefault("created_at", datetime.utcnow())
            run_payload["updated_at"] = datetime.utcnow()

            await collection.replace_one({"_id": run_id}, run_payload, upsert=True)
            logger.info(f"✓ Saved macro model run: {run_id}")
            return run_id

        except Exception as e:
            logger.error(f"✗ Failed to save macro model run: {e}")
            return None

    async def get_macro_model_runs(
        self,
        *,
        model_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """查询宏观模型训练记录"""
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping macro model run query")
            return []

        try:
            collection = self.db[self.collections['macro_model_runs']]

            query: Dict[str, Any] = {}
            if model_name:
                query['model_name'] = model_name

            cursor = collection.find(query).sort([
                ('run_date', DESCENDING),
            ]).limit(limit)

            return await cursor.to_list(length=limit)

        except Exception as e:
            logger.error(f"✗ Failed to get macro model runs: {e}")
            return []

    async def save_macro_report(self, report: Dict[str, Any]) -> Optional[str]:
        """保存每日宏观报告快照"""
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping macro report save")
            return None

        try:
            collection = self.db[self.collections['macro_reports']]

            report_date = report.get("report_date")
            if isinstance(report_date, datetime):
                report_date = report_date.date().isoformat()
            elif hasattr(report_date, "isoformat"):
                report_date = report_date.isoformat()  # type: ignore[arg-type]
            elif report_date is None:
                report_date = datetime.utcnow().date().isoformat()

            report_id = report.get("_id") or report_date
            report["_id"] = report_id
            report["report_date"] = report_date

            generated_at = report.get("generated_at")
            if isinstance(generated_at, datetime):
                report["generated_at"] = generated_at.isoformat()
            elif not generated_at:
                report["generated_at"] = datetime.utcnow().isoformat()

            report["updated_at"] = datetime.utcnow().isoformat()

            await collection.replace_one({"_id": report_id}, report, upsert=True)
            logger.info("✓ Saved macro report: %s", report_id)
            return report_id

        except Exception as exc:
            logger.error("✗ Failed to save macro report: %s", exc)
            return None

    async def get_latest_macro_report(self) -> Optional[Dict[str, Any]]:
        """获取最新一份宏观日报"""
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping macro report query")
            return None

        collection = self.db[self.collections['macro_reports']]
        try:
            document = await collection.find_one(
                sort=[("report_date", DESCENDING), ("generated_at", DESCENDING)]
            )
            return document
        except Exception as exc:
            logger.error("✗ Failed to get latest macro report: %s", exc)
            return None

    async def get_macro_report_by_date(self, report_date: Any) -> Optional[Dict[str, Any]]:
        """按日期获取宏观日报"""
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping macro report query")
            return None

        if isinstance(report_date, datetime):
            key = report_date.date().isoformat()
        elif hasattr(report_date, "isoformat"):
            key = report_date.isoformat()  # type: ignore[arg-type]
        else:
            key = str(report_date)

        collection = self.db[self.collections['macro_reports']]
        try:
            return await collection.find_one({"_id": key})
        except Exception as exc:
            logger.error("✗ Failed to get macro report for %s: %s", key, exc)
            return None

    async def get_macro_reports(self, *, limit: int = 7) -> List[Dict[str, Any]]:
        """按时间倒序获取多份宏观日报"""
        if self.client is None or self.db is None:
            logger.warning("MongoDB not available, skipping macro report list query")
            return []

        collection = self.db[self.collections['macro_reports']]
        try:
            cursor = collection.find().sort([
                ("report_date", DESCENDING),
                ("generated_at", DESCENDING),
            ]).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as exc:
            logger.error("✗ Failed to list macro reports: %s", exc)
            return []
    
    async def close(self):
        """关闭数据库连接"""
        if self.client is not None:
            self.client.close()
            logger.info("✓ MongoDB connection closed")

# 全局存储实例
stock_news_storage = StockNewsStorage()

async def get_storage() -> Optional[StockNewsStorage]:
    """获取存储实例"""
    if not MONGODB_AVAILABLE:
        return None
        
    if stock_news_storage.client is None:
        success = await stock_news_storage.initialize()
        if not success:
            return None
    return stock_news_storage
