#!/usr/bin/env python3
"""
百度百科信息爬取脚本 - Baidu Baike Scraper

专门用于从百度百科(baike.baidu.com)提取企业/人物/概念信息的独立脚本
支持多种爬取方式：Playwright浏览器、requests库、Jina Reader API

主要功能:
- 使用 Playwright 真实浏览器绕过反爬虫
- 智能信息提取（结构化/非结构化）
- 多重备选方案（自动 fallback）
- 缓存机制，避免重复爬取
- 详细的进度和错误日志

使用示例:
    python baike_scraper.py "阿里巴巴" --output json
    python baike_scraper.py "腾讯集团" --use-cache --timeout 60
"""
import json
import sys
import re
import time
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import asyncio
import argparse
import logging
from functools import lru_cache, partial

# 新增：导入traceback模块
import traceback

# 第三方库
import httpx
from bs4 import BeautifulSoup

# 可选：Playwright 浏览器支持
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️  Playwright 未安装。请运行: pip install playwright && python -m playwright install chromium")

# 可选：LLM 支持
try:
    from ..news.qwen_local_llm import get_qwen_client
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    print("⚠️  Qwen3LocalLLMClient 未找到，LLM 相关功能将不可用。")


# ==================== 配置 ====================

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 缓存目录
CACHE_DIR = Path(__file__).parent / ".cache" / "baike"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


# ==================== 数据类 ====================

@dataclass
class BaikeInfo:
    """百度百科信息数据类"""
    name: str                      # 名称/标题
    url: str                       # 百度百科URL
    summary: Optional[str] = None  # 摘要/简介
    categories: List[str] = None   # 分类标签
    basic_info: Dict[str, str] = None  # 基本信息框（如成立日期、总部等）
    content: str = ""              # 完整内容
    html_content: str = ""         # 原始HTML（可选）
    fetch_method: str = "unknown"  # 爬取方法（playwright/requests/jina）
    timestamp: str = ""            # 爬取时间
    success: bool = False          # 是否成功
    error_message: str = ""        # 错误信息
    # 企业profile数据字段
    profile: Optional[Dict[str, Any]] = None  # 企业profile数据
    
    def __post_init__(self):
        if self.categories is None:
            self.categories = []
        if self.basic_info is None:
            self.basic_info = {}
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if self.profile is None:
            self.profile = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ==================== 爬取方法 ====================

