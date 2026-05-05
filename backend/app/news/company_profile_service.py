"""
企业Profile搜索服务 - CompanyProfileSearchService

专门用于搜索和提取企业基本信息（而非新闻）
支持多个信源：维基百科、百度百科、天眼查、企查查、金融网站等

主要特性：
- 企业名称、简称、成立日期等基本信息提取
- 行业、业务范围、主营产品识别
- 公司规模、员工数、注册资本等财务基本信息
- 高管团队、股东信息（如可得）
- 多信源信息聚合与去重
"""

import asyncio
import json
import os
import re
import random
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urljoin, urlparse, urlencode
from concurrent.futures import ThreadPoolExecutor

import httpx
from bs4 import BeautifulSoup

# ==== 行业分类支持相关基础类实现（内嵌，保持单文件，不新增依赖）====
class _TaxonomyRegistry:
    """行业分类注册中心：
    - 加载标准行业/板块 taxonomy（可从数据库或本地缓存）
    - 支持同义词 / 别名 / 正则 / 关键词 -> 规范行业映射
    数据结构示例 (self._taxonomy):
    {
        '信息技术': {
            'code': 'IT',
            'sector': 'TMT',
            'aliases': ['信息技术服务','IT服务','科技','技术','互联网技术'],
            'keywords': ['软件','云计算','SaaS','平台','AI','人工智能','数据中心'],
        },
        '金融': {
            'code': 'FIN', 'sector': '金融', 'aliases': ['金融服务','金融业','金融机构'], 'keywords': ['银行','保险','证券','基金','资产管理']
        },
        ...
    }
    """
    def __init__(self, min_len: int = 2):
        self._loaded = False
        self._taxonomy: Dict[str, Dict[str, Any]] = {}
        self._alias_to_canonical: Dict[str, str] = {}
        self._keyword_index: Dict[str, set] = {}
        self._min_len = min_len

    def load(self):
        if self._loaded:
            return
        # TODO: 未来可替换为数据库加载逻辑 (e.g. Mongo / Postgres)。当前内嵌最小集。
        base = [
            {
                'name': '信息技术', 'code': 'IT', 'sector': 'TMT',
                'aliases': ['信息技术服务','IT服务','科技','技术','互联网技术','软件服务'],
                'keywords': ['软件','云计算','SaaS','平台','AI','人工智能','数据中心','芯片','半导体','操作系统']
            },
            {
                'name': '金融', 'code': 'FIN', 'sector': '金融',
                'aliases': ['金融服务','金融业','金融机构'],
                'keywords': ['银行','保险','证券','基金','资产管理','理财','信贷','支付','清算']
            },
            {
                'name': '制造业', 'code': 'MFG', 'sector': '制造',
                'aliases': ['制造','制造行业','工业制造'],
                'keywords': ['生产','工厂','设备','加工','零部件','制造基地']
            },
            {
                'name': '互联网', 'code': 'INET', 'sector': 'TMT',
                'aliases': ['互联网公司','互联网服务','在线服务','电商','电子商务'],
                'keywords': ['平台','社交','搜索','广告','电商','在线','门户','社区']
            },
            {
                'name': '通信', 'code': 'TEL', 'sector': '通信',
                'aliases': ['通讯','通信服务','运营商','通信运营'],
                'keywords': ['网络','运营商','5G','通信设备','信号','基站']
            },
            {
                'name': '能源', 'code': 'ENE', 'sector': '能源',
                'aliases': ['能源产业','能源行业'],
                'keywords': ['石油','天然气','电力','新能源','光伏','风电','储能']
            },
            {
                'name': '医疗健康', 'code': 'HC', 'sector': '医疗',
                'aliases': ['医疗','健康','大健康','医药','生物医药'],
                'keywords': ['医院','药品','诊疗','医疗器械','生物','疫苗']
            },
            {
                'name': '教育', 'code': 'EDU', 'sector': '教育',
                'aliases': ['教育培训','培训','在线教育'],
                'keywords': ['学校','培训','课程','学习','K12','职业教育']
            },
            {
                'name': '房地产', 'code': 'RE', 'sector': '房地产',
                'aliases': ['房产','地产开发','房地产开发'],
                'keywords': ['楼盘','物业','开发','资产','不动产']
            }
        ]

        for item in base:
            name = item['name']
            self._taxonomy[name] = item
            # 规范名称本身加入别名映射
            self._alias_to_canonical[name.lower()] = name
            for alias in item.get('aliases', []):
                self._alias_to_canonical[alias.lower()] = name
            for kw in item.get('keywords', []):
                kw_l = kw.lower()
                if kw_l not in self._keyword_index:
                    self._keyword_index[kw_l] = set()
                self._keyword_index[kw_l].add(name)

        self._loaded = True

    def load_from_dict(self, data: Dict[str, Dict[str, Any]]):
        """从外部字典注入 taxonomy 数据结构。
        期望结构：{
            canonical_name: {
               'code': str?, 'sector': str?, 'aliases': [..], 'keywords': [..]
            }
        }
        """
        if not data:
            return self.load()
        # 重置
        self._taxonomy = {}
        self._alias_to_canonical = {}
        self._keyword_index = {}
        for name, item in data.items():
            self._taxonomy[name] = {
                'code': item.get('code'),
                'sector': item.get('sector', ''),
                'aliases': list(item.get('aliases', [])),
                'keywords': list(item.get('keywords', [])),
            }
            self._alias_to_canonical[name.lower()] = name
            for alias in item.get('aliases', []):
                self._alias_to_canonical[str(alias).lower()] = name
            for kw in item.get('keywords', []):
                kw_l = str(kw).lower()
                if kw_l not in self._keyword_index:
                    self._keyword_index[kw_l] = set()
                self._keyword_index[kw_l].add(name)
        self._loaded = True

    def resolve(self, text: str) -> Optional[str]:
        if not text:
            return None
        if not self._loaded:
            self.load()
        t = text.lower().strip()
        if t in self._alias_to_canonical:
            return self._alias_to_canonical[t]
        # 简单截断匹配（如“信息技术服务”->“信息技术”）
        for alias, canonical in self._alias_to_canonical.items():
            if len(alias) >= self._min_len and alias in t:
                return canonical
        return None

    def keyword_vote(self, text: str) -> Optional[str]:
        if not text:
            return None
        if not self._loaded:
            self.load()
        votes: Dict[str, int] = {}
        lt = text.lower()
        for kw, targets in self._keyword_index.items():
            if kw in lt:
                for target in targets:
                    votes[target] = votes.get(target, 0) + 1
        if not votes:
            return None
        # 返回得票最多的行业
        return sorted(votes.items(), key=lambda x: x[1], reverse=True)[0][0]

    def get_sector(self, industry: str) -> Optional[str]:
        if not industry:
            return None
        if not self._loaded:
            self.load()
        data = self._taxonomy.get(industry)
        return data.get('sector') if data else None


