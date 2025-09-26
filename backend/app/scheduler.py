"""
模块说明（中文）
此模块负责后端定时任务调度与日常数据管道的 orchestrator。主要职责包括：
- 按计划拉取并持久化自选股的历史日线数据与资金流向（EOD 数据），避免盘中数据污染；
- 计算并写入技术指标信号（signals），对 symbol+trade_date 去重；
- 调用增强预测模型生成未来若干交易日的预测（forecasts），按 run_at 分批次写入；
- 触发增强与智能新闻采集流程，并提供若干手动触发接口；
- 使用 APScheduler 的 AsyncIOScheduler 进行作业注册与管理，支持基于 CRON 的调度。
主要环境变量
- TZ: 调度器时区，默认 "Asia/Taipei"。
- FORECAST_AHEAD_DAYS: 预测天数，默认 5。
- CRON_HOUR / CRON_MINUTE: 主日常管道运行时间（默认 16:10）。
- CRON_HOUR2 / CRON_MINUTE2: 收盘后保障作业运行时间（默认 16:30）。
关键函数及行为（异步函数为 async）
- run_daily_pipeline() -> bool
    执行完整日常管道。流程概述：
        1. 遍历启用的自选股（Watchlist.enabled），拉取近三年日线并按 (symbol, trade_date) UPSERT 到 prices_daily；
        2. 读取该股票历史价，若样本足够则计算技术信号并写入 signals（按 symbol+trade_date 去重）；
        3. 使用增强预测模型预测未来 AHEAD 天的价格，结果写入 forecasts（包含 yhat、上下界、model 与 run_at）；
        4. 拉取个股资金流向并 UPSERT 到 fund_flow_daily，仅写入已收盘日期；
        5. 提交事务并在完成后触发增强新闻采集 run_enhanced_daily_news_collection。
    返回 True 表示流程成功。函数会在遇到不可恢复错误时抛出异常。
- run_enhanced_daily_news_collection()
    触发并运行增强新闻采集器（EnhancedNewsScheduler），打印并返回采集统计（status、duration_seconds、articles_found 等）。
    异常时打印错误并向上抛出。
- run_intelligent_news_collection()
    基于自选股与策略运行智能新闻采集（EnhancedNewsScheduler.run_intelligent_news_collection），返回策略执行统计。
- run_news_collection()
    传统/备份新闻采集流程（NewsScheduler.run_scheduled_news_collection），主要用于容灾或历史兼容。
- run_manual_intelligent_collection()
    手动触发智能新闻采集的包装，异常时会抛出。
- run_manual_news_collection(symbol: str)
    手动为指定股票触发新闻采集。会先校验 symbol 是否存在于 watchlist，若存在则调用 NewsScheduler 的单股采集方法。发生错误时抛出异常。
- attach_scheduler(app)
    将 AsyncIOScheduler 挂载到给定的 app（例如 FastAPI app）并启动调度。注册的作业包括：
        - daily_pipeline（CRON_HOUR:CRON_MINUTE）
        - daily_pipeline_post_close（CRON_HOUR2:CRON_MINUTE2）
        - intelligent_news_collection（每 4 小时）
        - legacy_news_collection（每 12 小时）
    启动后会把 scheduler 存入 app.state.scheduler，便于运行时管理与关闭。该函数在启动失败时会抛出异常。
副作用与外部依赖
- 依赖外部组件：数据库 SessionLocal 与 engine、ORM models（Watchlist、PriceDaily、Signal、Forecast、FundFlowDaily、Task 等）、数据拉取函数（fetch_daily、fetch_fund_flow_daily）、信号计算（compute_signals）、预测模型（predict_stock_price）、以及若干新闻采集调度器（NewsScheduler、NewsStrategyScheduler、EnhancedNewsScheduler）。
- 对数据库执行大量插入/UPSERT 操作并显式提交事务；应确保连接与事务管理在高并发场景下的健壮性。
- 用到 pandas 读取数据库视图用于信号计算与预测输入。
错误与稳定性说明
- 模块对单只股票的处理采用局部事务提交以降低回滚范围，但若外部组件（例如预测器或新闻采集器）失败，相关调用会抛出异常并记录（打印）错误。
- 调度作业设置了 max_instances=1 以避免重入。需在生产环境配置合适的时区与 CRON 环境变量以保证作业按预期执行。
示例：将调度器挂载到 FastAPI 应用时，调用 attach_scheduler(app) 即可在 app.state.scheduler 中获取调度对象。

"""
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timedelta
import pandas as pd

