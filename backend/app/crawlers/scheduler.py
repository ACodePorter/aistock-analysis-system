"""
定时爬虫任务调度器

功能：
1. 定时抓取关注股票的新闻
2. 定时抓取行业政策新闻
3. 定时抓取财联社电报快讯
4. 支持配置抓取频率

作者：AI Stock Analysis Enhancement
日期：2026-01
"""

import os
import time
import logging
import threading
import schedule
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from .orchestrator import get_orchestrator, CrawlerOrchestrator
from .crawler_queue import TaskPriority

logger = logging.getLogger(__name__)


# ===== 默认关注列表 =====

# 重点关注的股票（可以从数据库/配置文件加载）
DEFAULT_WATCHLIST = [
    # 科技龙头
    {'code': '600519', 'name': '贵州茅台', 'industry': '白酒'},
    {'code': '000858', 'name': '五粮液', 'industry': '白酒'},
    {'code': '601318', 'name': '中国平安', 'industry': '保险'},
    {'code': '600036', 'name': '招商银行', 'industry': '银行'},
    {'code': '000333', 'name': '美的集团', 'industry': '家电'},
    {'code': '000651', 'name': '格力电器', 'industry': '家电'},
    
    # 新能源
    {'code': '300750', 'name': '宁德时代', 'industry': '新能源'},
    {'code': '002594', 'name': '比亚迪', 'industry': '新能源汽车'},
    {'code': '601012', 'name': '隆基绿能', 'industry': '光伏'},
    {'code': '002459', 'name': '晶澳科技', 'industry': '光伏'},
    
    # 半导体
    {'code': '688981', 'name': '中芯国际', 'industry': '半导体'},
    {'code': '002371', 'name': '北方华创', 'industry': '半导体设备'},
    {'code': '688012', 'name': '中微公司', 'industry': '半导体设备'},
    
    # 医药
    {'code': '600276', 'name': '恒瑞医药', 'industry': '创新药'},
    {'code': '300760', 'name': '迈瑞医疗', 'industry': '医疗器械'},
    
    # 互联网/科技
    {'code': '002415', 'name': '海康威视', 'industry': '安防'},
    {'code': '300059', 'name': '东方财富', 'industry': '互联网金融'},
]

# 重点关注的行业
DEFAULT_INDUSTRIES = [
    '新能源',
    '半导体',
    '人工智能',
    '光伏',
    '新能源汽车',
    '医药',
    '消费',
    '银行',
    '房地产',
]


