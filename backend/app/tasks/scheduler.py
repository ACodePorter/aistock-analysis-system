"""
模块说明（中文）
此模块负责后端定时任务调度与日常数据管道的 orchestrator。主要职责包括：
- 按计划拉取并持久化自选股的历史日线数据与资金流向（EOD 数据），避免盘中数据污染；
- 计算并写入技术指标信号（signals），对 symbol+trade_date 去重；
- 调用增强预测模型生成未来若干日的预测（forecasts），按 run_at 分批次写入；
- 触发增强/智能/数据中心新闻采集流程，并提供若干手动触发接口；
- 运行宏观新闻观测流水线、模型训练作业与日报生成作业；
- 使用 APScheduler 的 AsyncIOScheduler 进行作业注册与管理，支持基于 CRON 的调度；
- 提供每日 Agent 智能分析（Top20 等）定时触发的包装作业。

主要环境变量
- TZ: 调度器时区，默认 "Asia/Taipei"。
- FORECAST_AHEAD_DAYS: 预测天数，默认 5。
- CRON_HOUR / CRON_MINUTE: 主日常管道运行时间（默认 16:10）。
- CRON_HOUR2 / CRON_MINUTE2: 收盘后保障作业运行时间（默认 16:30）。

新闻相关：
- NEWS_CENTER_CRON_EVERY_HOURS: 新闻数据中心作业运行间隔（小时），默认 2。
- NEWS_CENTER_CRON_MINUTE: 新闻数据中心作业运行分钟，默认 5。

宏观相关：
- MACRO_CRON_HOUR / MACRO_CRON_MINUTE: 宏观观测流水线运行时间（默认 19:45）。
- MACRO_TRAIN_CRON_HOUR / MACRO_TRAIN_CRON_MINUTE: 宏观模型训练作业运行时间（默认 20:15）。
- MACRO_REPORT_CRON_HOUR / MACRO_REPORT_CRON_MINUTE: 宏观日报生成作业运行时间（默认 20:45）。

Agent 相关：
- AGENT_DAILY_CRON_HOUR / AGENT_DAILY_CRON_MINUTE: 每日 Agent 作业运行时间（默认 20:10）。
- ENABLE_AGENT_PIPELINE_SCHEDULER: 是否启用 Agent Pipeline 自动调度，默认 1。
- AGENT_PRE_MARKET_CRON_HOUR / AGENT_PRE_MARKET_CRON_MINUTE: 盘前 Agent Pipeline 时间，默认 8:50。
- AGENT_INTRADAY_CRON_HOUR / AGENT_INTRADAY_CRON_MINUTE: 盘中低频 Agent Pipeline 时间，默认 11,14:30。
- AGENT_POST_MARKET_CRON_HOUR / AGENT_POST_MARKET_CRON_MINUTE: 盘后 Agent Pipeline 时间，默认 18:05。
- AGENT_PIPELINE_RUN_ON_NON_TRADING_DAYS: 非交易日是否仍运行 Agent Pipeline，默认 0。

关键函数及行为（异步函数为 async）
- run_daily_pipeline() -> bool
    执行完整日常管道。流程概述：
        1) 遍历启用的自选股（Watchlist.enabled），拉取近三年日线并按 (symbol, trade_date) UPSERT 到 prices_daily；
        2) 从数据库读取该股票历史价，样本足够则计算技术信号并写入 signals（按 symbol+trade_date 去重）；
        3) 使用增强预测模型预测未来 AHEAD 天价格，结果写入 forecasts（包含 yhat、上下界、model 与 run_at）；
        4) 拉取个股资金流向并 UPSERT 到 fund_flow_daily，仅写入已收盘日期以避免盘中数据污染；
        5) 完成后触发增强新闻采集 run_enhanced_daily_news_collection。
    返回 True 表示流程成功；遇到不可恢复错误会抛出异常并记录日志。

- run_enhanced_daily_news_collection()
    触发并运行增强新闻采集器（EnhancedNewsScheduler.run_daily_news_collection），记录并返回采集统计（status、duration_seconds、articles_found 等）。
    异常时记录日志并向上抛出。

- run_news_center_collection()
    按固定频率执行“新闻数据中心”采集任务（增量入库）。
    通常先运行常规每日收集（广泛抓取与处理），再运行滚动补齐（rolling top-up）以尽量保证每股每日达到最低篇数。
    异常时记录日志并向上抛出。

- run_intelligent_news_collection()
    基于自选股与策略运行智能新闻采集（EnhancedNewsScheduler.run_intelligent_news_collection），返回策略执行统计。
    异常时记录日志并向上抛出。

- run_news_collection()
    传统/备份新闻采集流程（NewsScheduler.run_scheduled_news_collection），主要用于容灾或历史兼容。
    异常时记录日志（不向上抛出，避免影响调度器稳定）。

- run_manual_intelligent_collection()
    手动触发智能新闻采集的包装，异常时会抛出。

- run_manual_news_collection(symbol: str)
    手动为指定股票触发新闻采集。会先校验 symbol 是否存在于 watchlist，若存在则调用 NewsScheduler 的单股采集方法。
    异常时记录日志并向上抛出。

- run_macro_observation_pipeline()
    执行宏观新闻观测流水线（macro pipeline），记录观测数量、错误数量与耗时。
    异常时记录日志并向上抛出。

- run_macro_training_job()
    执行宏观新闻驱动模型训练作业。若数据集为空则返回 None 并记录 warning；否则记录模型指标并返回训练结果。
    异常时记录日志并向上抛出。

- run_macro_report_job()
    生成并存储每日宏观日报，记录产物统计；若无输出则返回 None。
    异常时记录日志并向上抛出。

- configure_scheduler_jobs(sched: AsyncIOScheduler) -> dict
    仅注册作业（不启动 sched），并返回作业计划摘要。作业包含：
        - daily_pipeline（CRON_HOUR:CRON_MINUTE）
        - daily_pipeline_post_close（CRON_HOUR2:CRON_MINUTE2）
        - intelligent_news_collection（每 4 小时）
        - legacy_news_collection（每 12 小时）
        - news_center_collection（每 N 小时，N=NEWS_CENTER_CRON_EVERY_HOURS，分钟=NEWS_CENTER_CRON_MINUTE）
        - macro_observation_pipeline（MACRO_CRON_*）
        - macro_training_job（MACRO_TRAIN_CRON_*）
        - macro_report_job（MACRO_REPORT_CRON_*）
        - agent_daily_job（AGENT_DAILY_CRON_*；内部包装调用 run_agent）

- attach_scheduler(app)
    将 AsyncIOScheduler 挂载到给定的 app（例如 FastAPI app）并启动调度。
    启动后会把 scheduler 存入 app.state.scheduler，便于运行时管理与关闭。启动失败时会抛出异常。

副作用与外部依赖
- 依赖外部组件：数据库 SessionLocal 与 engine、ORM models（Watchlist、PriceDaily、Signal、Forecast、FundFlowDaily 等）、
  数据拉取函数（fetch_daily、fetch_fund_flow_daily）、信号计算（compute_signals）、预测模型（predict_stock_price）、
  新闻采集调度器（NewsScheduler、EnhancedNewsScheduler）、宏观流水线与报告组件等。
- 对数据库执行大量插入/UPSERT 操作并显式提交事务；应确保连接池与事务管理在高并发/长任务场景下的健壮性。
- 采用 pandas 从数据库读取历史数据用于信号计算与预测输入。

错误与稳定性说明
- 对单只股票的处理采用局部提交以降低回滚范围；若外部组件（预测/新闻/宏观流水线等）失败，相关调用会记录日志并（多数情况下）抛出异常。
- 调度作业普遍设置 max_instances=1 以避免重入；生产环境需配置合适的时区与 CRON 环境变量以保证作业按预期执行。

"""
import os
import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, insert, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timedelta, date
from functools import partial
import pandas as pd

