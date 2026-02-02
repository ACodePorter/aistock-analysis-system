"""
统一文档管理器：PDF/公告的下载、对象存储、LLM结构化提取、入库
实现完整流水线：采集 -> PDF下载 -> 对象存储 -> LLM分析 -> 结构化入库
"""
import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

import httpx

logger = logging.getLogger(__name__)


# ===================== 数据模型 =====================

@dataclass
class PDFMetadata:
    """PDF 元数据"""
    url: str                          # 原始 URL
    storage_path: str = ''            # 对象存储路径（本地或云端）
    file_hash: str = ''               # 文件 SHA256
    file_size: int = 0                # 文件大小（字节）
    page_count: int = 0               # 页数
    downloaded_at: Optional[str] = None
    extraction_status: str = 'pending'  # pending/ok/failed/empty
    extraction_error: Optional[str] = None


@dataclass
class StructuredTags:
    """LLM 提取的结构化标签"""
    document_type: str = ''           # 公告类型：定期报告/临时公告/风险提示/招募说明书等
    industry: List[str] = field(default_factory=list)        # 行业分类
    themes: List[str] = field(default_factory=list)          # 主题标签：并购/分红/业绩/风险等
    keywords: List[str] = field(default_factory=list)        # 关键词
    entities: Dict[str, List[str]] = field(default_factory=dict)  # 命名实体：公司/人物/金额等
    sentiment: str = 'neutral'        # positive/negative/neutral
    sentiment_score: float = 0.0      # -1 ~ 1
    importance: str = 'normal'        # high/normal/low
    summary: str = ''                 # LLM 生成的摘要
    key_points: List[str] = field(default_factory=list)      # 要点列表
    financial_data: Dict[str, Any] = field(default_factory=dict)  # 提取的财务数据
    risk_factors: List[str] = field(default_factory=list)    # 风险因素
    action_items: List[str] = field(default_factory=list)    # 需关注事项


@dataclass
class UnifiedDocument:
    """统一文档模型"""
    # 基础信息
    title: str
    url: str
    source: str                       # cninfo/eastmoney/sse/szse 等
    symbol: Optional[str] = None      # 关联股票代码
    published_at: Optional[str] = None
    
    # 内容
    content_type: str = 'html'        # html/pdf/text
    raw_content: str = ''             # 原始内容（HTML或提取的文本）
    extracted_text: str = ''          # 提取的纯文本
    
    # PDF 相关
    is_pdf: bool = False
    pdf_meta: Optional[PDFMetadata] = None
    
    # 结构化标签
    tags: Optional[StructuredTags] = None
    
    # 处理状态
    processed_at: Optional[str] = None
    llm_analyzed: bool = False
    ingested_to_db: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ===================== 对象存储 =====================

