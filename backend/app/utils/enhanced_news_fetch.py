"""
增强新闻获取模块

问题：深度分析报告中很多股票新闻数为0或1，无法提供有价值的分析
解决方案：
1. 多维度搜索策略 - 当直接搜索无果时，使用行业关键词、核心产品扩展搜索
2. 行业新闻聚合 - 为信息不足的股票补充行业级新闻
3. 关联股票新闻参考 - 从同行业股票获取参考信息

使用方式：
- 与 top20_llm_agent_full.py 集成
- 在常规搜索后调用 enhance_stock_news() 补充信息

作者：AI Stock Analysis Enhancement
日期：2026-01
"""

import os
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# 尝试导入爬虫系统
try:
    from app.crawlers.orchestrator import get_orchestrator, CrawlerOrchestrator
    from app.crawlers.crawler_queue import TaskPriority
    CRAWLER_SYSTEM_AVAILABLE = True
except ImportError:
    CRAWLER_SYSTEM_AVAILABLE = False
    logger.info("[增强新闻] 爬虫系统未启用，使用传统模式")

# 尝试导入直接API模块（绕过SearXNG）
try:
    from app.utils.direct_news_api import fetch_news_direct, get_direct_api, DIRECT_API_ENABLED
    DIRECT_API_AVAILABLE = True
except ImportError:
    DIRECT_API_AVAILABLE = False
    DIRECT_API_ENABLED = False
    logger.info("[增强新闻] 直接API模块未启用")


# ============ 配置 ============
ENHANCED_SEARCH_ENABLE = os.getenv('ENHANCED_SEARCH_ENABLE', '1') in ('1', 'true', 'yes')
ENHANCED_SEARCH_MIN_NEWS = int(os.getenv('ENHANCED_SEARCH_MIN_NEWS', '2'))  # 低于此数触发增强搜索
ENHANCED_SEARCH_MAX_INDUSTRY_NEWS = int(os.getenv('ENHANCED_SEARCH_MAX_INDUSTRY_NEWS', '5'))  # 行业新闻上限
ENHANCED_SEARCH_TIMEOUT = float(os.getenv('ENHANCED_SEARCH_TIMEOUT', '30'))

# 后端API
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8080")
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:10000")


# ============ 行业分类映射 ============
INDUSTRY_TAXONOMY = {
    # 科技
    '信息技术': {
        'keywords': ['软件', '云计算', '大数据', '人工智能', 'AI', '芯片', '半导体', '集成电路', '信息安全', '网络安全'],
        'sub_industries': ['软件服务', '云计算', '大数据', '人工智能', '半导体', '电子元器件', '信息安全'],
        'search_terms': ['科技股', '数字经济', '信息化', '数字化转型']
    },
    '半导体': {
        'keywords': ['芯片', '半导体', '集成电路', 'IC设计', '晶圆', '封装测试', 'EDA', 'GPU', 'CPU', '存储芯片'],
        'sub_industries': ['芯片设计', '芯片制造', '封装测试', '半导体设备', '半导体材料'],
        'search_terms': ['芯片国产化', '半导体产业', '集成电路产业']
    },
    # 新能源
    '新能源': {
        'keywords': ['光伏', '风电', '储能', '锂电池', '新能源汽车', '充电桩', '氢能', '太阳能', '风力发电'],
        'sub_industries': ['光伏', '风电', '储能', '锂电池', '新能源汽车', '充电设施', '氢能'],
        'search_terms': ['新能源产业', '碳中和', '绿色能源', '清洁能源']
    },
    '新能源汽车': {
        'keywords': ['新能源汽车', '电动车', '智能驾驶', '自动驾驶', '动力电池', '充电桩', '换电', '电驱系统'],
        'sub_industries': ['整车制造', '动力电池', '电驱系统', '智能座舱', '充换电设施'],
        'search_terms': ['新能源车销量', '电动汽车', '智能汽车']
    },
    # 金融
    '金融': {
        'keywords': ['银行', '保险', '证券', '基金', '信托', '金融科技', '支付', '消费金融'],
        'sub_industries': ['银行', '保险', '证券', '基金', '金融科技'],
        'search_terms': ['金融监管', '利率', '信贷', '理财']
    },
    # 医疗健康
    '医疗健康': {
        'keywords': ['医药', '生物医药', '医疗器械', '创新药', '仿制药', '医疗服务', 'CXO', '疫苗', '基因'],
        'sub_industries': ['创新药', '仿制药', '医疗器械', 'CRO', 'CMO', '医疗服务', '生物制品'],
        'search_terms': ['医药产业', '生物医药', '医疗改革', '集采']
    },
    # 消费
    '消费': {
        'keywords': ['白酒', '食品饮料', '家电', '零售', '电商', '餐饮', '旅游', '酒店', '免税'],
        'sub_industries': ['白酒', '食品饮料', '家用电器', '零售', '餐饮旅游'],
        'search_terms': ['消费升级', '消费复苏', '内需', '消费数据']
    },
    # 制造业
    '制造业': {
        'keywords': ['机械设备', '工程机械', '数控机床', '工业机器人', '自动化', '智能制造'],
        'sub_industries': ['机械设备', '工业自动化', '专用设备', '通用设备'],
        'search_terms': ['制造业PMI', '工业生产', '智能制造']
    },
    # 房地产基建
    '房地产': {
        'keywords': ['房地产', '地产', '物业', '建材', '水泥', '钢铁', '玻璃', '装修'],
        'sub_industries': ['房地产开发', '物业服务', '建材', '装饰装修'],
        'search_terms': ['房地产政策', '楼市', '土地市场']
    },
    # 通信
    '通信': {
        'keywords': ['5G', '通信设备', '光通信', '物联网', '运营商', '通信服务', '光模块', '基站'],
        'sub_industries': ['通信设备', '光通信', '物联网', '运营商'],
        'search_terms': ['5G建设', '通信产业', '数字基建']
    },
}