from ..core.db import SessionLocal, engine
from ..core.models import Watchlist, PriceDaily, Signal, Forecast, Task, TaskType, TaskStatus, StockPoolMember
from .pipeline_recorder import persist_pipeline_run, TailCollector
from ..data.data_source import fetch_daily, fetch_fund_flow_daily
from ..analysis.signals import compute_signals
from ..prediction.forecast import predict_stock_price
from ..reports.report import plain_summary, llm_summarize
from ..news.news_service import NewsScheduler
from ..news.news_strategy import NewsStrategyScheduler
from ..news.enhanced_news_scheduler import EnhancedNewsScheduler
from ..reports.macro_pipeline import run_pipeline as run_macro_pipeline
from ..reports.macro_model_trainer import run_training_job as run_macro_training
from ..reports.macro_report import generate_and_store_macro_report

TZ = os.getenv("TZ", "Asia/Taipei")
AHEAD = int(os.getenv("FORECAST_AHEAD_DAYS", "5"))

logger = logging.getLogger(__name__)

TRUTHY_ENV_VALUES = {"1", "true", "yes", "y", "on"}


# ========== A股交易日判断 ==========
# 统一交易日历实现已迁移到 core.trading_calendar，本模块仅转发并保留原函数名，
# 以避免外部调用方出现破坏性变更。
from ..core.trading_calendar import (
    is_trading_day,
    last_trading_day_on_or_before,
    get_next_n_trading_days,
)


def get_last_trading_day(d: date | None = None) -> date:
    """向后兼容别名：等价于 core.trading_calendar.last_trading_day_on_or_before。"""
    return last_trading_day_on_or_before(d)


def _env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in TRUTHY_ENV_VALUES


def _run_scheduled_agent_pipeline(pipeline_type: str) -> dict | None:
    """由 APScheduler 调用的 Agent Pipeline 包装器。"""
    today = date.today()
    if not _env_enabled("AGENT_PIPELINE_RUN_ON_NON_TRADING_DAYS", "0") and not is_trading_day(today):
        logger.info(
            "Skipping scheduled Agent Pipeline %s - %s is not a trading day",
            pipeline_type,
            today,
        )
        return {"status": "skipped", "pipelineType": pipeline_type, "reason": "non_trading_day"}

    try:
        from ..agent_runtime.pipeline_orchestrator import AgentPipelineOrchestrator
        from ..agent_runtime.schemas import UserAgentContext

        result = AgentPipelineOrchestrator().run_pipeline(
            pipeline_type,
            triggered_by="scheduler",
            context=UserAgentContext(currentPage="scheduler"),
        )
        logger.info(
            "Scheduled Agent Pipeline completed: type=%s status=%s run=%s duration_ms=%s",
            pipeline_type,
            result.get("status"),
            result.get("pipelineRunId"),
            result.get("durationMs"),
        )
        return result
    except Exception as exc:
        logger.exception("Scheduled Agent Pipeline %s failed: %s", pipeline_type, exc)
        return {"status": "failed", "pipelineType": pipeline_type, "error": str(exc)}


def _configure_agent_pipeline_jobs(sched: AsyncIOScheduler) -> dict[str, tuple[str, str]] | str:
    if not _env_enabled("ENABLE_AGENT_PIPELINE_SCHEDULER", "1"):
        return "disabled"

    pre_market_hour = os.getenv("AGENT_PRE_MARKET_CRON_HOUR", "8")
    pre_market_minute = os.getenv("AGENT_PRE_MARKET_CRON_MINUTE", "50")
    intraday_hour = os.getenv("AGENT_INTRADAY_CRON_HOUR", "11,14")
    intraday_minute = os.getenv("AGENT_INTRADAY_CRON_MINUTE", "30")
    post_market_hour = os.getenv("AGENT_POST_MARKET_CRON_HOUR", "18")
    post_market_minute = os.getenv("AGENT_POST_MARKET_CRON_MINUTE", "5")

    agent_pipeline_jobs = {
        "agent_pipeline_pre_market": ("pre-market", pre_market_hour, pre_market_minute),
        "agent_pipeline_intraday": ("intraday", intraday_hour, intraday_minute),
        "agent_pipeline_post_market": ("post-market", post_market_hour, post_market_minute),
    }

    for job_id, (pipeline_type, pipeline_hour, pipeline_minute) in agent_pipeline_jobs.items():
        sched.add_job(
            partial(_run_scheduled_agent_pipeline, pipeline_type),
            CronTrigger(hour=pipeline_hour, minute=pipeline_minute),
            id=job_id,
            replace_existing=True,
            max_instances=1,
        )
    return {
        "pre_market": (pre_market_hour, pre_market_minute),
        "intraday": (intraday_hour, intraday_minute),
        "post_market": (post_market_hour, post_market_minute),
    }


