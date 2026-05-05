"""
独立 Worker 进程 — 与 API 服务完全隔离

设计目标：
  API 进程 (main.py + uvicorn) 只处理 HTTP 请求，不跑任何重型后台任务。
  本模块作为独立进程运行所有调度器和后台管道，崩溃/OOM 不影响 API。

启动方式：
  python -m app.worker          # 前台运行
  WORKER_ONLY=1 python -m app.worker  # 显式标记（Docker CMD 推荐）

环境变量：
  WORKER_MEMORY_LIMIT_MB  — 内存硬上限（MB），超过后自动重启，默认 2048
  WORKER_BATCH_SIZE       — 每次 pipeline 单批处理股票数上限，默认 50
  WORKER_STOCK_TIMEOUT    — 单只股票处理超时（秒），默认 120
  ENABLE_SCHEDULER        — 是否启用主调度器，默认 1
  ENABLE_TASK_SCHEDULER   — 是否启用画像调度器，默认 1
    ENABLE_AGENT_PIPELINE_SCHEDULER — 是否启用 Agent Pipeline 自动调度，默认 1
    AGENT_PRE_MARKET_CRON_HOUR / AGENT_PRE_MARKET_CRON_MINUTE — 盘前 Agent Pipeline 时间，默认 8:50
    AGENT_INTRADAY_CRON_HOUR / AGENT_INTRADAY_CRON_MINUTE — 盘中低频 Agent Pipeline 时间，默认 11,14:30
    AGENT_POST_MARKET_CRON_HOUR / AGENT_POST_MARKET_CRON_MINUTE — 盘后 Agent Pipeline 时间，默认 18:05
    AGENT_PIPELINE_RUN_ON_NON_TRADING_DAYS — 非交易日是否仍运行 Agent Pipeline，默认 0
"""

import os
import gc
import sys
import time
import signal
import logging
import asyncio
import threading
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from .core import logging_config  # noqa: F401 — 确保日志配置生效
from .core.db import SessionLocal, init_database

logger = logging.getLogger("app.worker")

# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------
MEMORY_LIMIT_MB = int(os.getenv("WORKER_MEMORY_LIMIT_MB", "2048"))
BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "50"))
STOCK_TIMEOUT = int(os.getenv("WORKER_STOCK_TIMEOUT", "120"))

_shutdown_event = threading.Event()


# ---------------------------------------------------------------------------
# 内存守卫
# ---------------------------------------------------------------------------
def _get_rss_mb() -> float:
    """获取当前进程 RSS（MB）"""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        # 如果没有 psutil，用 resource 模块（Linux）或返回 0
        try:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except Exception:
            return 0.0


def _memory_watchdog():
    """后台线程：定期检查内存，超限时触发 worker 自重启"""
    while not _shutdown_event.is_set():
        rss = _get_rss_mb()
        if rss > 0:
            if rss > MEMORY_LIMIT_MB:
                logger.critical(
                    "Worker 内存超限: RSS=%.0fMB > 上限 %dMB，触发自动重启",
                    rss, MEMORY_LIMIT_MB,
                )
                os._exit(1)  # 硬退出，由 Docker restart / supervisor 重启
            elif rss > MEMORY_LIMIT_MB * 0.8:
                logger.warning("Worker 内存偏高: RSS=%.0fMB (上限 %dMB)", rss, MEMORY_LIMIT_MB)
                gc.collect()
            elif rss > MEMORY_LIMIT_MB * 0.5:
                logger.info("Worker 内存: RSS=%.0fMB", rss)
        _shutdown_event.wait(30)  # 每 30 秒检查一次


# ---------------------------------------------------------------------------
# 信号处理
# ---------------------------------------------------------------------------
def _setup_signals():
    """注册优雅关闭信号"""
    def _handler(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.info("Worker 收到信号 %s，正在关闭...", sig_name)
        _shutdown_event.set()

    try:
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# 主调度器运行
# ---------------------------------------------------------------------------
async def _run_schedulers():
    """启动所有调度器并保持运行直到收到关闭信号"""
    from .tasks.scheduler import AsyncIOScheduler, configure_scheduler_jobs, TZ

    logger.info("=" * 60)
    logger.info("AIStock Worker 进程启动")
    logger.info("  PID: %d", os.getpid())
    logger.info("  内存上限: %d MB", MEMORY_LIMIT_MB)
    logger.info("  Pipeline 批次大小: %d", BATCH_SIZE)
    logger.info("  单股超时: %d 秒", STOCK_TIMEOUT)
    logger.info("=" * 60)

    # 初始化数据库
    init_database()

    sched = None
    task_sched_started = False

    try:
        # 1) 主调度器（AsyncIOScheduler）
        if os.getenv("ENABLE_SCHEDULER", "1").lower() in ("1", "true", "yes"):
            sched = AsyncIOScheduler(timezone=TZ)
            schedule_summary = configure_scheduler_jobs(sched)
            sched.start()
            logger.info("主调度器已启动: %s", schedule_summary)
        else:
            logger.warning("主调度器已禁用 (ENABLE_SCHEDULER)")

        # 2) 画像调度器（BackgroundScheduler）
        if os.getenv("ENABLE_TASK_SCHEDULER", "1").lower() in ("1", "true", "yes"):
            try:
                from .tasks.task_scheduler import init_task_scheduler
                init_task_scheduler()
                task_sched_started = True
                logger.info("画像调度器已启动")
            except Exception as e:
                logger.error("画像调度器启动失败: %s", e)
        else:
            logger.warning("画像调度器已禁用 (ENABLE_TASK_SCHEDULER)")

        # 3) 保持运行
        logger.info("Worker 就绪，等待调度任务...")
        await asyncio.to_thread(_shutdown_event.wait)

    finally:
        logger.info("Worker 正在关闭...")
        if sched and sched.running:
            sched.shutdown(wait=False)
            logger.info("主调度器已关闭")
        if task_sched_started:
            try:
                from .tasks.task_scheduler import shutdown_task_scheduler
                shutdown_task_scheduler()
                logger.info("画像调度器已关闭")
            except Exception:
                pass
        logger.info("Worker 已退出")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    _setup_signals()

    # 启动内存守卫线程
    watchdog = threading.Thread(target=_memory_watchdog, daemon=True, name="mem-watchdog")
    watchdog.start()

    try:
        asyncio.run(_run_schedulers())
    except KeyboardInterrupt:
        logger.info("Worker 被用户中断")
    except Exception:
        logger.exception("Worker 意外退出")
        sys.exit(1)


if __name__ == "__main__":
    main()