class BaikeScraper:
    """百度百科爬取器"""
    
    def __init__(self, use_cache: bool = True, timeout: int = 30):
        """
        初始化爬取器
        
        Args:
            use_cache: 是否使用缓存
            timeout: 请求超时秒数
        """
        self.use_cache = use_cache
        self.timeout = timeout
        self.session = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENTS[0]
            }
        )
        self.llm_processor = None
        if LLM_AVAILABLE:
            try:
                self.llm_processor = get_qwen_client()
            except Exception as e:
                logger.warning(f"⚠️  LLM处理器初始化失败: {e}")
                self.llm_processor = None
    
    def _get_cache_path(self, keyword: str) -> Path:
        """获取缓存文件路径"""
        hash_key = hashlib.md5(keyword.encode()).hexdigest()
        return CACHE_DIR / f"{hash_key}.json"
    
    def _load_cache(self, keyword: str) -> Optional[BaikeInfo]:
        """从缓存加载数据"""
        if not self.use_cache:
            return None
        
        cache_file = self._get_cache_path(keyword)
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"✅ 从缓存加载: {keyword}")
                return BaikeInfo(**data)
            except Exception as e:
                logger.warning(f"⚠️  缓存加载失败: {e}")
        return None
    
    def _save_cache(self, keyword: str, info: BaikeInfo):
        """保存到缓存"""
        if not self.use_cache:
            return
        
        cache_file = self._get_cache_path(keyword)
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(info.to_dict(), f, ensure_ascii=False, indent=2)
            logger.debug(f"💾 已保存到缓存: {cache_file}")
        except Exception as e:
            logger.warning(f"⚠️  缓存保存失败: {e}")
    
    def _search_baike_url(self, keyword: str) -> Optional[str]:
        """搜索百度百科URL"""
        try:
            logger.info(f"🔍 搜索百度百科: {keyword}")
            
            # 尝试直接构造URL（最快）
            baike_urls = [
                f"https://baike.baidu.com/item/{keyword}",
                f"https://baike.baidu.com/search/word?word={keyword}",
            ]
            
            for url in baike_urls:
                response = self.session.get(url)
                if response.status_code == 200 and "百度百科" in response.text:
                    logger.info(f"✅ 找到百度百科页面: {url}")
                    return url
            
            return None
        except Exception as e:
            logger.error(f"❌ 搜索百度百科失败: {e}")
            return None
    
    def _fetch_with_requests(self, url: str) -> Tuple[Optional[str], str]:
        """
        使用 requests 库爬取（最快但可能被反爬）
        
        Returns:
            (html_content, status_message)
        """
        try:
            logger.info(f"📡 使用 requests 爬取: {url}")
            
            # 随机 User-Agent
            import random
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Referer": "https://www.baidu.com/",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
            
            response = self.session.get(url, headers=headers)
            
            if response.status_code == 200:
                logger.info(f"✅ 请求成功 (requests): {response.status_code}")
                return response.text, "requests"
            elif response.status_code == 403:
                logger.warning(f"⚠️  被反爬虫拦截 (403 Forbidden)")
                return None, "requests_403"
            else:
                logger.warning(f"⚠️  请求失败: {response.status_code}")
                return None, f"requests_{response.status_code}"
        
        except Exception as e:
            logger.error(f"❌ requests 爬取失败: {e}")
            return None, f"requests_error: {str(e)}"
    
    def _fetch_with_playwright(self, url: str) -> Tuple[Optional[str], str]:
        """
        使用 Playwright 真实浏览器爬取（绕过反爬虫）
        
        Returns:
            (html_content, status_message)
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("⚠️  Playwright 未安装，跳过浏览器爬取")
            return None, "playwright_not_available"
        
        try:
            logger.info(f"🌐 使用 Playwright 浏览器爬取: {url}")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent=USER_AGENTS[0],
                    viewport={"width": 1280, "height": 720}
                )
                
                try:
                    # 访问页面，等待网络空闲
                    page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
                    
                    # ⭐ 关键：等待实际内容加载（百度百科使用 JS 渲染）
                    # 方法1：等待 h1 标题出现
                    try:
                        page.wait_for_selector("h1", timeout=10000)
                    except:
                        logger.warning("⚠️  h1 选择器未找到")
                    
                    # 方法2：等待任何可能包含内容的元素
                    try:
                        # 等待多种可能的内容选择器
                        content_selectors = [
                            "div.para",
                            "div[class*='lemma']",
                            "div[class*='content']",
                            "div.knowledge-box-container",
                            "div.J-knowledge-*",
                        ]
                        for selector in content_selectors:
                            try:
                                page.wait_for_selector(selector, timeout=5000)
                                break
                            except:
                                pass
                    except:
                        pass
                    
                    # 方法3：额外等待内容渲染和 JS 执行
                    page.wait_for_timeout(2000)
                    
                    # 获取页面内容
                    html_content = page.content()
                    
                    logger.info(f"✅ Playwright 爬取成功 ({len(html_content)} 字节)")
                    return html_content, "playwright"
                
                except Exception as e:
                    logger.error(f"❌ Playwright 爬取失败: {e}")
                    return None, f"playwright_error: {str(e)}"
                
                finally:
                    page.close()
                    browser.close()
        
        except Exception as e:
            logger.error(f"❌ Playwright 初始化失败: {e}")
            return None, f"playwright_init_error: {str(e)}"
    
    def _fetch_with_jina(self, url: str) -> Tuple[Optional[str], str]:
        """
        使用 Jina Reader API 爬取
        
        Returns:
            (html_content, status_message)
        """
        try:
            logger.info(f"🔗 使用 Jina Reader API 爬取: {url}")
            
            jina_url = f"https://r.jina.ai/{url}"
            response = self.session.get(jina_url)
            
            if response.status_code == 200:
                logger.info(f"✅ Jina Reader 爬取成功")
                return response.text, "jina"
            else:
                logger.warning(f"⚠️  Jina Reader 请求失败: {response.status_code}")
                return None, f"jina_{response.status_code}"
        
        except Exception as e:
            logger.error(f"❌ Jina Reader 爬取失败: {e}")
            return None, f"jina_error: {str(e)}"
    
    async def _extract_info_from_html(self, html: str, url: str) -> BaikeInfo:
        """从HTML提取信息"""
        logger.info("📖 解析HTML提取信息...")
        
        try:
            import re
            import json as json_lib
            
            # ⭐ 优先尝试提取 window.PAGE_DATA JSON 数据
            logger.info("🔍 尝试从 PAGE_DATA 提取...")
            page_data = self._extract_page_data_json(html)
            
            if page_data:
                logger.info("✅ 成功提取 PAGE_DATA JSON")
                
                # 从 PAGE_DATA 提取关键信息
                title = page_data.get('lemmaTitle', 'Unknown')
                summary = page_data.get('lemmaDesc', '')[:300]
                
                # 尝试从 extData 中提取分类和基本信息
                basic_info = {}
                categories = []
                
                if 'extData' in page_data:
                    ext_data = page_data['extData']
                    
                    # 分类通常在 classify 中
                    if 'classify' in ext_data and isinstance(ext_data['classify'], list):
                        for classify_item in ext_data['classify']:
                            if isinstance(classify_item, dict) and 'leafName' in classify_item:
                                categories.append(classify_item['leafName'])
                
                # 尝试从 card 中提取基本信息（结构化数据）
                if 'card' in page_data and isinstance(page_data['card'], dict):
                    card = page_data['card']
                    
                    # 合并 left 和 right 的字段
                    for field_list in [card.get('left', []), card.get('right', [])]:
                        if isinstance(field_list, list):
                            for field in field_list:
                                if isinstance(field, dict):
                                    title_key = field.get('title', '')
                                    # 获取 data 字段中的值
                                    data_val = field.get('data', [])
                                    if isinstance(data_val, list) and data_val:
                                        # 尝试提取简单的文本值
                                        text_content = self._extract_simple_text_from_card(data_val)
                                        
                                        if text_content and title_key and len(title_key) < 50:
                                            basic_info[title_key] = text_content[:200]
                
                logger.info(f"🔍 从 PAGE_DATA 提取: 标题={title}, 摘要长度={len(summary)}, 分类={len(categories)}, 基本信息={len(basic_info)}")
                
                # 提取企业profile数据
                profile = await self.get_company_profile_from_html(html)
                
                return BaikeInfo(
                    name=title,
                    url=url,
                    summary=summary,
                    categories=categories,
                    basic_info=basic_info,
                    content="",  # PAGE_DATA 中通常不包含完整内容
                    profile=profile,
                    success=True
                )
            
            # 如果 PAGE_DATA 提取失败，回退到 BeautifulSoup
            logger.warning("⚠️  PAGE_DATA 提取失败，使用 BeautifulSoup 回退")
            soup = BeautifulSoup(html, 'html.parser')
            
            # 提取页面标题 - 多种可能的选择器
            title = "Unknown"
            title_elem = soup.find('h1', class_='title')
            if not title_elem:
                title_elem = soup.find('h1')
            if not title_elem:
                title_elem = soup.find('title')
            if title_elem:
                title = title_elem.get_text(strip=True)
                # 去掉尾部的"_百度百科"
                if '_百度百科' in title:
                    title = title.replace('_百度百科', '').strip()
            
            logger.info(f"🔍 提取标题: {title}")
            
            # 提取摘要/简介
            summary = ""
            # 方法1：查找摘要容器
            summary_box = soup.find('div', class_='summary-content')
            if summary_box:
                summary = summary_box.get_text(strip=True)[:300]
            
            # 方法2：第一段落
            if not summary:
                first_para = soup.find('div', class_='para')
                if first_para:
                    summary = first_para.get_text(strip=True)[:300]
            
            # 方法3：从 title 属性中提取
            if not summary and '<title>' in html:
                title_match = re.search(r'<title>(.*?)</title>', html)
                if title_match:
                    summary = title_match.group(1)[:300]
            
            logger.info(f"🔍 提取摘要: {summary[:60] if summary else '(无)'}")
            
            # 提取基本信息框
            basic_info = {}
            
            # 方法1：.basicInfo 结构
            basic_info_box = soup.find('div', class_='basicInfo')
            if basic_info_box:
                rows = basic_info_box.find_all('dl')
                for row in rows:
                    dt = row.find('dt')
                    dd = row.find('dd')
                    if dt and dd:
                        key = dt.get_text(strip=True)
                        value = dd.get_text(strip=True)[:100]
                        if key and value:
                            basic_info[key] = value
            
            # 方法2：表格结构
            if not basic_info:
                info_tables = soup.find_all('table', class_=['infobox', 'wikitable'])
                for table in info_tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            key = cells[0].get_text(strip=True)
                            value = cells[1].get_text(strip=True)[:100]
                            if key and value and len(key) < 50:
                                basic_info[key] = value
            
            logger.info(f"🔍 提取基本信息: {len(basic_info)} 项")
            
            # 提取分类标签
            categories = []
            category_box = soup.find('div', class_='cat-tag')
            if category_box:
                for tag in category_box.find_all('a'):
                    cat = tag.get_text(strip=True)
                    if cat and len(cat) < 30:
                        categories.append(cat)
            
            logger.info(f"🔍 提取分类: {len(categories)} 项")
            
            # 提取主体内容 - 所有段落
            content_parts = []
            
            # 查找主要内容容器
            main_content = soup.find('div', id='mw-content-text') or soup.find('div', class_='mw-parser-output') or soup.find('div', id='content')
            if not main_content:
                main_content = soup.find('div', class_='para-title')
            
            if main_content:
                # 在主要内容区域中查找段落
                search_area = main_content
            else:
                # 使用整个 body
                search_area = soup.body if soup.body else soup
            
            # 查找所有段落 div
            for para in search_area.find_all('div', class_='para', limit=50):
                text = para.get_text(strip=True)
                # 过滤掉太短的、重复的、和UI文本
                if (text and len(text) > 50 and 
                    text not in content_parts and
                    '播报' not in text and 
                    '编辑' not in text and
                    '讨论' not in text and
                    '分类' not in text and
                    'javascript' not in text.lower()):
                    content_parts.append(text)
            
            content = "\n".join(content_parts[:20])  # 取前20段
            
            # 提取企业profile数据
            profile = await self.get_company_profile_from_html(html)
            
            logger.info(f"✅ 信息提取成功: 标题={title}, 基本信息={len(basic_info)}项, 分类={len(categories)}项, 内容段落={len(content_parts)}段")
            
            return BaikeInfo(
                name=title,
                url=url,
                summary=summary,
                categories=categories,
                basic_info=basic_info,
                content=content,
                profile=profile,
                success=True
            )
        
        except Exception as e:
            logger.error(f"❌ HTML解析失败: {e}")
            traceback.print_exc()
            return BaikeInfo(
                name="Unknown",
                url=url,
                success=False,
                error_message=f"解析失败: {str(e)}"
            )
    
    def _extract_page_data_json(self, html: str) -> Optional[dict]:
        """从 HTML 中提取 window.PAGE_DATA JSON 数据"""
        try:
            import re
            import json as json_lib
            
            # 查找 window.PAGE_DATA = {...}
            start_pos = html.find('window.PAGE_DATA= {')
            if start_pos == -1:
                start_pos = html.find('window.PAGE_DATA = {')
            
            if start_pos == -1:
                logger.debug("未找到 PAGE_DATA")
                return None
            
            # 从 { 开始
            start_pos = html.find('{', start_pos)
            
            # 找到匹配的 }
            brace_count = 0
            end_pos = -1
            for i in range(start_pos, len(html)):
                if html[i] == '{':
                    brace_count += 1
                elif html[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break
            
            if end_pos == -1:
                logger.debug("未找到 JSON 结束")
                return None
            
            json_str = html[start_pos:end_pos]
            data = json_lib.loads(json_str)
            logger.debug(f"✅ 成功解析 PAGE_DATA JSON: {len(json_str)} 字节")
            return data
        
        except Exception as e:
            logger.debug(f"PAGE_DATA 提取失败: {e}")
            return None
    
    def _extract_simple_text_from_card(self, data_list: list) -> str:
        """从百度百科 card 数据中提取简单文本"""
        if not isinstance(data_list, list) or not data_list:
            return ""
        
        texts = []
        for item in data_list:
            if isinstance(item, dict):
                # 优先提取 'text' 字段
                if 'text' in item:
                    text = item['text']
                    if isinstance(text, str):
                        texts.append(text)
                    # 如果 text 是列表，递归处理
                    elif isinstance(text, list):
                        sub_text = self._extract_simple_text_from_card(text)
                        if sub_text:
                            texts.append(sub_text)
                
                # 如果是 innerlink（链接），提取链接文本
                elif item.get('tag') == 'innerlink' and 'text' in item:
                    texts.append(item['text'])
            
            elif isinstance(item, str):
                texts.append(item)
        
        # 连接所有文本
        result = "".join(texts).strip()
        # 清理多余空格
        result = " ".join(result.split())
        return result
    
    def _extract_company_profile(self, html: str) -> Optional[Dict[str, Any]]:
        """
        从百度百科HTML中提取企业profile数据
        
        返回包含以下字段的字典：
        - industry: 行业
        - sector: 细分行业
        - founded_date: 成立日期
        - business_scope: 主营业务
        - company_size: 公司规模
        - employees: 员工数
        - headquarters: 总部地址
        - description: 企业描述
        - registered_capital: 注册资本
        - confidence: 置信度
        """
        try:
            logger.info("🔍 提取企业profile数据...")
            
            profile = {
                "confidence": 0.85,
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
                "registered_capital": None,
            }
            
            # 方法1：从 PAGE_DATA JSON 提取
            page_data = self._extract_page_data_json(html)
            if page_data:
                # 提取描述
                
                if 'lemmaDesc' in page_data and page_data['lemmaDesc']:
                    profile["description"] = page_data['lemmaDesc'][:300]
                
                # 从 card 中提取基本信息
                if 'card' in page_data and isinstance(page_data['card'], dict):
                    card = page_data['card']
                    
                    # 构建字段名映射
                    field_mappings = {
                        '行业': 'industry',
                        '产业': 'industry',
                        '行业类别': 'sector',
                        '成立时间': 'founded_date',
                        '成立日期': 'founded_date',
                        '创立时间': 'founded_date',
                        '经营范围': 'business_scope',
                        '主营业务': 'business_scope',
                        '业务范围': 'business_scope',
                        '员工数': 'employees',
                        '员工人数': 'employees',
                        '总部位置': 'headquarters',
                        '总部地点': 'headquarters',
                        '注册资本': 'registered_capital',
                        '公司规模': 'company_size',
                        '年营业额': 'company_size',
                    }
                    
                    # 处理 left 和 right 字段
                    for field_list in [card.get('left', []), card.get('right', [])]:
                        if isinstance(field_list, list):
                            for field in field_list:
                                if isinstance(field, dict):
                                    title_key = field.get('title', '')
                                    data_val = field.get('data', [])
                                    
                                    # 查找字段映射
                                    for key_pattern, profile_key in field_mappings.items():
                                        if key_pattern in title_key:
                                            # 提取数据值
                                            if isinstance(data_val, list) and data_val:
                                                text_content = self._extract_simple_text_from_card(data_val)
                                                if text_content and not profile[profile_key]:
                                                    profile[profile_key] = text_content[:200]
                                            break

                return profile
            
            # 方法2：使用BeautifulSoup回退
            logger.warning("⚠️  PAGE_DATA不可用，使用BeautifulSoup提取")
            soup = BeautifulSoup(html, 'html.parser')
            
            # 提取描述
            intro_elem = soup.select_one('div[class*="summary"], div[class*="Summary"]')
            
            
            if intro_elem:
                profile["description"] = intro_elem.get_text(strip=True)[:300]
            else:
                # 尝试第一段落
                first_para = soup.find('div', class_='para')
                if first_para:
                    profile["description"] = first_para.get_text(strip=True)[:300]
            
            # 提取基本信息框
            info_container = (
                soup.find('div', class_=lambda x: x and ('itemWrapper' in str(x) or 'basicInfo' in str(x)))
                or soup.find('dl', class_=lambda x: x and ('basicInfo' in str(x) or 'basic-info' in str(x)))
                or soup.find('dl', class_=lambda x: x and 'lemmaWgt-lemmaBasicInfo' in str(x))
                or soup.find('dl')
            )
            
            if info_container:
                dts = info_container.find_all("dt")
                for dt in dts:
                    dd = dt.find_next_sibling("dd")
                    if not dd:
                        continue
                    
                    key = dt.get_text(strip=True)
                    value = dd.get_text(strip=True)
                    
                    if not value or len(value) > 200:
                        continue
                    
                    # 映射字段
                    if "成立" in key or "创立" in key:
                        profile["founded_date"] = value
                    elif "行业" in key:
                        profile["industry"] = value
                    elif "经营范围" in key or "主营业务" in key or "业务范围" in key:
                        profile["business_scope"] = value
                    elif "总部" in key or "办公地址" in key:
                        profile["headquarters"] = value
                    elif "员工" in key or "人数" in key:
                        profile["employees"] = value
                    elif "注册资本" in key or "资本" in key:
                        profile["registered_capital"] = value
                    elif "年营业额" in key or "营收" in key:
                        profile["company_size"] = value
            
            logger.info(f"✅ 从BeautifulSoup提取profile: {[f'{k}={v}' for k,v in profile.items() if v and k != 'confidence']}")
            return profile
        
        except Exception as e:
            logger.error(f"❌ 企业profile提取失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_web_text_content(self, html: str) -> Optional[str]:
        """从HTML中提取干净的文本内容，并过滤掉百科框架的无关文本"""
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # 定义要排除的文本和CSS选择器
            excluded_selectors = [
                "script", "style", "nav", "footer", "header", 
                ".top-nav", ".footer-wrapper", ".copyright", "div[class*='side-content']",
                "div[class*='before-content']", "div[class*='after-content']",
                "div[id*='search']", "div[class*='search-box']",
                "div.user-info", "div.task-box", "div.help",
                "div[class*='bottom-tool-bar']"
            ]
            
            # 移除脚本、样式、导航、页脚等无关内容的DOM节点
            for selector in excluded_selectors:
                for element in soup.select(selector):
                    element.decompose()
            
            # 获取主要内容区域
            main_content = soup.find('main') or soup.find('div', class_='main-content') or soup.find('body')
            if not main_content:
                return None
                
            # 提取所有文本
            text = main_content.get_text(separator='\n', strip=True)
            
            # 定义要过滤掉的固定文本短语
            excluded_phrases = {
                "新闻", "贴吧", "知道", "网盘", "图片", "视频", "地图", "文库", "资讯", "采购",
                "百科", "百度首页", "登录", "注册", "进入词条", "全站搜索", "帮助", "首页",
                "秒懂百科", "特色百科", "知识专题", "加入百科", "百科团队", "权威合作", "个人中心",
                "播报", "讨论", "上传视频", "展开", "词条申诉", "投诉侵权信息", "封禁查询与解封",
                "使用百度前必读", "百科协议", "隐私政策", "百度百科合作平台"
            }

            # 清理和过滤
            lines = []
            for line in text.splitlines():
                stripped_line = line.strip()
                
                # 过滤掉完全匹配的短语和一些模式
                if not stripped_line:
                    continue
                if stripped_line in excluded_phrases:
                    continue
                if stripped_line.startswith('©') and 'Baidu' in stripped_line:
                    continue
                if '京ICP证' in stripped_line or '京公网安备' in stripped_line:
                    continue
                if '个同名词条' in stripped_line:
                    continue
                
                lines.append(stripped_line)

            # 重新组合文本
            clean_text = '\n'.join(lines)
            
            return clean_text
            
        except Exception as e:
            logger.error(f"❌ 提取网页文本内容失败: {e}")
            return None

    async def _extract_description_with_llm(self, text_content: str, company_name: str) -> Optional[str]:
        """使用LLM从文本内容中提取公司描述"""
        if not self.llm_processor or not self.llm_processor.enabled:
            logger.warning("⚠️ LLM处理器不可用或未启用，跳过描述提取")
            return None
        
        if not text_content:
            return None

        system_prompt = "你是一个专业的商业分析师，你的任务是根据提供的网页文本，为指定公司生成一段精确、简洁、专业的中文描述。描述应重点突出公司的主营业务、核心产品和市场地位。"
        
        prompt = f"""
        请根据以下关于“{company_name}”的网页内容，生成一段不超过150字的中文公司描述。

        网页内容:
        ---
        {text_content[:1500]}
        ---

        要求:
        1.  内容必须完全基于提供的文本，不得引入外部信息。
        2.  描述要客观、中立，避免使用宣传性或主观性词汇。
        3.  重点概括公司的核心业务和价值。
        4.  如果文本内容不足以生成有意义的描述，请返回空字符串。
        5.  直接返回描述内容，不要包含任何额外的前缀或解释。
        """
        
        try:
            logger.info(f"🤖 使用 LLM 为“{company_name}”生成描述...")
            
            # 使用 await 调用异步方法，而不是 asyncio.run()
            description = await self.llm_processor.generate(
                prompt=prompt,
                system_prompt=system_prompt
            )
            
            if description:
                logger.info(f"✅ LLM 生成描述成功 (长度: {len(description)})")
                # 把<think> </think> 标签和其标签之间的内容去掉
                description = re.sub(r'<think>.*?</think>', '', description, flags=re.DOTALL)


                return description.strip()
            else:
                logger.warning("⚠️ LLM未能生成描述")
                return None
        except Exception as e:
            logger.error(f"❌ LLM描述生成失败: {e}")
            traceback.print_exc()
            return None

    async def scrape(self, keyword: str, method: str = "auto") -> BaikeInfo:
        """
        爬取百度百科信息 (异步版本)
        
        Args:
            keyword: 搜索关键词（如"阿里巴巴"）
            method: 爬取方法 ("auto"/"requests"/"playwright"/"jina")
        
        Returns:
            BaikeInfo 对象
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"开始爬取: {keyword}")
        logger.info(f"{'='*60}")
        
        # 检查缓存
        cached = self._load_cache(keyword)
        if cached:
            cached.fetch_method = f"{cached.fetch_method} (cached)"
            return cached
        
        # 搜索百度百科URL
        baike_url = self._search_baike_url(keyword)
        if not baike_url:
            logger.error(f"❌ 未找到百度百科页面: {keyword}")
            return BaikeInfo(
                name=keyword,
                url="",
                success=False,
                error_message="未找到百度百科页面"
            )
        
        # 根据方法选择爬取 (run sync code in executor)
        loop = asyncio.get_running_loop()
        html_content = None
        fetch_method = "unknown"
        
        if method == "auto" or method == "playwright":
            html_content, fetch_method = await loop.run_in_executor(
                None, partial(self._fetch_with_playwright, baike_url)
            )
            if not html_content and method == "auto":
                logger.info("💡 Playwright 失败，尝试 requests...")
                html_content, fetch_method = await loop.run_in_executor(
                    None, partial(self._fetch_with_requests, baike_url)
                )
        
        elif method == "requests":
            html_content, fetch_method = await loop.run_in_executor(
                None, partial(self._fetch_with_requests, baike_url)
            )
        
        elif method == "jina":
             html_content, fetch_method = await loop.run_in_executor(
                None, partial(self._fetch_with_jina, baike_url)
            )

        if not html_content:
            logger.error(f"❌ 所有爬取方法都失败")
            return BaikeInfo(
                name=keyword,
                url=baike_url,
                success=False,
                error_message=f"爬取失败: {fetch_method}",
                fetch_method=fetch_method
            )
        
        # 提取信息
        info = await self._extract_info_from_html(html_content, baike_url)
        info.fetch_method = fetch_method
        
        # 保存缓存
        self._save_cache(keyword, info)
        
        logger.info(f"✅ 爬取完成: {keyword}")
        logger.info(f"{'='*60}\n")
        
        return info
    
    async def get_company_profile_from_html(self, html_content: str, keyword: str = "") -> Optional[Dict[str, Any]]:
        """
        从HTML内容中异步获取企业profile数据
        """
        try:
            # 提取profile数据 (同步部分)
            profile = self._extract_company_profile(html_content)
            
            # 如果从结构化数据中未提取到描述，则尝试用LLM生成
            text_content = self._extract_web_text_content(html_content)
            if text_content:
                # 使用LLM从文本内容生成描述
                llm_description = await self._extract_description_with_llm(text_content, keyword)
                if llm_description:
                    profile['description'] = llm_description

            return profile
        except Exception as e:
            logger.error(f"❌ get_company_profile_from_html 失败: {e}")
            traceback.print_exc()
            return None

    async def get_company_profile(self, keyword: str) -> Optional[Dict[str, Any]]:
        """
        获取企业profile数据 (异步版本)
        
        这是一个便利方法，用于直接获取企业profile信息
        
        Args:
            keyword: 企业名称（如"阿里巴巴"）
        
        Returns:
            包含企业profile数据的字典，或None如果获取失败
        """
        try:
            logger.info(f"🏢 获取企业profile: {keyword}")
            
            # 搜索百度百科URL
            baike_url = self._search_baike_url(keyword)
            if not baike_url:
                logger.warning(f"⚠️  未找到百度百科页面")
                return None
            
            # 获取HTML
            loop = asyncio.get_running_loop()
            html_content, _ = await loop.run_in_executor(
                None, partial(self._fetch_with_playwright, baike_url)
            )

            if not html_content:
                html_content, _ = await loop.run_in_executor(
                    None, partial(self._fetch_with_requests, baike_url)
                )

            if not html_content:
                logger.warning(f"⚠️  无法获取HTML内容")
                return None

            
            # 提取profile数据
            profile = await self.get_company_profile_from_html(html_content, keyword)
            if profile:
                logger.info(f"✅ 成功获取profile数据")
            else:
                logger.warning(f"⚠️  profile数据提取失败")
            
            return profile
        
        except Exception as e:
            logger.error(f"❌ 获取profile失败: {e}")
            traceback.print_exc()
            return None