# 北交所/科创板/创业板关键词补充
SPECIAL_BOARD_KEYWORDS = {
    '920': ['北交所', '专精特新', '创新型中小企业'],  # 北交所
    '688': ['科创板', '硬科技', '科技创新'],  # 科创板
    '300': ['创业板', '成长股', '创新企业'],  # 创业板
}

# 公司名称后缀到行业的映射（用于快速识别）
NAME_SUFFIX_INDUSTRY_MAP = {
    # 医疗健康
    '药业': '医疗健康', '制药': '医疗健康', '医药': '医疗健康', '生物': '医疗健康',
    '医疗': '医疗健康', '健康': '医疗健康', '诊断': '医疗健康', '疫苗': '医疗健康',
    '基因': '医疗健康', '细胞': '医疗健康', '医学': '医疗健康',
    # 半导体/信息技术
    '芯片': '半导体', '半导体': '半导体', '微电子': '半导体', '集成电路': '半导体',
    '微纳': '半导体', '芯': '半导体', '晶': '半导体', '封测': '半导体',
    '软件': '信息技术', '信息': '信息技术', '数据': '信息技术', '网络': '信息技术',
    '科技': '信息技术', '智能': '信息技术', '电子': '信息技术', '云': '信息技术',
    '互联': '信息技术', '数字': '信息技术', '安全': '信息技术',
    # 新能源
    '新能源': '新能源', '锂电': '新能源', '光伏': '新能源', '风电': '新能源',
    '储能': '新能源', '太阳能': '新能源', '电池': '新能源', '绿能': '新能源',
    '氢能': '新能源', '清洁': '新能源',
    # 新能源汽车
    '汽车': '新能源汽车', '整车': '新能源汽车', '电动': '新能源汽车',
    # 金融
    '银行': '金融', '保险': '金融', '证券': '金融', '基金': '金融', '信托': '金融',
    '金融': '金融', '期货': '金融', '资产': '金融',
    # 消费
    '食品': '消费', '饮料': '消费', '白酒': '消费', '乳业': '消费', '餐饮': '消费',
    '旅游': '消费', '酒店': '消费', '零售': '消费', '商业': '消费', '酒': '消费',
    '茅台': '消费', '五粮': '消费', '泸州': '消费', '汾酒': '消费',
    # 房地产
    '地产': '房地产', '置业': '房地产', '房产': '房地产', '建设': '房地产',
    '建材': '房地产', '水泥': '房地产', '钢铁': '制造业', '建工': '房地产',
    # 制造业
    '机械': '制造业', '设备': '制造业', '装备': '制造业', '重工': '制造业',
    '工业': '制造业', '制造': '制造业', '自动化': '制造业',
    # 通信
    '通信': '通信', '电信': '通信', '光纤': '通信', '基站': '通信', '光模块': '通信',
}

