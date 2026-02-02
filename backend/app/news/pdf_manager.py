import os
import logging
from typing import Optional
from datetime import datetime

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except Exception:
    AsyncIOMotorClient = None

logger = logging.getLogger(__name__)


def _get_mongo_client():
    if AsyncIOMotorClient is None:
        return None
    host = os.getenv('MONGO_HOST', 'localhost')
    port = int(os.getenv('MONGO_PORT', '27017'))
    user = os.getenv('MONGO_USER', '')
    password = os.getenv('MONGO_PASSWORD', '')
    db = os.getenv('MONGO_DB', 'aistock_news')

    if user:
        uri = f"mongodb://{user}:{password}@{host}:{port}/{db}"
    else:
        uri = f"mongodb://{host}:{port}/{db}"

    return AsyncIOMotorClient(uri)


class PDFCacheManager:
    def __init__(self):
        self.client = _get_mongo_client()
        self.db = None
        self.col = None
        if self.client:
            dbname = os.getenv('MONGO_DB', 'aistock_news')
            self.db = self.client[dbname]
            self.col = self.db['pdf_cache']

    async def get(self, url: str) -> Optional[dict]:
        if not self.col:
            return None
        try:
            doc = await self.col.find_one({'url': url})
            return doc
        except Exception as e:
            logger.debug(f'pdf_cache get error: {e}')
            return None

    async def save(self, url: str, text: Optional[str], status: str = 'ok', error: Optional[str] = None):
        if not self.col:
            return
        try:
            doc = {
                'url': url,
                'text': text,
                'status': status,
                'error': error,
                'updated_at': datetime.utcnow(),
            }
            await self.col.update_one({'url': url}, {'$set': doc}, upsert=True)
        except Exception as e:
            logger.debug(f'pdf_cache save error: {e}')


_manager = PDFCacheManager()


async def get_cached_text(url: str) -> Optional[str]:
    doc = await _manager.get(url)
    if not doc:
        return None
    return doc.get('text')


async def save_cached_text(url: str, text: Optional[str], status: str = 'ok', error: Optional[str] = None):
    await _manager.save(url, text, status=status, error=error)