# ==================== 命令行接口 ====================

def print_info(info: BaikeInfo, output_format: str = "text"):
    """打印信息"""
    if output_format == "json":
        print(info.to_json())
    
    elif output_format == "text":
        print(f"\n📋 百度百科信息 - {info.name}")
        print(f"{'='*60}")
        print(f"URL: {info.url}")
        print(f"爬取方法: {info.fetch_method}")
        print(f"爬取时间: {info.timestamp}")
        print(f"状态: {'✅ 成功' if info.success else '❌ 失败'}")
        
        if not info.success:
            print(f"错误: {info.error_message}")
            return
        
        if info.summary:
            print(f"\n📝 摘要:\n{info.summary}")
        
        if info.basic_info:
            print(f"\n📊 基本信息:")
            for key, value in list(info.basic_info.items())[:10]:
                print(f"  • {key}: {value}")
        
        if info.categories:
            print(f"\n🏷️  分类: {', '.join(info.categories[:5])}")
        
        # 显示企业profile数据
        if info.profile and any(v for k, v in info.profile.items() if k != 'confidence' and v):
            print(f"\n🏢 企业Profile信息:")
            for key, value in info.profile.items():
                if value and key != 'confidence':
                    print(f"  • {key}: {value}")
        
        if info.content:
            content_preview = info.content[:300] + "..." if len(info.content) > 300 else info.content
            print(f"\n📄 内容:\n{content_preview}")
        
        print(f"\n{'='*60}")