class CrawlerScheduler:
    """爬虫定时调度器
    
    定时执行以下任务：
    1. 每4小时抓取关注股票新闻
    2. 每6小时抓取行业新闻
    3. 每30分钟抓取财联社快讯
    4. 每天凌晨清理过期数据
    """
    
    def __init__(
        self,
        orchestrator: CrawlerOrchestrator = None,
        stock_interval_hours: int = 4,
        industry_interval_hours: int = 6,
        telegraph_interval_minutes: int = 30,
    ):
        self.orchestrator = orchestrator or get_orchestrator()
        self.stock_interval = stock_interval_hours
        self.industry_interval = industry_interval_hours
        self.telegraph_interval = telegraph_interval_minutes
        
        self.is_running = False
        self.scheduler_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # 初始化关注列表
        self._init_watchlist()
    
    def _init_watchlist(self):
        """初始化关注列表"""
        for stock in DEFAULT_WATCHLIST:
            self.orchestrator.add_to_watchlist(
                stock['code'],
                stock['name'],
                stock.get('industry', '')
            )
        
        logger.info(f"[调度器] 初始化关注列表: {len(DEFAULT_WATCHLIST)} 只股票")
    
    def start(self):
        """启动调度器"""
        if self.is_running:
            return
        
        self.is_running = True
        self.stop_event.clear()
        
        # 配置定时任务
        self._setup_schedules()
        
        # 启动调度线程
        self.scheduler_thread = threading.Thread(
            target=self._run_scheduler,
            name="CrawlerScheduler",
            daemon=True
        )
        self.scheduler_thread.start()
        
        # 立即执行一次快讯抓取
        self._crawl_telegraph()
        
        logger.info("✅ [定时调度] 爬虫定时调度器已启动")
        logger.info(f"   - 股票新闻: 每 {self.stock_interval} 小时")
        logger.info(f"   - 行业新闻: 每 {self.industry_interval} 小时")
        logger.info(f"   - 财联社快讯: 每 {self.telegraph_interval} 分钟")
    
    def stop(self):
        """停止调度器"""
        if not self.is_running:
            return
        
        self.stop_event.set()
        
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        
        schedule.clear()
        self.is_running = False
        
        logger.info("⛔ [定时调度] 爬虫定时调度器已停止")
    
    def _setup_schedules(self):
        """配置定时任务"""
        # 清除旧的任务
        schedule.clear()
        
        # 股票新闻（每4小时）
        schedule.every(self.stock_interval).hours.do(self._crawl_watchlist_stocks)
        
        # 行业新闻（每6小时）
        schedule.every(self.industry_interval).hours.do(self._crawl_industries)
        
        # 财联社快讯（每30分钟）
        schedule.every(self.telegraph_interval).minutes.do(self._crawl_telegraph)
        
        # 每天凌晨2点清理过期数据
        schedule.every().day.at("02:00").do(self._cleanup_old_data)
        
        # 每天早上8点抓取一次所有关注股票
        schedule.every().day.at("08:00").do(self._crawl_watchlist_stocks)
        
        # 每天下午3点收盘后抓取一次
        schedule.every().day.at("15:30").do(self._crawl_watchlist_stocks)
    
    def _run_scheduler(self):
        """运行调度循环"""
        while not self.stop_event.is_set():
            try:
                schedule.run_pending()
                self.stop_event.wait(10)  # 每10秒检查一次
            except Exception as e:
                logger.error(f"[定时调度] 调度异常: {e}")
                time.sleep(60)
    
    def _crawl_watchlist_stocks(self):
        """抓取关注列表中的股票新闻"""
        logger.info("[定时调度] 开始抓取关注股票新闻...")
        
        watchlist = self.orchestrator.store.get_watchlist()
        
        for stock in watchlist:
            try:
                self.orchestrator.crawl_stock(
                    stock['stock_name'],
                    stock['stock_code'],
                    industry=stock.get('industry', ''),
                    priority=TaskPriority.BACKGROUND,
                )
                
                # 控制抓取速度，避免压力过大
                time.sleep(2)
            except Exception as e:
                logger.warning(f"[定时调度] 抓取 {stock['stock_name']} 失败: {e}")
        
        logger.info(f"[定时调度] 完成 {len(watchlist)} 只股票的新闻抓取任务提交")
    
    def _crawl_industries(self):
        """抓取行业新闻"""
        logger.info("[定时调度] 开始抓取行业新闻...")
        
        for industry in DEFAULT_INDUSTRIES:
            try:
                self.orchestrator.crawl_industry(
                    industry,
                    priority=TaskPriority.BACKGROUND,
                )
                time.sleep(1)
            except Exception as e:
                logger.warning(f"[定时调度] 抓取 {industry} 行业新闻失败: {e}")
        
        logger.info(f"[定时调度] 完成 {len(DEFAULT_INDUSTRIES)} 个行业的新闻抓取任务提交")
    
    def _crawl_telegraph(self):
        """抓取财联社电报快讯"""
        logger.info("[定时调度] 抓取财联社电报快讯...")
        
        try:
            self.orchestrator.crawl_telegraph(limit=50)
        except Exception as e:
            logger.warning(f"[定时调度] 抓取快讯失败: {e}")
    
    def _cleanup_old_data(self):
        """清理过期数据"""
        logger.info("[定时调度] 开始清理过期数据...")
        
        # 这里可以添加清理逻辑
        # 例如删除30天前的新闻数据
        pass
    
    def trigger_crawl(self, stock_code: str = None, industry: str = None):
        """手动触发抓取"""
        if stock_code:
            # 查找股票信息
            watchlist = self.orchestrator.store.get_watchlist()
            for stock in watchlist:
                if stock['stock_code'] == stock_code:
                    self.orchestrator.crawl_stock(
                        stock['stock_name'],
                        stock['stock_code'],
                        industry=stock.get('industry', ''),
                        priority=TaskPriority.HIGH,
                    )
                    return
            
            # 不在关注列表中，直接抓取
            self.orchestrator.crawl_stock('', stock_code, priority=TaskPriority.HIGH)
        
        elif industry:
            self.orchestrator.crawl_industry(industry, priority=TaskPriority.HIGH)


# ===== 全局实例 =====

_scheduler: Optional[CrawlerScheduler] = None


def get_scheduler() -> CrawlerScheduler:
    """获取全局调度器"""
    global _scheduler
    if _scheduler is None:
        _scheduler = CrawlerScheduler()
    return _scheduler


def start_crawler_scheduler():
    """启动爬虫定时调度"""
    scheduler = get_scheduler()
    scheduler.start()
    return scheduler


def stop_crawler_scheduler():
    """停止爬虫定时调度"""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None
