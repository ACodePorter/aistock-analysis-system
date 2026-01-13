"""
后台定期任务调度模块

功能：
- 每周自动更新所有股票的公司画像数据
- 使用 APScheduler 实现定时任务
- 支持任务重试和错误处理
- 记录任务执行日志和统计

调度规则：
- 每周一 02:00 执行更新任务
- 更新所有已监控的股票信息
- 避免重复处理相同股票
"""

import logging
import json
from typing import List, Optional
from datetime import datetime, timedelta
from functools import wraps

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..core.models import StockProfile, Watchlist
from ..utils.stock_profile_enrichment import StockProfileEnricher
from ..core.db import SessionLocal, engine


logger = logging.getLogger(__name__)


def ensure_watchlist_columns():
    """
    确保 watchlist 表有 last_updated_at 列
    在应用启动时调用此函数以检查和创建缺失的列
    """
    try:
        inspector = inspect(engine)
        
        if 'watchlist' not in inspector.get_table_names():
            logger.warning("⚠️  watchlist 表不存在，跳过列检查")
            return
        
        columns = [col['name'] for col in inspector.get_columns('watchlist')]
        
        if 'last_updated_at' not in columns:
            logger.info("➕ 检测到 watchlist 表缺少 last_updated_at 列，正在添加...")
            
            db_session = SessionLocal()
            try:
                from sqlalchemy import text
                
                # 根据数据库类型执行相应的 SQL
                db_dialect = engine.dialect.name
                
                if db_dialect == 'postgresql':
                    sql = "ALTER TABLE watchlist ADD COLUMN last_updated_at TIMESTAMP NULL;"
                elif db_dialect == 'sqlite':
                    sql = "ALTER TABLE watchlist ADD COLUMN last_updated_at TIMESTAMP NULL;"
                elif db_dialect == 'mysql':
                    sql = "ALTER TABLE watchlist ADD COLUMN last_updated_at TIMESTAMP NULL COMMENT '最后一次资讯更新完成时间';"
                else:
                    logger.warning(f"⚠️  不支持的数据库类型: {db_dialect}")
                    return
                
                db_session.execute(text(sql))
                db_session.commit()
                logger.info("✅ 成功添加 last_updated_at 列到 watchlist 表")
                
            except Exception as e:
                logger.warning(f"⚠️  添加列时出错（可能已存在）: {e}")
                db_session.rollback()
            finally:
                db_session.close()
        else:
            logger.info("✓ watchlist 表已有 last_updated_at 列")
    
    except Exception as e:
        logger.error(f"❌ 检查 watchlist 列时出错: {e}")


