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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, insert, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timedelta, date
import pandas as pd

from ..core.db import SessionLocal, engine
from ..core.models import Watchlist, PriceDaily, Signal, Forecast, Task, TaskType, TaskStatus
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


# ========== A股交易日判断 ==========
def is_trading_day(d: date = None) -> bool:
    """判断是否为A股交易日
    
    简化版：排除周末，可扩展添加节假日
    """
    if d is None:
        d = date.today()
    
    # 周末不交易
    if d.weekday() >= 5:
        return False
    
    # 已知节假日（2026年示例，可从数据库或API获取）
    holidays = {
        # 2026年元旦
        date(2026, 1, 1),
        # 2026年春节 (预估)
        date(2026, 1, 26), date(2026, 1, 27), date(2026, 1, 28),
        date(2026, 1, 29), date(2026, 1, 30), date(2026, 2, 2),
        # 可根据实际情况补充
    }
    
    if d in holidays:
        return False
    
    return True


def get_last_trading_day(d: date = None) -> date:
    """获取最近的交易日"""
    if d is None:
        d = date.today()
    while not is_trading_day(d):
        d = d - timedelta(days=1)
    return d


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
    """
    now = datetime.now()
    with SessionLocal() as session:
        watches = session.execute(select(Watchlist).where(Watchlist.enabled == True)).scalars().all()
        for w in watches:
            start = (now - timedelta(days=365 * 3)).strftime("%Y%m%d")
            df = fetch_daily(w.symbol, start_date=start)
            if not df.empty:
                # 只有成功拉取数据时才更新数据库
                for _, row in df.iterrows():
                    # Guarded insert to avoid requiring a unique constraint for ON CONFLICT
                    insert_price_sql = """
                    INSERT INTO prices_daily (symbol, trade_date, open, high, low, close, pct_chg, vol, amount)
                    SELECT :symbol, :trade_date, :open, :high, :low, :close, :pct_chg, :vol, :amount
                    WHERE NOT EXISTS (
                        SELECT 1 FROM prices_daily WHERE symbol = :symbol AND trade_date = :trade_date
                    )
                    """
                    params_price = {
                        "symbol": row["symbol"],
                        "trade_date": row["trade_date"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "pct_chg": row.get("pct_chg"),
                        "vol": (int(row["vol"]) if pd.notna(row["vol"]) else None),
                        "amount": row.get("amount"),
                    }
                    session.execute(text(insert_price_sql), params_price)
                session.commit()

            # 无论是否成功拉取新数据，都从数据库读取已有数据进行信号/预测计算
            qdf = pd.read_sql_query(
                "SELECT trade_date, open, high, low, close, pct_chg, vol, amount FROM prices_daily WHERE symbol = %s ORDER BY trade_date",
                con=engine,
                params=(w.symbol,),
            )
            if len(qdf) < 50:
                continue
            sig_df = compute_signals(qdf)
            last_sig = sig_df.iloc[-1]
            # Use a guarded INSERT to avoid requiring a unique constraint for ON CONFLICT
            # Insert only when no existing (symbol, trade_date) row exists
            insert_sig_sql = """
            INSERT INTO signals (symbol, trade_date, ma_short, ma_long, rsi, macd, signal_score, action)
            SELECT :symbol, :trade_date, :ma_short, :ma_long, :rsi, :macd, :signal_score, :action
            WHERE NOT EXISTS (
                SELECT 1 FROM signals WHERE symbol = :symbol AND trade_date = :trade_date
            )
            """
            params_sig = {
                "symbol": w.symbol,
                "trade_date": last_sig["trade_date"],
                "ma_short": last_sig["ma_s"],
                "ma_long": last_sig["ma_l"],
                "rsi": last_sig["rsi"],
                "macd": last_sig["macd"],
                "signal_score": last_sig["signal_score"],
                "action": last_sig["action"],
            }
            session.execute(text(insert_sig_sql), params_sig)

            # 使用增强预测模型
            prediction_result = predict_stock_price(qdf, w.symbol, ahead_days=AHEAD)
            
            if prediction_result.get("predictions"):
                run_at = now
                model_name = prediction_result.get("method", "enhanced").upper()
                
                for pred in prediction_result["predictions"]:
                    day = pred["day"]
                    target_date = qdf["trade_date"].iloc[-1] + timedelta(days=day)
                    stmt_fc = insert(Forecast).values(
                        symbol=w.symbol,
                        run_at=run_at,
                        target_date=target_date,
                        model=model_name,
                        yhat=float(pred["predicted_price"]),
                        yhat_lower=float(pred["lower_bound"]),
                        yhat_upper=float(pred["upper_bound"]),
                    )
                    session.execute(stmt_fc)
            session.commit()

            fdf = pd.read_sql_query(
                "SELECT target_date, avg(yhat) yhat, avg(yhat_lower) yl, avg(yhat_upper) yu FROM forecasts WHERE symbol=%s AND run_at=%s GROUP BY target_date ORDER BY target_date",
                con=engine,
                params=(w.symbol, run_at),
            )
            preds_view: list[tuple] = []
            if not fdf.empty:
                for _, row in fdf.iterrows():
                    preds_view.append((row["target_date"], row["yhat"], row["yl"], row["yu"]))
            today_row = qdf.iloc[-1]
            # Fund flow upsert
            ff_df = fetch_fund_flow_daily(w.symbol, start_date=start, include_today_rank=False)
            if not ff_df.empty:
                from ..core.models import FundFlowDaily
                # 只保留已收盘的日期，避免把当日盘中数据写入EOD表
                today = datetime.now().date()
                for _, r in ff_df.iterrows():
                    if r.get("trade_date") == today:
                        continue
                    insert_ff_sql = """
                    INSERT INTO fundflow_daily (symbol, trade_date, main_net, main_ratio, super_net, super_ratio, large_net, large_ratio, medium_net, medium_ratio, small_net, small_ratio)
                    SELECT :symbol, :trade_date, :main_net, :main_ratio, :super_net, :super_ratio, :large_net, :large_ratio, :medium_net, :medium_ratio, :small_net, :small_ratio
                    WHERE NOT EXISTS (
                        SELECT 1 FROM fundflow_daily WHERE symbol = :symbol AND trade_date = :trade_date
                    )
                    """
                    params_ff = {
                        "symbol": r["symbol"],
                        "trade_date": r["trade_date"],
                        "main_net": r.get("main_net"),
                        "main_ratio": r.get("main_ratio"),
                        "super_net": r.get("super_net"),
                        "super_ratio": r.get("super_ratio"),
                        "large_net": r.get("large_net"),
                        "large_ratio": r.get("large_ratio"),
                        "medium_net": r.get("medium_net"),
                        "medium_ratio": r.get("medium_ratio"),
                        "small_net": r.get("small_net"),
                        "small_ratio": r.get("small_ratio"),
                    }
                    session.execute(text(insert_ff_sql), params_ff)
                session.commit()
    # Run enhanced daily news collection
    await run_enhanced_daily_news_collection()
    
    return True

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
            stock = session.execute(
                select(Watchlist).where(Watchlist.symbol == symbol)
            ).scalar_one_or_none()
            if not stock:
                raise ValueError(f"Stock {symbol} not found in watchlist")

        news_scheduler = NewsScheduler()
        await news_scheduler._collect_news_for_stock(symbol, stock.name)
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

def configure_scheduler_jobs(sched: AsyncIOScheduler) -> dict[str, tuple[int, int] | str]:
    """根据环境变量注册所有调度作业，不启动调度器。"""
    hour = int(os.getenv("CRON_HOUR", "16"))
    minute = int(os.getenv("CRON_MINUTE", "10"))
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

    # News center job: run every N hours (default 2), minute configurable
    news_center_every_hours = int(os.getenv("NEWS_CENTER_CRON_EVERY_HOURS", "2"))
    news_center_minute = int(os.getenv("NEWS_CENTER_CRON_MINUTE", "5"))
    # guard against invalid values
    if news_center_every_hours <= 0:
        news_center_every_hours = 2
    sched.add_job(
        run_news_center_collection,
        CronTrigger(hour=f"*/{news_center_every_hours}", minute=news_center_minute),
        id='news_center_collection',
        replace_existing=True,
        max_instances=1
    )

    hour2 = int(os.getenv("CRON_HOUR2", "16"))
    minute2 = int(os.getenv("CRON_MINUTE2", "30"))
    sched.add_job(
        run_daily_pipeline,
        CronTrigger(hour=hour2, minute=minute2),
        id='daily_pipeline_post_close',
        replace_existing=True,
        max_instances=1
    )

    macro_hour = int(os.getenv("MACRO_CRON_HOUR", "19"))
    macro_minute = int(os.getenv("MACRO_CRON_MINUTE", "45"))
    sched.add_job(
        run_macro_observation_pipeline,
        CronTrigger(hour=macro_hour, minute=macro_minute),
        id='macro_observation_pipeline',
        replace_existing=True,
        max_instances=1
    )

    macro_train_hour = int(os.getenv("MACRO_TRAIN_CRON_HOUR", "20"))
    macro_train_minute = int(os.getenv("MACRO_TRAIN_CRON_MINUTE", "15"))
    sched.add_job(
        run_macro_training_job,
        CronTrigger(hour=macro_train_hour, minute=macro_train_minute),
        id='macro_training_job',
        replace_existing=True,
        max_instances=1
    )

    macro_report_hour = int(os.getenv("MACRO_REPORT_CRON_HOUR", "20"))
    macro_report_minute = int(os.getenv("MACRO_REPORT_CRON_MINUTE", "45"))
    sched.add_job(
        run_macro_report_job,
        CronTrigger(hour=macro_report_hour, minute=macro_report_minute),
        id='macro_report_job',
        replace_existing=True,
        max_instances=1
    )

    # Daily agent intelligent analysis job (Top20) persistence
    agent_hour = int(os.getenv('AGENT_DAILY_CRON_HOUR', '20'))
    agent_minute = int(os.getenv('AGENT_DAILY_CRON_MINUTE', '10'))
    def _agent_job_wrapper():
        # import inside to avoid circular
        try:
            import uuid
            from ..main import run_agent  # FastAPI endpoint function (async)
            import anyio
            async def _inner():
                # strict_json 可由 env 控制; 这里默认 False
                await run_agent(strict_json=False)
            anyio.run(_inner)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning('Scheduled agent run failed: %s', e, exc_info=True)
    sched.add_job(
        _agent_job_wrapper,
        CronTrigger(hour=agent_hour, minute=agent_minute),
        id='agent_daily_job',
        replace_existing=True,
        max_instances=1
    )

    # ===== 每日分析中心定时任务 =====
    # 每日分析任务（收盘后18:00）- 仅在交易日执行
    analysis_hour = int(os.getenv('ANALYSIS_CRON_HOUR', '18'))
    analysis_minute = int(os.getenv('ANALYSIS_CRON_MINUTE', '0'))
    def _daily_analysis_job():
        try:
            from ..core.db import SessionLocal
            from ..analysis.analysis_engine import AnalysisEngine
            from ..analysis.report_generator import DailyReportGenerator
            from datetime import date
            import logging
            _logger = logging.getLogger(__name__)
            
            # 检查是否为交易日
            today = date.today()
            if not is_trading_day(today):
                _logger.info(f"Skipping daily analysis - {today} is not a trading day")
                return
            
            _logger.info("Starting scheduled daily analysis job...")
            with SessionLocal() as session:
                engine = AnalysisEngine(session)
                results = engine.analyze_watchlist(today)
                saved = engine.save_analysis_results(results)
                _logger.info(f"Daily analysis completed: {len(results)} stocks analyzed, {saved} saved")
                
                # 生成综合报告
                if results:
                    generator = DailyReportGenerator(session)
                    generator.generate_report(today, results)
                    _logger.info("Daily report generated")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f'Scheduled daily analysis failed: {e}', exc_info=True)
    
    sched.add_job(
        _daily_analysis_job,
        CronTrigger(hour=analysis_hour, minute=analysis_minute),
        id='daily_analysis_job',
        replace_existing=True,
        max_instances=1
    )

    # 每周投资潜力评估（周日02:00）
    def _weekly_potential_evaluation():
        try:
            from ..core.db import SessionLocal
            from ..core.models import Watchlist
            from ..analysis.analysis_engine import AnalysisEngine
            from sqlalchemy import select
            import logging
            _logger = logging.getLogger(__name__)
            
            _logger.info("Starting weekly investment potential evaluation...")
            with SessionLocal() as session:
                watchlist = session.execute(
                    select(Watchlist).where(Watchlist.enabled == True)
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
                _logger.info(f"Potential evaluation completed: {len(watchlist)} stocks, {removal_suggestions} removal suggestions")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f'Weekly potential evaluation failed: {e}', exc_info=True)
    
    sched.add_job(
        _weekly_potential_evaluation,
        CronTrigger(day_of_week='sun', hour=2, minute=0),
        id='weekly_potential_evaluation',
        replace_existing=True,
        max_instances=1
    )

    # ===== 每小时增量分析任务 =====
    # 检测新增股票并进行分析
    def _hourly_incremental_analysis():
        global _last_incremental_analysis_time, _last_watchlist_hash
        try:
            from ..core.db import SessionLocal
            from ..analysis.analysis_engine import AnalysisEngine
            from ..analysis.report_generator import DailyReportGenerator
            from sqlalchemy import select, func
            from datetime import date, datetime
            import logging
            import hashlib
            _logger = logging.getLogger(__name__)
            
            # 检查是否为交易日
            today = date.today()
            if not is_trading_day(today):
                return
            
            # 检查是否在交易时间内（9:30-15:00）
            now = datetime.now()
            if not (9 <= now.hour < 16):
                return
            
            with SessionLocal() as session:
                # 计算当前观察列表的hash
                watchlist = session.execute(
                    select(Watchlist).where(Watchlist.enabled == True)
                ).scalars().all()
                
                symbols = sorted([w.symbol for w in watchlist])
                current_hash = hashlib.md5(",".join(symbols).encode()).hexdigest()
                
                # 检查是否有新增股票
                if _last_watchlist_hash == current_hash:
                    return  # 没有变化，跳过
                
                _logger.info(f"Watchlist changed, running incremental analysis...")
                
                # 找出新增的股票
                new_symbols = []
                if _last_watchlist_hash:
                    # 查找今天新增的（added_at在今天）
                    for w in watchlist:
                        if w.added_at and w.added_at.date() == today:
                            if not session.execute(
                                select(DailyAnalysis).where(
                                    DailyAnalysis.symbol == w.symbol,
                                    DailyAnalysis.analysis_date == today
                                )
                            ).scalar_one_or_none():
                                new_symbols.append(w.symbol)
                else:
                    # 首次运行，分析所有未分析的
                    for w in watchlist:
                        if not session.execute(
                            select(DailyAnalysis).where(
                                DailyAnalysis.symbol == w.symbol,
                                DailyAnalysis.analysis_date == today
                            )
                        ).scalar_one_or_none():
                            new_symbols.append(w.symbol)
                
                if new_symbols:
                    _logger.info(f"Analyzing {len(new_symbols)} new stocks: {new_symbols}")
                    engine = AnalysisEngine(session)
                    
                    for symbol in new_symbols:
                        try:
                            result = engine.analyze_stock(symbol, today)
                            if result:
                                engine.save_analysis_results([result])
                                _logger.info(f"Incremental analysis completed for {symbol}")
                        except Exception as e:
                            _logger.warning(f"Failed to analyze {symbol}: {e}")
                    
                    # 重新生成当日报告
                    results = engine.analyze_watchlist(today)
                    if results:
                        generator = DailyReportGenerator(session)
                        generator.generate_report(today, results)
                        _logger.info("Daily report regenerated after incremental analysis")
                
                _last_watchlist_hash = current_hash
                _last_incremental_analysis_time = datetime.now()
                
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f'Hourly incremental analysis failed: {e}', exc_info=True)
    
    sched.add_job(
        _hourly_incremental_analysis,
        IntervalTrigger(hours=1),
        id='hourly_incremental_analysis',
        replace_existing=True,
        max_instances=1
    )

    return {
        "daily": (hour, minute),
        "daily_post_close": (hour2, minute2),
        "macro": (macro_hour, macro_minute),
        "macro_train": (macro_train_hour, macro_train_minute),
        "macro_report": (macro_report_hour, macro_report_minute),
        "news_center": (f"*/{news_center_every_hours}", news_center_minute),
        "agent_daily": (agent_hour, agent_minute),
        "daily_analysis": (analysis_hour, analysis_minute),
        "weekly_potential": "Sunday 02:00",
        "hourly_incremental": "every 1 hour",
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
            },
        )
        return sched
    except Exception as e:
        logger.exception("Failed to start scheduler: %s", e)
        raise