if __name__ == "__main__":
    try:
        def main():
            """主函数"""
            parser = argparse.ArgumentParser(
                description="百度百科信息爬取脚本",
                formatter_class=argparse.RawDescriptionHelpFormatter,
                epilog="""
示例:
  python baike_scraper.py "阿里巴巴"                    # 默认自动选择方法
  python baike_scraper.py "腾讯集团" --method playwright  # 使用浏览器
  python baike_scraper.py "华为" --output json          # 输出为JSON
  python baike_scraper.py "百度" --no-cache             # 不使用缓存
            """
            )
            
            parser.add_argument("keyword", help="搜索关键词（如'阿里巴巴'）")
            parser.add_argument("--method", choices=["auto", "requests", "playwright", "jina"],
                               default="auto", help="爬取方法 (默认: auto)")
            parser.add_argument("--output", choices=["text", "json"],
                               default="text", help="输出格式 (默认: text)")
            parser.add_argument("--no-cache", action="store_true", help="不使用缓存")
            parser.add_argument("--timeout", type=int, default=30, help="请求超时秒数 (默认: 30)")
            parser.add_argument("--verbose", "-v", action="store_true", help="详细日志输出")
            
            args = parser.parse_args()
            
            # 设置日志级别
            if args.verbose:
                logging.getLogger().setLevel(logging.DEBUG)
            
            # 创建爬取器
            scraper = BaikeScraper(
                use_cache=not args.no_cache,
                timeout=args.timeout
            )
            
            # 爬取信息 (run the async scrape method)
            info = asyncio.run(scraper.scrape(args.keyword, method=args.method))
            
            # 打印结果
            print_info(info, output_format=args.output)
            
            return 0
        
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n⏹️  程序被中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ 程序错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