class ScheduledTaskManager:
    """后台任务管理器"""
    
    def __init__(self):
        # 在初始化时检查并确保数据库列存在
        ensure_watchlist_columns()
        
        self.scheduler = BackgroundScheduler()
        self.enricher = StockProfileEnricher()
        self.task_stats = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'last_run': None,
            'next_run': None
        }
        self.is_running = False  # 标记是否正在执行任务
        
        # 实时进度跟踪
        self.current_progress = {
            'is_running': False,
            'current_stock_index': 0,
            'total_stocks': 0,
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'current_stock': None,
            'current_stock_name': None,
            'start_time': None,
            'last_update_at': None
        }
    
    def start(self):
        """启动任务调度器"""
        if not self.scheduler.running:
            # 添加周期任务：每周一 02:00 执行
            self.scheduler.add_job(
                func=self.update_all_stock_profiles,
                trigger=CronTrigger(day_of_week=0, hour=2, minute=0),  # 周一 02:00
                id='stock_profile_update',
                name='Weekly Stock Profile Update',
                replace_existing=True,
                misfire_grace_time=3600  # 如果错过，1小时内仍可补执行
            )
            
            self.scheduler.start()
            logger.info("✅ 后台任务调度器已启动")
            self.log_schedule_info()
            
            # 启动后在后台线程中立即执行一次 Profile 更新
            # （不使用 APScheduler 的 date trigger，而是用后台任务）
            import threading
            def run_initial_update():
                import time
                time.sleep(5)  # 等待 5 秒确保系统完全初始化
                logger.info("🚀 启动后初始 Profile 更新任务...")
                try:
                    self.update_all_stock_profiles()
                except Exception as e:
                    logger.error(f"❌ 初始 Profile 更新失败: {str(e)}")
            
            thread = threading.Thread(target=run_initial_update, daemon=True)
            thread.start()
    
    def shutdown(self):
        """关闭任务调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("✅ 后台任务调度器已关闭")
    
    def log_schedule_info(self):
        """记录调度信息"""
        try:
            jobs = self.scheduler.get_jobs()
            for job in jobs:
                logger.info(f"📅 已安排任务: {job.name}")
                logger.info(f"   - ID: {job.id}")
                logger.info(f"   - 触发器: {job.trigger}")
                logger.info(f"   - 下次执行: {job.next_run_time}")
        except Exception as e:
            logger.error(f"记录调度信息失败: {e}")
    
    def update_all_stock_profiles(self, delay_between_stocks: float = 2.0):
        """
        更新所有股票的公司画像数据
        
        参数：
            delay_between_stocks: 相邻两只股票更新之间的延迟时间（秒），默认 2 秒，避免被ban
        
        流程：
        1. 获取所有需要更新的股票列表
        2. 逐个调用 LLM 分析更新
        3. 每只股票间隔适度延迟（避免爬虫被ban）
        4. 记录成功/失败统计
        5. 生成执行报告
        """
        if self.is_running:
            logger.warning("⚠️ 任务已在运行中，跳过本次请求")
            return
        
        self.is_running = True
        
        try:
            logger.info("=" * 80)
            logger.info("🚀 开始股票数据更新任务")
            logger.info(f"⏱️  爬虫速率: {delay_between_stocks} 秒/股票 (避免被ban)")
            logger.info("=" * 80)
            
            start_time = datetime.now()
            self.task_stats['last_run'] = start_time
            self.task_stats['successful'] = 0
            self.task_stats['failed'] = 0
            
            # 初始化实时进度
            import time
            self.current_progress = {
                'is_running': True,
                'current_stock_index': 0,
                'total_stocks': 0,
                'processed': 0,
                'successful': 0,
                'failed': 0,
                'current_stock': None,
                'current_stock_name': None,
                'start_time': time.time(),
                'last_update_at': datetime.now()
            }
            
            # 获取数据库会话
            db_session = SessionLocal()
            
            try:
                # 获取所有需要更新的股票
                stocks_to_update = self._get_stocks_for_update(db_session)
                self.task_stats['total'] = len(stocks_to_update)
                self.current_progress['total_stocks'] = len(stocks_to_update)
                
                logger.info(f"📊 找到 {len(stocks_to_update)} 只股票需要更新")
                
                if len(stocks_to_update) == 0:
                    logger.warning("⚠️ 没有找到需要更新的股票")
                    return
                
                # 逐个更新（带延迟控制）
                for idx, (symbol, company_name) in enumerate(stocks_to_update, 1):
                    try:
                        # 更新进度信息
                        self.current_progress['current_stock_index'] = idx
                        self.current_progress['current_stock'] = symbol
                        self.current_progress['current_stock_name'] = company_name
                        self.current_progress['last_update_at'] = datetime.now()
                        
                        logger.info(f"🔄 [{idx}/{len(stocks_to_update)}] 正在更新: {company_name} ({symbol})")
                        
                        # 调用 enricher 进行分析（使用同步包装器）
                        try:
                            logger.debug(f"   调用 enricher.enrich_stock_profile_sync()...")
                            result = self.enricher.enrich_stock_profile_sync(
                                symbol=symbol,
                                company_name=company_name,
                                db=db_session,
                                force_refresh=True  # 强制刷新，不使用缓存
                            )
                            logger.debug(f"   enricher 返回: {result is not None}")
                        except Exception as inner_e:
                            logger.error(f"❌ enricher 调用异常: {str(inner_e)}", exc_info=True)
                            raise
                        
                        # 更新 Watchlist 表的 last_updated_at 字段
                        try:
                            self._update_watchlist_timestamp(db_session, symbol)
                        except Exception as inner_e:
                            logger.warning(f"⚠️ 更新 Watchlist 时间戳失败: {str(inner_e)}")
                        
                        self.task_stats['successful'] += 1
                        self.current_progress['successful'] += 1
                        self.current_progress['processed'] += 1
                        logger.info(f"✅ 成功更新: {symbol} (已处理: {self.current_progress['processed']})")
                        
                        # 在更新之间添加适度延迟，避免爬虫被 ban
                        if idx < len(stocks_to_update):
                            logger.info(f"⏳ 等待 {delay_between_stocks} 秒后继续...")
                            time.sleep(delay_between_stocks)
                        
                    except Exception as e:
                        self.task_stats['failed'] += 1
                        self.current_progress['failed'] += 1
                        self.current_progress['processed'] += 1
                        logger.error(f"❌ 更新失败: {symbol} - {str(e)}")
                        # 继续处理其他股票，不中断
                        # 失败也延迟，避免频繁重试被ban
                        if idx < len(stocks_to_update):
                            logger.info(f"⏳ 等待 {delay_between_stocks} 秒后继续...")
                            time.sleep(delay_between_stocks)
                
                # 生成报告
                self._generate_report(start_time)
                
            finally:
                db_session.close()
        
        except Exception as e:
            logger.error(f"❌ 任务执行出错: {str(e)}", exc_info=True)
            self.task_stats['failed'] = self.task_stats['total']
        
        finally:
            self.is_running = False
            # 清除进度信息
            self.current_progress['is_running'] = False
            self.current_progress['last_update_at'] = datetime.now()
    
    def _get_stocks_for_update(self, db_session: Session) -> List[tuple]:
        """
        获取需要更新的股票列表
        
        新策略（已更新）：
        - 从 NewsArticle.related_stocks JSON 字段中提取所有唯一的股票代码
        - 这包含所有出现在新闻中的股票（~2930 只），而不仅仅是 Watchlist 中的 5 只
        - 按完成度排序，优先更新完成度最低的股票
        
        Returns:
            [(symbol, company_name), ...] 列表，按完成度从低到高排序
        """
        try:
            from ..core.models import NewsArticle
            
            logger.info("📰 从 NewsArticle.related_stocks 中提取所有股票...")
            
            # Step 1: 从所有新闻文章中提取股票代码
            all_articles = db_session.query(NewsArticle.related_stocks).filter(
                NewsArticle.related_stocks.isnot(None)
            ).all()
            
            all_symbols = set()
            for row in all_articles:
                if row[0] and isinstance(row[0], list):
                    all_symbols.update(row[0])
            
            all_symbols_list = sorted(list(all_symbols))
            logger.info(f"✅ 从 {len(all_articles)} 篇新闻中提取 {len(all_symbols_list)} 个不同的股票代码")
            
            if len(all_symbols_list) == 0:
                logger.warning("⚠️  没有从新闻中找到任何股票")
                return []
            
            # Step 2: 检查这些股票的 Profile 完成度
            stocks_with_completion = []
            
            for symbol in all_symbols_list:
                profile = db_session.query(StockProfile).filter(
                    StockProfile.symbol == symbol
                ).first()
                
                if profile:
                    # 计算完成度
                    fields = [
                        profile.industry,
                        profile.business_summary,
                        profile.core_products,
                        profile.competitive_position,
                        profile.competitors,
                        profile.strategic_keywords,
                        profile.risk_factors,
                        profile.history_highlights,
                        profile.profile_json
                    ]
                    filled_count = sum(1 for f in fields if f)
                    completion_percentage = (filled_count / 9) * 100 if fields else 0
                    
                    company_name = profile.company_name or symbol
                    stocks_with_completion.append((symbol, company_name, completion_percentage))
                else:
                    # 如果没有 Profile 记录，创建一个
                    try:
                        new_profile = StockProfile(
                            symbol=symbol,
                            company_name=None  # 稍后会更新
                        )
                        db_session.add(new_profile)
                        db_session.commit()
                        stocks_with_completion.append((symbol, symbol, 0.0))
                    except Exception as e:
                        logger.warning(f"⚠️  为 {symbol} 创建 Profile 记录失败: {e}")
                        stocks_with_completion.append((symbol, symbol, 0.0))
            
            # Step 3: 按完成度排序（优先更新完成度最低的）
            stocks_with_completion.sort(key=lambda x: x[2])
            
            logger.info(f"📊 股票完成度统计:")
            completed_count = sum(1 for _, _, completion in stocks_with_completion if completion >= 50)
            logger.info(f"   - 已完成 (≥50%): {completed_count} 只")
            logger.info(f"   - 待完成 (<50%): {len(stocks_with_completion) - completed_count} 只")
            logger.info(f"   - 平均完成度: {(sum(c for _, _, c in stocks_with_completion) / len(stocks_with_completion)):.1f}%")
            
            # 返回前 N 个不完整的股票
            incomplete_stocks = [(symbol, name) for symbol, name, completion in stocks_with_completion if completion < 50]
            logger.info(f"📋 本次将更新 {len(incomplete_stocks[:100])} 个不完整股票（总数 {len(incomplete_stocks)}）")
            
            return incomplete_stocks
        
        except Exception as e:
            logger.error(f"❌ 获取股票列表失败: {e}", exc_info=True)
            return []
    
    def _generate_report(self, start_time: datetime):
        """生成任务执行报告"""
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        report = {
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'total_stocks': self.task_stats['total'],
            'successful': self.task_stats['successful'],
            'failed': self.task_stats['failed'],
            'success_rate': (
                f"{(self.task_stats['successful'] / self.task_stats['total'] * 100):.2f}%" 
                if self.task_stats['total'] > 0 
                else "N/A"
            )
        }
        
        logger.info("=" * 80)
        logger.info("📈 任务执行报告")
        logger.info("=" * 80)
        logger.info(f"执行时间: {report['timestamp']}")
        logger.info(f"总耗时: {duration:.2f} 秒")
        logger.info(f"总数: {report['total_stocks']}")
        logger.info(f"成功: {report['successful']}")
        logger.info(f"失败: {report['failed']}")
        logger.info(f"成功率: {report['success_rate']}")
        logger.info("=" * 80)
        
        return report
    
    def _update_watchlist_timestamp(self, db_session: Session, symbol: str):
        """
        更新 Watchlist 表中该股票的 last_updated_at 时间戳
        
        参数：
            db_session: 数据库会话
            symbol: 股票代码
        """
        try:
            from ..core.models import Watchlist
            
            watchlist = db_session.query(Watchlist).filter(
                Watchlist.symbol == symbol
            ).first()
            
            if watchlist:
                watchlist.last_updated_at = datetime.now()
                db_session.commit()
                logger.debug(f"✏️  已更新 {symbol} 的 last_updated_at 时间戳")
            else:
                logger.warning(f"⚠️  未找到 Watchlist 中的 {symbol} 记录")
        except Exception as e:
            logger.error(f"❌ 更新 Watchlist 时间戳失败 ({symbol}): {str(e)}")
            # 不抛出异常，以免中断主流程
    
    def get_next_run_time(self) -> Optional[datetime]:
        """获取下一次任务执行时间"""
        try:
            job = self.scheduler.get_job('stock_profile_update')
            if job:
                return job.next_run_time
        except Exception as e:
            logger.error(f"获取下次执行时间失败: {e}")
        return None
    
    def get_stats(self) -> dict:
        """获取任务统计信息"""
        return {
            **self.task_stats,
            'next_run': self.get_next_run_time().isoformat() if self.get_next_run_time() else None,
            'is_running': self.is_running
        }
    
    def get_progress(self) -> dict:
        """
        获取当前实时进度信息
        
        返回格式:
        {
            'is_running': bool,
            'current_stock_index': int,
            'total_stocks': int,
            'processed': int,
            'successful': int,
            'failed': int,
            'progress_percentage': float,
            'current_stock': str,
            'current_stock_name': str,
            'elapsed_time_seconds': int,
            'estimated_remaining_seconds': int,
            'speed_stocks_per_minute': float,
            'last_update_at': str
        }
        """
        import time
        
        progress = self.current_progress.copy()
        
        # 计算进度百分比
        if progress['total_stocks'] > 0:
            progress['progress_percentage'] = (progress['processed'] / progress['total_stocks']) * 100
        else:
            progress['progress_percentage'] = 0
        
        # 计算耗时
        if progress['start_time']:
            elapsed = time.time() - progress['start_time']
            progress['elapsed_time_seconds'] = int(elapsed)
            
            # 计算处理速度和预计剩余时间
            if progress['processed'] > 0:
                speed = progress['processed'] / (elapsed / 60)  # 股/分钟
                progress['speed_stocks_per_minute'] = round(speed, 2)
                
                remaining = progress['total_stocks'] - progress['processed']
                if speed > 0:
                    remaining_minutes = remaining / speed
                    progress['estimated_remaining_seconds'] = int(remaining_minutes * 60)
                else:
                    progress['estimated_remaining_seconds'] = 0
            else:
                progress['speed_stocks_per_minute'] = 0
                progress['estimated_remaining_seconds'] = 0
        else:
            progress['elapsed_time_seconds'] = 0
            progress['estimated_remaining_seconds'] = 0
            progress['speed_stocks_per_minute'] = 0
        
        # 确保 last_update_at 是 ISO 格式字符串
        if progress['last_update_at'] and isinstance(progress['last_update_at'], datetime):
            progress['last_update_at'] = progress['last_update_at'].isoformat()
        
        return progress
    
    def run_now_async(self, delay_between_stocks: float = 2.0):
        """
        立即异步执行一次更新任务（在后台线程中）
        
        参数：
            delay_between_stocks: 相邻两只股票更新之间的延迟时间（秒），默认 2 秒
        
        返回：
            dict: 包含任务状态的响应
        """
        import threading
        
        if self.is_running:
            return {
                'success': False,
                'message': '任务已在运行中，请稍后重试',
                'is_running': True
            }
        
        # 在后台线程中运行任务
        task_thread = threading.Thread(
            target=self.update_all_stock_profiles,
            args=(delay_between_stocks,),
            daemon=True,
            name='stock-profile-update-async'
        )
        task_thread.start()
        
        logger.info(f"✅ 已启动异步更新任务 (爬虫延迟: {delay_between_stocks}s/股)")
        
        return {
            'success': True,
            'message': '异步更新任务已启动',
            'is_running': True,
            'delay_between_stocks': delay_between_stocks,
            'stats': self.get_stats()
        }


# 全局任务管理器实例
_task_manager = None


def init_task_scheduler():
    """初始化并启动任务调度器"""
    global _task_manager
    if _task_manager is None:
        _task_manager = ScheduledTaskManager()
        _task_manager.start()
    return _task_manager


def get_task_manager() -> ScheduledTaskManager:
    """获取任务管理器实例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = ScheduledTaskManager()
    return _task_manager


def shutdown_task_scheduler():
    """关闭任务调度器"""
    global _task_manager
    if _task_manager is not None:
        _task_manager.shutdown()
        _task_manager = None