# 著名公司直接映射（优先级最高）- 覆盖A股主要知名企业
FAMOUS_COMPANY_INDUSTRY = {
    # === 新能源汽车 ===
    '比亚迪': '新能源汽车',
    '长城汽车': '新能源汽车',
    '广汽': '新能源汽车',
    '上汽': '新能源汽车',
    '蔚来': '新能源汽车',
    '小鹏': '新能源汽车',
    '理想': '新能源汽车',
    '吉利': '新能源汽车',
    '长安汽车': '新能源汽车',
    '北汽': '新能源汽车',
    '赛力斯': '新能源汽车',
    '零跑': '新能源汽车',
    
    # === 新能源/光伏/电池 ===
    '宁德时代': '新能源',
    '隆基': '新能源',
    '通威': '新能源',
    '阳光电源': '新能源',
    '天合光能': '新能源',
    '晶澳': '新能源',
    '晶科': '新能源',
    '亿纬锂能': '新能源',
    '国轩高科': '新能源',
    '欣旺达': '新能源',
    '比亚迪电池': '新能源',
    '特变电工': '新能源',
    '正泰': '新能源',
    '爱旭': '新能源',
    
    # === 半导体/芯片 ===
    '中芯国际': '半导体',
    '北方华创': '半导体',
    '韦尔股份': '半导体',
    '兆易创新': '半导体',
    '澜起科技': '半导体',
    '卓胜微': '半导体',
    '圣邦股份': '半导体',
    '北京君正': '半导体',
    '晶晨股份': '半导体',
    '瑞芯微': '半导体',
    '全志科技': '半导体',
    '国芯科技': '半导体',
    '紫光': '半导体',
    '海光信息': '半导体',
    '寒武纪': '半导体',
    '中微公司': '半导体',
    '华大九天': '半导体',
    '概伦电子': '半导体',
    '盛美上海': '半导体',
    '拓荆科技': '半导体',
    '华海清科': '半导体',
    '长电科技': '半导体',
    '通富微电': '半导体',
    '华天科技': '半导体',
    
    # === 消费/白酒/食品 ===
    '茅台': '消费',
    '贵州茅台': '消费',
    '五粮液': '消费',
    '泸州老窖': '消费',
    '汾酒': '消费',
    '洋河': '消费',
    '古井贡': '消费',
    '剑南春': '消费',
    '舍得': '消费',
    '水井坊': '消费',
    '伊利': '消费',
    '蒙牛': '消费',
    '海天味业': '消费',
    '金龙鱼': '消费',
    '双汇': '消费',
    '绝味': '消费',
    '安井': '消费',
    '三只松鼠': '消费',
    '良品铺子': '消费',
    '格力': '消费',
    '美的': '消费',
    '海尔': '消费',
    '小米': '消费',
    '苏泊尔': '消费',
    '老板电器': '消费',
    
    # === 金融 ===
    '中国平安': '金融',
    '招商银行': '金融',
    '工商银行': '金融',
    '农业银行': '金融',
    '建设银行': '金融',
    '中国银行': '金融',
    '交通银行': '金融',
    '兴业银行': '金融',
    '浦发银行': '金融',
    '民生银行': '金融',
    '光大银行': '金融',
    '华夏银行': '金融',
    '中信银行': '金融',
    '平安银行': '金融',
    '宁波银行': '金融',
    '南京银行': '金融',
    '北京银行': '金融',
    '中国人寿': '金融',
    '中国太保': '金融',
    '新华保险': '金融',
    '中信证券': '金融',
    '华泰证券': '金融',
    '国泰君安': '金融',
    '海通证券': '金融',
    '广发证券': '金融',
    '招商证券': '金融',
    '东方财富': '金融',
    '同花顺': '金融',
    
    # === 医疗健康 ===
    '恒瑞': '医疗健康',
    '迈瑞': '医疗健康',
    '药明': '医疗健康',
    '复星医药': '医疗健康',
    '长春高新': '医疗健康',
    '智飞生物': '医疗健康',
    '康泰生物': '医疗健康',
    '沃森生物': '医疗健康',
    '华兰生物': '医疗健康',
    '泰格医药': '医疗健康',
    '康龙化成': '医疗健康',
    '凯莱英': '医疗健康',
    '百济神州': '医疗健康',
    '君实生物': '医疗健康',
    '信达生物': '医疗健康',
    '康方生物': '医疗健康',
    '爱尔眼科': '医疗健康',
    '通策医疗': '医疗健康',
    '乐普医疗': '医疗健康',
    '鱼跃医疗': '医疗健康',
    '迈瑞医疗': '医疗健康',
    '联影医疗': '医疗健康',
    '华大基因': '医疗健康',
    '贝达药业': '医疗健康',
    
    # === 信息技术/互联网 ===
    '腾讯': '信息技术',
    '阿里': '信息技术',
    '百度': '信息技术',
    '京东': '信息技术',
    '网易': '信息技术',
    '美团': '信息技术',
    '字节': '信息技术',
    '华为': '信息技术',
    '科大讯飞': '信息技术',
    '用友': '信息技术',
    '金蝶': '信息技术',
    '广联达': '信息技术',
    '中科创达': '信息技术',
    '恒生电子': '信息技术',
    '深信服': '信息技术',
    '启明星辰': '信息技术',
    '奇安信': '信息技术',
    '绿盟科技': '信息技术',
    '浪潮': '信息技术',
    '紫光股份': '信息技术',
    '中兴': '信息技术',
    '海康威视': '信息技术',
    '大华股份': '信息技术',
    '汇川技术': '信息技术',
    '汇顶科技': '信息技术',
    '立讯精密': '信息技术',
    '歌尔': '信息技术',
    '蓝思': '信息技术',
    '领益智造': '信息技术',
    '传音控股': '信息技术',
    
    # === 通信 ===
    '中国移动': '通信',
    '中国电信': '通信',
    '中国联通': '通信',
    '中兴通讯': '通信',
    '烽火通信': '通信',
    '亨通光电': '通信',
    '中天科技': '通信',
    '光迅科技': '通信',
    '新易盛': '通信',
    '天孚通信': '通信',
    '中际旭创': '通信',
    
    # === 制造业/工业 ===
    '三一重工': '制造业',
    '中联重科': '制造业',
    '徐工机械': '制造业',
    '潍柴动力': '制造业',
    '福耀玻璃': '制造业',
    '先导智能': '制造业',
    '杭可科技': '制造业',
    '利元亨': '制造业',
    '埃斯顿': '制造业',
    '汇川': '制造业',
    '拓斯达': '制造业',
    '绿的谐波': '制造业',
    '北摩高科': '制造业',
    
    # === 房地产/基建 ===
    '万科': '房地产',
    '保利': '房地产',
    '招商蛇口': '房地产',
    '金地': '房地产',
    '绿城': '房地产',
    '龙湖': '房地产',
    '中国建筑': '房地产',
    '中国中铁': '房地产',
    '中国铁建': '房地产',
    '中国交建': '房地产',
    '海螺水泥': '房地产',
    '东方雨虹': '房地产',
    '北新建材': '房地产',
}


@dataclass
class EnhancedSearchResult:
    """增强搜索结果"""
    direct_news: List[Dict[str, Any]] = field(default_factory=list)  # 直接搜索到的新闻
    industry_news: List[Dict[str, Any]] = field(default_factory=list)  # 行业新闻
    related_stocks_news: List[Dict[str, Any]] = field(default_factory=list)  # 关联股票新闻
    search_strategies_used: List[str] = field(default_factory=list)  # 使用的搜索策略
    industry: str = ""  # 识别到的行业
    industry_keywords: List[str] = field(default_factory=list)  # 行业关键词
    diagnostics: Dict[str, Any] = field(default_factory=dict)  # 诊断信息