def _scheduled_agent_daily_job() -> None:
    try:
        from ..main import run_agent
        import anyio

        async def _inner():
            await run_agent(strict_json=False)

        anyio.run(_inner)
    except Exception as e:
        logging.getLogger(__name__).warning('Scheduled agent run failed: %s', e, exc_info=True)


def _scheduled_stock_pool_daily() -> None:
    try:
        from ..services.stock_pool_service import daily_top20_to_pool
        daily_top20_to_pool()
    except Exception as e:
        logging.getLogger(__name__).warning('Stock pool daily top20 failed: %s', e, exc_info=True)


def _scheduled_daily_analysis_job() -> None:
    try:
        from ..analysis.analysis_engine import AnalysisEngine
        from ..analysis.report_generator import DailyReportGenerator

        _logger = logging.getLogger(__name__)
        today = date.today()
        if not is_trading_day(today):
            _logger.info("Skipping daily analysis - %s is not a trading day", today)
            return

        _logger.info("Starting scheduled daily analysis job...")
        with SessionLocal() as session:
            engine = AnalysisEngine(session)
            results = engine.analyze_watchlist(today)
            saved = engine.save_analysis_results(results)
            _logger.info("Daily analysis completed: %d stocks analyzed, %d saved", len(results), saved)

            if results:
                generator = DailyReportGenerator(session)
                generator.generate_report(today, results)
                _logger.info("Daily report generated")
    except Exception as e:
        logging.getLogger(__name__).error('Scheduled daily analysis failed: %s', e, exc_info=True)


def _scheduled_weekly_potential_evaluation() -> None:
    try:
        from ..core.models import Watchlist
        from ..analysis.analysis_engine import AnalysisEngine

        _logger = logging.getLogger(__name__)
        _logger.info("Starting weekly investment potential evaluation...")
        with SessionLocal() as session:
            pool_syms = session.execute(
                text("SELECT symbol FROM stock_pool_members WHERE exit_date IS NULL")
            ).fetchall()
            pool_symbol_set = {r.symbol for r in pool_syms}
            watchlist = session.execute(
                select(Watchlist).where(Watchlist.symbol.in_(pool_symbol_set))
            ).scalars().all()

            engine = AnalysisEngine(session)
            removal_suggestions = 0

            for item in watchlist:
                result = engine.evaluate_investment_potential(item.symbol, lookback_days=90)
                item.investment_potential = result['investment_potential']
                if result['should_remove']:
                    item.remove_suggested = True
                    item.remove_reason = result['remove_reason']
                    removal_suggestions += 1

            session.commit()
            _logger.info(
                "Potential evaluation completed: %d stocks, %d removal suggestions",
                len(watchlist),
                removal_suggestions,
            )
    except Exception as e:
        logging.getLogger(__name__).error('Weekly potential evaluation failed: %s', e, exc_info=True)


def _scheduled_hourly_incremental_analysis() -> None:
    global _last_incremental_analysis_time, _last_watchlist_hash
    try:
        from ..analysis.analysis_engine import AnalysisEngine
        from ..analysis.report_generator import DailyReportGenerator
        from ..core.models import DailyAnalysis
        import hashlib

        _logger = logging.getLogger(__name__)
        today = date.today()
        if not is_trading_day(today):
            return

        now = datetime.now()
        if not (9 <= now.hour < 16):
            return

        with SessionLocal() as session:
            pool_rows = session.execute(
                text("SELECT symbol FROM stock_pool_members WHERE exit_date IS NULL")
            ).fetchall()

            symbols = sorted([r.symbol for r in pool_rows])
            current_hash = hashlib.md5(",".join(symbols).encode()).hexdigest()
            if _last_watchlist_hash == current_hash:
                return

            _logger.info("Watchlist changed, running incremental analysis...")
            new_symbols = _find_incremental_analysis_symbols(session, symbols, today)

            if new_symbols:
                _logger.info("Analyzing %d new stocks: %s", len(new_symbols), new_symbols)
                engine = AnalysisEngine(session)
                for symbol in new_symbols:
                    try:
                        result = engine.analyze_stock(symbol, today)
                        if result:
                            engine.save_analysis_results([result])
                            _logger.info("Incremental analysis completed for %s", symbol)
                    except Exception as e:
                        _logger.warning("Failed to analyze %s: %s", symbol, e)

                results = engine.analyze_watchlist(today)
                if results:
                    generator = DailyReportGenerator(session)
                    generator.generate_report(today, results)
                    _logger.info("Daily report regenerated after incremental analysis")

            _last_watchlist_hash = current_hash
            _last_incremental_analysis_time = datetime.now()
    except Exception as e:
        logging.getLogger(__name__).error('Hourly incremental analysis failed: %s', e, exc_info=True)


def _find_incremental_analysis_symbols(session, symbols: list[str], today: date) -> list[str]:
    from ..core.models import DailyAnalysis, Watchlist

    watchlist = session.execute(
        select(Watchlist).where(Watchlist.symbol.in_(symbols))
    ).scalars().all()

    if _last_watchlist_hash:
        candidates = [w.symbol for w in watchlist if w.added_at and w.added_at.date() == today]
    else:
        candidates = [w.symbol for w in watchlist]

    return [
        symbol for symbol in candidates
        if not session.execute(
            select(DailyAnalysis).where(
                DailyAnalysis.symbol == symbol,
                DailyAnalysis.analysis_date == today,
            )
        ).scalar_one_or_none()
    ]


def _scheduled_noon_profile_completion() -> None:
    try:
        _log = logging.getLogger(__name__)
        _log.info("[Scheduler] 每日画像补全任务开始")

        try:
            from ..services.stock_pool_service import daily_top_to_pool
            result = daily_top_to_pool(top_n=10)
            _log.info("[Scheduler] 新股入池完成: %s", result)
        except Exception as e:
            _log.warning("[Scheduler] 新股入池失败: %s", e)

        from ..services.stock_pool_service import check_pool_profile_status, _run_profile_completion
        status = check_pool_profile_status()
        incomplete = status.get("incomplete", 0)
        if incomplete > 0:
            _log.info("[Scheduler] 发现 %d 只未完成画像，启动补全", incomplete)
            _run_profile_completion(batch_limit=0, delay=3.0, force=False)
        else:
            _log.info("[Scheduler] 所有股票池画像已完成")
    except Exception as e:
        logging.getLogger(__name__).error("[Scheduler] 每日画像补全失败: %s", e, exc_info=True)