class _FeatureExtractor:
    """从已经抽取的 profile 字段拼接特征文本用于行业判定。
    输入: profile dict
    输出: {'raw_text': ..., 'hint_industry': ..., 'hint_scope': ...}
    """
    def extract(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        parts = []
        for k in ["description","business_scope","industry","sector"]:
            v = profile.get(k)
            if v:
                parts.append(str(v))
        raw = " \n".join(parts)
        return {
            'raw_text': raw,
            'hint_industry': profile.get('industry'),
            'hint_scope': profile.get('business_scope')
        }


class _IndustryClassifier:
    """多策略行业分类：
    - 1) 直接规范化已提取的 industry 字段
    - 2) 在业务范围 / 描述中根据关键词投票
    - 3) 可选 LLM 验证微调
    返回: {
      'industry': <canonical>, 'sector': <sector>, 'confidence': <0-1>, 'method': <string>, 'evidence': [...]}
    """
    def __init__(self, registry: _TaxonomyRegistry):
        self.registry = registry

    async def classify(self, features: Dict[str, Any], enable_llm: bool, llm_callable=None, min_conf: float=0.65) -> Dict[str, Any]:
        evidence = []
        raw_text = features.get('raw_text','')
        # Step1: 直接规范化
        direct = features.get('hint_industry')
        if direct:
            canonical = self.registry.resolve(direct)
            if canonical:
                sector = self.registry.get_sector(canonical)
                evidence.append(f"direct:{direct}")
                return {
                    'industry': canonical,
                    'sector': sector,
                    'confidence': 0.9,
                    'method': 'direct',
                    'evidence': evidence
                }
        # Step2: 关键词投票 (描述+范围)
        vote_source = raw_text
        voted = self.registry.keyword_vote(vote_source)
        if voted:
            sector = self.registry.get_sector(voted)
            evidence.append('keyword_vote')
            conf = 0.75 if len(vote_source) > 30 else 0.7
            result = {
                'industry': voted,
                'sector': sector,
                'confidence': conf,
                'method': 'keyword_vote',
                'evidence': evidence
            }
            # Step3: 可选 LLM 校验
            if enable_llm and llm_callable:
                try:
                    prompt = f"公司简介: {raw_text[:500]}\n当前推断行业: {voted}\n请判断该行业是否准确, 返回JSON {{'confirm': true/false, 'confidence': 0-1, 'suggest': '可选替代行业'}}"
                    llm_resp = await llm_callable(prompt)
                    if llm_resp:
                        import json as _json
                        # 粗解析
                        m = re.search(r"\{.*\}", llm_resp, re.DOTALL)
                        if m:
                            data = _json.loads(m.group(0))
                            if not data.get('confirm', True):
                                alt = data.get('suggest')
                                alt_can = self.registry.resolve(alt) if alt else None
                                if alt_can:
                                    evidence.append('llm_adjust')
                                    return {
                                        'industry': alt_can,
                                        'sector': self.registry.get_sector(alt_can),
                                        'confidence': min(0.8, float(data.get('confidence', 0.6))),
                                        'method': 'llm_adjust',
                                        'evidence': evidence
                                    }
                            else:
                                evidence.append('llm_confirm')
                                result['confidence'] = max(result['confidence'], float(data.get('confidence', result['confidence'])))
                except Exception:
                    pass
            return result
        # Step4: 无结果
        return {
            'industry': None,
            'sector': None,
            'confidence': 0.0,
            'method': 'none',
            'evidence': evidence
        }

# Source configuration manager
from .source_config_manager import get_config_manager

# Baike Scraper for enhanced Baidu Baike extraction
try:
    from ..utils.baike_scraper import BaikeScraper
    BAIKE_SCRAPER_AVAILABLE = True
except ImportError:
    BAIKE_SCRAPER_AVAILABLE = False

# Optional: use readability for main content extraction
try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False

# Optional: Playwright for real browser support (百度百科特殊处理)
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Scraper导入（可选）
try:
    from backend.app.scraper import (
        ScraperOrchestrator,
    )
    SCRAPER_AVAILABLE = True
except Exception:
    SCRAPER_AVAILABLE = False


# 真实浏览器User-Agent池（定期更新）
USER_AGENT_POOL = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


# 本地企业信息数据库（OpenClaw 不可用时的 fallback）
LOCAL_COMPANY_DATABASE = {
    "阿里巴巴": {
        "name": "阿里巴巴集团控股有限公司",
        "short_name": "阿里巴巴",
        "industry": "信息技术服务",
        "sector": "互联网",
        "founded_date": "1999年",
        "business_scope": "电子商务、云计算、支付",
        "company_size": "大企业",
        "employees": "250000+",
        "headquarters": "中国浙江省杭州市",
        "description": "中国领先的电商和云计算公司，提供B2B、B2C等电商平台，以及阿里云等云计算服务",
        "confidence": 0.95
    },
    "腾讯": {
        "name": "腾讯控股有限公司",
        "short_name": "腾讯",
        "industry": "信息技术",
        "sector": "互联网",
        "founded_date": "1998年11月",
        "business_scope": "互联网产品、游戏、社交、支付",
        "company_size": "大企业",
        "employees": "100000+",
        "headquarters": "中国广东省深圳市",
        "description": "中国领先的互联网公司，提供QQ、微信、游戏等产品和服务",
        "confidence": 0.95
    },
    "华为": {
        "name": "华为技术有限公司",
        "short_name": "华为",
        "industry": "信息技术",
        "sector": "通信设备制造",
        "founded_date": "1987年",
        "business_scope": "通信设备、手机、云服务",
        "company_size": "大企业",
        "employees": "200000+",
        "headquarters": "中国广东省深圳市",
        "description": "全球领先的ICT解决方案供应商，提供通信设备、手机和云计算服务",
        "confidence": 0.95
    },
    "apple": {
        "name": "Apple Inc.",
        "short_name": "Apple",
        "industry": "消费电子产品",
        "sector": "电子产品制造",
        "founded_date": "1976年",
        "business_scope": "iPhone、Mac、iPad、App Store等",
        "company_size": "大企业",
        "employees": "150000+",
        "headquarters": "美国加州库比蒂诺",
        "description": "全球领先的消费电子产品公司，以iPhone和Mac等产品著称",
        "confidence": 0.95
    },
    "microsoft": {
        "name": "Microsoft Corporation",
        "short_name": "Microsoft",
        "industry": "软件和信息技术服务",
        "sector": "云计算和企业软件",
        "founded_date": "1975年",
        "business_scope": "Windows、Office、Azure、Xbox等",
        "company_size": "大企业",
        "employees": "220000+",
        "headquarters": "美国华盛顿州雷蒙德",
        "description": "全球领先的软件公司，提供Windows操作系统、Office办公软件和Azure云服务",
        "confidence": 0.95
    },
    "google": {
        "name": "Alphabet Inc.",
        "short_name": "Google",
        "industry": "信息技术",
        "sector": "互联网和搜索引擎",
        "founded_date": "1998年",
        "business_scope": "搜索引擎、广告、云计算",
        "company_size": "大企业",
        "employees": "190000+",
        "headquarters": "美国加州山景城",
        "description": "全球领先的搜索引擎和在线广告公司，同时提供云计算和其他互联网服务",
        "confidence": 0.95
    }
}


class CompanyProfileSearchService:
    """
    企业Profile搜索服务
    
    使用 OpenClaw 风格检索链路，专门搜索企业基本信息而非新闻
    支持从维基百科、百度百科、天眼查等信源提取结构化企业信息
    
    配置管理：所有域名配置（白名单、黑名单、登录检测等）通过配置文件管理
    """
    
    # 这些类变量已废弃，改为从配置文件加载
    # 保留以保证向后兼容，但不再使用
    PREFERRED_SOURCES = []
    BLOCKED_SOURCES = []
    
    def __init__(self, search_url: str = None):
        """
        初始化CompanyProfileSearchService
        """
        self._config_manager = get_config_manager()
        self._config_manager.print_stats()
        self.PREFERRED_SOURCES = self._config_manager.get_preferred_sources()
        self.BLOCKED_SOURCES = self._config_manager.get_blocked_sources()
        self.timeout = int(os.getenv("WEB_SEARCH_TIMEOUT", os.getenv("SEARXNG_TIMEOUT", "30")))
        from ..agent.web_agent import AgenticWebRetriever
        self._web_retriever = AgenticWebRetriever()

        # 重试配置
        self._retry_attempts = int(os.getenv("COMPANY_PROFILE_FETCH_RETRIES", "1"))
        self._retry_backoff = float(os.getenv("COMPANY_PROFILE_FETCH_BACKOFF", "0.6"))
        self._http_timeout = float(os.getenv("COMPANY_PROFILE_HTTP_TIMEOUT", "15"))
        
        # 代理配置
        self._proxies = os.getenv("NEWS_HTTP_PROXY")
        
        # Cookie存储（按域名）
        self._cookies_store: Dict[str, Dict[str, str]] = {}
        
        # 请求延迟配置（避免被识别为机器人）
        self._min_delay = float(os.getenv("SCRAPER_MIN_DELAY", "0.5"))  # 最小延迟0.5秒
        self._max_delay = float(os.getenv("SCRAPER_MAX_DELAY", "2.0"))  # 最大延迟2秒
        self._last_request_time: Dict[str, float] = {}  # 记录每个域名的最后请求时间
        
        # LLM相关性筛选配置
        self._enable_llm_filter = os.getenv("COMPANY_PROFILE_ENABLE_LLM_FILTER", "true").lower() in ("1", "true", "yes")
        self._llm_processor = None  # 延迟初始化
        # 会话级缓存：遇到需要登录的域名，避免在一次运行中重复请求和频繁写配置文件
        self._login_required_cache: set = set()
        
        # 直接获取策略配置（优先尝试确定性信源，避免OpenClaw的不确定性）
        self._enable_direct_fetch = os.getenv("COMPANY_PROFILE_DIRECT_FETCH_ENABLED", "true").lower() in ("1", "true", "yes")
        self._fallback_to_web_search = os.getenv("COMPANY_PROFILE_fallback_to_web_search", "true").lower() in ("1", "true", "yes")
        self._direct_fetch_timeout = float(os.getenv("COMPANY_PROFILE_DIRECT_FETCH_TIMEOUT", "15"))

        # Scraper orchestrator（优先用于获取页面）
        self.scraper_orchestrator = None
        if SCRAPER_AVAILABLE:
            try:
                # 默认配置路径：backend/app/scraper/config.yaml
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                scraper_dir = os.path.join(base_dir, "scraper")
                default_cfg = os.path.join(scraper_dir, "config.yaml")
                
                if os.path.exists(default_cfg):
                    # 切换工作目录到 scraper 目录，确保相对路径正确
                    original_cwd = os.getcwd()
                    try:
                        os.chdir(scraper_dir)
                        self.scraper_orchestrator = ScraperOrchestrator(default_cfg)
                        print(f"✅ ScraperOrchestrator initialized from {default_cfg}")
                    finally:
                        # 恢复工作目录
                        os.chdir(original_cwd)
                else:
                    print("⚠️ Scraper config not found, Scraper orchestration disabled")
            except Exception as e:
                import traceback
                print(f"⚠️ Failed to init ScraperOrchestrator: {e}")
                traceback.print_exc()
                self.scraper_orchestrator = None

        # ===== 行业分类组件（Taxonomy + Feature + Classifier）=====
        # 功能开关与阈值
        self._enable_industry_classify = os.getenv("COMPANY_PROFILE_CLASSIFY_INDUSTRY_ENABLED", "true").lower() in ("1", "true", "yes")
        self._enable_industry_llm_qa = os.getenv("COMPANY_PROFILE_CLASSIFY_LLM_QA", "true").lower() in ("1", "true", "yes")
        try:
            self._industry_min_conf = float(os.getenv("COMPANY_PROFILE_INDUSTRY_MIN_CONF", "0.65"))
        except Exception:
            self._industry_min_conf = 0.65
        
        # 运行时缓存（进程内）
        self._industry_cache: Dict[str, Dict[str, Any]] = {}

        # 延迟初始化分类器组件
        self._taxonomy_registry = None
        self._feature_extractor = None
        self._industry_classifier = None

    async def _async_add_login_source(self, domain: str, status_code: int):
        """
        异步添加登录页面域名到配置文件
        在后台任务中执行，不阻塞主请求流程
        """
        try:
            await asyncio.sleep(0.1)  # 避免竞争，给其他任务优先权
            self._config_manager.add_login_required_source(
                domain=domain,
                reason=f"自动检测到登录页面 (HTTP {status_code})",
                auto_detected=True
            )
        except Exception as e:
            print(f"⚠️ Background task: Failed to add {domain} to login cache: {e}")
    
    async def _get_llm_processor(self):
        """获取LLM处理器实例（延迟初始化）"""
        if self._llm_processor is None and self._enable_llm_filter:
            try:
                from .llm_processor import LLMNewsProcessor
                self._llm_processor = LLMNewsProcessor()
            except Exception as e:
                print(f"⚠️ Failed to initialize LLM processor: {e}")
                self._enable_llm_filter = False
        return self._llm_processor
    
    def _get_random_user_agent(self) -> str:
        """获取随机User-Agent"""
        return random.choice(USER_AGENT_POOL)
    
    def _build_headers(self, url: str, is_zhihu: bool = False) -> Dict[str, str]:
        """
        构建完整的HTTP请求头，模拟真实浏览器
        
        Args:
            url: 目标URL
            is_zhihu: 是否是知乎域名（需要特殊处理）
        """
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        domain = parsed.netloc.lower()
        
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "DNT": "1",  # Do Not Track
            "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        }
        
        # 知乎特殊处理
        if is_zhihu or "zhihu.com" in parsed.netloc:
            headers.update({
                "Referer": "https://www.zhihu.com/",
                "Origin": "https://www.zhihu.com",
                # 知乎特有的请求头
                "x-requested-with": "fetch",
                "x-zse-93": "101_3_3.0",  # 知乎的反爬参数（可能需要动态生成）
                "x-zse-96": "2.0_" + self._generate_zhihu_signature(url),
            })
        # World Economic Forum 等国际网站特殊处理
        elif "weforum.org" in domain:
            # 使用Google搜索作为Referer，模拟从搜索引擎来的流量
            headers.update({
                "Referer": "https://www.google.com/",
                "Accept-Language": "en-US,en;q=0.9",  # 英文网站用英文
                "Sec-Fetch-Site": "cross-site",  # 从其他网站跳转
                # 移除可能被识别的中文语言标识
            })
        else:
            # 通用Referer
            headers["Referer"] = origin + "/"
        
        return headers
    
    def _generate_zhihu_signature(self, url: str) -> str:
        """
        生成知乎的反爬签名
        注意：这是一个简化版本，实际知乎的算法更复杂
        """
        # 简单的MD5签名（知乎实际使用的是更复杂的算法）
        timestamp = str(int(datetime.now().timestamp() * 1000))
        raw = f"{url}{timestamp}"
        return hashlib.md5(raw.encode()).hexdigest()
    
    async def _rate_limit(self, domain: str):
        """
        实现请求频率限制，避免被识别为机器人
        
        Args:
            domain: 目标域名
        """
        now = asyncio.get_event_loop().time()
        last_request = self._last_request_time.get(domain, 0)
        
        # 对严格的网站使用更长的延迟
        # 检查是否为反爬虫严格的域名
        is_strict = self._config_manager.is_strict_domain(domain)
        
        # 计算需要等待的时间
        elapsed = now - last_request
        
        if is_strict:
            # 严格网站：2-5秒随机延迟
            min_interval = random.uniform(self._max_delay, self._max_delay * 2.5)
        else:
            # 普通网站：0.5-2秒随机延迟
            min_interval = random.uniform(self._min_delay, self._max_delay)
        
        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            await asyncio.sleep(wait_time)
        
        # 更新最后请求时间
        self._last_request_time[domain] = asyncio.get_event_loop().time()
    
    def _build_baidu_baike_url(self, company_name: str) -> str:
        """
        构造百度百科 URL
        
        Args:
            company_name: 企业名称
            
        Returns:
            百度百科 URL
        """
        from urllib.parse import quote
        encoded_name = quote(company_name)
        return f"https://baike.baidu.com/item/{encoded_name}"
    
    def _build_wikipedia_urls(self, company_name: str) -> List[str]:
        """
        构造维基百科 URL（尝试多个变体）
        
        Args:
            company_name: 企业名称
            
        Returns:
            维基百科 URL 列表（包含多个可能的变体）
        """
        from urllib.parse import quote
        encoded_name = quote(company_name)
        urls = [f"https://zh.wikipedia.org/wiki/{encoded_name}"]
        
        # 如果名称不包含"集团"、"公司"等后缀，尝试添加
        suffixes = ["集团", "公司", "股份有限公司"]
        for suffix in suffixes:
            if suffix not in company_name:
                encoded_variant = quote(f"{company_name}{suffix}")
                urls.append(f"https://zh.wikipedia.org/wiki/{encoded_variant}")
        
        return urls
    
    def _build_finance_urls(self, stock_symbol: str) -> List[Dict[str, str]]:
        """
        构造财经网站 URL
        
        Args:
            stock_symbol: 股票代码（如 SH600000, SZ000001）
            
        Returns:
            URL 信息列表，包含 url, source, extractor
        """
        if not stock_symbol:
            return []
        
        # 标准化股票代码格式
        code = stock_symbol.upper().replace("SH", "").replace("SZ", "")
        market = "sh" if "SH" in stock_symbol.upper() else "sz"
        
        urls = [
            {
                "url": f"https://finance.sina.com.cn/realstock/company/{market}{code}/nc.shtml",
                "source": "新浪财经",
                "extractor": "_extract_sina_finance"
            },
            {
                "url": f"https://quote.eastmoney.com/{market}{code}.html",
                "source": "东方财富",
                "extractor": "_extract_eastmoney"
            },
            {
                "url": f"https://xueqiu.com/S/{stock_symbol.upper()}",
                "source": "雪球",
                "extractor": "_extract_generic"
            }
        ]
        
        return urls
    
    async def search_company_profile(
        self,
        company_name: str,
        stock_symbol: Optional[str] = None,
        limit: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        搜索企业Profile信息
        
        Args:
            company_name: 企业名称（支持简称和全名）
            stock_symbol: 股票代码（可选，如SZ000858、SH600000）
            limit: 最多搜索结果条数
            
        Returns:
            Dict: 结构化企业信息，包含：
                - name: 企业全名
                - short_name: 企业简称
                - industry: 行业分类
                - sector: 细分行业/板块
                - founded_date: 成立日期
                - business_scope: 主营业务范围
                - company_size: 公司规模
                - employees: 员工数
                - registered_capital: 注册资本
                - headquarters: 总部位置
                - description: 企业描述/简介
                - sources: 信息来源列表（URL和域名）
                - confidence: 置信度评分 (0-1)
        """
        try:
            # 验证输入
            if not company_name or not company_name.strip():
                return None
            
            company_name = company_name.strip()
            
            print(f"\n{'='*80}")
            print(f"🔍 开始搜索企业 Profile: {company_name}")
            if stock_symbol:
                print(f"   股票代码: {stock_symbol}")
            print(f"{'='*80}\n")
            
            # ============================================================
            # 步骤 1: 本地数据库快速查询
            # ============================================================
            local_result = self._search_local_database(company_name)
            # if local_result:
            #     print(f"✅ 从本地数据库找到: {company_name}")
            #     return local_result
            
            # ============================================================
            # 步骤 2: 直接尝试百科类网站（免费、确定性强）
            # ============================================================

            print(f"\n 📚 步骤 1: 尝试本地数据库查询, _enable_direct_fetch: {self._enable_direct_fetch}")
            if self._enable_direct_fetch:
                print(f"\n📚 步骤 2: 尝试百科类网站（确定性信源）")
                encyclopedia_result = await self._try_direct_fetch_encyclopedia(company_name)
                if encyclopedia_result:
                    print(f"✅ 百科类网站获取成功！跳过 OpenClaw 搜索")
                    return await self._post_process_profile(company_name, encyclopedia_result)
            

            print(f"\n💰 步骤 2: 尝试财经网站（需要股票代码）, stock_symbol: {stock_symbol}")
            # ============================================================
            # 步骤 3: 如果有股票代码，直接尝试财经网站
            # ============================================================
            if self._enable_direct_fetch and stock_symbol:
                print(f"\n💰 步骤 3: 尝试财经网站（需要股票代码）")
                finance_result = await self._try_direct_fetch_finance(company_name, stock_symbol)
                if finance_result:
                    print(f"✅ 财经网站获取成功！跳过 OpenClaw 搜索")
                    return await self._post_process_profile(company_name, finance_result)
            
            # ============================================================
            # 步骤 4: OpenClaw 搜索（作为兜底方案）
            # ============================================================
            if not self._fallback_to_web_search:
                print(f"\n⚠️ OpenClaw 兜底已禁用，搜索失败")
                return None
            
            print(f"\n🔎 步骤 4: 使用 OpenClaw 搜索（兜底方案）")
            
            # 构建搜索查询
            search_queries = self._build_search_queries(company_name, stock_symbol)
            
            # 从OpenClaw聚合搜索
            search_results = []
            for query in search_queries:
                results = await self._search_openclaw(query, limit)
                search_results.extend(results)
            
            if not search_results:
                print(f"⚠️ OpenClaw 未找到任何结果")
                return None

            # 去重搜索结果（多个查询可能返回相同URL）
            unique_urls = {}
            for result in search_results:
                url = result.get("url", "")
                if url and url not in unique_urls:
                    unique_urls[url] = result
            search_results = list(unique_urls.values())

            print(f"🔍 OpenClaw 返回 {len(search_results)} 个结果（去重后）")
            
            # 过滤和排序结果（优先选择信源）
            filtered_results = await self._filter_and_rank_results(company_name, search_results)
            
            if not filtered_results:
                print(f"⚠️ LLM 过滤后无有效结果")
                return None
            
            # 提取关键结果的信息
            profile_data = await self._extract_profile_data(
                company_name,
                filtered_results[:10]  # 只处理前10个最优信源
            )
            
            if profile_data:
                print(f"\n✅ 搜索完成！来源: OpenClaw")
                return await self._post_process_profile(company_name, profile_data)
            else:
                print(f"\n⚠️ OpenClaw 提取数据失败")
            
            return None
            
        except Exception as e:
            print(f"\n❌ 搜索过程出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _search_local_database(self, company_name: str) -> Optional[Dict[str, Any]]:
        """
        在本地数据库中搜索企业信息（OpenClaw 不可用时的 fallback）
        
        支持完全匹配和模糊匹配
        """
        company_name_lower = company_name.lower()
        
        # 完全匹配（不区分大小写）
        for key, data in LOCAL_COMPANY_DATABASE.items():
            if key.lower() == company_name_lower:
                return {
                    "name": data["name"],
                    "short_name": data["short_name"],
                    "industry": data["industry"],
                    "sector": data["sector"],
                    "founded_date": data["founded_date"],
                    "business_scope": data["business_scope"],
                    "company_size": data["company_size"],
                    "employees": data["employees"],
                    "headquarters": data["headquarters"],
                    "description": data["description"],
                    "sources": [{"url": "local://database", "domain": "local"}],
                    "confidence": data["confidence"],
                    "_from_local_db": True
                }
        
        # 模糊匹配（包含关系）
        for key, data in LOCAL_COMPANY_DATABASE.items():
            if company_name_lower in key.lower() or key.lower() in company_name_lower:
                return {
                    "name": data["name"],
                    "short_name": data["short_name"],
                    "industry": data["industry"],
                    "sector": data["sector"],
                    "founded_date": data["founded_date"],
                    "business_scope": data["business_scope"],
                    "company_size": data["company_size"],
                    "employees": data["employees"],
                    "headquarters": data["headquarters"],
                    "description": data["description"],
                    "sources": [{"url": "local://database", "domain": "local"}],
                    "confidence": data["confidence"] * 0.85,  # 降低模糊匹配的置信度
                    "_from_local_db": True
                }
        
        return None
    
    def _build_search_queries(
        self,
        company_name: str,
        stock_symbol: Optional[str] = None
    ) -> List[str]:
        """
        构建多个搜索查询来获取企业Profile信息
        
        返回按优先级排序的查询列表
        
        注意：site: 操作符在OpenClaw中支持有限，很多搜索引擎不支持或会被过滤
        因此优先使用不带site:的通用查询，然后通过域名过滤结果
        """

        print('# 1 Building search queries...')
        # 验证企业名称不为空
        if not company_name or not company_name.strip():
            return []
        
        company_name = company_name.strip()
        queries = []
        
        # 优先级1: 通用查询（不使用site:限制，依赖后续域名过滤）
        # 这些查询成功率最高，因为不依赖site:操作符
        queries.append(f"{company_name} 企业信息 公司简介")
        queries.append(f"{company_name} 公司 百度百科")
        queries.append(f"{company_name} 公司 维基百科")
        
        # 优先级2: 如果有股票代码，使用代码查询
        if stock_symbol and stock_symbol.strip():
            queries.append(f"{stock_symbol} {company_name} 公司")
            queries.append(f"{stock_symbol} 上市公司")
        
        # 优先级3: 企业查询（天眼查、企查查）
        queries.append(f"{company_name} 天眼查 企业信息")
        queries.append(f"{company_name} 企查查 工商信息")
        
        # 优先级4: 财经资讯
        queries.append(f"{company_name} 新浪财经 公司简介")
        
        # 过滤：移除空查询和过长查询 (>200字符)
        valid_queries = [q.strip() for q in queries if q.strip() and len(q.strip()) <= 200]
        
        return valid_queries
    
    async def _search_openclaw(
        self,
        query: str,
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """使用 OpenClaw 检索链路执行单个查询"""
        try:
            query = (query or "").strip()
            if not query:
                return []
            return await self._web_retriever.search_only(
                question=query,
                top_k=max_results,
                category="general",
                time_range="month",
                language="zh-CN",
            )
        except Exception as e:
            print(f"⚠️ OpenClaw search failed for query '{query}': {e}")
            return []

    async def _llm_validate_relevance(
        self,
        company_name: str,
        url: str,
        title: str,
        content: str
    ) -> Tuple[bool, float, str]:
        """
        使用LLM验证搜索结果的相关性
        
        Args:
            company_name: 公司名称
            url: 结果URL
            title: 页面标题
            content: 页面摘要或前200字内容
            
        Returns:
            (is_relevant, confidence, reason)
            - is_relevant: 是否相关
            - confidence: 置信度 0.0-1.0
            - reason: 判断原因
        """
        if not self._enable_llm_filter:
            return True, 1.0, "LLM筛选未启用"
        
        llm = await self._get_llm_processor()
        if llm is None:
            return True, 1.0, "LLM不可用"
        
        # 构建验证提示词
        prompt = f"""你是企业信息筛选专家。请判断以下搜索结果是否与"**{company_name}**"的企业档案信息相关。

【目标】: 寻找 **{company_name}** 的企业档案信息（公司简介、成立日期、行业、业务范围、规模、总部等）

【搜索结果】:
- URL: {url}
- 标题: {title}
- 摘要: {content[:300]}

【判断标准】:
✅ **相关** - 满足以下之一:
  - 企业百科页面（百度百科、维基百科）
  - 企业工商信息页面（天眼查、企查查）
  - 企业官网或关于页面
  - 企业财务信息页面（上市公司信息）
  - 企业新闻但包含公司背景介绍

❌ **不相关** - 包括:
  - 上市公司列表页（如"上海证券交易所主板上市公司列表"）
  - 论坛、贴吧、问答页面
  - 应用下载页面（App Store、应用市场）
  - 纯产品介绍页面（不包含公司信息）
  - 游戏、娱乐、视频内容页面
  - 与企业档案无关的其他公司内容
  - 网页模板、错误页面、空白页面

请以JSON格式返回:
{{
    "relevant": true/false,
    "confidence": 0.0-1.0,
    "reason": "判断理由（30字以内）"
}}"""

        try:
            # 调用LLM
            response = await llm._call_azure_openai_responses(prompt)
            
            if not response:
                return True, 1.0, "LLM响应为空，默认保留"
            
            # 解析JSON响应
            # 尝试提取JSON（可能被包裹在markdown代码块中）
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response
            
            result = json.loads(json_str.strip())
            
            is_relevant = result.get("relevant", True)
            confidence = float(result.get("confidence", 1.0))
            reason = result.get("reason", "无理由")
            
            return is_relevant, confidence, reason
            
        except json.JSONDecodeError as e:
            # 尝试从文本中提取布尔值
            response_lower = response.lower() if response else ""
            if "relevant" in response_lower and "false" in response_lower:
                return False, 0.7, "LLM判断不相关（解析失败）"
            return True, 0.5, "LLM响应解析失败，保守保留"
            
        except Exception as e:
            print(f"⚠️ LLM relevance validation failed: {e}")
            return True, 1.0, f"LLM验证异常: {str(e)}"
    
    async def _filter_and_rank_results(
        self,
        company_name: str,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        过滤和排序搜索结果
        - 排除黑名单域名
        - 使用LLM验证相关性（可选）
        - 优先排列白名单域名
        - 按优先级排序
        """
        filtered = []
        
        for result in results:
            url = result.get("url", "")
            if not url:
                continue
            
            # 提取域名
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # 检查黑名单
            is_blocked = any(blocked in domain for blocked in self.BLOCKED_SOURCES)
            if is_blocked:
                continue
            
            # LLM相关性验证（如果启用）
            if self._enable_llm_filter:
                title = result.get("title", "")
                content = result.get("content", "") or result.get("snippet", "")
                
                is_relevant, confidence, reason = await self._llm_validate_relevance(
                    company_name=company_name,
                    url=url,
                    title=title,
                    content=content
                )
                
                if not is_relevant:
                    print(f"🚫 LLM过滤: {title[:50]}... ({reason})")
                    continue
                else:
                    print(f"✅ LLM通过: {title[:50]}... (置信度: {confidence:.2f})")
                
                result["_llm_confidence"] = confidence
                result["_llm_reason"] = reason
            
            # 计算优先级
            priority = 1000  # 默认优先级
            for idx, preferred in enumerate(self.PREFERRED_SOURCES):
                if preferred in domain:
                    priority = idx  # 0最高，依次递增
                    break
            
            result["_priority"] = priority
            result["_domain"] = domain
            filtered.append(result)
        
        # 按优先级排序
        filtered.sort(key=lambda x: x["_priority"])
        
        return filtered
    
    async def _try_direct_fetch_encyclopedia(self, company_name: str) -> Optional[Dict[str, Any]]:
        """
        直接尝试从百科类网站获取企业信息（避免 OpenClaw 搜索的不确定性）
        
        优先级顺序：
        1. 百度百科（最稳定、内容最全）
        2. 维基百科（权威、但可能被墙）
        
        Args:
            company_name: 企业名称
            
        Returns:
            企业 Profile 数据，如果获取失败则返回 None
        """
        print(f"📖 尝试直接从百科类网站获取: {company_name}")
        per_site_timeout = float(os.getenv("COMPANY_PROFILE_PER_SITE_TIMEOUT", "30"))

        # 1. 尝试百度百科
        baidu_url = self._build_baidu_baike_url(company_name)
        print(f"   → 尝试百度百科: {baidu_url}")

        try:
            html = await asyncio.wait_for(
                self._fetch_html(baidu_url), timeout=per_site_timeout,
            )
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                data = await self._extract_baidu_baike(soup, company_name)
                if data and data.get("confidence", 0) > 0.5:
                    print(f"   ✅ 百度百科获取成功 (置信度: {data.get('confidence', 0):.2f})")
                    return self._format_single_source_profile(company_name, baidu_url, "baike.baidu.com", data)
        except asyncio.TimeoutError:
            print(f"   ⏱️ 百度百科超时 ({per_site_timeout}s)")
        except Exception as e:
            print(f"   ⚠️ 百度百科获取失败: {e}")

        # 2. 尝试维基百科（只试第一个变体，减少无效重试）
        wiki_urls = self._build_wikipedia_urls(company_name)
        for idx, wiki_url in enumerate(wiki_urls[:1]):
            print(f"   → 尝试维基百科: {wiki_url}")
            try:
                html = await asyncio.wait_for(
                    self._fetch_html(wiki_url), timeout=per_site_timeout,
                )
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    data = self._extract_wikipedia(soup, company_name)
                    if data and data.get("confidence", 0) > 0.5:
                        print(f"   ✅ 维基百科获取成功 (置信度: {data.get('confidence', 0):.2f})")
                        return self._format_single_source_profile(company_name, wiki_url, "zh.wikipedia.org", data)
            except asyncio.TimeoutError:
                print(f"   ⏱️ 维基百科超时 ({per_site_timeout}s)")
            except Exception as e:
                print(f"   ⚠️ 维基百科获取失败: {e}")

        print(f"   ❌ 所有百科类网站均获取失败")
        return None
    
    async def _try_direct_fetch_finance(self, company_name: str, stock_symbol: str) -> Optional[Dict[str, Any]]:
        """
        直接尝试从财经网站获取企业信息（需要股票代码）
        
        优先级顺序：
        1. 新浪财经（上市公司信息全）
        2. 东方财富（财务数据全）
        3. 雪球（社区讨论多）
        
        Args:
            company_name: 企业名称
            stock_symbol: 股票代码（如 SH600000）
            
        Returns:
            企业 Profile 数据，如果获取失败则返回 None
        """
        if not stock_symbol:
            return None
        
        print(f"💰 尝试直接从财经网站获取: {company_name} ({stock_symbol})")
        
        finance_urls = self._build_finance_urls(stock_symbol)
        
        per_site_timeout = float(os.getenv("COMPANY_PROFILE_PER_SITE_TIMEOUT", "30"))
        for url_info in finance_urls:
            url = url_info["url"]
            source = url_info["source"]
            extractor = url_info["extractor"]

            print(f"   → 尝试{source}: {url}")

            try:
                html = await asyncio.wait_for(
                    self._fetch_html(url), timeout=per_site_timeout,
                )
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    extractor_method = getattr(self, extractor, None)
                    if extractor_method:
                        data = extractor_method(soup, company_name)
                        if data and data.get("confidence", 0) > 0.5:
                            print(f"   ✅ {source}获取成功 (置信度: {data.get('confidence', 0):.2f})")
                            domain = urlparse(url).netloc
                            return self._format_single_source_profile(company_name, url, domain, data)
            except asyncio.TimeoutError:
                print(f"   ⏱️ {source}超时 ({per_site_timeout}s)")
            except Exception as e:
                print(f"   ⚠️ {source}获取失败: {e}")
        
        print(f"   ❌ 所有财经网站均获取失败")
        return None
    
    def _format_single_source_profile(
        self,
        company_name: str,
        url: str,
        domain: str,
        extracted_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        将单个信源的提取数据格式化为标准 Profile 结构
        
        Args:
            company_name: 企业名称
            url: 信源 URL
            domain: 信源域名
            extracted_data: 提取的数据（包含 confidence, industry 等字段）
            
        Returns:
            标准化的 Profile 数据结构
        """
        return {
            "name": company_name,
            "short_name": extracted_data.get("short_name"),
            "industry": extracted_data.get("industry"),
            "sector": extracted_data.get("sector"),
            "founded_date": extracted_data.get("founded_date"),
            "business_scope": extracted_data.get("business_scope"),
            "company_size": extracted_data.get("company_size"),
            "employees": extracted_data.get("employees"),
            "registered_capital": extracted_data.get("registered_capital"),
            "headquarters": extracted_data.get("headquarters"),
            "description": extracted_data.get("description"),
            "sources": [{
                "url": url,
                "domain": domain,
                "extracted_fields": [k for k, v in extracted_data.items() if k != "confidence" and v is not None]
            }],
            "confidence": extracted_data.get("confidence", 0.0)
        }
    
    async def _extract_profile_data(
        self,
        company_name: str,
        results: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        从搜索结果中提取企业Profile数据
        
        处理多个来源，进行信息融合
        - 自动去重重复的URL（多个查询可能返回相同结果）
        - 跳过已标记为登录页的域名
        - 第一次检测到某域名需要登录后，立即跳过该域名的所有后续结果
        """
        profile_info = {
            "name": company_name,
            "short_name": None,
            "industry": None,
            "sector": None,
            "founded_date": None,
            "business_scope": None,
            "company_size": None,
            "employees": None,
            "registered_capital": None,
            "headquarters": None,
            "description": None,
            "sources": [],
            "confidence": 0.0
        }
        
        extracted_count = 0
        total_confidence = 0.0
        processed_urls = set()  # 记录已处理的URL，避免重复
        domains_requiring_login = set()  # 本次会话中检测到需要登录的域名
        
        for result in results:
            try:
                url = result.get("url", "")
                domain = result.get("_domain", "")
                
                # 去重：如果同一URL已处理，跳过
                if url in processed_urls:
                    continue
                processed_urls.add(url)
                
                # 快速检查：如果该域名已被标记为需要登录（本次会话或之前），直接跳过
                if domain in domains_requiring_login or domain in self._login_required_cache or self._config_manager.is_login_required(domain):
                    if '阿里巴巴' in company_name:
                        print(f'🔒 Skipping fetch for {domain} because it\'s marked as login-required')
                    domains_requiring_login.add(domain)
                    continue
                
                # 根据域名选择合适的提取器
                extracted = await self._extract_by_domain(url, domain, company_name)

                # 检查_fetch_html是否检测到登录页并标记该域名（在调用后立即检查）
                if domain in self._login_required_cache:
                    domains_requiring_login.add(domain)
                    if '阿里巴巴' in company_name:
                        print(f'🔒 Detected login-required for {domain}, skipping remaining results from this domain')
                    continue

                if '阿里巴巴' in company_name:
                    print(f'Extracted from {domain}: {extracted}')
                
                if extracted:
                    extracted_count += 1
                    
                    # 融合信息
                    if extracted.get("industry"):
                        profile_info["industry"] = extracted["industry"]
                    if extracted.get("sector"):
                        profile_info["sector"] = extracted["sector"]
                    if extracted.get("founded_date") and not profile_info["founded_date"]:
                        profile_info["founded_date"] = extracted["founded_date"]
                    if extracted.get("business_scope"):
                        profile_info["business_scope"] = extracted["business_scope"]
                    if extracted.get("company_size"):
                        profile_info["company_size"] = extracted["company_size"]
                    if extracted.get("employees"):
                        profile_info["employees"] = extracted["employees"]
                    if extracted.get("headquarters"):
                        profile_info["headquarters"] = extracted["headquarters"]
                    if extracted.get("description"):
                        profile_info["description"] = extracted["description"]
                    
                    # 记录来源
                    profile_info["sources"].append({
                        "url": url,
                        "domain": domain,
                        "extracted_fields": list(extracted.keys())
                    })
                    
                    total_confidence += extracted.get("confidence", 0.5)
                    
            except Exception as e:
                print(f"⚠️ Failed to extract from {result.get('url', '')}: {e}")
                continue
        
        # 计算最终置信度
        if extracted_count > 0:
            profile_info["confidence"] = min(total_confidence / extracted_count, 1.0)
            return profile_info
        else:
            return None
    
    async def _extract_by_domain(
        self,
        url: str,
        domain: str,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        根据域名选择合适的信息提取策略
        """
        try:
            # 获取页面内容
            html = await self._fetch_html(url)

            if domain == 'zh.wikipedia.org' or domain == 'en.wikipedia.org':
                print(f'Fetched HTML from Wikipedia for {company_name}, length: {len(html) if html else "None"}')


            if not html:
                return None
            
            soup = BeautifulSoup(html, 'lxml')
            
            # 根据域名分类处理
            if "baike.baidu.com" in domain:
                print(f'Extracting from Baidu Baike for {company_name}')
                return await self._extract_baidu_baike(soup, company_name)
            elif "wikipedia" in domain:
                print(f'Extracting from Wikipedia for {company_name}')
                return self._extract_wikipedia(soup, company_name)
            elif "zhihu.com" in domain:
                print(f'Extracting from Zhihu for {company_name}')
                return self._extract_zhihu(soup, company_name)
            elif "tianyancha.com" in domain:
                print(f'Extracting from Tianyancha for {company_name}')
                return self._extract_tianyancha(soup, company_name)
            elif "qcc.com" in domain:
                print(f'Extracting from Qichacha for {company_name}')   
                return self._extract_qcc(soup, company_name)
            elif "stock.finance.sina.com.cn" in domain:
                print(f'Extracting from Sina Finance for {company_name}')
                return self._extract_sina_finance(soup, company_name)
            elif "eastmoney.com" in domain:
                print(f'Extracting from Eastmoney for {company_name}')
                return self._extract_eastmoney(soup, company_name)
            else:
                print(f"⚠️ No specific extractor for {domain}, using generic.")
                # 通用提取器
                return self._extract_generic(soup, company_name)
                
        except Exception as e:
            print(f"⚠️ Extract error for {domain}: {e}")
            return None

    async def _fetch_html_with_scraper(self, url: str) -> Optional[str]:
        """
        使用ScraperOrchestrator获取页面内容（如果可用）。
        返回HTML字符串或None。
        
        Scraper会自动路由到最佳fetcher：
        - Wikipedia -> WikipediaFetcher (使用API)
        - 其他 -> RequestsFetcher 或 PlaywrightFetcher
        """
        if not self.scraper_orchestrator:
            return None

        try:
            # 获取路由配置
            router_cfg = None
            try:
                router_cfg = self.scraper_orchestrator.domain_router.route(url)
                fetcher_type = router_cfg.get('fetcher', 'requests') if router_cfg else 'requests'
            except Exception as e:
                print(f"⚠️ Router error for {url}: {e}")
                fetcher_type = 'requests'

            # 获取fetcher实例
            fetcher = getattr(self.scraper_orchestrator, 'fetchers', {}).get(fetcher_type)

            if not fetcher:
                # 回退到 requests fetcher
                fetcher = getattr(self.scraper_orchestrator, 'fetchers', {}).get('requests')

            if not fetcher:
                print(f"⚠️ No fetcher available for {url}")
                return None

            print(f"🔄 Using {fetcher_type} fetcher for {urlparse(url).netloc}")

            # 调用 fetcher（处理同步/异步，以及 Wikipedia 特殊情况）
            result = None
            timeout = 30.0  # 默认超时30秒
            
            try:
                # Wikipedia fetcher 特殊处理
                if fetcher_type == 'wikipedia' and hasattr(fetcher, 'fetch_page_text'):
                    # 从URL提取标题
                    from backend.app.scraper.fetchers.wikipedia import WikipediaFetcher
                    title = WikipediaFetcher.extract_title_from_url(url)
                    if not title:
                        print(f"⚠️ Cannot extract Wikipedia title from {url}")
                        return None
                    
                    # 获取语言代码
                    parsed = urlparse(url)
                    lang = parsed.netloc.split('.')[0] if '.' in parsed.netloc else 'en'
                    
                    # 调用 fetch_page_text（同步方法）with timeout
                    loop = asyncio.get_event_loop()
                    wiki_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, 
                            fetcher.fetch_page_text,
                            title,
                            lang,
                            True  # get_full_page
                        ),
                        timeout=15.0  # Wikipedia API timeout 15秒
                    )
                    
                    if wiki_result and wiki_result.get('content'):
                        # 转换为标准格式（返回HTML格式的内容）
                        # 将纯文本转换为简单的HTML
                        content = wiki_result['content']
                        html = f"""<html><head><title>{wiki_result.get('title', '')}</title></head>
<body><div id="mw-content-text"><p>{content}</p></div></body></html>"""
                        result = {
                            'content': html,
                            'url': wiki_result.get('url', url),
                            'status_code': 200,
                            'is_login_page': False
                        }
                    else:
                        print(f"⚠️ Wikipedia fetcher returned no content for {title}")
                        return None
                
                # 检查是否有 fetch_async 方法（优先）
                elif hasattr(fetcher, 'fetch_async') and asyncio.iscoroutinefunction(fetcher.fetch_async):
                    result = await asyncio.wait_for(fetcher.fetch_async(url), timeout=timeout)
                # 检查是否有异步的 fetch 方法
                elif hasattr(fetcher, 'fetch') and asyncio.iscoroutinefunction(fetcher.fetch):
                    result = await asyncio.wait_for(fetcher.fetch(url), timeout=timeout)
                # 检查是否有同步的 fetch 方法
                elif hasattr(fetcher, 'fetch'):
                    loop = asyncio.get_event_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, fetcher.fetch, url),
                        timeout=timeout
                    )
                else:
                    print(f"⚠️ Fetcher {fetcher_type} has no supported fetch method")
                    return None
            except asyncio.TimeoutError:
                print(f"⏱️ Timeout ({timeout}s) fetching {url} with {fetcher_type}")
                return None
            except Exception as e:
                print(f"⚠️ Error calling {fetcher_type}.fetch for {url}: {e}")
                import traceback
                traceback.print_exc()
                return None

            if not result:
                print(f"⚠️ {fetcher_type} returned no result for {url}")
                return None

            # 处理返回结果
            html = None
            is_login = False
            
            if isinstance(result, dict):
                html = result.get('content')
                is_login = result.get('is_login_page', False)
                
                # 检查登录检测（但对于 Wikipedia API fetcher 应该不会发生）
                if is_login:
                    domain = urlparse(url).netloc.lower()
                    print(f"🔒 Scraper detected login page for {domain}")
                    self._login_required_cache.add(domain)
                    asyncio.create_task(self._async_add_login_source(domain, result.get('status_code', 0)))
                    return None
            elif isinstance(result, str):
                # 直接返回字符串内容
                html = result
            
            if html:
                print(f"✅ {fetcher_type} fetched {len(html)} bytes from {urlparse(url).netloc}")
                
            return html
            
        except Exception as e:
            print(f"⚠️ Scraper fetch error for {url}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """
        使用Playwright真实浏览器获取页面内容（绕过反爬虫）
        主要用于百度百科等有反爬机制的网站
        
        Args:
            url: 要获取的URL
            
        Returns:
            页面的HTML内容，或None如果获取失败
        """
        if not PLAYWRIGHT_AVAILABLE:
            return None
        
        try:
            from playwright.sync_api import sync_playwright
            
            print(f"  🌐 使用Playwright浏览器获取: {url}")
            
            with sync_playwright() as p:
                # 启动浏览器（headless模式）
                browser = p.chromium.launch(headless=True)
                
                # 创建页面
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                try:
                    # 访问页面，等待网络空闲
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    
                    # 等待关键内容加载
                    page.wait_for_timeout(2000)
                    
                    # 获取页面HTML
                    html_content = page.content()
                    
                    print(f"  ✅ Playwright成功获取内容 ({len(html_content)} bytes)")
                    return html_content
                    
                except Exception as e:
                    print(f"  ❌ Playwright获取失败: {e}")
                    return None
                finally:
                    page.close()
                    browser.close()
                    
        except Exception as e:
            print(f"  ❌ Playwright错误: {e}")
            return None
    
    async def _fetch_html(self, url: str) -> Optional[str]:
        """
        获取URL的HTML内容，支持重试和反反爬虫策略
        
        特性：
        - 优先使用 Scraper（智能路由到最佳 fetcher）
        - 动态User-Agent轮换
        - 完整的浏览器请求头
        - Cookie管理和保持
        - 请求频率限制
        - 知乎等网站的特殊处理
        - 代理支持
        - 智能重试机制
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        is_zhihu = "zhihu.com" in domain

        # 检查是否为已知的登录问题域名（强制使用 Scraper）
        known_login_domains = ['wikipedia.org', 'tianyancha.com', 'qcc.com', 'zhihu.com']
        is_known_login_domain = any(known_domain in domain for known_domain in known_login_domains)

        # 如果该域名已被标记为需要登录，立刻跳过
        if domain in self._login_required_cache or self._config_manager.is_login_required(domain):
            print(f"🔒 Skipping fetch for {domain} because it's marked as login-required")
            return None

        # 优先使用 ScraperOrchestrator 获取（如果已初始化）
        # 对于已知登录域名，强制使用 Scraper（如果可用）
        if self.scraper_orchestrator:
            try:
                html_from_scraper = await self._fetch_html_with_scraper(url)
                if html_from_scraper:
                    print(f"💠 Fetched via Scraper for {domain} ({len(html_from_scraper)} bytes)")
                    return html_from_scraper
                elif is_known_login_domain:
                    # 对于已知登录域名，如果 Scraper 失败就直接返回 None（不再尝试 HTTP）
                    print(f"🔒 Scraper failed for known-login domain {domain}, skipping HTTP fallback")
                    # 标记为需要登录
                    self._login_required_cache.add(domain)
                    asyncio.create_task(self._async_add_login_source(domain, 0))
                    return None
                else:
                    print(f"💡 Scraper did not return content for {url}, falling back to HTTP client")
            except Exception as e:
                if is_known_login_domain:
                    print(f"⚠️ Scraper error for known-login domain {domain}: {e}, skipping HTTP fallback")
                    # 标记为需要登录
                    self._login_required_cache.add(domain)
                    asyncio.create_task(self._async_add_login_source(domain, 0))
                    return None
                print(f"⚠️ Error while using Scraper for {url}: {e}, falling back to HTTP")
        
        for attempt in range(self._retry_attempts):
            try:
                # 频率限制（避免被识别为机器人）
                await self._rate_limit(domain)
                
                # 构建请求头
                headers = self._build_headers(url, is_zhihu=is_zhihu)
                
                # 准备Cookie
                cookies = self._cookies_store.get(domain, {})
                
                # 构建httpx客户端配置
                client_kwargs = {
                    "timeout": self._http_timeout,
                    "follow_redirects": True,
                    "headers": headers,
                }
                
                # 添加代理配置
                if self._proxies:
                    client_kwargs["proxies"] = self._proxies
                
                # 添加Cookie
                if cookies:
                    client_kwargs["cookies"] = cookies
                
                async with httpx.AsyncClient(**client_kwargs) as client:
                    # 发送请求
                    response = await client.get(url)
                    
                    # 保存Cookie
                    if response.cookies:
                        self._cookies_store[domain] = dict(response.cookies)
                    
                    # 处理重定向后的最终URL
                    final_url = str(response.url)
                    
                    # 成功获取
                    if response.status_code == 200:
                        # 尝试多种编码
                        try:
                            html_content = response.text
                        except Exception:
                            try:
                                html_content = response.content.decode('gbk', errors='ignore')
                            except Exception:
                                html_content = response.content.decode('utf-8', errors='ignore')
                        
                        # 自动检测登录页面
                        if self._config_manager.detect_login_page(final_url, html_content, response.status_code):
                            print(f"🔒 Detected login page for {domain}")
                            
                            # 🌐 对于百度百科，尝试使用Playwright真实浏览器绕过反爬
                            if "baike.baidu.com" in domain and PLAYWRIGHT_AVAILABLE:
                                print(f"  💡 尝试使用Playwright获取百度百科...")
                                playwright_html = await asyncio.get_event_loop().run_in_executor(None, self._fetch_with_playwright, url)
                                if playwright_html and len(playwright_html) > 5000:
                                    print(f"  ✅ Playwright成功获取百度百科内容")
                                    return playwright_html
                                else:
                                    print(f"  ❌ Playwright也无法获取内容，标记为需要登录")
                            
                            # ⚡ 仅在内存中标记（不阻塞I/O），避免卡住
                            self._login_required_cache.add(domain)
                            # 🔧 异步保存配置（不会阻塞当前请求链）
                            # 异步更新配置文件，放在后台任务中处理
                            asyncio.create_task(self._async_add_login_source(domain, response.status_code))
                            # 登录页面视为无效内容，返回None
                            return None
                        
                        return html_content
                    
                    # 403错误特殊处理
                    elif response.status_code == 403:
                        print(f"⚠️ 403 Forbidden for {url} (attempt {attempt + 1}/{self._retry_attempts})")
                        
                        # 对所有403错误应用反爬虫策略
                        if attempt < self._retry_attempts - 1:
                            # 策略1: 清除Cookie，重新开始
                            if domain in self._cookies_store:
                                del self._cookies_store[domain]
                                print(f"  → Clearing cookies for {domain}, retrying...")
                            
                            # 策略2: 增加延迟时间（每次尝试延迟加倍）
                            backoff = self._retry_backoff * (2 ** attempt) * 3  # 指数退避
                            print(f"  → Waiting {backoff:.1f}s before retry...")
                            await asyncio.sleep(backoff)
                            
                            # 策略3: 轮换User-Agent（强制获取新的UA）
                            print(f"  → Rotating User-Agent for retry...")
                            
                            continue
                        else:
                            # 最后一次尝试失败 - 对于百度百科，尝试Playwright
                            print(f"  → Giving up on requests, last attempt.")
                            if "baike.baidu.com" in domain and PLAYWRIGHT_AVAILABLE:
                                print(f"  💡 最后尝试：使用Playwright获取百度百科...")
                                playwright_html = await asyncio.get_event_loop().run_in_executor(None, self._fetch_with_playwright, url)
                                if playwright_html and len(playwright_html) > 5000:
                                    print(f"  ✅ Playwright成功绕过403获取内容")
                                    return playwright_html
                                else:
                                    print(f"  ❌ Playwright也无法绕过403")
                            return None
                    
                    # 429 Too Many Requests
                    elif response.status_code == 429:
                        retry_after = response.headers.get("Retry-After", "60")
                        try:
                            wait_time = int(retry_after)
                        except ValueError:
                            wait_time = 60
                        
                        print(f"⚠️ 429 Too Many Requests for {url}, waiting {wait_time}s...")
                        
                        if attempt < self._retry_attempts - 1:
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            return None
                    
                    # 其他4xx/5xx错误
                    elif response.status_code >= 400:
                        print(f"⚠️ HTTP {response.status_code} for {url}")
                        
                        # 检查是否为登录相关的重定向或错误
                        if response.status_code in [302, 401, 403]:
                            try:
                                html_content = response.text or ""
                                if self._config_manager.detect_login_page(final_url, html_content, response.status_code):
                                    print(f"🔒 Detected login requirement for {domain} (status={response.status_code})")
                                    # ⚡ 仅在内存中标记（不阻塞I/O），避免卡住
                                    self._login_required_cache.add(domain)
                                    # 🔧 异步保存配置（不会阻塞当前请求链）
                                    asyncio.create_task(self._async_add_login_source(domain, response.status_code))
                                    return None
                            except Exception:
                                pass
                        
                        if attempt < self._retry_attempts - 1:
                            await asyncio.sleep(self._retry_backoff * (attempt + 1))
                            continue
                        else:
                            return None
                            
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                print(f"⚠️ HTTP error {status_code} for {url} (attempt {attempt + 1}/{self._retry_attempts})")
                
                if attempt < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_backoff * (attempt + 1))
                    continue
                else:
                    return None
                    
            except httpx.ConnectError as e:
                print(f"⚠️ Connection error for {url}: {e}")
                
                if attempt < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_backoff * (attempt + 1))
                    continue
                else:
                    return None
                    
            except httpx.TimeoutException as e:
                print(f"⚠️ Timeout for {url} (attempt {attempt + 1}/{self._retry_attempts})")
                
                if attempt < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_backoff * (attempt + 1))
                    continue
                else:
                    return None
                    
            except Exception as e:
                print(f"⚠️ Unexpected error for {url}: {type(e).__name__}: {e}")
                
                if attempt < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_backoff * (attempt + 1))
                    continue
                else:
                    return None
        
        return None
    
    async def _extract_baidu_baike(
        self,
        soup: BeautifulSoup,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        从百度百科提取企业信息
        
        支持两种提取方式：
        1. 优先使用 BaikeScraper 的 get_company_profile 方法（更可靠）
        2. 回退到 BeautifulSoup 解析（当 BaikeScraper 不可用时）
        """
        try:
            result = {
                "confidence": 0.85,  # 百度百科可信度高
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
            }
            
            # 方法1：优先使用 BaikeScraper 的 get_company_profile 方法
            if BAIKE_SCRAPER_AVAILABLE:
                try:
                    baike_scraper = BaikeScraper(use_cache=True, timeout=30)
                    profile = await baike_scraper.get_company_profile(company_name)
                    if profile:
                        # 将 profile 数据合并到 result
                        for key in result.keys():
                            if key in profile and profile[key]:
                                result[key] = profile[key]
                        return result if any(v for k, v in result.items() if k != "confidence") else None
                except Exception as e:
                    print(f"⚠️ BaikeScraper 获取失败，切换到 BeautifulSoup: {e}")
                    # 继续使用 BeautifulSoup 回退
            
            # 方法2：回退到 BeautifulSoup 解析（原有逻辑）
            # 保存HTML到本地用于调试
            try:
                os.makedirs('./tmp', exist_ok=True)
                with open(f'./tmp/baidu_baike_{company_name}.html', 'w', encoding='utf-8') as f:
                    f.write(str(soup))
                    f.write("\n\n")
                print('✅ 已保存百度百科HTML')
            except Exception as e:
                print(f"⚠️ 保存HTML失败: {e}")

            # 提取简介 - 使用更通用的选择器
            intro_elem = soup.select_one('div[class*="summary"], div[class*="Summary"]')
            if intro_elem:
                result["description"] = intro_elem.get_text(strip=True)[:300]
            
            # 提取信息框中的数据 - 需要先找到信息框容器，兼容新版和多种class写法
            info_container = (
                soup.find('div', class_=lambda x: x and ('itemWrapper' in str(x) or 'basicInfo' in str(x)))
                or soup.find('dl', class_=lambda x: x and ('basicInfo' in str(x) or 'basic-info' in str(x)))
                or soup.find('dl', class_=lambda x: x and 'lemmaWgt-lemmaBasicInfo' in str(x))
            )
            # 兼容新版百科（如无class，直接找dl标签）
            if not info_container:
                info_container = soup.find('dl')

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
                        result["founded_date"] = value
                    elif "行业" in key or "公司类型" in key:
                        result["industry"] = value
                    elif "经营范围" in key or "主营业务" in key or "业务范围" in key:
                        result["business_scope"] = value[:200]
                    elif "总部" in key or "办公地址" in key:
                        result["headquarters"] = value
                    elif "员工" in key or "人数" in key:
                        result["employees"] = value
                    elif "注册资本" in key or "资本" in key:
                        result["registered_capital"] = value
                    elif "年营业额" in key or "营收" in key:
                        result["company_size"] = value
            else:
                print(f"⚠️ 未找到百度百科信息框容器 for {company_name}")
            
            print(f"✅ 成功从 BeautifulSoup 提取profile数据")
            
            return result if any(v for k, v in result.items() if k != "confidence") else None
            
        except Exception as e:
            print(f"⚠️ Baidu Baike extraction error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_wikipedia(
        self,
        soup: BeautifulSoup,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        从维基百科提取企业信息
        Wikipedia 使用 infobox 表格，key在th标签，value在td标签
        """
        try:
            result = {
                "confidence": 0.80,
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
            }
            
            # 提取简介段落
            content = soup.find("div", id="mw-content-text")
            if content:
                paras = content.find_all("p", recursive=False)
                # 找第一个有实际内容的段落
                for para in paras[:5]:
                    text = para.get_text(strip=True)
                    if len(text) > 50:  # 至少50字符才算有效简介
                        result["description"] = text[:300]
                        break
            
            # 提取信息框 - Wikipedia使用th/td结构
            infobox = soup.find("table", class_="infobox") or soup.find("table", class_="infobox-box")
            if infobox:
                rows = infobox.find_all("tr")
                for row in rows:
                    # Wikipedia 的 infobox 使用 th 作为标签，td 作为值
                    th = row.find("th")
                    td = row.find("td")
                    
                    if not th or not td:
                        continue
                    
                    key = th.get_text(strip=True).lower()
                    value = td.get_text(strip=True)
                    
                    # 跳过过长的值（可能是嵌套表格或列表）
                    if len(value) > 300:
                        continue
                    
                    # 映射字段
                    if "founded" in key or "成立" in key or "创立" in key:
                        result["founded_date"] = value
                    elif "industry" in key or "行业" in key or "产业" in key:
                        result["industry"] = value
                    elif "headquarters" in key or "总部" in key or "地址" in key:
                        result["headquarters"] = value
                    elif "employees" in key or "员工" in key or "僱員" in key:
                        result["employees"] = value
                    elif "products" in key or "产品" in key or "服务" in key:
                        result["business_scope"] = value[:200]
            

            print('# Wikipedia extraction result:', result)
            return result if any(v for k, v in result.items() if k != "confidence") else None
            
        except Exception as e:
            print(f"⚠️ Wikipedia extraction error: {e}")
            return None
    
    def _extract_zhihu(
        self,
        soup: BeautifulSoup,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        从知乎提取企业信息
        知乎主要是问答和话题，提取相关讨论中的企业信息
        """
        try:
            result = {
                "confidence": 0.65,  # 知乎内容质量参差不齐
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
            }
            
            # 提取话题描述
            topic_desc = soup.find("div", class_="TopicMetaCard-description")
            if topic_desc:
                result["description"] = topic_desc.get_text(strip=True)[:300]
            
            # 提取回答内容（高赞回答通常包含有用信息）
            answers = soup.find_all("div", class_="RichContent-inner")
            if answers:
                # 合并前3个高赞回答的文本
                combined_text = ""
                for answer in answers[:3]:
                    text = answer.get_text(strip=True)
                    combined_text += text + " "
                    if len(combined_text) > 500:
                        break
                
                # 从文本中提取关键信息
                # 行业识别
                industry_patterns = [
                    r"(互联网|金融|制造业|零售|电商|科技|医疗|教育|房地产|能源|通信|传媒)(?:行业|领域|产业)",
                    r"(?:属于|从事|专注于|主营)(.*?)(?:行业|领域|产业)"
                ]
                for pattern in industry_patterns:
                    match = re.search(pattern, combined_text)
                    if match:
                        result["industry"] = match.group(1)[:50]
                        break
                
                # 成立时间识别
                date_patterns = [
                    r"成立于\s*(\d{4}年)",
                    r"创立于\s*(\d{4}年)",
                    r"(\d{4}年)\s*成立",
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, combined_text)
                    if match:
                        result["founded_date"] = match.group(1)
                        break
                
                # 总部地址识别
                location_patterns = [
                    r"总部(?:位于|在)([\u4e00-\u9fa5]+(?:省|市|区))",
                    r"(?:位于|在)([\u4e00-\u9fa5]+(?:省|市|区)).*?总部",
                ]
                for pattern in location_patterns:
                    match = re.search(pattern, combined_text)
                    if match:
                        result["headquarters"] = match.group(1)
                        break
                
                # 如果没有话题描述，使用回答文本作为描述
                if not result["description"] and combined_text:
                    result["description"] = combined_text[:300]
            
            # 提取标题中的信息
            title = soup.find("h1", class_="QuestionHeader-title")
            if title and not result["description"]:
                result["description"] = title.get_text(strip=True)
            
            return result if any(v for k, v in result.items() if k != "confidence") else None
            
        except Exception as e:
            print(f"⚠️ Zhihu extraction error: {e}")
            return None
    
    def _extract_tianyancha(
        self,
        soup: BeautifulSoup,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        从天眼查提取企业信息
        """
        try:
            result = {
                "confidence": 0.82,
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
            }
            
            # 提取基本信息块
            base_info = soup.find("div", class_="base-info")
            if base_info:
                # 成立时间
                founded = base_info.find("span", string=re.compile("成立时间|创立时间"))
                if founded and founded.next_sibling:
                    result["founded_date"] = founded.next_sibling.get_text(strip=True)
                
                # 公司类型/行业
                industry = base_info.find("span", string=re.compile("行业|类型"))
                if industry and industry.next_sibling:
                    result["industry"] = industry.next_sibling.get_text(strip=True)
            
            # 提取经营范围
            business = soup.find("div", class_="business-scope")
            if business:
                result["business_scope"] = business.get_text(strip=True)[:200]
            
            return result if any(v for k, v in result.items() if k != "confidence") else None
            
        except Exception as e:
            print(f"⚠️ Tianyancha extraction error: {e}")
            return None
    
    def _extract_qcc(
        self,
        soup: BeautifulSoup,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        从企查查提取企业信息
        """
        try:
            result = {
                "confidence": 0.80,
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
            }
            
            # 提取基本信息
            info_section = soup.find("div", class_="attr-text")
            if info_section:
                items = info_section.find_all("p")
                for item in items:
                    text = item.get_text(strip=True)
                    
                    if "成立时间" in text:
                        result["founded_date"] = re.search(r":\s*(.+?)(?:\n|$)", text).group(1) if re.search(r":\s*(.+?)(?:\n|$)", text) else None
                    elif "行业" in text:
                        result["industry"] = re.search(r":\s*(.+?)(?:\n|$)", text).group(1) if re.search(r":\s*(.+?)(?:\n|$)", text) else None
            
            return result if any(v for k, v in result.items() if k != "confidence") else None
            
        except Exception as e:
            print(f"⚠️ Qcc extraction error: {e}")
            return None
    
    def _extract_sina_finance(
        self,
        soup: BeautifulSoup,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        从新浪财经提取企业信息
        """
        try:
            result = {
                "confidence": 0.75,
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
            }
            
            # 查找公司简介
            intro = soup.find("div", class_="introduction")
            if intro:
                result["description"] = intro.get_text(strip=True)[:200]
            
            # 查找基本信息表
            info_table = soup.find("table", class_="table-data")
            if info_table:
                rows = info_table.find_all("tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True).lower()
                        value = cells[1].get_text(strip=True)
                        
                        if "行业" in key:
                            result["industry"] = value
                        elif "所属地区" in key:
                            result["headquarters"] = value
            
            return result if any(v for k, v in result.items() if k != "confidence") else None
            
        except Exception as e:
            print(f"⚠️ Sina Finance extraction error: {e}")
            return None
    
    def _extract_eastmoney(
        self,
        soup: BeautifulSoup,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        从东方财富提取企业信息
        """
        try:
            result = {
                "confidence": 0.75,
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
            }
            
            # 提取基本信息
            info_panel = soup.find("div", class_="info-panel")
            if info_panel:
                items = info_panel.find_all("div", class_="item")
                for item in items:
                    label = item.find("label")
                    value_elem = item.find("span")
                    
                    if label and value_elem:
                        label_text = label.get_text(strip=True).lower()
                        value_text = value_elem.get_text(strip=True)
                        
                        if "行业" in label_text:
                            result["industry"] = value_text
                        elif "地区" in label_text:
                            result["headquarters"] = value_text
            
            return result if any(v for k, v in result.items() if k != "confidence") else None
            
        except Exception as e:
            print(f"⚠️ Eastmoney extraction error: {e}")
            return None
    
    def _extract_generic(
        self,
        soup: BeautifulSoup,
        company_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        通用提取器 - 适用于未明确定义的站点
        """
        try:
            result = {
                "confidence": 0.60,  # 通用提取置信度较低
                "industry": None,
                "sector": None,
                "founded_date": None,
                "business_scope": None,
                "company_size": None,
                "employees": None,
                "headquarters": None,
                "description": None,
            }
            
            # 移除脚本和样式
            for script in soup(["script", "style"]):
                script.decompose()
            
            # 提取第一段文本作为描述
            paragraphs = soup.find_all("p")
            if paragraphs:
                text = paragraphs[0].get_text(strip=True)
                if len(text) > 30:
                    result["description"] = text[:200]
            
            # 查找包含关键词的文本
            full_text = soup.get_text(separator=" ", strip=True).lower()
            
            # 简单的关键词匹配
            if "成立" in full_text or "创立" in full_text:
                match = re.search(r"(?:成立|创立)[于在]?\s*([0-9]{4}年[0-9]{1,2}月(?:[0-9]{1,2}日)?)", full_text)
                if match:
                    result["founded_date"] = match.group(1)
            
            if "行业" in full_text:
                match = re.search(r"行业[：:]\s*(.+?)(?:[，。；]|$)", full_text)
                if match:
                    result["industry"] = match.group(1)[:50]
            
            return result if any(v for k, v in result.items() if k != "confidence") else None
            
        except Exception as e:
            print(f"⚠️ Generic extraction error: {e}")
            return None

    # ================= 行业分类后处理 ==================
    async def _init_industry_components(self):
        """延迟初始化行业分类组件。"""
        if not self._enable_industry_classify:
            return
        if self._taxonomy_registry is None:
            self._taxonomy_registry = _TaxonomyRegistry()
            # 尝试从环境或已加载的配置管理器中获取外部 taxonomy 数据（若后续集成DB，可在此替换）
            try:
                external_taxonomy = getattr(self._config_manager, 'get_industry_taxonomy', lambda: None)()
                if external_taxonomy:
                    self._taxonomy_registry.load_from_dict(external_taxonomy)
                else:
                    # 优先尝试从数据库加载
                    loaded = await self._load_taxonomy_from_db()
                    if not loaded:
                        self._taxonomy_registry.load()  # 回退本地内置
            except Exception:
                loaded = await self._load_taxonomy_from_db()
                if not loaded:
                    self._taxonomy_registry.load()
        if self._feature_extractor is None:
            self._feature_extractor = _FeatureExtractor()
        if self._industry_classifier is None:
            self._industry_classifier = _IndustryClassifier(self._taxonomy_registry)

    async def _post_process_profile(self, company_name: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        """在主流程提取完成后统一执行：
        1. 行业分类补全 / 规范化
        2. 结果缓存
        3. 低置信度触发人工队列（当前仅打印日志占位）
        """
        if not profile:
            return profile
        if not self._enable_industry_classify:
            return profile

        # 命中缓存
        cache_key = company_name.lower()
        cached = self._industry_cache.get(cache_key)
        if cached:
            # 合并缓存的 industry/sector
            if not profile.get('industry') and cached.get('industry'):
                profile['industry'] = cached['industry']
            if not profile.get('sector') and cached.get('sector'):
                profile['sector'] = cached['sector']
            return profile

        # 初始化组件
        await self._init_industry_components()

        # 若 DB 已存公司行业，直接回填并缓存
        try:
            db_hit = await self._get_company_industry_from_db(company_name)
            if db_hit and (db_hit.get('industry') or db_hit.get('sector')):
                if not profile.get('industry') and db_hit.get('industry'):
                    profile['industry'] = db_hit['industry']
                if not profile.get('sector') and db_hit.get('sector'):
                    profile['sector'] = db_hit['sector']
                # 写入缓存后返回
                self._industry_cache[cache_key] = {
                    'industry': profile.get('industry'),
                    'sector': profile.get('sector'),
                    'ts': datetime.utcnow().isoformat()
                }
                return profile
        except Exception:
            pass

        # 特征抽取
        features = self._feature_extractor.extract(profile)
        llm_callable = await self._get_custom_llm_callable()
        if self._enable_industry_llm_qa:
            if not llm_callable:
                llm = await self._get_llm_processor()
                if llm:
                    llm_callable = llm._call_azure_openai_responses  # 复用现有本地/远程 LLM 接口

        classify_result = await self._industry_classifier.classify(
            features,
            enable_llm=self._enable_industry_llm_qa,
            llm_callable=llm_callable,
            min_conf=self._industry_min_conf
        )

        # 如果原 extraction 没有 industry，使用分类
        if (not profile.get('industry')) and classify_result.get('industry'):
            profile['industry'] = classify_result['industry']
            profile['sector'] = classify_result.get('sector')
            profile.setdefault('meta', {})
            profile['meta']['industry_classification'] = classify_result
            # 持久化公司 -> 行业映射
            try:
                await self._save_company_industry_to_db(company_name, profile.get('industry'), profile.get('sector'))
            except Exception:
                pass
        else:
            # 即便已有 industry，也可以写入规范化建议
            if classify_result.get('industry'):
                profile.setdefault('meta', {})
                profile['meta']['industry_suggestion'] = classify_result

        # 缓存
        to_cache = {
            'industry': profile.get('industry'),
            'sector': profile.get('sector'),
            'ts': datetime.utcnow().isoformat()
        }
        self._industry_cache[cache_key] = to_cache

        # 持久化缓存（可选，若配置了Mongo）
        try:
            await self._save_industry_cache_to_db(company_name, to_cache)
        except Exception:
            pass

        # 低置信度人工队列（占位逻辑）
        try:
            ic = profile.get('meta', {}).get('industry_classification') or classify_result
            if ic.get('confidence', 0) < self._industry_min_conf:
                print(f"🧪 [QUEUE] 行业分类置信度低 {company_name}: {ic.get('confidence'):.2f}, 需要人工复核")
                await self._enqueue_manual_industry_review(company_name, profile, reason="low_confidence")
            # 若完全没有 industry，也触发人工
            if not profile.get('industry'):
                await self._enqueue_manual_industry_review(company_name, profile, reason="no_industry")
        except Exception:
            pass

        return profile

    # ================= 可选数据库集成（MongoDB） ==================
    def _get_mongo_collection(self, name: str):
        """惰性获取 MongoDB 集合；若未配置或不可用则返回 None。
        环境变量：
        - MONGODB_URI (mongodb://user:pwd@host:port)
        - MONGODB_DB (默认 aistock)
        - 可自定义集合名：INDUSTRY_TAXONOMY_COLLECTION / INDUSTRY_CACHE_COLLECTION / INDUSTRY_QUEUE_COLLECTION
        """
        uri = os.getenv("MONGODB_URI")
        if not uri:
            return None
        db_name = os.getenv("MONGODB_DB", "aistock")
        try:
            # 延迟导入，避免依赖问题
            from pymongo import MongoClient
            if not hasattr(self, "_mongo_client") or self._mongo_client is None:
                self._mongo_client = MongoClient(uri, tlsAllowInvalidCertificates=True)
            db = self._mongo_client[db_name]
            return db[name]
        except Exception as e:
            print(f"⚠️ MongoDB unavailable: {e}")
            return None

    async def _save_industry_cache_to_db(self, company_name: str, cache: Dict[str, Any]):
        col_name = os.getenv("INDUSTRY_CACHE_COLLECTION", "industry_cache")
        col = self._get_mongo_collection(col_name)
        if not col:
            return
        loop = asyncio.get_event_loop()
        def _upsert():
            col.update_one(
                {"company": company_name},
                {"$set": {"company": company_name, **cache}},
                upsert=True
            )
        await loop.run_in_executor(None, _upsert)

    async def _enqueue_manual_industry_review(self, company_name: str, profile: Dict[str, Any], reason: str = "manual"):
        col_name = os.getenv("INDUSTRY_QUEUE_COLLECTION", "industry_manual_queue")
        col = self._get_mongo_collection(col_name)
        if not col:
            return
        doc = {
            "company": company_name,
            "reason": reason,
            "profile": {k: v for k, v in profile.items() if k != 'sources'},
            "created_at": datetime.utcnow()
        }
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: col.insert_one(doc))

    async def _load_taxonomy_from_db(self) -> bool:
        """从 MongoDB 加载 taxonomy（如无则可自动引导写入默认）。
        预期文档结构：{ name, code?, sector?, aliases: [], keywords: [] }
        返回：是否成功加载
        """
        col_name = os.getenv("INDUSTRY_TAXONOMY_COLLECTION", "industry_taxonomy")
        col = self._get_mongo_collection(col_name)
        if not col:
            return False
        loop = asyncio.get_event_loop()
        def _fetch_all():
            return list(col.find({}, {"_id": 0}))
        try:
            docs = await loop.run_in_executor(None, _fetch_all)
            if not docs:
                # 自动引导写入默认数据
                await self._bootstrap_default_taxonomy_to_db()
                docs = await loop.run_in_executor(None, _fetch_all)
            if not docs:
                return False
            data: Dict[str, Dict[str, Any]] = {}
            for d in docs:
                name = d.get('name') or d.get('canonical')
                if not name:
                    continue
                data[name] = {
                    'code': d.get('code'),
                    'sector': d.get('sector'),
                    'aliases': d.get('aliases', []),
                    'keywords': d.get('keywords', [])
                }
            if not data:
                return False
            self._taxonomy_registry.load_from_dict(data)
            return True
        except Exception as e:
            print(f"⚠️ Load taxonomy from DB failed: {e}")
            return False

    async def _bootstrap_default_taxonomy_to_db(self):
        """当 taxonomy 集合为空时，写入一个默认的最小可用集合。"""
        col_name = os.getenv("INDUSTRY_TAXONOMY_COLLECTION", "industry_taxonomy")
        col = self._get_mongo_collection(col_name)
        if not col:
            return
        base = [
            { 'name': '信息技术', 'code': 'IT', 'sector': 'TMT', 'aliases': ['信息技术服务','IT服务','科技','技术','互联网技术','软件服务'], 'keywords': ['软件','云计算','SaaS','平台','AI','人工智能','数据中心','芯片','半导体','操作系统'] },
            { 'name': '金融', 'code': 'FIN', 'sector': '金融', 'aliases': ['金融服务','金融业','金融机构'], 'keywords': ['银行','保险','证券','基金','资产管理','理财','信贷','支付','清算'] },
            { 'name': '制造业', 'code': 'MFG', 'sector': '制造', 'aliases': ['制造','制造行业','工业制造'], 'keywords': ['生产','工厂','设备','加工','零部件','制造基地'] },
            { 'name': '互联网', 'code': 'INET', 'sector': 'TMT', 'aliases': ['互联网公司','互联网服务','在线服务','电商','电子商务'], 'keywords': ['平台','社交','搜索','广告','电商','在线','门户','社区'] },
            { 'name': '通信', 'code': 'TEL', 'sector': '通信', 'aliases': ['通讯','通信服务','运营商','通信运营'], 'keywords': ['网络','运营商','5G','通信设备','信号','基站'] },
            { 'name': '能源', 'code': 'ENE', 'sector': '能源', 'aliases': ['能源产业','能源行业'], 'keywords': ['石油','天然气','电力','新能源','光伏','风电','储能'] },
            { 'name': '医疗健康', 'code': 'HC', 'sector': '医疗', 'aliases': ['医疗','健康','大健康','医药','生物医药'], 'keywords': ['医院','药品','诊疗','医疗器械','生物','疫苗'] },
            { 'name': '教育', 'code': 'EDU', 'sector': '教育', 'aliases': ['教育培训','培训','在线教育'], 'keywords': ['学校','培训','课程','学习','K12','职业教育'] },
            { 'name': '房地产', 'code': 'RE', 'sector': '房地产', 'aliases': ['房产','地产开发','房地产开发'], 'keywords': ['楼盘','物业','开发','资产','不动产'] },
        ]
        loop = asyncio.get_event_loop()
        def _bulk_write():
            for item in base:
                col.update_one({'name': item['name']}, {'$set': item}, upsert=True)
        await loop.run_in_executor(None, _bulk_write)

    async def _get_company_industry_from_db(self, company_name: str) -> Optional[Dict[str, Any]]:
        col_name = os.getenv("COMPANY_INDUSTRY_COLLECTION", "company_industry")
        col = self._get_mongo_collection(col_name)
        if not col:
            return None
        loop = asyncio.get_event_loop()
        def _find_one():
            return col.find_one({"company": company_name}, {"_id": 0})
        try:
            doc = await loop.run_in_executor(None, _find_one)
            return doc
        except Exception:
            return None

    async def _save_company_industry_to_db(self, company_name: str, industry: Optional[str], sector: Optional[str]):
        if not industry and not sector:
            return
        col_name = os.getenv("COMPANY_INDUSTRY_COLLECTION", "company_industry")
        col = self._get_mongo_collection(col_name)
        if not col:
            return
        loop = asyncio.get_event_loop()
        def _upsert():
            col.update_one({"company": company_name}, {"$set": {"company": company_name, "industry": industry, "sector": sector, "updated_at": datetime.utcnow()}}, upsert=True)
        await loop.run_in_executor(None, _upsert)

    async def _get_custom_llm_callable(self):
        """支持通过环境变量注入自定义 LLM 可调用：
        COMPANY_PROFILE_LLM_HOOK=package.module:callable
        需返回一个可 await 的函数签名 fn(prompt:str)->str
        """
        hook = os.getenv("COMPANY_PROFILE_LLM_HOOK")
        if not hook:
            return None
        try:
            mod_name, func_name = hook.split(":", 1)
            import importlib
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, func_name)
            # 包一层以兼容同步/异步
            async def _runner(prompt: str):
                res = fn(prompt)
                if asyncio.iscoroutine(res):
                    return await res
                return res
            return _runner
        except Exception as e:
            print(f"⚠️ Custom LLM hook invalid: {e}")
            return None