class EnhancedNewsFetcher:
    """增强新闻获取器
    
    优先级策略：
    1. 从信源库(NewsStore)获取已抓取的新闻
    2. 从后端数据库获取
    3. 使用爬虫系统实时抓取
    4. 最后使用SearXNG兜底
    """
    
    def __init__(self, backend_url: str = BACKEND_BASE_URL, searxng_url: str = SEARXNG_URL):
        self.backend_url = backend_url.rstrip('/')
        self.searxng_url = searxng_url.rstrip('/')
        
        # 尝试获取爬虫系统
        self._orchestrator = None
        if CRAWLER_SYSTEM_AVAILABLE:
            try:
                self._orchestrator = get_orchestrator()
            except Exception as e:
                logger.debug(f"[增强新闻] 获取爬虫调度器失败: {e}")
        # Proxy pool for SearXNG / fallback requests (comma-separated)
        raw_pool = os.getenv('SEARXNG_PROXY_POOL', '') or ''
        self.proxy_pool = [p.strip() for p in raw_pool.split(',') if p.strip()]
        self._proxy_index = 0
        # Default NEWS_HTTP_PROXY fallback
        self.default_news_proxy = os.getenv('NEWS_HTTP_PROXY') or None
    
    def _get_from_news_store(self, stock_code: str, limit: int = 15) -> List[Dict[str, Any]]:
        """从信源库获取新闻（优先级最高）
        
        信源库存储了之前抓取的所有新闻，避免重复请求
        """
        if not self._orchestrator:
            return []
        
        try:
            news = self._orchestrator.store.query_by_stock(stock_code, limit=limit, days=14)
            if news:
                logger.debug(f"[信源库] 获取 {len(news)} 条 {stock_code} 的缓存新闻")
            return news
        except Exception as e:
            logger.debug(f"[信源库] 查询失败: {e}")
            return []
    
    def _get_industry_from_news_store(self, industry: str, limit: int = 10) -> List[Dict[str, Any]]:
        """从信源库获取行业新闻"""
        if not self._orchestrator:
            return []
        
        try:
            news = self._orchestrator.store.query_by_industry(industry, limit=limit, days=14)
            return news
        except Exception as e:
            logger.debug(f"[信源库] 行业新闻查询失败: {e}")
            return []
    
    def _trigger_async_crawl(self, stock_name: str, stock_code: str, industry: str = ''):
        """触发异步爬虫抓取（不等待结果）
        
        当信源库数据不足时，触发后台爬虫补充数据
        """
        if not self._orchestrator:
            return
        
        try:
            self._orchestrator.crawl_stock(
                stock_name, 
                stock_code, 
                industry=industry,
                priority=TaskPriority.LOW  # 低优先级，不阻塞主流程
            )
            logger.debug(f"[爬虫] 已触发 {stock_name} 的后台抓取")
        except Exception as e:
            logger.debug(f"[爬虫] 触发失败: {e}")
        
    def _safe_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """安全的HTTP请求"""
        try:
            timeout = kwargs.pop('timeout', ENHANCED_SEARCH_TIMEOUT)
            # determine proxy to use
            proxies = kwargs.pop('proxies', None)
            if not proxies:
                chosen = None
                if self.proxy_pool:
                    # round-robin selection
                    chosen = self.proxy_pool[self._proxy_index % len(self.proxy_pool)]
                    self._proxy_index = (self._proxy_index + 1) % max(1, len(self.proxy_pool))
                elif self.default_news_proxy:
                    chosen = self.default_news_proxy
                if chosen:
                    proxies = {'http': chosen, 'https': chosen}
            resp = requests.request(method, url, timeout=timeout, proxies=proxies, **kwargs)
            return resp
        except Exception as e:
            logger.warning(f"Request failed for {url}: {e}")
            return None

    def _is_searxng_healthy(self, force: bool = False) -> bool:
        """快速健康检查 SearXNG 实例，结果会被短时缓存以减少请求量"""
        now = datetime.utcnow()
        last = getattr(self, '_searxng_last_check', None)
        healthy_cache = getattr(self, '_searxng_healthy', None)
        if not force and last and healthy_cache is not None and (now - last) < timedelta(seconds=30):
            return healthy_cache

        self._searxng_last_check = now
        try:
            # 首先尝试根路径
            resp = self._safe_request('get', f"{self.searxng_url}/", timeout=3)
            if resp and resp.status_code == 200:
                self._searxng_healthy = True
                return True

            # 尝试 info 页面
            resp = self._safe_request('get', f"{self.searxng_url}/info/en", timeout=3)
            if resp and resp.status_code == 200:
                self._searxng_healthy = True
                return True

            # 最后尝试简单的 search 请求
            resp = self._safe_request('get', f"{self.searxng_url}/search", params={'q': 'test', 'format': 'json'}, timeout=3)
            healthy = bool(resp and resp.status_code == 200)
            self._searxng_healthy = healthy
            if not healthy:
                logger.warning(f"SearXNG appears unhealthy at {self.searxng_url}")
            return healthy
        except Exception as e:
            logger.warning(f"SearXNG health check exception: {e}")
            self._searxng_healthy = False
            return False
    
    def _identify_industry(self, stock: Dict[str, Any], profile_data: Optional[Dict] = None) -> Tuple[str, List[str]]:
        """识别股票所属行业及关键词
        
        Args:
            stock: 股票信息 {'symbol': ..., 'name': ...}
            profile_data: 可选的股票画像数据
        
        Returns:
            (行业名称, 行业关键词列表)
        """
        name = (stock.get('name') or '').strip()
        symbol = (stock.get('symbol') or '').strip().upper()
        
        # 从profile获取行业
        if profile_data:
            industry = profile_data.get('industry', '') or profile_data.get('sub_industry', '')
            keywords = []
            
            # 提取strategic_keywords
            strategic = profile_data.get('strategic_keywords', '')
            if strategic:
                keywords.extend([k.strip() for k in strategic.split(',') if k.strip()])
            
            # 提取core_products
            products = profile_data.get('core_products', '')
            if products:
                keywords.extend([k.strip() for k in products.split(',') if k.strip()])
            
            if industry and industry in INDUSTRY_TAXONOMY:
                keywords.extend(INDUSTRY_TAXONOMY[industry].get('keywords', [])[:5])
                return industry, list(set(keywords))[:10]
        
        # 从公司名称推断行业 - 首先检查著名公司直接映射
        for famous_name, industry in FAMOUS_COMPANY_INDUSTRY.items():
            if famous_name in name:
                keywords = INDUSTRY_TAXONOMY.get(industry, {}).get('keywords', [])[:8]
                if not keywords:
                    keywords = [famous_name, '股票', 'A股']
                return industry, keywords
        
        # 然后使用后缀映射
        for suffix, industry in NAME_SUFFIX_INDUSTRY_MAP.items():
            if suffix in name:
                keywords = INDUSTRY_TAXONOMY.get(industry, {}).get('keywords', [])[:8]
                if not keywords:
                    keywords = [suffix, '股票', 'A股']
                return industry, keywords
        
        # 最后尝试行业关键词匹配
        for industry, config in INDUSTRY_TAXONOMY.items():
            for kw in config.get('keywords', []):
                if kw in name:
                    return industry, config.get('keywords', [])[:8]
        
        # 从股票代码判断板块
        if symbol:
            for prefix, board_kws in SPECIAL_BOARD_KEYWORDS.items():
                if symbol.startswith(prefix):
                    return '创新企业', board_kws
        
        return '综合', ['股票', '上市公司', 'A股']
    
    def _fetch_stock_profile(self, symbol: str) -> Optional[Dict[str, Any]]:
        """从后端获取股票画像"""
        url = f"{self.backend_url}/api/stock-profile/{symbol}"
        resp = self._safe_request('get', url, timeout=10)
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                if data.get('success'):
                    return data.get('data')
            except Exception:
                pass
        return None
    
    def _search_company_realtime(self, company_name: str, limit: int = 3) -> List[Dict[str, Any]]:
        """使用SearXNG实时搜索公司新闻
        
        当数据库和行业新闻都不足时的最后备选方案
        
        Args:
            company_name: 公司名称
            limit: 返回数量上限
        
        Returns:
            新闻列表
        """
        results = []
        seen_urls = set()
        
        # 构建搜索查询
        queries = [
            f"{company_name} 股票",
            f"{company_name} 最新消息",
        ]
        
        for query in queries:
            if len(results) >= limit:
                break
            try:
                params = {
                    'q': query,
                    'format': 'json',
                    'categories': 'news',
                    'time_range': 'week',
                    'language': 'zh-CN',
                }
                # 如果 SearXNG 不可用，回退到后端 DB 搜索接口
                if not self._is_searxng_healthy():
                    logger.warning(f"SearXNG unavailable, falling back to backend DB search for '{query}'")
                    resp = self._safe_request('get', f"{self.backend_url}/api/news/search_db", params={'query': query, 'limit': limit, 'include_content': True}, timeout=8)
                    if resp and resp.status_code == 200:
                        try:
                            data = resp.json()
                            for r in data.get('articles', []):
                                url = (r.get('url') or '').strip()
                                if not url or url in seen_urls:
                                    continue
                                seen_urls.add(url)
                                results.append({
                                    'title': (r.get('title') or '').strip(),
                                    'url': url,
                                    'content': (r.get('content') or r.get('summary') or '')[:500],
                                    'source': 'db_fallback',
                                    'search_query': query,
                                })
                                if len(results) >= limit:
                                    break
                        except Exception:
                            logger.debug(f"DB fallback parse failed for '{query}'")
                    continue

                resp = self._safe_request('get', f"{self.searxng_url}/search", params=params, timeout=15)
                
                if resp and resp.status_code == 200:
                    data = resp.json()
                    for r in data.get('results', []):
                        url = (r.get('url') or '').strip()
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        
                        results.append({
                            'title': (r.get('title') or '').strip(),
                            'url': url,
                            'content': (r.get('content') or '').strip()[:500],
                            'source': 'searx_realtime',
                            'search_query': query,
                        })
                        
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.debug(f"Company realtime search failed for '{query}': {e}")
        
        return results
    
    def _search_industry_news(self, industry: str, keywords: List[str], limit: int = 5) -> List[Dict[str, Any]]:
        """搜索行业新闻
        
        Args:
            industry: 行业名称
            keywords: 搜索关键词列表
            limit: 返回数量上限
        
        Returns:
            行业新闻列表
        """
        results = []
        
        # 获取行业搜索词
        search_terms = []
        if industry in INDUSTRY_TAXONOMY:
            search_terms = INDUSTRY_TAXONOMY[industry].get('search_terms', [])[:2]
        
        # 组合搜索词
        queries = []
        if search_terms:
            queries.append(' '.join(search_terms[:2]))
        if keywords:
            queries.append(' '.join(keywords[:3]))
        
        if not queries:
            queries = [f"{industry} 行业动态"]
        
        seen_urls = set()
        
        for query in queries[:2]:  # 最多2个查询
            try:
                params = {
                    'q': query,
                    'format': 'json',
                    'categories': 'news',
                    'time_range': 'week',
                    'language': 'zh-CN',
                }
                if not self._is_searxng_healthy():
                    logger.warning(f"SearXNG unavailable, falling back to backend DB industry search for '{query}'")
                    resp = self._safe_request('get', f"{self.backend_url}/api/news/search_db", params={'query': query, 'limit': limit, 'include_content': True}, timeout=8)
                    if resp and resp.status_code == 200:
                        try:
                            data = resp.json()
                            for r in data.get('articles', []):
                                url = (r.get('url') or '').strip()
                                if not url or url in seen_urls:
                                    continue
                                seen_urls.add(url)
                                results.append({
                                    'title': (r.get('title') or '').strip(),
                                    'url': url,
                                    'content': (r.get('content') or r.get('summary') or '')[:500],
                                    'source': 'db_fallback',
                                    'search_query': query,
                                    'is_industry_news': True,
                                })
                                if len(results) >= limit:
                                    return results
                        except Exception:
                            logger.debug(f"DB fallback parse failed for industry query '{query}'")
                    continue

                resp = self._safe_request('get', f"{self.searxng_url}/search", params=params, timeout=15)
                
                if resp and resp.status_code == 200:
                    data = resp.json()
                    for r in data.get('results', []):
                        url = (r.get('url') or '').strip()
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        
                        results.append({
                            'title': (r.get('title') or '').strip(),
                            'url': url,
                            'content': (r.get('content') or '').strip()[:500],
                            'source': 'industry_search',
                            'search_query': query,
                            'is_industry_news': True,
                        })
                        
                        if len(results) >= limit:
                            return results
            except Exception as e:
                logger.warning(f"Industry search failed for '{query}': {e}")
                continue
        
        return results
    
    def _expand_search_with_keywords(self, stock: Dict[str, Any], keywords: List[str]) -> List[Dict[str, Any]]:
        """使用扩展关键词搜索
        
        Args:
            stock: 股票信息
            keywords: 扩展关键词
        
        Returns:
            搜索到的新闻列表
        """
        name = (stock.get('name') or '').strip()
        results = []
        seen_urls = set()
        
        # 构建扩展查询
        queries = []
        
        # 公司名 + 关键词组合
        for kw in keywords[:3]:
            queries.append(f"{name} {kw}")
        
        # 仅关键词（适用于产品/技术类）
        if keywords:
            queries.append(' '.join(keywords[:2]))
        
        for query in queries[:3]:  # 限制查询次数
            try:
                params = {
                    'q': query,
                    'format': 'json',
                    'categories': 'news',
                    'time_range': 'month',
                    'language': 'zh-CN',
                }
                if not self._is_searxng_healthy():
                    logger.debug(f"SearXNG unavailable, falling back to DB for keyword expand query '{query}'")
                    resp = self._safe_request('get', f"{self.backend_url}/api/news/search_db", params={'query': query, 'limit': 5, 'include_content': True}, timeout=8)
                    if resp and resp.status_code == 200:
                        try:
                            data = resp.json()
                            for r in data.get('articles', []):
                                url = (r.get('url') or '').strip()
                                if not url or url in seen_urls:
                                    continue
                                seen_urls.add(url)
                                results.append({
                                    'title': (r.get('title') or '').strip(),
                                    'url': url,
                                    'content': (r.get('content') or r.get('summary') or '')[:500],
                                    'source': 'db_fallback',
                                    'search_query': query,
                                })
                                if len(results) >= 5:
                                    return results
                        except Exception:
                            logger.debug(f"DB fallback parse failed for keyword query '{query}'")
                    continue

                resp = self._safe_request('get', f"{self.searxng_url}/search", params=params, timeout=15)
                
                if resp and resp.status_code == 200:
                    data = resp.json()
                    for r in data.get('results', []):
                        url = (r.get('url') or '').strip()
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        
                        results.append({
                            'title': (r.get('title') or '').strip(),
                            'url': url,
                            'content': (r.get('content') or '').strip()[:500],
                            'source': 'keyword_expand',
                            'search_query': query,
                        })
                        
                        if len(results) >= 5:
                            return results
            except Exception as e:
                logger.debug(f"Keyword expand search failed for '{query}': {e}")
                continue
        
        return results
    
    def _search_db_industry_news(self, industry: str, days: int = 30, limit: int = 5) -> List[Dict[str, Any]]:
        """从数据库获取已入库的行业新闻"""
        results = []
        seen_urls = set()
        
        # 获取搜索词列表：先用search_terms，再用keywords
        search_queries = []
        if industry in INDUSTRY_TAXONOMY:
            # 先尝试单独的搜索词
            for term in INDUSTRY_TAXONOMY[industry].get('search_terms', [])[:2]:
                search_queries.append(term)
            # 再尝试关键词
            for kw in INDUSTRY_TAXONOMY[industry].get('keywords', [])[:3]:
                search_queries.append(kw)
        
        if not search_queries:
            search_queries = [industry]
        
        for query in search_queries:
            if len(results) >= limit:
                break
            try:
                params = {
                    'query': query,
                    'limit': limit - len(results),
                    'days': days,
                    'include_content': True,
                }
                
                resp = self._safe_request('get', f"{self.backend_url}/api/news/search_db", params=params, timeout=15)
                
                if resp and resp.status_code == 200:
                    data = resp.json()
                    articles = data.get('articles', [])
                    
                    for a in articles:
                        url = a.get('url', '')
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        
                        results.append({
                            'title': a.get('title', ''),
                            'url': url,
                            'content': (a.get('content') or a.get('summary') or '')[:500],
                            'source': 'db_industry',
                            'is_industry_news': True,
                            'published_at': a.get('published_at'),
                            '_is_industry_context': True,
                        })
                        
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.debug(f"DB industry search failed for '{query}': {e}")
        
        return results
    
    def enhance_stock_news(
        self,
        stock: Dict[str, Any],
        existing_news: List[Dict[str, Any]],
        min_required: int = ENHANCED_SEARCH_MIN_NEWS
    ) -> EnhancedSearchResult:
        """增强单只股票的新闻获取
        
        优先级策略（保障成功率）：
        1. 优先从信源库获取已抓取的新闻（避免重复请求）
        2. 从后端数据库获取
        3. 使用扩展关键词搜索
        4. 获取行业新闻作为背景
        5. 最后使用SearXNG兜底
        6. 数据不足时触发后台爬虫补充
        
        Args:
            stock: 股票信息 {'symbol': ..., 'name': ...}
            existing_news: 已有的新闻列表
            min_required: 最小需要的新闻数
        
        Returns:
            EnhancedSearchResult 增强结果
        """
        result = EnhancedSearchResult()
        result.direct_news = list(existing_news)
        result.diagnostics['existing_count'] = len(existing_news)
        result.diagnostics['min_required'] = min_required
        
        symbol = (stock.get('symbol') or '').strip().upper()
        name = (stock.get('name') or '').strip()
        stock_code = symbol.split('.')[0] if '.' in symbol else symbol
        
        # 获取股票画像（用于行业识别）
        profile_data = None
        if symbol:
            profile_data = self._fetch_stock_profile(symbol)
            if profile_data:
                result.diagnostics['has_profile'] = True
        
        # 识别行业
        industry, keywords = self._identify_industry(stock, profile_data)
        result.industry = industry
        result.industry_keywords = keywords
        result.diagnostics['identified_industry'] = industry
        result.diagnostics['keywords_count'] = len(keywords)
        
        # ===== 优先策略0: 从信源库获取（最高优先级，避免重复请求）=====
        store_news = self._get_from_news_store(stock_code, limit=15)
        if store_news:
            seen_urls = {n.get('url') for n in result.direct_news if n.get('url')}
            for n in store_news:
                if n.get('url') and n.get('url') not in seen_urls:
                    result.direct_news.append(n)
                    seen_urls.add(n.get('url'))
            result.search_strategies_used.append('news_store')
            result.diagnostics['news_store_count'] = len(store_news)
        
        # 如果信源库数据已足够，直接返回
        if len(result.direct_news) >= min_required:
            result.diagnostics['strategy'] = 'news_store_sufficient'
            return result
        
        # ===== 策略1: 使用扩展关键词搜索 =====
        if keywords and len(result.direct_news) < min_required:
            expanded = self._expand_search_with_keywords(stock, keywords)
            if expanded:
                result.direct_news.extend(expanded)
                result.search_strategies_used.append('keyword_expand')
                result.diagnostics['keyword_expand_count'] = len(expanded)
        
        # ===== 策略1.5: 直接API获取（SearXNG不可用时的主要信源）=====
        if len(result.direct_news) < min_required and DIRECT_API_AVAILABLE and DIRECT_API_ENABLED:
            try:
                direct_news = fetch_news_direct(
                    stock_code=symbol,
                    stock_name=name,
                    industry=industry,
                    limit=min_required - len(result.direct_news) + 3
                )
                if direct_news:
                    seen_urls = {n.get('url') for n in result.direct_news if n.get('url')}
                    added = 0
                    for n in direct_news:
                        url = n.get('url', '')
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            result.direct_news.append(n)
                            added += 1
                    if added > 0:
                        result.search_strategies_used.append('direct_api')
                        result.diagnostics['direct_api_count'] = added
                        logger.info(f"[直接API] 为 {name}({symbol}) 补充 {added} 条新闻")
            except Exception as e:
                logger.debug(f"[直接API] 获取失败: {e}")
        
        # ===== 策略2: 获取行业新闻 =====
        if len(result.direct_news) < min_required or True:  # 总是补充一些行业新闻作为背景
            # 先从信源库获取行业新闻
            store_industry_news = self._get_industry_from_news_store(industry, limit=5)
            if store_industry_news:
                result.industry_news.extend(store_industry_news)
                result.search_strategies_used.append('store_industry')
            
            # 再从DB获取
            if len(result.industry_news) < 3:
                db_industry = self._search_db_industry_news(industry, days=30, limit=5)
                if db_industry:
                    existing_urls = {n.get('url') for n in result.industry_news}
                    for n in db_industry:
                        if n.get('url') not in existing_urls:
                            result.industry_news.append(n)
                    result.search_strategies_used.append('db_industry')
            
            # ===== 策略2.5: 直接API获取行业新闻 =====
            if len(result.industry_news) < 3 and DIRECT_API_AVAILABLE and DIRECT_API_ENABLED:
                try:
                    api = get_direct_api()
                    direct_industry = api.fetch_eastmoney_industry_news(industry, limit=5)
                    if direct_industry:
                        existing_urls = {n.get('url') for n in result.industry_news}
                        for n in direct_industry:
                            if n.get('url') not in existing_urls:
                                result.industry_news.append(n)
                                existing_urls.add(n.get('url'))
                        result.search_strategies_used.append('direct_api_industry')
                        result.diagnostics['direct_api_industry_count'] = len(direct_industry)
                except Exception as e:
                    logger.debug(f"[直接API] 行业新闻获取失败: {e}")
            
            # ===== 策略3: 如果还是不足，使用SearXNG实时搜索补充 =====
            remaining = ENHANCED_SEARCH_MAX_INDUSTRY_NEWS - len(result.industry_news)
            if remaining > 0 and len(result.industry_news) < 3:
                # SearXNG行业新闻搜索
                searx_industry = self._search_industry_news(industry, keywords, limit=remaining)
                if searx_industry:
                    # 去重
                    existing_urls = {n.get('url') for n in result.industry_news}
                    for n in searx_industry:
                        if n.get('url') not in existing_urls:
                            result.industry_news.append(n)
                            existing_urls.add(n.get('url'))
                    result.search_strategies_used.append('searx_industry')
                    result.diagnostics['searx_industry_count'] = len(searx_industry)
            
            # ===== 策略4: 如果还是不足，尝试直接搜索公司名 =====
            if len(result.direct_news) + len(result.industry_news) < min_required:
                company_news = self._search_company_realtime(name, limit=3)
                if company_news:
                    result.direct_news.extend(company_news)
                    result.search_strategies_used.append('searx_company')
                    result.diagnostics['searx_company_count'] = len(company_news)
        
        # ===== 策略5: 如果数据仍不足，触发后台爬虫补充（不阻塞当前请求）=====
        total_news = len(result.direct_news) + len(result.industry_news)
        if total_news < min_required:
            self._trigger_async_crawl(name, stock_code, industry)
            result.diagnostics['triggered_async_crawl'] = True
        
        result.diagnostics['final_direct_count'] = len(result.direct_news)
        result.diagnostics['industry_news_count'] = len(result.industry_news)
        result.diagnostics['strategies_used'] = result.search_strategies_used
        
        return result