def _scheduled_daily_signal_generation() -> None:
    try:
        from ..prediction.services.signal_engine import run_daily_signal_generation
        report = run_daily_signal_generation()
        logger.info(
            "Daily signal generation: buy=%d sell=%d hold=%d scored=%d",
            len(report.buy_signals),
            len(report.sell_signals),
            len(report.hold_signals),
            report.total_stocks_scored,
        )
    except Exception as e:
        logger.error("Daily signal generation failed: %s", e, exc_info=True)


def _scheduled_daily_portfolio_optimization() -> None:
    try:
        from ..prediction.services.portfolio_optimizer import run_daily_portfolio_optimization
        result = run_daily_portfolio_optimization()
        n_pos = len([a for a in result.assets if a.quantity > 0])
        logger.info(
            "Daily portfolio optimization: %d positions, vol=%.1f%%, dd=%.1f%%",
            n_pos,
            result.risk.portfolio_annual_vol * 100,
            result.risk.max_drawdown * 100,
        )
    except Exception as e:
        logger.error("Daily portfolio optimization failed: %s", e, exc_info=True)


def _scheduled_daily_paper_trading() -> None:
    try:
        from ..prediction.services.paper_trading import run_daily_paper_trading
        report = run_daily_paper_trading()
        if report.snapshot:
            logger.info(
                "Paper trading %s: NAV=%.4f ret=%+.2f%% dd=%.2f%% buys=%d sells=%d",
                report.run_date, report.snapshot.nav,
                report.snapshot.total_return * 100,
                report.snapshot.max_drawdown * 100,
                report.buy_count, report.sell_count,
            )
    except Exception as e:
        logger.error("Daily paper trading failed: %s", e, exc_info=True)


def _scheduled_prediction_evaluation() -> None:
    try:
        from ..prediction.services.continuous_learning import run_daily_evaluation
        report = run_daily_evaluation()
        logger.info(
            "Daily prediction evaluation: synced=%d backfilled=%d critical=%d",
            report.forecasts_synced,
            report.actuals_backfilled,
            report.monitoring.critical if report.monitoring else 0,
        )
    except Exception as e:
        logger.error("Daily prediction evaluation failed: %s", e, exc_info=True)


def _scheduled_weekly_model_retrain() -> None:
    try:
        from ..prediction.services.continuous_learning import run_weekly_retrain
        report = run_weekly_retrain()
        n_retrained = sum(1 for r in report.retrain_results if r.success)
        n_improved = sum(1 for r in report.retrain_results if r.improved)
        logger.info(
            "Weekly retrain: %d retrained, %d improved, %.1fs",
            n_retrained, n_improved, report.total_time_sec,
        )
    except Exception as e:
        logger.error("Weekly model retrain failed: %s", e, exc_info=True)


def _scheduled_event_factor_scan() -> None:
    try:
        from ..prediction.framework.event_alpha import extract_events_from_db
        from ..core.database import SessionLocal as EventSessionLocal
        from ..core.models import Watchlist
        import datetime as _dt

        session = EventSessionLocal()
        try:
            symbols = [
                r.symbol for r in
                session.query(Watchlist.symbol).filter(Watchlist.status == "active").all()
            ]
            if not symbols:
                return
            end = _dt.date.today()
            start = end - _dt.timedelta(days=3)
            events, event_df = extract_events_from_db(session, symbols, start, end)
            logger.info(
                "Event factor scan: %d events detected, %d rows for %d symbols",
                len(events), len(event_df) if event_df is not None else 0, len(symbols),
            )
        finally:
            session.close()
    except Exception as e:
        logger.error("Event factor scan failed: %s", e, exc_info=True)


# 记录上次增量分析的时间戳
_last_incremental_analysis_time = None
_last_watchlist_hash = None

async def run_daily_pipeline() -> bool:
    """执行日常数据管道。

    步骤：
    1) 遍历启用的自选股，拉取近三年日线并 UPSERT 到 prices_daily
    2) 计算技术指标信号，追加写入 signals（按 symbol+trade_date 去重）
    3) 运行增强预测模型，将预测结果写入 forecasts（按 run_at 区分批次）
    4) 拉取个股资金流向（仅保留已收盘的日期，避免盘中污染 EOD 表）
    5) 触发增强新闻采集

    资源保护：
    - WORKER_BATCH_SIZE 限制单批处理数量（默认 50）
    - WORKER_STOCK_TIMEOUT 限制单只股票超时（默认 120 秒）
    - 每只股票独立 session + 定期 GC
    """
    import gc

    batch_size = int(os.getenv("WORKER_BATCH_SIZE", "50"))
    stock_timeout = int(os.getenv("WORKER_STOCK_TIMEOUT", "120"))

    now = datetime.now()
    today = now.date()

    if not is_trading_day(today):
        logger.info("Skipping daily pipeline - %s is not a trading day", today)
        return True

    watches, skip_count = _load_daily_pipeline_watches(batch_size)
    success_count = fail_count = 0

    total_this_run = len(watches)
    logger.info("Daily pipeline starting for %d stocks (skipped %d)", total_this_run, skip_count)

    for idx, w in enumerate(watches, 1):
        result = await _process_daily_pipeline_stock(w, now, today, stock_timeout)
        if result == "success":
            success_count += 1
        elif result == "failed":
            fail_count += 1
        if idx % 20 == 0:
            logger.info("Daily pipeline progress: %d/%d stocks processed", idx, total_this_run)
        if idx % 10 == 0:
            gc.collect()

        # 让出 event loop 给其他协程（如 HTTP 请求处理）
        await asyncio.sleep(0)

    # 清理过期 forecast 数据
    with SessionLocal() as session:
        try:
            session.execute(text("DELETE FROM forecasts WHERE target_date < current_date - interval '30 days'"))
            session.commit()
            logger.info("Cleaned up old forecast records")
        except Exception as e:
            logger.warning("Failed to clean old forecasts: %s", e)

    gc.collect()
    logger.info("Daily pipeline completed: %d success, %d failed out of %d", success_count, fail_count, success_count + fail_count)
    await run_enhanced_daily_news_collection()

    return fail_count == 0


