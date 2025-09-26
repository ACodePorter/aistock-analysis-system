"""
News Deduplication System
Advanced deduplication mechanism for news articles and URLs
"""

import asyncio
import hashlib
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple, Set
from dataclasses import dataclass
import difflib

# MongoDB 相关导入 - 可选
try:
    import pymongo
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False
    pymongo = None

from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, or_
import threading

from .models import NewsArticle, NewsSource
from .db import SessionLocal, get_redis_client


@dataclass
class DuplicationResult:
    """去重检查结果"""
    is_duplicate: bool
    duplicate_type: str  # url, content, title
    similarity_score: float
    original_article_id: Optional[int] = None
    original_url: Optional[str] = None


_DEDUP_INIT_LOCK = threading.Lock()
_DEDUP_MONGO_CLIENT = None
_DEDUP_MONGO_DB = None
_DEDUP_MONGO_READY = False


class NewsDeduplicator:
    """
    新闻去重系统

    说明：
    - 为避免在 FastAPI 热重载或多处实例化时重复初始化 MongoDB，本类复用模块级单例连接；
    - 首次初始化成功后，仅在进程内打印一次“MongoDB deduplication cache initialized”。
    """
    
    def __init__(self):
        self.redis_client = get_redis_client()
        self.mongo_client = None
        self.db = None
        
        # 去重配置
        self.content_similarity_threshold = 0.85  # 内容相似度阈值
        self.title_similarity_threshold = 0.90    # 标题相似度阈值
        self.url_cache_expire = 86400 * 7        # URL缓存过期时间(7天)
        self.content_hash_length = 64            # 内容哈希长度
        
        # MongoDB配置（复用单例，避免重复初始化/日志噪音）
        self._ensure_mongo_singleton()

    def _ensure_mongo_singleton(self):
        global _DEDUP_MONGO_CLIENT, _DEDUP_MONGO_DB, _DEDUP_MONGO_READY
        if not MONGODB_AVAILABLE:
            # 无 MongoDB 依赖时静默降级
            return
        # 快路径：已初始化则直接复用
        if _DEDUP_MONGO_READY and _DEDUP_MONGO_CLIENT is not None:
            self.mongo_client = _DEDUP_MONGO_CLIENT
            self.db = _DEDUP_MONGO_DB
            return
        # 慢路径：加锁初始化
        with _DEDUP_INIT_LOCK:
            if _DEDUP_MONGO_READY and _DEDUP_MONGO_CLIENT is not None:
                self.mongo_client = _DEDUP_MONGO_CLIENT
                self.db = _DEDUP_MONGO_DB
                return
            # 初始化并赋值到单例
            self._init_mongodb()
            if self.mongo_client is not None:
                _DEDUP_MONGO_CLIENT = self.mongo_client
                _DEDUP_MONGO_DB = self.db
                _DEDUP_MONGO_READY = True
    
    def _init_mongodb(self):
        """初始化MongoDB连接（只在进程首次调用时执行）"""
        if not MONGODB_AVAILABLE:
            print("⚠ MongoDB not available, deduplication will use PostgreSQL only")
            return
            
        import os
        try:
            mongo_host = os.getenv("MONGO_HOST", "localhost")
            mongo_port = int(os.getenv("MONGO_PORT", "27017"))
            mongo_user = os.getenv("MONGO_USER", "")
            mongo_password = os.getenv("MONGO_PASSWORD", "")
            mongo_db = os.getenv("MONGO_DB", "aistock_news")
            
            if mongo_user and mongo_password:
                uri = f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/{mongo_db}"
            else:
                uri = f"mongodb://{mongo_host}:{mongo_port}/{mongo_db}"
            
            self.mongo_client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.db = self.mongo_client[mongo_db]
            
            # 测试连接
            self.mongo_client.server_info()
            
            # 创建索引
            self._create_indexes()
            # 仅首次初始化时打印
            print("✓ MongoDB deduplication cache initialized")
            
        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
                print(f"⚠ MongoDB authentication failed: {e}")
                print("⚠ Please check MONGO_USER and MONGO_PASSWORD in .env file")
                print("⚠ Or disable MongoDB authentication on your MongoDB server")
            else:
                print(f"⚠ MongoDB initialization failed: {e}")
            print("⚠ Deduplication will use PostgreSQL only")
            self.mongo_client = None
            self.db = None
    
    def _create_indexes(self):
        """创建MongoDB索引"""
        if self.db is None:
            return
            
        try:
            # URL去重索引
            self.db.url_cache.create_index("url_hash", unique=True)
            self.db.url_cache.create_index("created_at", expireAfterSeconds=self.url_cache_expire)
            
            # 内容指纹索引
            self.db.content_fingerprints.create_index("content_hash", unique=True)
            self.db.content_fingerprints.create_index("title_hash")
            self.db.content_fingerprints.create_index("created_at", expireAfterSeconds=86400 * 30)  # 30天过期
            
            # 文本相似度索引
            self.db.similarity_cache.create_index("text_hash")
            self.db.similarity_cache.create_index("created_at", expireAfterSeconds=86400 * 7)   # 7天过期
            
        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
                print(f"⚠ MongoDB authentication failed during index creation: {e}")
                print("⚠ Please check MONGO_USER and MONGO_PASSWORD in .env file")
                print("⚠ Disabling MongoDB features for this session")
                # 清理连接，避免后续操作失败
                if self.mongo_client:
                    self.mongo_client.close()
                self.mongo_client = None
                self.db = None
            else:
                print(f"Failed to create MongoDB indexes: {e}")
    
    async def check_duplicate(self, url: str, title: str, content: str) -> DuplicationResult:
        """
        全面的去重检查
        """
        # 1. URL去重检查
        url_result = await self._check_url_duplicate(url)
        if url_result.is_duplicate:
            return url_result
        
        # 2. 标题去重检查
        title_result = await self._check_title_duplicate(title)
        if title_result.is_duplicate:
            return title_result
        
        # 3. 内容去重检查
        content_result = await self._check_content_duplicate(content)
        if content_result.is_duplicate:
            return content_result
        
        # 4. 如果都不重复，记录指纹
        await self._record_fingerprints(url, title, content)
        
        return DuplicationResult(
            is_duplicate=False,
            duplicate_type="none",
            similarity_score=0.0
        )
    
    async def _check_url_duplicate(self, url: str) -> DuplicationResult:
        """
        检查URL是否重复
        """
        url_hash = self._generate_url_hash(url)
        
        # 检查Redis缓存
        if self.redis_client:
            try:
                cached = await self.redis_client.get(f"url_cache:{url_hash}")
                if cached:
                    return DuplicationResult(
                        is_duplicate=True,
                        duplicate_type="url",
                        similarity_score=1.0,
                        original_url=url
                    )
            except Exception:
                pass
        
        # 检查数据库
        session = SessionLocal()
        try:
            existing = session.execute(
                select(NewsArticle).where(NewsArticle.url == url)
            ).scalar_one_or_none()
            
            if existing:
                # 记录到缓存
                if self.redis_client:
                    try:
                        await self.redis_client.setex(
                            f"url_cache:{url_hash}",
                            self.url_cache_expire,
                            str(existing.id)
                        )
                    except Exception:
                        pass
                
                return DuplicationResult(
                    is_duplicate=True,
                    duplicate_type="url",
                    similarity_score=1.0,
                    original_article_id=existing.id,
                    original_url=existing.url
                )
            
            return DuplicationResult(
                is_duplicate=False,
                duplicate_type="url",
                similarity_score=0.0
            )
            
        finally:
            session.close()
    
    async def _check_title_duplicate(self, title: str) -> DuplicationResult:
        """
        检查标题是否重复或高度相似
        """
        if not title or len(title.strip()) < 10:
            return DuplicationResult(
                is_duplicate=False,
                duplicate_type="title",
                similarity_score=0.0
            )
        
        title_hash = self._generate_text_hash(title)
        
        # 检查MongoDB缓存
        if self.db is not None:
            try:
                cached = self.db.content_fingerprints.find_one({"title_hash": title_hash})
                if cached:
                    return DuplicationResult(
                        is_duplicate=True,
                        duplicate_type="title",
                        similarity_score=1.0,
                        original_article_id=cached.get("article_id")
                    )
            except Exception:
                pass
        
        # 检查数据库中相似标题
        session = SessionLocal()
        try:
            # 查找最近的标题进行相似度比较
            recent_articles = session.execute(
                select(NewsArticle.id, NewsArticle.title, NewsArticle.url)
                .where(NewsArticle.crawled_at >= datetime.utcnow() - timedelta(days=7))
                .order_by(NewsArticle.crawled_at.desc())
                .limit(1000)
            ).all()
            
            for article_id, existing_title, existing_url in recent_articles:
                if existing_title:
                    similarity = self._calculate_text_similarity(title, existing_title)
                    if similarity >= self.title_similarity_threshold:
                        return DuplicationResult(
                            is_duplicate=True,
                            duplicate_type="title",
                            similarity_score=similarity,
                            original_article_id=article_id,
                            original_url=existing_url
                        )
            
            return DuplicationResult(
                is_duplicate=False,
                duplicate_type="title",
                similarity_score=0.0
            )
            
        finally:
            session.close()
    
    async def _check_content_duplicate(self, content: str) -> DuplicationResult:
        """
        检查内容是否重复或高度相似
        """
        if not content or len(content.strip()) < 100:
            return DuplicationResult(
                is_duplicate=False,
                duplicate_type="content",
                similarity_score=0.0
            )
        
        content_hash = self._generate_content_hash(content)
        
        # 检查MongoDB缓存
        if self.db is not None:
            try:
                cached = self.db.content_fingerprints.find_one({"content_hash": content_hash})
                if cached:
                    return DuplicationResult(
                        is_duplicate=True,
                        duplicate_type="content",
                        similarity_score=1.0,
                        original_article_id=cached.get("article_id")
                    )
            except Exception:
                pass
        
        # 使用内容特征进行相似度检查
        content_features = self._extract_content_features(content)
        
        # 检查数据库中的相似内容
        session = SessionLocal()
        try:
            # 查找最近的文章进行内容相似度比较
            recent_articles = session.execute(
                select(NewsArticle.id, NewsArticle.content, NewsArticle.url)
                .where(
                    and_(
                        NewsArticle.content.isnot(None),
                        NewsArticle.crawled_at >= datetime.utcnow() - timedelta(days=3)
                    )
                )
                .order_by(NewsArticle.crawled_at.desc())
                .limit(500)
            ).all()
            
            for article_id, existing_content, existing_url in recent_articles:
                if existing_content:
                    similarity = self._calculate_content_similarity(content, existing_content)
                    if similarity >= self.content_similarity_threshold:
                        return DuplicationResult(
                            is_duplicate=True,
                            duplicate_type="content",
                            similarity_score=similarity,
                            original_article_id=article_id,
                            original_url=existing_url
                        )
            
            return DuplicationResult(
                is_duplicate=False,
                duplicate_type="content",
                similarity_score=0.0
            )
            
        finally:
            session.close()
    
    async def _record_fingerprints(self, url: str, title: str, content: str):
        """
        记录文章指纹信息
        """
        url_hash = self._generate_url_hash(url)
        title_hash = self._generate_text_hash(title) if title else None
        content_hash = self._generate_content_hash(content) if content else None
        
        # 记录到Redis
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    f"url_cache:{url_hash}",
                    self.url_cache_expire,
                    "pending"
                )
            except Exception:
                pass
        
        # 记录到MongoDB
        if self.db is not None:
            try:
                # 注意：当 content_hash 为 None 时不要写入该字段，
                # 以避免在唯一索引(content_hash)下因 null 值触发重复键错误。
                fingerprint_doc = {
                    "url": url,
                    "url_hash": url_hash,
                    "created_at": datetime.utcnow(),
                }
                if title_hash:
                    fingerprint_doc["title_hash"] = title_hash
                if content_hash:
                    fingerprint_doc["content_hash"] = content_hash
                
                self.db.content_fingerprints.insert_one(fingerprint_doc)
            except Exception as e:
                print(f"Failed to record fingerprints: {e}")
    
    def _generate_url_hash(self, url: str) -> str:
        """
        生成URL标准化哈希
        """
        from urllib.parse import urlparse, urlunparse
        
        # 标准化URL
        parsed = urlparse(url.lower())
        # 移除查询参数和片段
        clean_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/'),
            '',  # params
            '',  # query
            ''   # fragment
        ))
        
        return hashlib.md5(clean_url.encode('utf-8')).hexdigest()
    
    def _generate_text_hash(self, text: str) -> str:
        """
        生成文本哈希
        """
        # 标准化文本
        normalized = re.sub(r'\s+', ' ', text.strip().lower())
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    
    def _generate_content_hash(self, content: str) -> str:
        """
        生成内容特征哈希
        """
        # 提取内容特征
        features = self._extract_content_features(content)
        feature_string = ''.join(sorted(features))
        
        return hashlib.sha256(feature_string.encode('utf-8')).hexdigest()[:self.content_hash_length]
    
    def _extract_content_features(self, content: str) -> Set[str]:
        """
        提取内容特征用于相似度比较
        """
        features = set()
        
        # 移除标点符号和空白字符
        cleaned = re.sub(r'[^\w\s]', '', content.lower())
        words = cleaned.split()
        
        # 提取3-gram
        for i in range(len(words) - 2):
            trigram = ' '.join(words[i:i+3])
            features.add(trigram)
        
        # 提取数字模式
        numbers = re.findall(r'\d+(?:\.\d+)?%?', content)
        features.update(numbers)
        
        # 提取关键短语
        key_phrases = re.findall(r'[^，。！？\s]{3,8}(?:[股份有限公司|有限公司|集团|控股])', content)
        features.update(key_phrases)
        
        return features
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        计算文本相似度
        """
        if not text1 or not text2:
            return 0.0
        
        # 使用difflib计算序列相似度
        similarity = difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
        
        # 计算Jaccard相似度作为补充
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        jaccard = intersection / union if union > 0 else 0.0
        
        # 综合相似度
        return (similarity + jaccard) / 2
    
    def _calculate_content_similarity(self, content1: str, content2: str) -> float:
        """
        计算内容相似度
        """
        if not content1 or not content2:
            return 0.0
        
        # 提取内容特征
        features1 = self._extract_content_features(content1)
        features2 = self._extract_content_features(content2)
        
        if not features1 and not features2:
            return 1.0
        if not features1 or not features2:
            return 0.0
        
        # 计算Jaccard相似度
        intersection = len(features1 & features2)
        union = len(features1 | features2)
        
        return intersection / union if union > 0 else 0.0
    
    async def batch_check_duplicates(self, articles: List[Dict[str, Any]]) -> List[DuplicationResult]:
        """
        批量检查重复
        """
        results = []
        
        for article in articles:
            url = article.get('url', '')
            title = article.get('title', '')
            content = article.get('content', '')
            
            result = await self.check_duplicate(url, title, content)
            results.append(result)
        
        return results
    
    async def clean_duplicates(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        清理重复的新闻文章
        """
        session = SessionLocal()
        try:
            # 查找可能的重复文章
            duplicates_found = []
            
            # 查找相同URL的文章
            url_duplicates = session.execute(
                select(NewsArticle.url, func.count(NewsArticle.id).label('count'))
                .group_by(NewsArticle.url)
                .having(func.count(NewsArticle.id) > 1)
            ).all()
            
            for url, count in url_duplicates:
                articles = session.execute(
                    select(NewsArticle)
                    .where(NewsArticle.url == url)
                    .order_by(NewsArticle.crawled_at.asc())
                ).scalars().all()
                
                # 保留第一个，标记其他为重复
                for i, article in enumerate(articles):
                    if i == 0:
                        continue  # 保留第一个
                    
                    duplicates_found.append({
                        'id': article.id,
                        'url': article.url,
                        'title': article.title,
                        'duplicate_type': 'url',
                        'original_id': articles[0].id
                    })
                    
                    if not dry_run:
                        article.is_duplicate = True
                        article.duplicate_of = articles[0].id
            
            if not dry_run:
                session.commit()
            
            return {
                'total_duplicates_found': len(duplicates_found),
                'url_duplicates': len(url_duplicates),
                'duplicates': duplicates_found,
                'dry_run': dry_run
            }
            
        finally:
            session.close()
    
    async def get_deduplication_stats(self) -> Dict[str, Any]:
        """
        获取去重统计信息
        """
        session = SessionLocal()
        try:
            total_articles = session.execute(select(func.count(NewsArticle.id))).scalar()
            duplicate_articles = session.execute(
                select(func.count(NewsArticle.id)).where(NewsArticle.is_duplicate == True)
            ).scalar()
            
            # Redis缓存统计
            redis_stats = {}
            if self.redis_client:
                try:
                    url_cache_keys = await self.redis_client.keys("url_cache:*")
                    redis_stats['url_cache_count'] = len(url_cache_keys)
                except Exception:
                    redis_stats['url_cache_count'] = 0
            
            # MongoDB统计
            mongo_stats = {}
            if self.db is not None:
                try:
                    mongo_stats['fingerprints_count'] = self.db.content_fingerprints.count_documents({})
                    mongo_stats['similarity_cache_count'] = self.db.similarity_cache.count_documents({})
                except Exception:
                    mongo_stats = {'fingerprints_count': 0, 'similarity_cache_count': 0}
            
            return {
                'total_articles': total_articles,
                'duplicate_articles': duplicate_articles,
                'unique_articles': total_articles - duplicate_articles,
                'duplication_rate': (duplicate_articles / total_articles * 100) if total_articles > 0 else 0,
                'redis_stats': redis_stats,
                'mongo_stats': mongo_stats,
                'last_updated': datetime.utcnow().isoformat()
            }
            
        finally:
            session.close()