def enhance_stock_news_for_analysis(
    stock: Dict[str, Any],
    existing_news: List[Dict[str, Any]],
    backend_url: str = BACKEND_BASE_URL,
    searxng_url: str = SEARXNG_URL,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    增强新闻获取的简化接口，供 top20_llm_agent_full.py 调用
    
    Args:
        stock: 股票信息
        existing_news: 已有新闻
        backend_url: 后端URL
        searxng_url: SearXNG URL
    
    Returns:
        (合并后的新闻列表, 诊断信息)
    """
    if not ENHANCED_SEARCH_ENABLE:
        return existing_news, {'enhanced': False}
    
    try:
        fetcher = EnhancedNewsFetcher(backend_url, searxng_url)
        result = fetcher.enhance_stock_news(stock, existing_news)
        
        # 合并新闻（去重）
        # 优先使用 rich_content 标注的条目（通常来自 headless 并包含正文）
        def _priority_key(n: Dict[str, Any]):
            rich = 1 if n.get('rich_content') else 0
            content_len = len((n.get('content') or '').strip())
            pub = n.get('published_at', '')
            pub_dt = datetime.min
            if pub:
                try:
                    pub_dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                except Exception:
                    pub_dt = datetime.min
            return (rich, content_len, pub_dt)

        # 先对直接新闻按 (rich, content_len, time) 排序，rich 优先
        try:
            result.direct_news.sort(key=_priority_key, reverse=True)
        except Exception:
            pass

        all_news = list(result.direct_news)
        seen_urls = {n.get('url') for n in all_news if n.get('url')}
        
        # 添加行业新闻（标记来源）
        for n in result.industry_news:
            url = n.get('url', '')
            if url and url not in seen_urls:
                n['_is_industry_context'] = True  # 标记为行业背景信息
                all_news.append(n)
                seen_urls.add(url)
        
        diagnostics = {
            'enhanced': True,
            'industry': result.industry,
            'strategies': result.search_strategies_used,
            'direct_count': len(result.direct_news),
            'industry_count': len(result.industry_news),
            'total_count': len(all_news),
            **result.diagnostics
        }
        
        return all_news, diagnostics
    
    except Exception as e:
        logger.error(f"Enhanced news fetch failed for {stock.get('symbol')}: {e}")
        return existing_news, {'enhanced': False, 'error': str(e)}


# 并行处理多只股票的增强搜索
def batch_enhance_news(
    stocks_with_news: List[Tuple[Dict, List[Dict]]],
    max_workers: int = 4
) -> Dict[str, Tuple[List[Dict], Dict]]:
    """
    批量增强新闻获取
    
    Args:
        stocks_with_news: [(stock, existing_news), ...]
        max_workers: 并行线程数
    
    Returns:
        {symbol: (enhanced_news, diagnostics), ...}
    """
    results = {}
    
    def process_one(item: Tuple[Dict, List[Dict]]) -> Tuple[str, List[Dict], Dict]:
        stock, news = item
        symbol = stock.get('symbol', 'unknown')
        enhanced, diag = enhance_stock_news_for_analysis(stock, news)
        return symbol, enhanced, diag
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one, item): item for item in stocks_with_news}
        
        for future in as_completed(futures):
            try:
                symbol, enhanced, diag = future.result()
                results[symbol] = (enhanced, diag)
            except Exception as e:
                item = futures[future]
                symbol = item[0].get('symbol', 'unknown')
                results[symbol] = (item[1], {'error': str(e)})
    
    return results


# ============ 用于生成更有价值分析的辅助函数 ============

def generate_industry_context_prompt(
    industry: str,
    industry_news: List[Dict[str, Any]],
    max_news: int = 3
) -> str:
    """生成行业背景提示词
    
    用于在LLM分析时提供行业上下文
    """
    if not industry_news:
        return ""
    
    news_summaries = []
    for n in industry_news[:max_news]:
        title = n.get('title', '')[:80]
        content = n.get('content', '')[:150]
        if title:
            news_summaries.append(f"- {title}: {content}")
    
    if not news_summaries:
        return ""
    
    return f"""
【{industry}行业背景】
近期行业动态：
{chr(10).join(news_summaries)}

请在分析该股票时考虑上述行业背景信息。
"""


def get_industry_trend_factors(industry: str) -> List[Dict[str, Any]]:
    """获取行业趋势因子（用于分析报告）"""
    # 预定义的行业趋势因子
    INDUSTRY_FACTORS = {
        '新能源': [
            {'factor': '碳中和政策推进', 'direction': 'positive', 'weight': 0.3},
            {'factor': '原材料价格波动', 'direction': 'neutral', 'weight': 0.2},
            {'factor': '产能扩张风险', 'direction': 'negative', 'weight': 0.15},
        ],
        '半导体': [
            {'factor': '国产替代加速', 'direction': 'positive', 'weight': 0.35},
            {'factor': '技术封锁风险', 'direction': 'negative', 'weight': 0.2},
            {'factor': '下游需求周期', 'direction': 'neutral', 'weight': 0.15},
        ],
        '医疗健康': [
            {'factor': '医保控费压力', 'direction': 'negative', 'weight': 0.2},
            {'factor': '创新药审批加速', 'direction': 'positive', 'weight': 0.25},
            {'factor': '老龄化趋势利好', 'direction': 'positive', 'weight': 0.2},
        ],
        '金融': [
            {'factor': '利率政策影响', 'direction': 'neutral', 'weight': 0.3},
            {'factor': '资产质量压力', 'direction': 'negative', 'weight': 0.2},
            {'factor': '政策支持实体', 'direction': 'positive', 'weight': 0.15},
        ],
        '消费': [
            {'factor': '消费复苏预期', 'direction': 'positive', 'weight': 0.25},
            {'factor': '价格竞争加剧', 'direction': 'negative', 'weight': 0.15},
            {'factor': '品牌升级趋势', 'direction': 'positive', 'weight': 0.2},
        ],
    }
    
    return INDUSTRY_FACTORS.get(industry, [
        {'factor': '行业信息不足', 'direction': 'neutral', 'weight': 0.5}
    ])


if __name__ == '__main__':
    # 测试代码
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    # 测试单只股票
    test_stock = {
        'symbol': '688002.SH',
        'name': '睿创微纳',
    }
    test_news = []  # 模拟无新闻情况
    
    enhanced, diag = enhance_stock_news_for_analysis(test_stock, test_news)
    
    print(f"\n=== 增强搜索结果 ===")
    print(f"原始新闻数: {diag.get('existing_count', 0)}")
    print(f"增强后新闻数: {diag.get('total_count', len(enhanced))}")
    print(f"识别行业: {diag.get('industry', 'N/A')}")
    print(f"使用策略: {diag.get('strategies', [])}")
    print(f"\n新闻标题:")
    for i, n in enumerate(enhanced[:5], 1):
        print(f"  {i}. {n.get('title', 'N/A')[:60]}...")