def _load_daily_pipeline_watches(batch_size: int):
    with SessionLocal() as session:
        pool_rows = session.execute(text("""
            SELECT spm.symbol, COALESCE(sp.company_name, wl.name) AS name
            FROM stock_pool_members spm
            LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
            LEFT JOIN watchlist wl ON spm.symbol = wl.symbol
            WHERE spm.exit_date IS NULL
        """)).fetchall()
        watches = [type('W', (), {'symbol': r.symbol, 'name': r.name})() for r in pool_rows]

    total = len(watches)
    if batch_size > 0 and total > batch_size:
        logger.info(
            "Daily pipeline: %d stocks total, processing first %d (WORKER_BATCH_SIZE=%d)",
            total, batch_size, batch_size,
        )
        return watches[:batch_size], total - batch_size
    return watches, 0


def _persist_daily_prices(session, symbol: str, start: str) -> int:
    df = fetch_daily(symbol, start_date=start)
    fetched_rows = 0
    if df.empty:
        return fetched_rows

    fetched_rows = int(len(df))
    insert_price_sql = """
    INSERT INTO prices_daily (symbol, trade_date, open, high, low, close, pct_chg, vol, amount)
    SELECT :symbol, :trade_date, :open, :high, :low, :close, :pct_chg, :vol, :amount
    WHERE NOT EXISTS (
        SELECT 1 FROM prices_daily WHERE symbol = :symbol AND trade_date = :trade_date
    )
    """
    for _, row in df.iterrows():
        session.execute(text(insert_price_sql), {
            "symbol": row["symbol"],
            "trade_date": row["trade_date"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "pct_chg": row.get("pct_chg"),
            "vol": (int(row["vol"]) if pd.notna(row["vol"]) else None),
            "amount": row.get("amount"),
        })
    session.commit()
    return fetched_rows


def _load_symbol_price_history(symbol: str):
    return pd.read_sql_query(
        "SELECT trade_date, open, high, low, close, pct_chg, vol, amount FROM prices_daily WHERE symbol = %s ORDER BY trade_date",
        con=engine,
        params=(symbol,),
    )


def _persist_skip_runs(symbol: str, message: str) -> None:
    for run_type in ("compute_signal", "predict"):
        persist_pipeline_run(
            symbol=symbol,
            run_type=run_type,
            status="skipped",
            trigger="scheduler",
            message=message,
        )


def _persist_fund_flow(session, symbol: str, start: str, today: date) -> None:
    try:
        ff_df = fetch_fund_flow_daily(symbol, start_date=start, include_today_rank=False)
        if ff_df.empty:
            return

        from ..core.models import FundFlowDaily
        for _, row in ff_df.iterrows():
            if row.get("trade_date") == today:
                continue
            try:
                stmt = pg_insert(FundFlowDaily.__table__).values(
                    symbol=row["symbol"],
                    trade_date=row["trade_date"],
                    main_net=row.get("main_net"),
                    main_ratio=row.get("main_ratio"),
                    super_net=row.get("super_net"),
                    super_ratio=row.get("super_ratio"),
                    large_net=row.get("large_net"),
                    large_ratio=row.get("large_ratio"),
                    medium_net=row.get("medium_net"),
                    medium_ratio=row.get("medium_ratio"),
                    small_net=row.get("small_net"),
                    small_ratio=row.get("small_ratio"),
                ).on_conflict_do_nothing(index_elements=["symbol", "trade_date"])
                session.execute(stmt)
            except Exception:
                _persist_fund_flow_row_fallback(session, row)
        session.commit()
    except Exception as e_ff:
        logger.warning("Fund flow fetch failed for %s: %s", symbol, e_ff)
        try:
            session.rollback()
        except Exception:
            pass


def _persist_fund_flow_row_fallback(session, row) -> None:
    insert_ff_sql = """
    INSERT INTO fundflow_daily (symbol, trade_date, main_net, main_ratio, super_net, super_ratio, large_net, large_ratio, medium_net, medium_ratio, small_net, small_ratio)
    SELECT :symbol, :trade_date, :main_net, :main_ratio, :super_net, :super_ratio, :large_net, :large_ratio, :medium_net, :medium_ratio, :small_net, :small_ratio
    WHERE NOT EXISTS (
        SELECT 1 FROM fundflow_daily WHERE symbol = :symbol AND trade_date = :trade_date
    )
    """
    session.execute(text(insert_ff_sql), {
        "symbol": row["symbol"],
        "trade_date": row["trade_date"],
        "main_net": row.get("main_net"),
        "main_ratio": row.get("main_ratio"),
        "super_net": row.get("super_net"),
        "super_ratio": row.get("super_ratio"),
        "large_net": row.get("large_net"),
        "large_ratio": row.get("large_ratio"),
        "medium_net": row.get("medium_net"),
        "medium_ratio": row.get("medium_ratio"),
        "small_net": row.get("small_net"),
        "small_ratio": row.get("small_ratio"),
    })


def _as_date(value):
    if isinstance(value, str):
        return pd.Timestamp(value).date()
    if hasattr(value, 'date'):
        return value.date() if callable(getattr(value, 'date', None)) else value
    return value


def _persist_latest_signal(session, symbol: str, qdf) -> None:
    sig_df = compute_signals(qdf)
    last_sig = sig_df.iloc[-1]
    insert_sig_sql = """
    INSERT INTO signals (symbol, trade_date, ma_short, ma_long, rsi, macd, signal_score, action)
    SELECT :symbol, :trade_date, :ma_short, :ma_long, :rsi, :macd, :signal_score, :action
    WHERE NOT EXISTS (
        SELECT 1 FROM signals WHERE symbol = :symbol AND trade_date = :trade_date
    )
    """
    session.execute(text(insert_sig_sql), {
        "symbol": symbol,
        "trade_date": last_sig["trade_date"],
        "ma_short": last_sig["ma_s"],
        "ma_long": last_sig["ma_l"],
        "rsi": last_sig["rsi"],
        "macd": last_sig["macd"],
        "signal_score": last_sig["signal_score"],
        "action": last_sig["action"],
    })
    persist_pipeline_run(
        symbol=symbol,
        run_type="compute_signal",
        status="success",
        trigger="scheduler",
        message=f"trade_date={last_sig['trade_date']}",
    )


async def _run_prediction_with_timeout(qdf, symbol: str, stock_timeout: int):
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, predict_stock_price, qdf, symbol, AHEAD),
            timeout=stock_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Prediction timed out for %s after %ds", symbol, stock_timeout)
        return {}


