"""
模块说明
----------
news_crawler.py 提供一个异步的新闻内容爬取器 NewsContentCrawler，用于从网页中抓取新闻文章的标题、作者、发布时间、正文、
摘要、关键词、命名实体和内容质量评分等信息，并提供批量并发爬取、去重检测和简单的内容清洗与解析策略。
主要特性
- 异步 HTTP 请求（基于 httpx.AsyncClient），支持超时、重试和指数退避。
- 支持作为异步上下文管理器使用：async with NewsContentCrawler() as crawler: ...
- 自动去重：通过标准化 URL（去掉查询参数）并计算 MD5 哈希，结合数据库中的 NewsArticle 表做去重判断。
- 多种正文提取策略：基于预定义选择器的 CSS 抽取 -> fallback 使用 Readability（如果可用）-> 最后回退到所有段落合并。
- 清理逻辑：移除注释、脚本、样式、广告/侧边栏/评论等不相关元素，并移除空段落。
- 编码检测：若安装 chardet，则使用其推断响应内容编码以更可靠地解码。
- 批量并发爬取：支持限制最大并发数并在每次请求后进行速率限制延时。
- 简单的 NLP / 规则提取：摘要生成、基于词表的关键词提取、基于正则的命名实体识别（股票代码、公司名称），以及内容质量评分。
- 支持基本的发布时间解析，尝试多种常见时间格式（含 ISO、SQL、中文日期等）。
使用说明
----------
- 以异步上下文管理器方式使用，示例：
    async with NewsContentCrawler() as crawler:
        result = await crawler.crawl_article("https://example.com/news/123")
- 批量示例：
    async with NewsContentCrawler() as crawler:
        results = await crawler.batch_crawl_articles(list_of_urls, max_concurrent=5)
注意事项与依赖
- 依赖库：httpx、beautifulsoup4。可选依赖：readability（用于更强的正文抽取）、chardet（用于更可靠的编码检测）。
- 去重检查依赖外部数据库模型与会话：SessionLocal、NewsArticle、NewsSource（在模块中引用）。调用方须确保数据库会话工厂和模型存在且可用。
- URL 去重当前基于原始 URL 的 scheme://netloc/path（忽略查询参数），因此对仅通过查询参数区分的不同内容可能视为同一篇文章。
- 正文抽取依赖于预定义的 CSS 选择器映射，针对常见中文财经站点提供了一些 site-specific 选择器；但对任意站点不保证完美命中，需要根据目标站点适配选择器。
- 时间解析基于字符串匹配与 datetime.strptime 的多个格式尝试，无法覆盖所有自然语言时间表达，复杂时间字符串可能解析失败并返回 None。
- 内容质量评分、关键词和实体提取为规则型启发式实现，仅作辅助用途，非严格的 NLP 模块。
返回结构（crawl_article / batch_crawl_articles 中每项结果）
- 成功时（status == "success"）包含字段：
    - url: 原始 URL（字符串）
    - url_hash: 规范化后 URL 的 MD5 哈希（用于去重）
    - crawled_at: 抓取时间（UTC ISO 格式）
    - title: 标题（字符串，若未提取到为空字符串）
    - content: 正文纯文本（字符串）
    - summary: 摘要（字符串）
    - author: 作者（字符串或 None）
    - published_date: datetime 或 None
    - keywords: 关键词列表
    - entities: 实体列表
    - content_quality: 质量分数（0.0 到 1.0）
    - word_count: 正文字数（int）
    - domain: 域名（字符串）
- 去重时返回 {"status": "duplicate", "url": ...}
- 出错时返回 {"status": "error", "url": ..., "error": "..."} 或 batch 中的对应项包含错误信息。
扩展建议
- 若需更可靠的实体识别或关键词抽取，建议集成专门的 NLP 库（如 spaCy、jieba、HanLP）或基于预训练模型的抽取器。
- 可将去重从仅检查完整 URL 扩展为检查正文摘要哈希或标题+发布时间组合以提高去重鲁棒性。
- 可增加对常见站点的 more-specific 解析规则或定制化解析器（例如处理分页文章、动态加载内容）。
- 可加入持久化抓取日志、失败重试队列、代理支持与请求速率动态调整等生产级功能。
异常与日志
- 本模块会在遇到请求失败或解析异常时通过 logging 记录警告或错误，调用方应根据返回的 status 字段判断并处理失败项。

"""

import asyncio
import re
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urljoin, urlparse, parse_qs
import logging

import httpx
from bs4 import BeautifulSoup, Comment
try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False
    
try:
    import chardet
    CHARDET_AVAILABLE = True
except ImportError:
    CHARDET_AVAILABLE = False

