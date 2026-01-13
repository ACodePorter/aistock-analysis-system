#!/usr/bin/env python3
"""
企业档案定时任务启动脚本

支持三种运行模式：
1. 立即执行一次
2. 定时执行（每周）
3. 测试模式（指定企业列表）

使用方法:
    # 立即执行一次
    python run_profile_scheduler.py --mode once
    
    # 启动定时任务（每周日凌晨2点执行）
    python run_profile_scheduler.py --mode schedule
    
    # 测试模式（仅更新指定企业）
    python run_profile_scheduler.py --mode test --stocks 600519,000858,600036

作者: AI Assistant
日期: 2025-11-30
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.news.company_profile_scheduler import CompanyProfileScheduler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/profile_scheduler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class ProfileSchedulerRunner:
    """定时任务运行器"""
    
    def __init__(self):
        """初始化运行器"""
        # 从环境变量读取配置
        self.mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.db_name = os.getenv("MONGO_DB_NAME", "aistock")
        
        # 创建 MongoDB 客户端
        self.mongo_client = AsyncIOMotorClient(self.mongo_uri)
        
        # 创建调度器
        self.scheduler = CompanyProfileScheduler(
            self.mongo_client,
            db_name=self.db_name
        )
        
        # APScheduler 实例
        self.job_scheduler = AsyncIOScheduler()
        
        logger.info("✅ 定时任务运行器初始化完成")
    
    async def run_once(self, stock_codes=None):
        """
        立即执行一次更新任务
        
        Args:
            stock_codes: 股票代码列表（None 表示全部）
        """
        logger.info("🚀 执行一次性更新任务")
        
        # 初始化索引
        await self.scheduler.initialize_indexes()
        
        # 执行更新
        stats = await self.scheduler.run_weekly_update(stock_codes)
        
        logger.info("✅ 一次性任务完成")
        return stats
    
    async def scheduled_job(self):
        """定时任务回调函数"""
        logger.info(f"⏰ 定时任务触发: {datetime.now()}")
        
        try:
            stats = await self.scheduler.run_weekly_update()
            logger.info(f"✅ 定时任务执行成功: {stats}")
        except Exception as e:
            logger.error(f"❌ 定时任务执行失败: {e}", exc_info=True)
    
    def start_scheduled_mode(self, cron_expr="0 2 * * 0"):
        """
        启动定时任务模式
        
        Args:
            cron_expr: Cron 表达式（默认每周日凌晨2点）
        """
        logger.info("📅 启动定时任务模式")
        logger.info(f"   Cron 表达式: {cron_expr}")
        
        # 添加定时任务
        self.job_scheduler.add_job(
            self.scheduled_job,
            trigger=CronTrigger.from_crontab(cron_expr),
            id='weekly_profile_update',
            name='企业档案每周更新',
            replace_existing=True
        )
        
        # 启动调度器
        self.job_scheduler.start()
        
        logger.info("✅ 定时任务已启动")
        logger.info("   按 Ctrl+C 停止")
        
        try:
            # 保持运行
            asyncio.get_event_loop().run_forever()
        except (KeyboardInterrupt, SystemExit):
            logger.info("⏹️ 接收到停止信号")
            self.job_scheduler.shutdown()
            logger.info("✅ 定时任务已停止")
    
    async def run_test_mode(self, stock_codes):
        """
        测试模式
        
        Args:
            stock_codes: 测试用的股票代码列表
        """
        logger.info(f"🧪 测试模式：{len(stock_codes)} 家企业")
        
        # 初始化索引
        await self.scheduler.initialize_indexes()
        
        # 执行更新
        stats = await self.scheduler.run_weekly_update(stock_codes, batch_size=5)
        
        logger.info("✅ 测试完成")
        return stats
    
    def close(self):
        """关闭连接"""
        self.mongo_client.close()
        logger.info("✅ MongoDB 连接已关闭")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="企业档案定时更新任务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行模式:
  once      立即执行一次更新任务
  schedule  启动定时任务（每周执行）
  test      测试模式（仅更新指定企业）

示例:
  # 立即执行一次
  python run_profile_scheduler.py --mode once
  
  # 启动定时任务
  python run_profile_scheduler.py --mode schedule
  
  # 测试模式
  python run_profile_scheduler.py --mode test --stocks 600519,000858
        """
    )
    
    parser.add_argument(
        '--mode',
        choices=['once', 'schedule', 'test'],
        default='once',
        help='运行模式'
    )
    
    parser.add_argument(
        '--stocks',
        type=str,
        help='股票代码列表（逗号分隔），仅在 test 模式下使用'
    )
    
    parser.add_argument(
        '--cron',
        type=str,
        default='0 2 * * 0',
        help='Cron 表达式（默认：每周日凌晨2点）'
    )
    
    args = parser.parse_args()
    
    # 创建运行器
    runner = ProfileSchedulerRunner()
    
    try:
        if args.mode == 'once':
            # 立即执行一次
            await runner.run_once()
        
        elif args.mode == 'schedule':
            # 定时任务模式
            runner.start_scheduled_mode(args.cron)
        
        elif args.mode == 'test':
            # 测试模式
            if not args.stocks:
                logger.error("❌ 测试模式需要指定 --stocks 参数")
                sys.exit(1)
            
            stock_codes = [s.strip() for s in args.stocks.split(',')]
            await runner.run_test_mode(stock_codes)
    
    finally:
        runner.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ 任务已取消")
    except Exception as e:
        logger.error(f"❌ 运行失败: {e}", exc_info=True)
        sys.exit(1)