def _persist_forecasts(session, symbol: str, qdf, prediction_result: dict, run_at: datetime) -> None:
    predictions = prediction_result.get("predictions") or []
    if not predictions:
        return

    model_name = prediction_result.get("method", "enhanced").upper()
    last_data_date = _as_date(qdf["trade_date"].iloc[-1])
    future_trading_days = get_next_n_trading_days(last_data_date, AHEAD)

    for i, pred in enumerate(predictions):
        target_date = future_trading_days[i] if i < len(future_trading_days) else last_data_date + timedelta(days=pred["day"])
        stmt_fc = insert(Forecast).values(
            symbol=symbol,
            run_at=run_at,
            target_date=target_date,
            model=model_name,
            yhat=float(pred["predicted_price"]),
            yhat_lower=float(pred["lower_bound"]),
            yhat_upper=float(pred["upper_bound"]),
        )
        session.execute(stmt_fc)


async def _process_daily_pipeline_stock(w, now: datetime, today: date, stock_timeout: int) -> str:
    import time as _time_mod

    started = _time_mod.monotonic()
    tail = TailCollector().attach()
    status = "success"
    message: str | None = None
    error_message: str | None = None

    with SessionLocal() as session:
        try:
            start = (now - timedelta(days=365 * 3)).strftime("%Y%m%d")
            fetched_rows = _persist_daily_prices(session, w.symbol, start)
            persist_pipeline_run(
                symbol=w.symbol,
                run_type="fetch_daily",
                status="success" if fetched_rows > 0 else "skipped",
                trigger="scheduler",
                message=f"rows={fetched_rows} start={start}" if fetched_rows > 0 else f"no_rows start={start}",
            )

            qdf = _load_symbol_price_history(w.symbol)
            if len(qdf) < 50:
                logger.debug("Skipping %s - only %d price rows (need 50)", w.symbol, len(qdf))
                status = "skipped"
                message = f"insufficient_rows={len(qdf)} need>=50"
                _persist_skip_runs(w.symbol, message)
                return "skipped"

            _persist_fund_flow(session, w.symbol, start, today)
            latest_date = _as_date(qdf["trade_date"].iloc[-1])
            data_age_days = (today - latest_date).days
            if data_age_days > 5:
                status = "skipped"
                message = f"last_date={latest_date} behind today by {data_age_days} days"
                logger.debug("Skipping %s signal/forecast - data %d days stale (latest=%s)", w.symbol, data_age_days, latest_date)
                _persist_skip_runs(w.symbol, message)
                return "success"

            _persist_latest_signal(session, w.symbol, qdf)
            prediction_result = await _run_prediction_with_timeout(qdf, w.symbol, stock_timeout)
            _persist_forecasts(session, w.symbol, qdf, prediction_result, now)
            forecast_count = len(prediction_result.get("predictions", []))
            persist_pipeline_run(
                symbol=w.symbol,
                run_type="predict",
                status="success" if forecast_count else "skipped",
                trigger="scheduler",
                message=f"forecast_points={forecast_count}" if forecast_count else "no_forecast_generated",
            )
            session.commit()
            message = (
                f"forecast_points={forecast_count} method={prediction_result.get('method', 'unknown')}"
                if prediction_result else "no_forecast_generated"
            )
            return "success"
        except Exception as e:
            logger.warning("Daily pipeline failed for %s: %s", w.symbol, e)
            try:
                session.rollback()
            except Exception:
                pass
            status = "failed"
            error_message = f"{type(e).__name__}: {e}"
            return "failed"
        finally:
            try:
                tail.detach()
                persist_pipeline_run(
                    symbol=w.symbol,
                    run_type="daily_pipeline",
                    status=status,
                    trigger="scheduler",
                    duration_ms=int((_time_mod.monotonic() - started) * 1000),
                    message=message,
                    error_message=error_message,
                    log_excerpt=tail.excerpt(),
                )
            except Exception as persist_error:
                logger.debug("persist pipeline_run swallowed: %s", persist_error)

async def run_enhanced_daily_news_collection():
    """执行增强新闻采集任务。

    - 汇总结果并打印关键统计，便于观测质量与性能
    """
    try:
        enhanced_scheduler = EnhancedNewsScheduler()
        result = await enhanced_scheduler.run_daily_news_collection()
        
        logger.info(
            "Enhanced daily news collection completed",
            extra={
                "event": "enhanced_news_collection",
                "status": result.get('status', 'unknown'),
                "duration_seconds": result.get('duration_seconds', 0.0),
                "articles_found": result.get('statistics', {}).get('articles_found', 0),
                "articles_saved": result.get('statistics', {}).get('articles_saved', 0),
                "duplicates_skipped": result.get('statistics', {}).get('duplicates_skipped', 0),
            },
        )
        return result
        
    except Exception as e:
        logger.exception("Enhanced daily news collection failed: %s", e)
        raise

async def run_news_center_collection():
    """按固定频率执行“新闻数据中心”采集任务（增量入库）。

    说明：
    - 与智能 Agent 解耦，仅负责通过 SearXNG→抓取→富化→去重→入库（PostgreSQL/Mongo）。
    - 由调度器每 N 小时运行一次（默认 2 小时，可通过环境变量 NEWS_CENTER_CRON_EVERY_HOURS 配置）。
    - 可与其他新闻策略作业并存（如 intelligent/legacy），建议 max_instances=1 防重入。
    """
    try:
        scheduler = EnhancedNewsScheduler()
        result = await scheduler.run_daily_news_collection()
        # 先运行常规每日收集（包含广泛抓取与处理）
        # 然后运行滚动补齐，确保每股每日至少 N 篇（默认 5）
        try:
            topup = await scheduler.run_rolling_topup_collection()
            logger.info("Rolling top-up completed", extra={"event": "news_topup", "summary": topup})
        except Exception as te:
            logger.warning(f"Rolling top-up failed: {te}")
        logger.info(
            "News center collection completed",
            extra={
                "event": "news_center_collection",
                "status": result.get('status', 'unknown'),
                "duration_seconds": result.get('duration_seconds', 0.0),
                "articles_found": result.get('statistics', {}).get('articles_found', 0),
                "articles_saved": result.get('statistics', {}).get('articles_saved', 0),
                "duplicates_skipped": result.get('statistics', {}).get('duplicates_skipped', 0),
            },
        )
        return result
    except asyncio.CancelledError:
        logger.warning("News center collection was cancelled (server shutting down?)")
        raise
    except Exception as e:
        logger.exception("News center collection failed: %s", e)
        raise