from .models import NewsArticle, NewsSource
from .db import SessionLocal


class NewsContentCrawler:
    """新闻内容爬虫"""
    
    def __init__(self):
        self.timeout = 30
        self.max_retries = 3
        self.rate_limit_delay = 1  # seconds between requests
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        ]
        self.session = None
        
        # 内容选择器配置
        self.content_selectors = {
            # 通用选择器
            'article': ['article', '.article', '.post-content', '.entry-content'],
            'content': ['.content', '.main-content', '.article-content', '.post-body'],
            'text': ['.text', '.article-text', '.news-content', '.story-content'],
            
            # 中文财经网站特定选择器
            'sina': ['.article', '.content', 'div[id*="artibody"]'],
            'eastmoney': ['.content', '.newsContent', '.article-content'],
            'cnbc': ['.InlineArticleBody-container', '.ArticleBody-articleBody'],
            'reuters': ['.StandardArticleBody_body', '.ArticleBodyWrapper'],
            'bloomberg': ['.body-copy', '.story-body'],
            'ifeng': ['.main_content', '.yc_con_txt'],
            'hexun': ['.art_content', '.content'],
            'jrj': ['.texttit_m1', '.content'],
            'wallstreetcn': ['.content', '.article-content'],
            'cls': ['.detail-content', '.article-content'],
            'caijing': ['.content', '.article-content'],
            'yicai': ['.m-content', '.article-content'],
            'thepaper': ['.news_txt', '.content'],
            'ftchinese': ['.story-body', '.content'],
            'caixin': ['.content', '.article-content']
        }
        
        # 需要移除的元素选择器
        self.remove_selectors = [
            'script', 'style', 'iframe', 'object', 'embed',
            '.ad', '.advertisement', '.sidebar', '.related',
            '.comments', '.comment', '.social-share', '.share',
            '.navigation', '.nav', '.menu', '.footer', '.header',
            '.popup', '.modal', '.overlay', '.banner'
        ]
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={'User-Agent': self.user_agents[0]}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.session:
            await self.session.aclose()
    
    async def crawl_article(self, url: str) -> Dict[str, Any]:
        """
        爬取单篇新闻文章
        """
        if not self.session:
            raise RuntimeError("Crawler must be used as async context manager")
            
        try:
            # 检查URL是否已被处理过
            url_hash = self._generate_url_hash(url)
            if await self._is_duplicate_url(url, url_hash):
                return {"status": "duplicate", "url": url}
            
            # 获取网页内容
            html_content = await self._fetch_content(url)
            if not html_content:
                return {"status": "error", "url": url, "error": "Failed to fetch content"}
            
            # 解析内容
            article_data = await self._parse_article(url, html_content)
            article_data.update({
                "status": "success",
                "url": url,
                "url_hash": url_hash,
                "crawled_at": datetime.utcnow().isoformat()
            })
            
            return article_data
            
        except Exception as e:
            logging.error(f"Error crawling article {url}: {e}")
            return {"status": "error", "url": url, "error": str(e)}
    
    async def batch_crawl_articles(self, urls: List[str], max_concurrent: int = 5) -> List[Dict[str, Any]]:
        """
        批量爬取新闻文章
        """
        if not self.session:
            raise RuntimeError("Crawler must be used as async context manager")
        
        # 创建信号量限制并发数
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def crawl_with_semaphore(url: str) -> Dict[str, Any]:
            async with semaphore:
                result = await self.crawl_article(url)
                # 添加速率限制
                await asyncio.sleep(self.rate_limit_delay)
                return result
        
        # 并发爬取
        tasks = [crawl_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "status": "error",
                    "url": urls[i],
                    "error": str(result)
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def _fetch_content(self, url: str) -> Optional[str]:
        """
        获取网页原始HTML内容
        """
        for attempt in range(self.max_retries):
            try:
                # 随机选择User-Agent
                import random
                headers = {'User-Agent': random.choice(self.user_agents)}
                
                response = await self.session.get(url, headers=headers)
                response.raise_for_status()
                
                # 检测编码
                content = response.content
                if CHARDET_AVAILABLE:
                    encoding = chardet.detect(content)['encoding']
                    if encoding:
                        return content.decode(encoding, errors='ignore')
                
                return response.text
                    
            except Exception as e:
                logging.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                else:
                    logging.error(f"All attempts failed for {url}")
                    return None
        
        return None
    
    async def _parse_article(self, url: str, html_content: str) -> Dict[str, Any]:
        """
        解析文章内容
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        domain = urlparse(url).netloc.lower()
        
        # 移除不需要的元素
        self._clean_soup(soup)
        
        # 提取基本信息
        title = self._extract_title(soup)
        author = self._extract_author(soup)
        published_date = self._extract_published_date(soup)
        
        # 提取正文内容
        content = self._extract_content(soup, domain)
        
        # 使用readability作为备选方案
        if not content or len(content.strip()) < 100:
            content = self._extract_content_with_readability(html_content)
        
        # 生成摘要
        summary = self._generate_summary(content)
        
        # 提取关键词和实体
        keywords = self._extract_keywords(title, content)
        entities = self._extract_entities(title, content)
        
        # 计算内容质量分数
        quality_score = self._calculate_content_quality(title, content)
        
        return {
            "title": title,
            "content": content,
            "summary": summary,
            "author": author,
            "published_date": published_date,
            "keywords": keywords,
            "entities": entities,
            "content_quality": quality_score,
            "word_count": len(content) if content else 0,
            "domain": domain
        }
    
    def _clean_soup(self, soup: BeautifulSoup):
        """
        清理HTML，移除不需要的元素
        """
        # 移除注释
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # 移除指定的标签和类
        for selector in self.remove_selectors:
            for element in soup.select(selector):
                element.decompose()
        
        # 移除空的段落和div
        for tag in soup.find_all(['p', 'div']):
            if not tag.get_text(strip=True):
                tag.decompose()
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """
        提取文章标题
        """
        # 按优先级尝试不同的标题选择器
        title_selectors = [
            'h1.title', 'h1.article-title', 'h1.post-title',
            '.article-header h1', '.content-header h1',
            'h1', 'title'
        ]
        
        for selector in title_selectors:
            element = soup.select_one(selector)
            if element:
                title = element.get_text(strip=True)
                if title and len(title) > 5:  # 过滤太短的标题
                    return title
        
        return ""
    
    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """
        提取作者信息
        """
        author_selectors = [
            '.author', '.by-author', '.article-author',
            '[rel="author"]', '.byline', '.writer'
        ]
        
        for selector in author_selectors:
            element = soup.select_one(selector)
            if element:
                author = element.get_text(strip=True)
                if author and len(author) < 50:  # 过滤太长的文本
                    return author
        
        return None
    
    def _extract_published_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """
        提取发布时间
        """
        # 尝试从meta标签获取
        meta_selectors = [
            'meta[property="article:published_time"]',
            'meta[name="publishdate"]',
            'meta[name="date"]',
            'meta[property="og:updated_time"]'
        ]
        
        for selector in meta_selectors:
            element = soup.select_one(selector)
            if element:
                date_str = element.get('content', '')
                parsed_date = self._parse_date_string(date_str)
                if parsed_date:
                    return parsed_date
        
        # 尝试从页面内容获取
        date_selectors = [
            '.publish-time', '.article-date', '.post-date',
            '.date', '.time', '.timestamp'
        ]
        
        for selector in date_selectors:
            element = soup.select_one(selector)
            if element:
                date_str = element.get_text(strip=True)
                parsed_date = self._parse_date_string(date_str)
                if parsed_date:
                    return parsed_date
        
        return None
    
    def _extract_content(self, soup: BeautifulSoup, domain: str) -> str:
        """
        提取文章正文内容
        """
        # 根据域名选择特定的选择器
        domain_key = None
        for key in self.content_selectors:
            if key in domain:
                domain_key = key
                break
        
        # 构建选择器列表
        selectors_to_try = []
        if domain_key and domain_key in self.content_selectors:
            selectors_to_try.extend(self.content_selectors[domain_key])
        
        # 添加通用选择器
        for category in ['article', 'content', 'text']:
            selectors_to_try.extend(self.content_selectors[category])
        
        # 尝试每个选择器
        for selector in selectors_to_try:
            elements = soup.select(selector)
            if elements:
                # 取第一个匹配的元素
                content_element = elements[0]
                text = self._extract_text_from_element(content_element)
                if text and len(text.strip()) > 100:  # 内容长度阈值
                    return text
        
        # 如果都没找到，尝试提取body中的所有段落
        paragraphs = soup.find_all('p')
        if paragraphs:
            text = '\n\n'.join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
            if len(text.strip()) > 100:
                return text
        
        return ""
    
    def _extract_content_with_readability(self, html_content: str) -> str:
        """
        使用readability库提取内容（备选方案）
        """
        if not READABILITY_AVAILABLE:
            return ""
            
        try:
            doc = Document(html_content)
            content = doc.summary()
            soup = BeautifulSoup(content, 'html.parser')
            return self._extract_text_from_element(soup)
        except Exception as e:
            logging.warning(f"Readability extraction failed: {e}")
            return ""
    
    def _extract_text_from_element(self, element) -> str:
        """
        从HTML元素中提取纯文本
        """
        if not element:
            return ""
        
        # 移除脚本和样式
        for script in element(["script", "style"]):
            script.decompose()
        
        # 获取文本并清理
        text = element.get_text(separator='\n', strip=True)
        
        # 清理多余的空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return '\n\n'.join(lines)
    
    def _generate_summary(self, content: str, max_length: int = 200) -> str:
        """
        生成文章摘要
        """
        if not content:
            return ""
        
        # 简单的摘要生成：取前面的句子
        sentences = re.split(r'[。！？.!?]', content)
        summary = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 10:  # 过滤太短的句子
                if len(summary + sentence) < max_length:
                    summary += sentence + "。"
                else:
                    break
        
        return summary.strip()
    
    def _extract_keywords(self, title: str, content: str) -> List[str]:
        """
        提取关键词（简单实现）
        """
        # 合并标题和内容
        text = f"{title} {content}"
        
        # 简单的关键词提取：查找常见的财经术语
        financial_terms = [
            "股价", "涨幅", "跌幅", "成交量", "市值", "营收", "利润",
            "财报", "业绩", "增长", "下滑", "投资", "融资", "IPO",
            "重组", "并购", "分红", "股息", "估值", "PE", "PB"
        ]
        
        keywords = []
        for term in financial_terms:
            if term in text:
                keywords.append(term)
        
        return keywords[:10]  # 限制关键词数量
    
    def _extract_entities(self, title: str, content: str) -> List[str]:
        """
        提取命名实体（简单实现）
        """
        # 简单的实体提取：查找公司名称模式
        text = f"{title} {content}"
        entities = []
        
        # 查找股票代码模式
        stock_pattern = r'\b\d{6}(?:\.[A-Z]{2})?\b'
        stock_codes = re.findall(stock_pattern, text)
        entities.extend(stock_codes)
        
        # 查找公司名称模式
        company_pattern = r'[^，。！？\s]{2,10}(?:股份有限公司|有限公司|集团|控股|科技|传媒|医药|银行)'
        companies = re.findall(company_pattern, text)
        entities.extend(companies)
        
        return list(set(entities))[:20]  # 去重并限制数量
    
    def _calculate_content_quality(self, title: str, content: str) -> float:
        """
        计算内容质量分数
        """
        if not content:
            return 0.0
        
        score = 0.5  # 基础分数
        
        # 标题长度合理性
        if title and 10 <= len(title) <= 100:
            score += 0.1
        
        # 内容长度
        content_length = len(content)
        if content_length >= 500:
            score += 0.2
        elif content_length >= 200:
            score += 0.1
        
        # 段落结构
        paragraphs = content.split('\n\n')
        if len(paragraphs) >= 3:
            score += 0.1
        
        # 包含数字和百分比（财经新闻特征）
        if re.search(r'\d+%|\d+\.\d+', content):
            score += 0.1
        
        return min(score, 1.0)
    
    def _parse_date_string(self, date_str: str) -> Optional[datetime]:
        """
        解析日期字符串
        """
        if not date_str:
            return None
        
        # 常见日期格式
        date_patterns = [
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})',  # ISO format
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',  # SQL datetime
            r'(\d{4}-\d{2}-\d{2})',  # Date only
            r'(\d{4}年\d{1,2}月\d{1,2}日)',  # Chinese format
            r'(\d{1,2}/\d{1,2}/\d{4})',  # MM/dd/yyyy
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, date_str)
            if match:
                try:
                    date_part = match.group(1)
                    # 尝试不同的解析格式
                    formats = [
                        '%Y-%m-%dT%H:%M:%S',
                        '%Y-%m-%d %H:%M:%S',
                        '%Y-%m-%d',
                        '%m/%d/%Y'
                    ]
                    
                    for fmt in formats:
                        try:
                            return datetime.strptime(date_part, fmt)
                        except ValueError:
                            continue
                            
                except Exception:
                    continue
        
        return None
    
    def _generate_url_hash(self, url: str) -> str:
        """
        生成URL哈希值用于去重
        """
        # 标准化URL（移除查询参数中的追踪信息）
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        
        # 生成MD5哈希
        return hashlib.md5(clean_url.encode('utf-8')).hexdigest()
    
    async def _is_duplicate_url(self, url: str, url_hash: str) -> bool:
        """
        检查URL是否已被处理过
        """
        session = SessionLocal()
        try:
            from sqlalchemy import select
            existing = session.execute(
                select(NewsArticle).where(
                    (NewsArticle.url == url)
                )
            ).scalar_one_or_none()
            
            return existing is not None
            
        finally:
            session.close()