from .db import SessionLocal, engine
from .models import Watchlist, PriceDaily, Signal, Forecast, Task, TaskType, TaskStatus
from .data_source import fetch_daily, fetch_fund_flow_daily
from .signals import compute_signals
from .forecast import predict_stock_price
from .report import plain_summary, llm_summarize
from .news_service import NewsScheduler
from .news_strategy import NewsStrategyScheduler
from .enhanced_news_scheduler import EnhancedNewsScheduler

TZ = os.getenv("TZ", "Asia/Taipei")
AHEAD = int(os.getenv("FORECAST_AHEAD_DAYS", "5"))

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
            if df.empty:
                continue
            for _, row in df.iterrows():
                stmt = pg_insert(PriceDaily).values(
                    symbol=row["symbol"],
                    trade_date=row["trade_date"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    pct_chg=row.get("pct_chg"),
                    vol=(int(row["vol"]) if pd.notna(row["vol"]) else None),
                    amount=row.get("amount"),
                ).on_conflict_do_nothing(index_elements=["symbol", "trade_date"])
                session.execute(stmt)
            session.commit()

            qdf = pd.read_sql_query(
                "SELECT trade_date, open, high, low, close, pct_chg, vol, amount FROM prices_daily WHERE symbol = %s ORDER BY trade_date",
                con=engine,
                params=(w.symbol,),
            )
            if len(qdf) < 50:
                continue
            sig_df = compute_signals(qdf)
            last_sig = sig_df.iloc[-1]
            stmt_sig = pg_insert(Signal).values(
                symbol=w.symbol,
                trade_date=last_sig["trade_date"],
                ma_short=last_sig["ma_s"],
                ma_long=last_sig["ma_l"],
                rsi=last_sig["rsi"],
                macd=last_sig["macd"],
                signal_score=last_sig["signal_score"],
                action=last_sig["action"],
            ).on_conflict_do_nothing(index_elements=["symbol", "trade_date"])
            session.execute(stmt_sig)

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
                from .models import FundFlowDaily
                # 只保留已收盘的日期，避免把当日盘中数据写入EOD表
                today = datetime.now().date()
                for _, r in ff_df.iterrows():
                    if r.get("trade_date") == today:
                        continue
                    stmt_ff = pg_insert(FundFlowDaily).values(
                        symbol=r["symbol"],
                        trade_date=r["trade_date"],
                        main_net=r.get("main_net"),
                        main_ratio=r.get("main_ratio"),
                        super_net=r.get("super_net"),
                        super_ratio=r.get("super_ratio"),
                        large_net=r.get("large_net"),
                        large_ratio=r.get("large_ratio"),
                        medium_net=r.get("medium_net"),
                        medium_ratio=r.get("medium_ratio"),
                        small_net=r.get("small_net"),
                        small_ratio=r.get("small_ratio"),
                    ).on_conflict_do_nothing(index_elements=["symbol","trade_date"])
                    session.execute(stmt_ff)
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
        
        print(f"✓ Enhanced daily news collection completed:")
        print(f"  - Status: {result.get('status', 'unknown')}")
        print(f"  - Duration: {result.get('duration_seconds', 0):.2f}s")
        print(f"  - Articles found: {result.get('statistics', {}).get('articles_found', 0)}")
        print(f"  - Articles saved: {result.get('statistics', {}).get('articles_saved', 0)}")
        print(f"  - Duplicates skipped: {result.get('statistics', {}).get('duplicates_skipped', 0)}")
        
        return result
        
    except Exception as e:
        print(f"✗ Enhanced daily news collection failed: {e}")
        raise

async def run_intelligent_news_collection():
    """基于自选股与策略的智能新闻采集。"""
    try:
        enhanced_scheduler = EnhancedNewsScheduler()
        result = await enhanced_scheduler.run_intelligent_news_collection()
        
        print(f"✓ Intelligent news collection completed:")
        print(f"  - Status: {result.get('status', 'unknown')}")
        print(f"  - Strategies executed: {result.get('strategies_executed', 0)}")
        
        return result
        
    except Exception as e:
        print(f"✗ Intelligent news collection failed: {e}")
        raise

async def run_news_collection():
    """传统（备份）新闻采集流程。"""
    try:
        news_scheduler = NewsScheduler()
        await news_scheduler.run_scheduled_news_collection()
        print("✓ Legacy news collection completed successfully")
    except Exception as e:
        print(f"✗ Legacy news collection failed: {e}")

async def run_manual_intelligent_collection():
    """手动触发智能新闻采集。"""
    try:
        return await run_intelligent_news_collection()
    except Exception as e:
        print(f"✗ Manual intelligent news collection failed: {e}")
        raise

async def run_manual_news_collection(symbol: str):
    """手动触发指定股票的新闻采集。"""
    try:
        with SessionLocal() as session:
            # Check if stock exists in watchlist
            stock = session.execute(
                select(Watchlist).where(Watchlist.symbol == symbol)
            ).scalar_one_or_none()
            
            if not stock:
                raise ValueError(f"Stock {symbol} not found in watchlist")
        
        news_scheduler = NewsScheduler()
        await news_scheduler._collect_news_for_stock(symbol, stock.name)
        print(f"✓ News collection for {symbol} completed successfully")
        
    except Exception as e:
        print(f"✗ News collection for {symbol} failed: {e}")
        raise

def attach_scheduler(app):
    """挂载并启动调度器，注册作业计划。

    已注册作业：
    - daily_pipeline: 每日主流程（CRON_HOUR/CRON_MINUTE）
    - intelligent_news_collection: 每 4 小时执行一次
    - legacy_news_collection: 每 12 小时执行一次（备份）
    - daily_pipeline_post_close: 收盘后保障作业（CRON_HOUR2/CRON_MINUTE2）
    """
    try:
        sched = AsyncIOScheduler(timezone=TZ)
        hour = int(os.getenv("CRON_HOUR", "16"))
        minute = int(os.getenv("CRON_MINUTE", "10"))
        
        # 添加主要数据处理作业
        main_job = sched.add_job(
            run_daily_pipeline, 
            CronTrigger(hour=hour, minute=minute),
            id='daily_pipeline',
            replace_existing=True,
            max_instances=1
        )
        
        # 添加智能新闻收集作业 - 每4小时运行一次
        intelligent_news_job = sched.add_job(
            run_intelligent_news_collection,
            CronTrigger(hour='*/4'),  # 每4小时
            id='intelligent_news_collection',
            replace_existing=True,
            max_instances=1
        )
        
        # 添加传统新闻收集作业 - 每12小时运行一次 (作为备份)
        legacy_news_job = sched.add_job(
            run_news_collection,
            CronTrigger(hour='*/12'),  # 每12小时
            id='legacy_news_collection',
            replace_existing=True,
            max_instances=1
        )
        
        # 在收盘后再跑一次保障（默认 16:30 Asia/Taipei，可通过 CRON_HOUR2/CRON_MINUTE2 覆盖）
        hour2 = int(os.getenv("CRON_HOUR2", "16"))
        minute2 = int(os.getenv("CRON_MINUTE2", "30"))
        sched.add_job(
            run_daily_pipeline,
            CronTrigger(hour=hour2, minute=minute2),
            id='daily_pipeline_post_close',
            replace_existing=True,
            max_instances=1
        )

        sched.start()
        app.state.scheduler = sched
        print(f"✓ Scheduler started:")
        print(f"  - Daily pipeline: {hour:02d}:{minute:02d} {TZ}")
        print(f"  - Daily pipeline (post-close): {hour2:02d}:{minute2:02d} {TZ}")
        print(f"  - Intelligent news collection: Every 4 hours")
        print(f"  - Legacy news collection: Every 12 hours")
        return sched
    except Exception as e:
        print(f"✗ Failed to start scheduler: {e}")
        raise