async def run_intelligent_news_collection():
    """基于自选股与策略的智能新闻采集。"""
    try:
        enhanced_scheduler = EnhancedNewsScheduler()
        result = await enhanced_scheduler.run_intelligent_news_collection()
        
        logger.info(
            "Intelligent news collection completed",
            extra={
                "event": "intelligent_news_collection",
                "status": result.get('status', 'unknown'),
                "strategies_executed": result.get('strategies_executed', 0),
            },
        )
        return result
        
    except Exception as e:
        logger.exception("Intelligent news collection failed: %s", e)
        raise

async def run_news_collection():
    """传统（备份）新闻采集流程。"""
    try:
        news_scheduler = NewsScheduler()
        await news_scheduler.run_scheduled_news_collection()
        logger.info("Legacy news collection completed", extra={"event": "legacy_news_collection"})
    except Exception as e:
        logger.exception("Legacy news collection failed: %s", e)

async def run_manual_intelligent_collection():
    """手动触发智能新闻采集。"""
    try:
        return await run_intelligent_news_collection()
    except Exception as e:
        logger.exception("Manual intelligent news collection failed: %s", e)
        raise

async def run_manual_news_collection(symbol: str):
    """手动触发指定股票的新闻采集。"""
    try:
        with SessionLocal() as session:
            row = session.execute(text("""
                SELECT spm.symbol, COALESCE(sp.company_name, wl.name) AS name
                FROM stock_pool_members spm
                LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
                LEFT JOIN watchlist wl ON spm.symbol = wl.symbol
                WHERE spm.symbol = :sym AND spm.exit_date IS NULL
            """), {"sym": symbol}).fetchone()
            if not row:
                raise ValueError(f"Stock {symbol} not found in stock pool")
            stock_name = row.name

        news_scheduler = NewsScheduler()
        await news_scheduler._collect_news_for_stock(symbol, stock_name)
        logger.info("News collection completed", extra={"event": "manual_news_collection", "symbol": symbol})
    except Exception as e:
        logger.exception("News collection for %s failed: %s", symbol, e)
        raise

async def run_macro_observation_pipeline():
    """执行宏观新闻观测流水线。"""
    try:
        result = await run_macro_pipeline()
        observations = len(getattr(result, "observations", []) or [])
        errors = len(getattr(result, "errors", []) or [])
        duration = (
            result.finished_at - result.started_at
            if getattr(result, "finished_at", None) and getattr(result, "started_at", None)
            else None
        )
        duration_seconds = round(duration.total_seconds(), 2) if duration else "n/a"

        logger.info(
            "Macro observation pipeline completed",
            extra={
                "event": "macro_observation_pipeline",
                "observations": observations,
                "errors": errors,
                "duration_seconds": duration_seconds,
            },
        )
        return result
    except Exception as exc:
        logger.exception("Macro observation pipeline failed: %s", exc)
        raise

async def run_macro_training_job():
    """执行宏观新闻驱动模型的训练作业。"""
    try:
        result = await run_macro_training()
        if result is None:
            logger.warning(
                "Macro training completed with no dataset",
                extra={"event": "macro_model_training", "status": "empty"},
            )
            return None

        logger.info(
            "Macro training job completed",
            extra={
                "event": "macro_model_training",
                "model_name": result.model_name,
                "metrics": result.metrics,
                "feature_columns": len(result.feature_columns),
            },
        )
        return result
    except Exception as exc:
        logger.exception("Macro training job failed: %s", exc)
        raise


async def run_macro_report_job():
    """生成并存储每日宏观日报。"""
    try:
        report = await generate_and_store_macro_report()
        if not report:
            logger.warning(
                "Macro report generation produced no output",
                extra={"event": "macro_report_generation", "status": "empty"},
            )
            return None

        logger.info(
            "Macro report generated",
            extra={
                "event": "macro_report_generation",
                "report_date": report.get("report_date"),
                "topic_count": (report.get("metrics") or {}).get("topic_count"),
                "article_count": (report.get("metrics") or {}).get("article_count"),
            },
        )
        return report
    except Exception as exc:
        logger.exception("Macro report generation failed: %s", exc)
        raise