class ObjectStorage:
    """对象存储管理器（支持本地文件系统，可扩展到 MinIO/Azure Blob）"""
    
    def __init__(self, base_path: str = None):
        if base_path is None:
            base_path = os.path.join(os.path.dirname(__file__), '..', '..', 'storage', 'documents')
        self.base_path = os.path.abspath(base_path)
        os.makedirs(self.base_path, exist_ok=True)
        os.makedirs(os.path.join(self.base_path, 'pdf'), exist_ok=True)
        os.makedirs(os.path.join(self.base_path, 'text'), exist_ok=True)
        os.makedirs(os.path.join(self.base_path, 'meta'), exist_ok=True)
    
    def _hash_url(self, url: str) -> str:
        return hashlib.sha256(url.encode('utf-8')).hexdigest()
    
    async def save_pdf(self, url: str, content: bytes) -> str:
        """保存 PDF 文件，返回存储路径"""
        key = self._hash_url(url)
        path = os.path.join(self.base_path, 'pdf', f'{key}.pdf')
        with open(path, 'wb') as f:
            f.write(content)
        return path
    
    async def save_text(self, url: str, text: str) -> str:
        """保存提取的文本"""
        key = self._hash_url(url)
        path = os.path.join(self.base_path, 'text', f'{key}.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path
    
    async def save_meta(self, url: str, meta: Dict[str, Any]) -> str:
        """保存元数据 JSON"""
        key = self._hash_url(url)
        path = os.path.join(self.base_path, 'meta', f'{key}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return path
    
    async def get_pdf(self, url: str) -> Optional[bytes]:
        """获取 PDF 内容"""
        key = self._hash_url(url)
        path = os.path.join(self.base_path, 'pdf', f'{key}.pdf')
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read()
        return None
    
    async def get_text(self, url: str) -> Optional[str]:
        """获取提取的文本"""
        key = self._hash_url(url)
        path = os.path.join(self.base_path, 'text', f'{key}.txt')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    
    async def get_meta(self, url: str) -> Optional[Dict[str, Any]]:
        """获取元数据"""
        key = self._hash_url(url)
        path = os.path.join(self.base_path, 'meta', f'{key}.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    def exists(self, url: str, file_type: str = 'pdf') -> bool:
        """检查文件是否存在"""
        key = self._hash_url(url)
        ext = {'pdf': 'pdf', 'text': 'txt', 'meta': 'json'}.get(file_type, file_type)
        path = os.path.join(self.base_path, file_type, f'{key}.{ext}')
        return os.path.exists(path)


# ===================== LLM 结构化提取 =====================

class LLMExtractor:
    """使用 LLM 提取结构化信息"""
    
    EXTRACTION_PROMPT = '''请分析以下文档内容，提取结构化信息。

文档标题：{title}
文档来源：{source}
关联股票：{symbol}

文档内容（截取前8000字）：
{content}

请以 JSON 格式返回以下信息：
{{
    "document_type": "文档类型（如：定期报告/临时公告/风险提示/招募说明书/业绩预告/董事会决议等）",
    "industry": ["相关行业1", "相关行业2"],
    "themes": ["主题标签1", "主题标签2"],  // 如：并购重组/分红派息/业绩变动/风险提示/人事变动/股权激励等
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "entities": {{
        "companies": ["公司名1"],
        "people": ["人名1"],
        "amounts": ["金额1"],
        "dates": ["日期1"]
    }},
    "sentiment": "positive/negative/neutral",
    "sentiment_score": 0.5,  // -1到1之间
    "importance": "high/normal/low",
    "summary": "100-200字的核心摘要",
    "key_points": ["要点1", "要点2", "要点3"],
    "financial_data": {{
        // 如有财务数据则提取，如营收、利润、同比增长等
    }},
    "risk_factors": ["风险因素1"],  // 如有
    "action_items": ["需关注事项1"]  // 投资者需关注的事项
}}

只返回 JSON，不要其他文字。'''

    def __init__(self):
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化 LLM 客户端"""
        # 优先使用本地 Qwen
        if os.getenv('LOCAL_QWEN_ENABLED', 'false').lower() == 'true':
            self.api_url = os.getenv('LOCAL_QWEN_URL', 'http://localhost:1234/v1')
            self.api_key = 'not-needed'
            self.model = os.getenv('LOCAL_QWEN_MODEL', 'local-model')
            self.is_local = True
        else:
            # Azure OpenAI
            endpoint = os.getenv('AZURE_OPENAI_ENDPOINT', '')
            self.api_key = os.getenv('AZURE_OPENAI_KEY', '')
            self.model = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4')
            self.api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
            self.api_url = f"{endpoint}/openai/deployments/{self.model}/chat/completions?api-version={self.api_version}"
            self.is_local = False
        
        self.timeout = int(os.getenv('LOCAL_QWEN_TIMEOUT', '120'))
    
    async def extract_structured_tags(self, doc: UnifiedDocument) -> StructuredTags:
        """使用 LLM 提取结构化标签"""
        content = doc.extracted_text or doc.raw_content
        if not content:
            return StructuredTags()
        
        # 截取前 8000 字
        content = content[:8000]
        
        prompt = self.EXTRACTION_PROMPT.format(
            title=doc.title,
            source=doc.source,
            symbol=doc.symbol or '未知',
            content=content
        )
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if self.is_local:
                    # OpenAI 兼容格式
                    resp = await client.post(
                        f"{self.api_url}/chat/completions",
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.3,
                            "max_tokens": 2048,
                        }
                    )
                else:
                    # Azure OpenAI
                    resp = await client.post(
                        self.api_url,
                        headers={
                            "api-key": self.api_key,
                            "Content-Type": "application/json"
                        },
                        json={
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.3,
                            "max_tokens": 2048,
                        }
                    )
                
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                    return self._parse_llm_response(text)
                else:
                    logger.warning(f"LLM API error: {resp.status_code}")
                    return StructuredTags()
                    
        except Exception as e:
            logger.error(f"LLM extraction error: {e}")
            return StructuredTags()
    
    def _parse_llm_response(self, text: str) -> StructuredTags:
        """解析 LLM 返回的 JSON"""
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                data = json.loads(json_match.group())
                return StructuredTags(
                    document_type=data.get('document_type', ''),
                    industry=data.get('industry', []),
                    themes=data.get('themes', []),
                    keywords=data.get('keywords', []),
                    entities=data.get('entities', {}),
                    sentiment=data.get('sentiment', 'neutral'),
                    sentiment_score=float(data.get('sentiment_score', 0)),
                    importance=data.get('importance', 'normal'),
                    summary=data.get('summary', ''),
                    key_points=data.get('key_points', []),
                    financial_data=data.get('financial_data', {}),
                    risk_factors=data.get('risk_factors', []),
                    action_items=data.get('action_items', [])
                )
        except Exception as e:
            logger.debug(f"Failed to parse LLM response: {e}")
        
        return StructuredTags()


# ===================== 文档处理流水线 =====================

class DocumentPipeline:
    """统一文档处理流水线"""
    
    def __init__(self):
        self.storage = ObjectStorage()
        self.llm_extractor = LLMExtractor()
        self._http_client = None
        self._semaphore = asyncio.Semaphore(3)  # 限制并发
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
        return self._http_client
    
    async def close(self):
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
    
    async def process_document(self, doc: UnifiedDocument) -> UnifiedDocument:
        """处理单个文档：下载 -> 存储 -> 提取 -> LLM 分析"""
        
        async with self._semaphore:
            try:
                # 1. 如果是 PDF，下载并存储
                if doc.is_pdf or doc.url.lower().endswith('.pdf'):
                    doc.is_pdf = True
                    doc = await self._process_pdf(doc)
                
                # 2. LLM 结构化提取
                if doc.extracted_text or doc.raw_content:
                    doc.tags = await self.llm_extractor.extract_structured_tags(doc)
                    doc.llm_analyzed = True
                
                doc.processed_at = datetime.utcnow().isoformat()
                
                # 3. 保存元数据
                await self.storage.save_meta(doc.url, doc.to_dict())
                
            except Exception as e:
                logger.error(f"Error processing document {doc.url}: {e}")
            
            return doc
    
    async def _process_pdf(self, doc: UnifiedDocument) -> UnifiedDocument:
        """处理 PDF 文档"""
        url = doc.url
        
        # 检查是否已存储
        if self.storage.exists(url, 'pdf'):
            # 从存储读取
            content = await self.storage.get_pdf(url)
            text = await self.storage.get_text(url)
            if text:
                doc.extracted_text = text
                doc.pdf_meta = PDFMetadata(
                    url=url,
                    storage_path=os.path.join(self.storage.base_path, 'pdf', f'{self.storage._hash_url(url)}.pdf'),
                    file_hash=self.storage._hash_url(url),
                    extraction_status='ok'
                )
                return doc
        
        # 下载 PDF
        client = await self._get_client()
        try:
            # 尝试多个 URL 变体（CNInfo 有时需要 static 域名）
            urls_to_try = [url]
            if 'cninfo.com.cn' in url and 'static.cninfo.com.cn' not in url:
                from urllib.parse import urlparse
                p = urlparse(url)
                path = p.path.lstrip('/')
                urls_to_try.append(f"https://static.cninfo.com.cn/{path}")
            
            pdf_content = None
            for try_url in urls_to_try:
                try:
                    resp = await client.get(try_url)
                    if resp.status_code == 200 and resp.content:
                        pdf_content = resp.content
                        url = try_url  # 使用成功的 URL
                        break
                except Exception:
                    continue
            
            if not pdf_content:
                doc.pdf_meta = PDFMetadata(url=url, extraction_status='failed', extraction_error='download_failed')
                return doc
            
            # 保存到对象存储
            storage_path = await self.storage.save_pdf(url, pdf_content)
            
            # 提取文本
            text = await self._extract_pdf_text(storage_path)
            if text:
                await self.storage.save_text(url, text)
                doc.extracted_text = text
            
            # 获取页数
            page_count = 0
            try:
                from pypdf import PdfReader
                import io
                reader = PdfReader(io.BytesIO(pdf_content))
                page_count = len(reader.pages)
            except Exception:
                pass
            
            doc.pdf_meta = PDFMetadata(
                url=url,
                storage_path=storage_path,
                file_hash=hashlib.sha256(pdf_content).hexdigest(),
                file_size=len(pdf_content),
                page_count=page_count,
                downloaded_at=datetime.utcnow().isoformat(),
                extraction_status='ok' if text else 'empty'
            )
            
        except Exception as e:
            logger.error(f"PDF download error for {url}: {e}")
            doc.pdf_meta = PDFMetadata(url=url, extraction_status='failed', extraction_error=str(e))
        
        return doc
    
    async def _extract_pdf_text(self, pdf_path: str) -> str:
        """从 PDF 文件提取文本"""
        # 复用现有的提取逻辑
        try:
            from pypdf import PdfReader
            reader = PdfReader(pdf_path)
            text_parts = []
            for page in reader.pages:
                try:
                    t = page.extract_text() or ''
                    if t:
                        text_parts.append(t)
                except Exception:
                    pass
            text = '\n'.join(text_parts).strip()
            if text:
                return text
        except Exception:
            pass
        
        # fallback: pdfminer
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(pdf_path) or ''
            if text:
                return text.strip()
        except Exception:
            pass
        
        return ''
    
    async def process_batch(self, documents: List[UnifiedDocument]) -> List[UnifiedDocument]:
        """批量处理文档"""
        results = []
        for doc in documents:
            processed = await self.process_document(doc)
            results.append(processed)
        return results


# ===================== MongoDB 入库 =====================

class DocumentIngester:
    """文档入库管理器"""
    
    def __init__(self):
        self.mongo_client = None
        self.db = None
        self._init_mongo()
    
    def _init_mongo(self):
        """初始化 MongoDB 连接"""
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            host = os.getenv('MONGO_HOST', 'localhost')
            port = int(os.getenv('MONGO_PORT', '27017'))
            db_name = os.getenv('MONGO_DB', 'aistock_news')
            self.mongo_client = AsyncIOMotorClient(f"mongodb://{host}:{port}")
            self.db = self.mongo_client[db_name]
        except Exception as e:
            logger.exception("MongoDB init failed (full traceback)")
            # 清理客户端，避免残留不完整连接
            try:
                if self.mongo_client:
                    self.mongo_client.close()
            except Exception:
                pass
            self.mongo_client = None
            self.db = None
    
    async def ingest_document(self, doc: UnifiedDocument) -> bool:
        """将处理后的文档入库"""
        if self.db is None:
            logger.warning("MongoDB not available")
            return False
        
        try:
            collection = self.db['documents']
            
            # 构建文档记录
            record = {
                'url': doc.url,
                'title': doc.title,
                'source': doc.source,
                'symbol': doc.symbol,
                'published_at': doc.published_at,
                'content_type': doc.content_type,
                'is_pdf': doc.is_pdf,
                'extracted_text': doc.extracted_text[:50000] if doc.extracted_text else '',  # 限制大小
                'processed_at': doc.processed_at,
                'llm_analyzed': doc.llm_analyzed,
                'updated_at': datetime.utcnow(),
            }
            
            # PDF 元数据
            if doc.pdf_meta:
                record['pdf_meta'] = {
                    'storage_path': doc.pdf_meta.storage_path,
                    'file_hash': doc.pdf_meta.file_hash,
                    'file_size': doc.pdf_meta.file_size,
                    'page_count': doc.pdf_meta.page_count,
                    'extraction_status': doc.pdf_meta.extraction_status,
                }
            
            # 结构化标签
            if doc.tags:
                record['tags'] = {
                    'document_type': doc.tags.document_type,
                    'industry': doc.tags.industry,
                    'themes': doc.tags.themes,
                    'keywords': doc.tags.keywords,
                    'entities': doc.tags.entities,
                    'sentiment': doc.tags.sentiment,
                    'sentiment_score': doc.tags.sentiment_score,
                    'importance': doc.tags.importance,
                    'summary': doc.tags.summary,
                    'key_points': doc.tags.key_points,
                    'financial_data': doc.tags.financial_data,
                    'risk_factors': doc.tags.risk_factors,
                    'action_items': doc.tags.action_items,
                }
            
            # upsert
            await collection.update_one(
                {'url': doc.url},
                {'$set': record},
                upsert=True
            )
            
            doc.ingested_to_db = True
            logger.info(f"Ingested document: {doc.title[:50]}")
            return True
            
        except Exception as e:
            logger.error(f"Ingest error: {e}")
            return False
    
    async def ingest_batch(self, documents: List[UnifiedDocument]) -> int:
        """批量入库"""
        success_count = 0
        for doc in documents:
            if await self.ingest_document(doc):
                success_count += 1
        return success_count


# ===================== 统一管理器 =====================

class UnifiedDocumentManager:
    """统一文档管理器 - 整合所有功能"""
    
    def __init__(self):
        self.pipeline = DocumentPipeline()
        self.ingester = DocumentIngester()
    
    async def close(self):
        await self.pipeline.close()
    
    async def process_and_ingest(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        处理并入库文档列表
        
        Args:
            documents: 文档列表，每个包含 title, url, source, symbol, is_pdf 等字段
        
        Returns:
            处理结果统计
        """
        stats = {
            'total': len(documents),
            'processed': 0,
            'pdf_downloaded': 0,
            'llm_analyzed': 0,
            'ingested': 0,
            'errors': 0,
        }
        
        # 转换为 UnifiedDocument
        docs = []
        for d in documents:
            doc = UnifiedDocument(
                title=d.get('title', ''),
                url=d.get('url', ''),
                source=d.get('source', 'unknown'),
                symbol=d.get('symbol'),
                published_at=d.get('published'),
                content_type='pdf' if d.get('is_pdf') or d.get('url', '').lower().endswith('.pdf') else 'html',
                is_pdf=d.get('is_pdf', False) or d.get('url', '').lower().endswith('.pdf'),
                raw_content=d.get('content', '') or d.get('summary', ''),
            )
            docs.append(doc)
        
        # 处理
        processed_docs = await self.pipeline.process_batch(docs)
        
        # 统计并入库
        for doc in processed_docs:
            stats['processed'] += 1
            if doc.pdf_meta and doc.pdf_meta.extraction_status == 'ok':
                stats['pdf_downloaded'] += 1
            if doc.llm_analyzed:
                stats['llm_analyzed'] += 1
            
            if await self.ingester.ingest_document(doc):
                stats['ingested'] += 1
            else:
                stats['errors'] += 1
        
        return stats
    
    async def process_pdf_samples(self, pdf_urls: List[str], symbol: str = None) -> List[UnifiedDocument]:
        """处理 PDF 样本列表"""
        docs = []
        for url in pdf_urls:
            doc = UnifiedDocument(
                title=url.split('/')[-1],
                url=url,
                source='cninfo',
                symbol=symbol,
                is_pdf=True,
                content_type='pdf'
            )
            docs.append(doc)
        
        return await self.pipeline.process_batch(docs)