def configure_scheduler_jobs(sched: AsyncIOScheduler) -> dict[str, object]:
    """根据环境变量注册所有调度作业，不启动调度器。"""
    hour = int(os.getenv("CRON_HOUR", "16"))
    minute = int(os.getenv("CRON_MINUTE", "10"))
    hour2 = int(os.getenv("CRON_HOUR2", "16"))
    minute2 = int(os.getenv("CRON_MINUTE2", "30"))
    news_center_every_hours = max(1, int(os.getenv("NEWS_CENTER_CRON_EVERY_HOURS", "2")))
    news_center_minute = int(os.getenv("NEWS_CENTER_CRON_MINUTE", "5"))
    macro_hour = int(os.getenv("MACRO_CRON_HOUR", "19"))
    macro_minute = int(os.getenv("MACRO_CRON_MINUTE", "45"))
    macro_train_hour = int(os.getenv("MACRO_TRAIN_CRON_HOUR", "20"))
    macro_train_minute = int(os.getenv("MACRO_TRAIN_CRON_MINUTE", "15"))
    macro_report_hour = int(os.getenv("MACRO_REPORT_CRON_HOUR", "20"))
    macro_report_minute = int(os.getenv("MACRO_REPORT_CRON_MINUTE", "45"))
    agent_hour = int(os.getenv('AGENT_DAILY_CRON_HOUR', '20'))
    agent_minute = int(os.getenv('AGENT_DAILY_CRON_MINUTE', '10'))
    pool_hour = int(os.getenv('STOCK_POOL_CRON_HOUR', '16'))
    pool_minute = int(os.getenv('STOCK_POOL_CRON_MINUTE', '15'))
    analysis_hour = int(os.getenv('ANALYSIS_CRON_HOUR', '18'))
    analysis_minute = int(os.getenv('ANALYSIS_CRON_MINUTE', '0'))
    profile_noon_hour = int(os.getenv('PROFILE_NOON_CRON_HOUR', '12'))
    profile_noon_minute = int(os.getenv('PROFILE_NOON_CRON_MINUTE', '0'))
    sig_hour = int(os.getenv('SIGNAL_CRON_HOUR', '17'))
    sig_minute = int(os.getenv('SIGNAL_CRON_MINUTE', '0'))
    port_hour = int(os.getenv('PORTFOLIO_CRON_HOUR', '17'))
    port_minute = int(os.getenv('PORTFOLIO_CRON_MINUTE', '10'))
    pt_hour = int(os.getenv('PAPER_TRADE_CRON_HOUR', '17'))
    pt_minute = int(os.getenv('PAPER_TRADE_CRON_MINUTE', '20'))
    cl_eval_hour = int(os.getenv('CL_EVAL_CRON_HOUR', '17'))
    cl_eval_minute = int(os.getenv('CL_EVAL_CRON_MINUTE', '30'))
    cl_retrain_day = os.getenv('CL_RETRAIN_DAY', 'sun')
    cl_retrain_hour = int(os.getenv('CL_RETRAIN_CRON_HOUR', '3'))
    cl_retrain_minute = int(os.getenv('CL_RETRAIN_CRON_MINUTE', '0'))
    event_scan_hours = int(os.getenv('EVENT_SCAN_EVERY_HOURS', '4'))

    sched.add_job(
        run_daily_pipeline,
        CronTrigger(hour=hour, minute=minute),
        id='daily_pipeline',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        run_intelligent_news_collection,
        CronTrigger(hour='*/4'),
        id='intelligent_news_collection',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        run_news_collection,
        CronTrigger(hour='*/12'),
        id='legacy_news_collection',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        run_news_center_collection,
        CronTrigger(hour=f"*/{news_center_every_hours}", minute=news_center_minute),
        id='news_center_collection',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        run_daily_pipeline,
        CronTrigger(hour=hour2, minute=minute2),
        id='daily_pipeline_post_close',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        run_macro_observation_pipeline,
        CronTrigger(hour=macro_hour, minute=macro_minute),
        id='macro_observation_pipeline',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        run_macro_training_job,
        CronTrigger(hour=macro_train_hour, minute=macro_train_minute),
        id='macro_training_job',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        run_macro_report_job,
        CronTrigger(hour=macro_report_hour, minute=macro_report_minute),
        id='macro_report_job',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        _scheduled_agent_daily_job,
        CronTrigger(hour=agent_hour, minute=agent_minute),
        id='agent_daily_job',
        replace_existing=True,
        max_instances=1
    )

    agent_pipeline_schedule = _configure_agent_pipeline_jobs(sched)
    sched.add_job(
        _scheduled_stock_pool_daily,
        CronTrigger(hour=pool_hour, minute=pool_minute),
        id='stock_pool_daily_top20',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        _scheduled_daily_analysis_job,
        CronTrigger(hour=analysis_hour, minute=analysis_minute),
        id='daily_analysis_job',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        _scheduled_weekly_potential_evaluation,
        CronTrigger(day_of_week='sun', hour=2, minute=0),
        id='weekly_potential_evaluation',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        _scheduled_hourly_incremental_analysis,
        IntervalTrigger(hours=1),
        id='hourly_incremental_analysis',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        _scheduled_noon_profile_completion,
        CronTrigger(hour=profile_noon_hour, minute=profile_noon_minute),
        id='noon_profile_completion',
        replace_existing=True,
        max_instances=1
    )
    sched.add_job(
        _scheduled_daily_signal_generation,
        CronTrigger(hour=sig_hour, minute=sig_minute),
        id='daily_signal_generation',
        replace_existing=True,
        max_instances=1,
    )
    sched.add_job(
        _scheduled_daily_portfolio_optimization,
        CronTrigger(hour=port_hour, minute=port_minute),
        id='daily_portfolio_optimization',
        replace_existing=True,
        max_instances=1,
    )
    sched.add_job(
        _scheduled_daily_paper_trading,
        CronTrigger(hour=pt_hour, minute=pt_minute),
        id='daily_paper_trading',
        replace_existing=True,
        max_instances=1,
    )
    sched.add_job(
        _scheduled_prediction_evaluation,
        CronTrigger(hour=cl_eval_hour, minute=cl_eval_minute),
        id='daily_prediction_evaluation',
        replace_existing=True,
        max_instances=1,
    )
    sched.add_job(
        _scheduled_weekly_model_retrain,
        CronTrigger(day_of_week=cl_retrain_day, hour=cl_retrain_hour, minute=cl_retrain_minute),
        id='weekly_model_retrain',
        replace_existing=True,
        max_instances=1,
    )
    sched.add_job(
        _scheduled_event_factor_scan,
        IntervalTrigger(hours=event_scan_hours),
        id='event_factor_scan',
        replace_existing=True,
        max_instances=1,
    )

    return {
        "daily": (hour, minute),
        "daily_post_close": (hour2, minute2),
        "macro": (macro_hour, macro_minute),
        "macro_train": (macro_train_hour, macro_train_minute),
        "macro_report": (macro_report_hour, macro_report_minute),
        "news_center": (f"*/{news_center_every_hours}", news_center_minute),
        "agent_daily": (agent_hour, agent_minute),
        "agent_pipelines": agent_pipeline_schedule,
        "daily_analysis": (analysis_hour, analysis_minute),
        "weekly_potential": "Sunday 02:00",
        "hourly_incremental": "every 1 hour",
        "noon_profile": (profile_noon_hour, profile_noon_minute),
        "daily_signal": (sig_hour, sig_minute),
        "daily_portfolio": (port_hour, port_minute),
        "daily_paper_trading": (pt_hour, pt_minute),
        "cl_daily_eval": (cl_eval_hour, cl_eval_minute),
        "cl_weekly_retrain": f"{cl_retrain_day} {cl_retrain_hour}:{cl_retrain_minute:02d}",
        "event_scan": f"every {event_scan_hours}h",
        "timezone": TZ,
    }


def attach_scheduler(app):
    """挂载并启动调度器，注册作业计划。"""
    try:
        sched = AsyncIOScheduler(timezone=TZ)
        schedule_summary = configure_scheduler_jobs(sched)
        sched.start()
        app.state.scheduler = sched
        logger.info(
            "Scheduler started",
            extra={
                "event": "scheduler_start",
                "timezone": schedule_summary["timezone"],
                "daily": schedule_summary["daily"],
                "daily_post_close": schedule_summary["daily_post_close"],
                "macro": schedule_summary["macro"],
                "macro_train": schedule_summary["macro_train"],
                "macro_report": schedule_summary["macro_report"],
                    "agent_daily": schedule_summary["agent_daily"],
                    "agent_pipelines": schedule_summary["agent_pipelines"],
            },
        )
        return sched
    except Exception as e:
        logger.exception("Failed to start scheduler: %s", e)
        raise
