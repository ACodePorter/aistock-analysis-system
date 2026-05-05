"""
主应用入口与路由定义（中文说明）

此模块负责构建并暴露完整的 FastAPI 应用： 
- 初始化数据库 schema（init_database）并在启动时根据环境变量选择性挂载调度器（attach_scheduler）。
- 提供股票数据、观察列表、行情快照、资金流向、技术信号、预测与报告相关的 HTTP API。
- 包含新闻抓取/处理/去重/质量审计/LLM 分析 等新闻子系统的路由和管理接口。
- 集成任务管理（TaskManager）用于异步/批量任务的创建与监控，支持报告生成、新闻采集等任务类型。
- 对外暴露用于调试与运维的端点：/health、/admin/db/init、/admin/scheduler/status、/api/llm/health 等。
- 内部使用缓存（如股票基础信息缓存 _stock_basic_cache）与重试/退避机制（retry_with_backoff）以增强稳定性。
- 支持多数据源（akshare / tushare / eastmoney / sina 等）并对网络/解析错误做友好处理与回退策略。
- 对接可选组件：LLM（Azure/本地）、MongoDB 存储、外部新闻检索服务与指标收集模块。
- 环境变量常用项：
    - DATA_SOURCE：'akshare' 或 'tushare'（默认 akshare）
    - TUSHARE_TOKEN：使用 tushare 时必需
    - ENABLE_SCHEDULER：是否启用定时调度（默认 1）
    - AZURE_OPENAI_*：LLM 相关配置（若使用 Azure）
- 错误和异常处理：常见场景返回 HTTPException，关键外部调用采用重试与降级策略，避免单点失败影响整体服务。

注意：本文件以路由定义为主，复杂业务逻辑（如爬虫、LLM 分析、去重、调度、任务执行）委托给项目内的子模块实现（如 news_service、llm_processor、task_manager、enhanced_news_scheduler 等）。
"""

from .news.news_service import NewsProcessor

import logging

from fastapi import FastAPI, Depends, HTTPException, Query, Form, Request
from fastapi.responses import ORJSONResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from sqlalchemy import select, text, and_, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from typing import Any, List, Optional
import json
import os
import random
import signal
import sys
import time
import asyncio
import tushare as ts
from datetime import datetime, timedelta, date
from dotenv import load_dotenv

load_dotenv()

# Windows 兼容：确保 asyncio 子进程 API 可用
# 在 Windows 的 SelectorEventLoopPolicy 下，create_subprocess_exec 会抛 NotImplementedError。
# 某些历史代码路径/第三方库仍可能触发该 API，因此统一切到 Proactor 策略兜底。
try:
    if sys.platform.startswith("win") and hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
except Exception:
    # best-effort；失败不阻塞服务启动
    pass

from .core.db import SessionLocal, init_database, engine
from .data.data_source import get_stock_info, search_stocks, get_realtime_stock, fetch_daily, get_spot_snapshot
# 使用数据源中的带缓存的资金流“今日排行”加载器，减少日志与请求频率
from .data.data_source import _load_fund_flow_rank_today as _ds_load_rank_today
from .core.models import Watchlist, PriceDaily, Forecast, Signal, Task, Report, TaskStatus, TaskType, Stock, AgentJob, AgentJobStatus, StockDailyFeature, FeatureCorrelation, StockEvent, StockPoolMember, StockProfile, TradingSignal, PositionManagement, Portfolio, PaperTradingSnapshot, PaperTradeLog, PredictionEvaluation, ModelLifecycleEvent, PipelineRun
from .prediction.model_inference import predict_symbol as _predict_symbol  # inference utility
from .prediction.forecast import predict_stock_price
from .reports.report import generate_report_data
from .reports.macro_report import generate_and_store_macro_report
from .reports.macro_pipeline import run_pipeline as run_macro_observation_pipeline
from .tasks.task_manager import TaskManager
from .tasks.scheduler import run_daily_pipeline, attach_scheduler
from .core.trading_calendar import (
    is_trading_day as _calendar_is_trading_day,
    next_trading_day as _calendar_next_trading_day,
    last_trading_day_on_or_before as _calendar_last_trading_day_on_or_before,
)
import pandas as pd
import httpx
from urllib.parse import urlparse
from .routers.news import router as news_router
from .routers.movers import router as movers_router
from .routers.movers import warm_live_insight_cache  # 预热实时行情缓存
from .core import logging_config  # ensure logging configured

# Agent script导入（延迟加载避免启动时耗时）
from pathlib import Path as _Path
import threading as _threading
import uuid as _uuid
import traceback as _tb
from collections import deque, Counter, OrderedDict
import math

# --- 子进程生命周期跟踪 ---
_CHILD_PROCESSES: list = []  # List[subprocess.Popen]
_CHILD_PROCS_LOCK = _threading.Lock()


def _track_child_process(proc) -> None:
    """注册一个 subprocess.Popen 实例以便 shutdown 时清理"""
    with _CHILD_PROCS_LOCK:
        # 顺便清理已经结束的进程
        _CHILD_PROCESSES[:] = [p for p in _CHILD_PROCESSES if p.poll() is None]
        _CHILD_PROCESSES.append(proc)


def _cleanup_child_processes() -> None:
    """终止所有仍在运行的子进程（优雅关闭 → 强制杀死）"""
    with _CHILD_PROCS_LOCK:
        alive = [p for p in _CHILD_PROCESSES if p.poll() is None]
    if not alive:
        return
    logger.info("正在清理 %d 个子进程...", len(alive))
    for p in alive:
        try:
            p.terminate()
        except Exception:
            pass
    # 等待 5 秒后强制杀死
    import time as _t
    _t.sleep(5)
    for p in alive:
        try:
            if p.poll() is None:
                p.kill()
                logger.warning("强制杀死子进程 PID=%s", p.pid)
        except Exception:
            pass


_AGENT_JOBS: dict[str, dict] = {}  # legacy in-memory cache (will mirror DB subset)
_AGENT_JOBS_LOCK = _threading.Lock()
_AGENT_QUEUE: list[str] = []  # store job_id referencing DB rows
_AGENT_METRICS = {
    'runs_total': 0,
    'runs_failed_total': 0,
    'runs_succeeded_total': 0,
    'last_run_duration_sec': 0.0,
    'last_run_finished_at': ''
}

# --- Redis safe helpers with in-process fallback ---
_redis_client = None
# in-process LRU cache used as fallback when Redis is unavailable
_LOCAL_CACHE_MAX = int(os.getenv('LOCAL_CACHE_MAX', '1024'))
_local_cache: "OrderedDict[str, tuple]" = OrderedDict()
_local_cache_lock = _threading.Lock()
# simple stats
_local_cache_hits = 0
_local_cache_misses = 0
# redis-layer stats (count only when redis client used)
_redis_cache_hits = 0
_redis_cache_misses = 0
_redis_cache_sets = 0
_local_cache_sets = 0
# TTLs for watchlist snapshot cache (fresh + stale). Make configurable via env for testing.
WATCHLIST_FRESH_TTL = int(os.getenv('WATCHLIST_FRESH_TTL', '8'))
WATCHLIST_STALE_TTL = int(os.getenv('WATCHLIST_STALE_TTL', '300'))

try:
    import redis as _redis_lib
    _redis_url = os.getenv('REDIS_URL') or os.getenv('REDIS_URI') or 'redis://127.0.0.1:6379/0'
    try:
        _redis_client = _redis_lib.from_url(_redis_url, socket_connect_timeout=1)
        # quick ping to confirm
        try:
            _redis_client.ping()
        except Exception:
            _redis_client = None
    except Exception:
        _redis_client = None
except Exception:
    _redis_client = None

def _redis_get(key: str):
    """Get key from Redis with local fallback."""
    # try redis first
    try:
        if _redis_client is not None:
            v = _redis_client.get(key)
            try:
                global _redis_cache_hits, _redis_cache_misses
            except Exception:
                pass
            if v is None:
                try:
                    _redis_cache_misses += 1
                except Exception:
                    pass
                return None
            try:
                _redis_cache_hits += 1
            except Exception:
                pass
            if isinstance(v, bytes):
                return v.decode('utf-8')
            return v
    except Exception:
        pass
    # fallback to local cache
    try:
        global _local_cache_hits, _local_cache_misses
        with _local_cache_lock:
            entry = _local_cache.get(key)
            if not entry:
                _local_cache_misses += 1
                return None
            value, exp = entry
            if exp is not None and time.time() > exp:
                try:
                    del _local_cache[key]
                except Exception:
                    pass
                _local_cache_misses += 1
                return None
            # move to end (most recently used)
            try:
                _local_cache.pop(key)
                _local_cache[key] = (value, exp)
            except Exception:
                pass
            _local_cache_hits += 1
            return value
    except Exception:
        return None

def _redis_set(key: str, value: str, ex: Optional[int] = None):
    """Set key to Redis with local fallback. value must be str."""
    global _redis_cache_sets, _local_cache_sets
    try:
        if _redis_client is not None:
            # redis-py accepts str/bytes
            if ex is not None:
                _redis_client.set(key, value, ex=ex)
            else:
                _redis_client.set(key, value)
            try:
                _redis_cache_sets += 1
            except Exception:
                try:
                    logger.warning("failed to increment _redis_cache_sets")
                except Exception:
                    pass
            try:
                logger.debug("_redis_set success key=%s ex=%s", key, ex)
            except Exception:
                pass
            try:
                logger.info("redis write success key=%s ex=%s", key, ex)
            except Exception:
                pass
            return True
    except Exception:
        try:
            logger.warning("_redis_set failed for key %s: %s", key, str(sys.exc_info()[1]))
        except Exception:
            pass
    # fallback to local cache
    try:
        with _local_cache_lock:
            exp = time.time() + ex if ex is not None else None
            # set/refresh and move to end
            if key in _local_cache:
                try:
                    _local_cache.pop(key)
                except Exception:
                    pass
            _local_cache[key] = (value, exp)
            try:
                _local_cache_sets += 1
            except Exception:
                pass
            # evict least-recently-used if over capacity
            try:
                while len(_local_cache) > _LOCAL_CACHE_MAX:
                    _local_cache.popitem(last=False)
            except Exception:
                pass
        return True
    except Exception:
        return False


def _acquire_refresh_lock(lock_key: str, ex: int = 30) -> bool:
    """Try to acquire a refresh lock. Return True if acquired."""
    try:
        if _redis_client is not None:
            # SET NX with expiration
            return _redis_client.set(lock_key, "1", nx=True, ex=ex)
    except Exception:
        pass
    # fallback: use local cache
    try:
        with _local_cache_lock:
            entry = _local_cache.get(lock_key)
            now = time.time()
            if entry:
                _, exp = entry
                if exp is None or now <= exp:
                    return False
            _local_cache[lock_key] = ("1", now + ex)
            return True
    except Exception:
        return False


def _release_refresh_lock(lock_key: str):
    try:
        if _redis_client is not None:
            _redis_client.delete(lock_key)
            return True
    except Exception:
        pass
    try:
        with _local_cache_lock:
            if lock_key in _local_cache:
                del _local_cache[lock_key]
        return True
    except Exception:
        return False


async def _refresh_watchlist_snapshot_async(cache_key: str, stale_key: str, limit: int, fundflow_prefer: str):
    """Asynchronously recompute watchlist snapshot and update fresh+stale cache keys."""
    try:
        # call the synchronous handler in a thread to reuse computation logic
        result = await asyncio.to_thread(watchlist_snapshot, limit, fundflow_prefer, True)
        # ensure we have a JSON-serializable dict
        if isinstance(result, (dict, list)):
            payload = json.dumps(result, ensure_ascii=False)
        else:
            try:
                payload = json.dumps(result.json(), ensure_ascii=False)
            except Exception:
                payload = json.dumps({'result': str(result)}, ensure_ascii=False)
        try:
            _redis_set(cache_key, payload, ex=WATCHLIST_FRESH_TTL)
            _redis_set(stale_key, payload, ex=WATCHLIST_STALE_TTL)
        except Exception:
            pass
    except Exception:
        logger.exception("_refresh_watchlist_snapshot_async failed")


def _refresh_watchlist_snapshot(cache_key: str, stale_key: str, limit: int, fundflow_prefer: str):
    """Schedule a background refresh using asyncio when available, else thread."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_refresh_watchlist_snapshot_async(cache_key, stale_key, limit, fundflow_prefer))
        return True
    except RuntimeError:
        # no running loop, fallback to thread
        def _bg():
            try:
                import asyncio as _asyncio
                _asyncio.run(_refresh_watchlist_snapshot_async(cache_key, stale_key, limit, fundflow_prefer))
            except Exception:
                logger.exception("threaded _refresh_watchlist_snapshot failed")

        _threading.Thread(target=_bg, daemon=True).start()
        return True
    except Exception:
        return False

_AGENT_DURATION_HISTORY: deque[float] = deque(maxlen=300)
_AGENT_FAILURE_REASON_COUNTS: Counter = Counter()

def _agent_max_concurrent() -> int:
    try:
        return max(1, int(os.getenv('AGENT_MAX_CONCURRENT', '1')))
    except Exception:
        return 1

def _dispatch_next_agent_if_possible():
    """Attempt to start next queued agent job if under concurrency limit (DB-backed)."""
    with _AGENT_JOBS_LOCK:
        running = sum(1 for j in _AGENT_JOBS.values() if j.get('status') == 'running')
        limit = _agent_max_concurrent()
        if running >= limit:
            return
        if not _AGENT_QUEUE:
            return
        job_id = _AGENT_QUEUE.pop(0)
        # mark running in DB
        with SessionLocal() as session:
            job_row = session.query(AgentJob).filter(AgentJob.job_id==job_id).first()
            if not job_row or job_row.status != AgentJobStatus.QUEUED.value:
                return
            job_row.status = AgentJobStatus.RUNNING.value
            job_row.started_at = datetime.utcnow()
            strict_flag = job_row.strict_mode
            created_at_value = job_row.created_at  # capture before session closes/commit to avoid expiration
            session.commit()
        _AGENT_JOBS[job_id] = {
            'status': 'running',
            'strict': strict_flag,
            'created_at': created_at_value.isoformat() if created_at_value else None
        }
    t = _threading.Thread(target=_run_agent_job, args=(job_id, strict_flag), daemon=True)
    t.start()
_AGENT_SCRIPT_PATH = _Path(__file__).resolve().parent / "scripts" / "top20_llm_agent_full.py"  # deprecated: script removed

def _run_agent_job(job_id: str, strict: bool):
    start_ts = time.time()
    env_backup = os.environ.get('AGENT_STRICT_JSON')
    try:
        if strict:
            os.environ['AGENT_STRICT_JSON'] = '1'
        cmd = [sys.executable, str(_AGENT_SCRIPT_PATH)]
        import subprocess, json as _json
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        _track_child_process(proc)
        stdout, stderr = proc.communicate()
        rc = proc.returncode
        report_paths = []
        # 解析 stdout 中出现的生成路径提示
        for line in stdout.splitlines()[-30:]:
            if 'agent_report_' in line and ('.json' in line or '.md' in line):
                report_paths.append(line.strip())
        status_final = 'finished' if rc == 0 else 'failed'
        duration = round(time.time() - start_ts,2)
        stdout_tail = stdout.splitlines()[-80:]
        stderr_tail = stderr.splitlines()[-80:]
        with SessionLocal() as session:
            row = session.query(AgentJob).filter(AgentJob.job_id==job_id).first()
            if row:
                row.status = AgentJobStatus.FINISHED.value if status_final=='finished' else AgentJobStatus.FAILED.value
                row.finished_at = datetime.utcnow()
                row.return_code = rc
                row.stdout_tail = "\n".join(stdout_tail)
                row.stderr_tail = "\n".join(stderr_tail)
                row.reports_json = json.dumps(report_paths, ensure_ascii=False)
                row.duration_sec = duration
                session.commit()
        with _AGENT_JOBS_LOCK:
            existing = _AGENT_JOBS.get(job_id, {})
            existing.update({
                'status': status_final,
                'return_code': rc,
                'stdout_tail': stdout_tail,
                'stderr_tail': stderr_tail,
                'duration_sec': duration,
                'reports_detected': report_paths
            })
            _AGENT_JOBS[job_id] = existing
            _AGENT_METRICS['runs_total'] += 1
            if status_final == 'failed':
                _AGENT_METRICS['runs_failed_total'] += 1
                # classify failure reason
                fail_reason = 'nonzero_exit' if rc != 0 else 'unknown'
                # simple heuristic from stderr tail
                joined_err = '\n'.join(stderr_tail).lower()
                if 'timeout' in joined_err:
                    fail_reason = 'timeout'
                elif 'azure' in joined_err and 'error' in joined_err:
                    fail_reason = 'azure_llm'
                elif 'connection' in joined_err or 'network' in joined_err:
                    fail_reason = 'network'
                _AGENT_FAILURE_REASON_COUNTS[fail_reason] += 1
            else:
                _AGENT_METRICS['runs_succeeded_total'] += 1
                # Trigger feature extraction in a background thread (non-blocking)
                def _bg_build_features():
                    try:
                        import subprocess, sys as _sys, shlex
                        script_path = _Path(__file__).resolve().parent.parent / 'scripts' / 'build_daily_features.py'
                        if script_path.exists():
                            _p1 = subprocess.Popen([_sys.executable, str(script_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            _track_child_process(_p1)
                        # trigger stock pool update (will call enrichment for new symbols)
                        try:
                            pool_script = _Path(__file__).resolve().parent.parent / 'scripts' / 'update_stock_pool.py'
                            if pool_script.exists():
                                _p2 = subprocess.Popen([_sys.executable, str(pool_script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                _track_child_process(_p2)
                        except Exception as e2:
                            logger.warning("auto update_stock_pool failed: %s", e2, exc_info=True)
                        # Persist daily agent report (best-effort)
                        try:
                            from .utils.agent_persistence import persist_agent_report
                            # Attempt to parse the last JSON file path from report_paths lines
                            json_path = None
                            md_path = None
                            for p_line in reversed(report_paths):
                                # lines like 'JSON: D:\\...agent_report_2025....json'
                                if '.json' in p_line and 'agent_report_' in p_line:
                                    # extract path after 'JSON:' or whole token
                                    part = p_line.split('JSON:')[-1].strip()
                                    if part.endswith('.json'):
                                        json_path = _Path(part)
                                        md_candidate = json_path.with_suffix('.md')
                                        if md_candidate.exists():
                                            md_path = md_candidate
                                        break
                            if json_path and json_path.exists():
                                persist_agent_report(json_path, md_path, job_id=job_id)
                        except Exception as pe:
                            logger.warning("persist_agent_report failed: %s", pe, exc_info=True)
                    except Exception as e:
                        logger.warning("auto build_daily_features failed: %s", e, exc_info=True)
                _threading.Thread(target=_bg_build_features, daemon=True).start()
            _AGENT_METRICS['last_run_duration_sec'] = duration
            _AGENT_METRICS['last_run_finished_at'] = datetime.utcnow().isoformat()
            _AGENT_DURATION_HISTORY.append(duration)
        _dispatch_next_agent_if_possible()
    except Exception as e:
        duration = round(time.time() - start_ts,2)
        # 在异常路径也使用 with，避免连接泄漏；如遇连接池/瞬时故障，短暂等待后重试一次
        try:
            with SessionLocal() as session:
                row = session.query(AgentJob).filter(AgentJob.job_id==job_id).first()
                if row:
                    row.status = AgentJobStatus.FAILED.value
                    row.finished_at = datetime.utcnow()
                    row.error_message = str(e)
                    row.traceback = _tb.format_exc()
                    row.duration_sec = duration
                    session.commit()
        except Exception:
            try:
                time.sleep(0.2)
                with SessionLocal() as session:
                    row = session.query(AgentJob).filter(AgentJob.job_id==job_id).first()
                    if row:
                        row.status = AgentJobStatus.FAILED.value
                        row.finished_at = datetime.utcnow()
                        row.error_message = str(e)
                        row.traceback = _tb.format_exc()
                        row.duration_sec = duration
                        session.commit()
            except Exception:
                pass
        with _AGENT_JOBS_LOCK:
            existing = _AGENT_JOBS.get(job_id, {})
            existing.update({
                'status': 'failed',
                'error': str(e),
                'traceback': _tb.format_exc(),
                'duration_sec': duration
            })
            _AGENT_JOBS[job_id] = existing
            _AGENT_METRICS['runs_total'] += 1
            _AGENT_METRICS['runs_failed_total'] += 1
            _AGENT_METRICS['last_run_duration_sec'] = duration
            _AGENT_METRICS['last_run_finished_at'] = datetime.utcnow().isoformat()
            _AGENT_DURATION_HISTORY.append(duration)
            # classify exception reason
            reason = type(e).__name__.lower()
            if 'timeout' in reason:
                reason = 'timeout'
            _AGENT_FAILURE_REASON_COUNTS[reason] += 1
        _dispatch_next_agent_if_possible()
    finally:
        # 还原环境（确保异常时也执行）
        if env_backup is None:
            os.environ.pop('AGENT_STRICT_JSON', None)
        else:
            os.environ['AGENT_STRICT_JSON'] = env_backup

logger = logging.getLogger(__name__)

# 创建任务管理器实例
task_manager = TaskManager()

# Prefer ORJSONResponse for performance, but gracefully fall back if orjson isn't installed
import importlib.util as _importlib_util
if _importlib_util.find_spec("orjson") is not None:
    DefaultResponse = ORJSONResponse
else:
    DefaultResponse = JSONResponse

app = FastAPI(title="AI Stock API", version="1.1", default_response_class=DefaultResponse)
app.include_router(news_router)
app.include_router(movers_router)

# 每日分析中心路由
from .routers.analysis import router as analysis_router
app.include_router(analysis_router)

# 回测系统路由
from .routers.backtest import router as backtest_router
app.include_router(backtest_router)

# 财务数据路由
from .routers.financial import router as financial_router
app.include_router(financial_router)

# Web 数据查询路由 (天气、股票、百科、新闻、搜索)
from .routers.webdata import router as webdata_router
app.include_router(webdata_router, prefix="/api")

# 股票池管理路由
from .routers.stock_pool import router as stock_pool_router
app.include_router(stock_pool_router)

# 用户真实持仓/交易流水路由
from .routers.user_portfolio import router as user_portfolio_router
app.include_router(user_portfolio_router)

# 潜力股票机会发现路由
from .routers.opportunities import router as opportunities_router
app.include_router(opportunities_router)

# === v1.1 升级：事件、简报、RAG 路由 ===
from .routers.events import router as events_router
from .routers.briefings import router as briefings_router
from .routers.rag import router as rag_router
app.include_router(events_router)
app.include_router(briefings_router)
app.include_router(rag_router)

from .routers.pipeline_status import router as pipeline_status_router
app.include_router(pipeline_status_router)

from .routers.agent_runtime import router as agent_runtime_router
app.include_router(agent_runtime_router)

# AI 量化引擎路由
from .quant_engine.api import quant_router
app.include_router(quant_router)


@app.get("/internal/metrics")
def internal_metrics(request: Request):
    """Internal metrics for caching and availability (for debugging/ops).

    Access control:
    - Always allow requests from localhost (127.0.0.1 or ::1).
    - Allow remote access only when ENV is 'dev'/'development' or INTERNAL_METRICS_ENABLED=true.
    """
    try:
        client_ip = None
        try:
            client_ip = request.client.host
        except Exception:
            client_ip = None

        env = os.getenv('ENV', '').lower()
        enabled_flag = os.getenv('INTERNAL_METRICS_ENABLED', '').lower() == 'true'
        is_local = client_ip in ("127.0.0.1", "::1", "localhost")
        if not (is_local or enabled_flag or env in ("dev", "development")):
            raise HTTPException(status_code=403, detail="internal metrics access denied")

        with _local_cache_lock:
            size = len(_local_cache)
        return {
            "local_cache_hits": globals().get('_local_cache_hits', 0),
            "local_cache_misses": globals().get('_local_cache_misses', 0),
            "local_cache_sets": globals().get('_local_cache_sets', 0),
            "local_cache_size": size,
            "local_cache_max": globals().get('_LOCAL_CACHE_MAX', None),
            "redis_available": bool(_redis_client),
            "redis_cache_hits": globals().get('_redis_cache_hits', 0),
            "redis_cache_misses": globals().get('_redis_cache_misses', 0),
            "redis_cache_sets": globals().get('_redis_cache_sets', 0),
            "client_ip": client_ip,
            "env": env,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"error": "failed to collect metrics", "detail": str(e)}

# === Persisted Agent Daily Reports API ===
from sqlalchemy import select as _select
from .core.models import AgentDailyReport as _AgentDailyReport

@app.get('/api/agent/daily/latest')
async def get_agent_daily_latest(with_markdown: bool = Query(True), prefer_filesystem: bool = Query(False, description="当为 true 时跳过数据库，优先读取 agent_reports 的最新文件，避免持久化副本滞后")):
    # 1) 首选持久化表（除非显式要求优先文件）
    if not prefer_filesystem:
        with SessionLocal() as session:
            row = session.execute(
                _select(_AgentDailyReport).order_by(_AgentDailyReport.report_date.desc())
            ).scalars().first()
            if row:
                return {
                    'report_date': row.report_date.isoformat(),
                    'generated_at': row.generated_at.isoformat() if row.generated_at else None,
                    'job_id': row.job_id,
                    'top20_count': row.top20_count,
                    'version': row.version,
                    'stock_reports': json.loads(row.stock_reports_json) if row.stock_reports_json else None,
                    'macro': json.loads(row.macro_json) if row.macro_json else None,
                    'analytics': json.loads(row.analytics_json) if row.analytics_json else None,
                    'diagnostics': json.loads(row.diagnostics_json) if row.diagnostics_json else None,
                    'markdown': row.markdown if with_markdown else None,
                }
    # 2) 回退到磁盘上的最新 agent_reports 文件
    try:
        reports_dir = _Path(__file__).resolve().parent.parent.parent / "agent_reports"
        files = []
        if reports_dir.exists():
            files = sorted(reports_dir.glob("agent_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise HTTPException(status_code=404, detail='no persisted agent daily report')
        f = files[0]
        rpt = json.loads(f.read_text('utf-8'))
        # 字段自适应映射
        report_date = None
        gen_at = None
        try:
            if isinstance(rpt.get('report_date'), str):
                # 可能是 'YYYY-MM-DD' 或 ISO 字符串
                try:
                    report_date = datetime.fromisoformat(rpt['report_date']).date().isoformat()
                except Exception:
                    report_date = rpt['report_date']
            elif isinstance(rpt.get('finished_at'), str):
                report_date = datetime.fromisoformat(rpt['finished_at']).date().isoformat()
        except Exception:
            report_date = datetime.utcnow().date().isoformat()
        try:
            if isinstance(rpt.get('finished_at'), str):
                gen_at = datetime.fromisoformat(rpt['finished_at']).isoformat()
        except Exception:
            gen_at = datetime.utcnow().isoformat()

        stock_reports = rpt.get('stock_reports') or rpt.get('top10') or rpt.get('top20')
        top20_count = len(stock_reports) if isinstance(stock_reports, list) else (rpt.get('top20_count') or 0)
        version = rpt.get('version') or 1
        entry = {
            'report_date': report_date,
            'generated_at': gen_at,
            'job_id': rpt.get('job_id'),
            'top20_count': top20_count,
            'version': version,
            'stock_reports': stock_reports,
            'macro': rpt.get('macro'),
            'analytics': rpt.get('analytics'),
            'diagnostics': rpt.get('diagnostics'),
        }
        if with_markdown:
            md_candidate = f.with_suffix('.md')
            if md_candidate.exists():
                try:
                    entry['markdown'] = md_candidate.read_text('utf-8')
                except Exception:
                    entry['markdown_error'] = 'failed to read markdown file'
        return entry
    except HTTPException:
        raise
    except Exception as e:
        # 3) 最终兜底：返回 404 + 简述错误，避免前端空指针
        raise HTTPException(status_code=404, detail=f'no persisted agent daily report (fallback failed: {str(e)})')

@app.get('/api/agent/daily/{report_date}')
async def get_agent_daily_by_date(report_date: str, with_markdown: bool = Query(True)):
    try:
        d = datetime.fromisoformat(report_date).date()
    except Exception:
        raise HTTPException(status_code=400, detail='invalid date format (YYYY-MM-DD)')
    with SessionLocal() as session:
        row = session.execute(
            _select(_AgentDailyReport).where(_AgentDailyReport.report_date==d)
        ).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail='report not found')
        return {
            'report_date': row.report_date.isoformat(),
            'generated_at': row.generated_at.isoformat() if row.generated_at else None,
            'job_id': row.job_id,
            'top20_count': row.top20_count,
            'version': row.version,
            'stock_reports': json.loads(row.stock_reports_json) if row.stock_reports_json else None,
            'macro': json.loads(row.macro_json) if row.macro_json else None,
            'analytics': json.loads(row.analytics_json) if row.analytics_json else None,
            'diagnostics': json.loads(row.diagnostics_json) if row.diagnostics_json else None,
            'markdown': row.markdown if with_markdown else None,
        }

@app.get('/api/agent/daily/list')
async def list_agent_daily_reports(limit: int = Query(7, ge=1, le=30), with_markdown: bool = Query(False)):
    with SessionLocal() as session:
        rows = session.execute(
            _select(_AgentDailyReport).order_by(_AgentDailyReport.report_date.desc()).limit(limit)
        ).scalars().all()
        out = []
        for r in rows:
            out.append({
                'report_date': r.report_date.isoformat(),
                'generated_at': r.generated_at.isoformat() if r.generated_at else None,
                'job_id': r.job_id,
                'top20_count': r.top20_count,
                'version': r.version,
                'macro': json.loads(r.macro_json) if r.macro_json else None,
                'analytics': json.loads(r.analytics_json) if r.analytics_json else None,
                'diagnostics': json.loads(r.diagnostics_json) if r.diagnostics_json else None,
                'markdown': r.markdown if with_markdown else None,
            })
        return out

@app.get('/metrics', response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics for agent runs and queue state."""
    with _AGENT_JOBS_LOCK:
        running = sum(1 for j in _AGENT_JOBS.values() if j.get('status') == 'running')
        queued = sum(1 for j in _AGENT_JOBS.values() if j.get('status') == 'queued')
    # compute avg & p95
    if _AGENT_DURATION_HISTORY:
        durations_sorted = sorted(_AGENT_DURATION_HISTORY)
        avg_dur = sum(_AGENT_DURATION_HISTORY)/len(_AGENT_DURATION_HISTORY)
        idx = max(0, int(math.ceil(0.95 * len(durations_sorted))) - 1)
        p95 = durations_sorted[idx]
    else:
        avg_dur = 0.0
        p95 = 0.0
    lines = [
        f"agent_runs_total {_AGENT_METRICS['runs_total']}",
        f"agent_runs_failed_total {_AGENT_METRICS['runs_failed_total']}",
        f"agent_runs_succeeded_total {_AGENT_METRICS['runs_succeeded_total']}",
        f"agent_last_run_duration_seconds {_AGENT_METRICS['last_run_duration_sec']}",
        f"agent_duration_avg_seconds {avg_dur:.3f}",
        f"agent_duration_p95_seconds {p95:.3f}",
        f"agent_running {running}",
        f"agent_queued {queued}"
    ]
    for reason, cnt in _AGENT_FAILURE_REASON_COUNTS.items():
        safe_reason = re.sub(r'[^a-zA-Z0-9_]', '_', reason)
        lines.append(f'agent_failure_reason_total{{reason="{safe_reason}"}} {cnt}')
    return "\n".join(lines) + "\n"

@app.post("/api/agent/run")
async def run_agent(strict_json: bool = False):
    """启动一次 Top20 智能分析 Agent 运行（异步）。

    参数：
    - strict_json: 是否强制启用严格 JSON 模式（覆盖当前进程环境变量）。

    返回：job_id 用于后续查询状态。
    """
    if not _AGENT_SCRIPT_PATH.exists():
        raise HTTPException(status_code=501, detail="Agent script has been removed; this endpoint is deprecated")
    job_id = _uuid.uuid4().hex
    limit = _agent_max_concurrent()
    with _AGENT_JOBS_LOCK:
        running_now = sum(1 for j in _AGENT_JOBS.values() if j.get('status') == 'running')
        queued_status = AgentJobStatus.QUEUED.value
        running_status = AgentJobStatus.RUNNING.value
        if running_now >= limit:
            # create queued row
            with SessionLocal() as session:
                row = AgentJob(job_id=job_id, status=queued_status, strict_mode=strict_json)
                session.add(row)
                session.commit()
            _AGENT_JOBS[job_id] = {'status': 'queued', 'strict': strict_json, 'created_at': datetime.utcnow().isoformat()}
            _AGENT_QUEUE.append(job_id)
            position = len(_AGENT_QUEUE)
            return {"job_id": job_id, "status": "queued", "queue_position": position, "concurrency_limit": limit}
        else:
            with SessionLocal() as session:
                row = AgentJob(job_id=job_id, status=running_status, strict_mode=strict_json, started_at=datetime.utcnow())
                session.add(row)
                session.commit()
            _AGENT_JOBS[job_id] = {'status': 'running', 'strict': strict_json, 'created_at': datetime.utcnow().isoformat()}
    t = _threading.Thread(target=_run_agent_job, args=(job_id, strict_json), daemon=True)
    t.start()
    return {"job_id": job_id, "status": "running", "concurrency_limit": limit}

@app.get("/api/agent/status/{job_id}")
async def get_agent_status(job_id: str):
    # prefer DB row for canonical state
    with SessionLocal() as session:
        row = session.query(AgentJob).filter(AgentJob.job_id==job_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="job not found")
        data = {
            'status': row.status,
            'job_id': row.job_id,
            'strict': row.strict_mode,
            'created_at': row.created_at.isoformat() if row.created_at else None,
            'started_at': row.started_at.isoformat() if row.started_at else None,
            'finished_at': row.finished_at.isoformat() if row.finished_at else None,
            'return_code': row.return_code,
            'stdout_tail': row.stdout_tail.split('\n') if row.stdout_tail else [],
            'stderr_tail': row.stderr_tail.split('\n') if row.stderr_tail else [],
            'reports_detected': json.loads(row.reports_json) if row.reports_json else [],
            'error': row.error_message,
            'traceback': row.traceback,
            'duration_sec': row.duration_sec
        }
    return data

@app.get("/api/agent/latest")
async def get_latest_agent_report(limit: int = Query(1, ge=1, le=20), with_markdown: bool = Query(False)):
    """返回最近生成的智能分析报告（JSON）。

    参数:
    - limit: 返回最近 N 份报告的 JSON 内容；=1 时仅返回最新；>1 返回数组。

    说明:
    - 扫描 `agent_reports/agent_report_*.json` 按修改时间倒序。
    - 若无报告，返回 404。
    - limit=1: {"report": {...}, "path": "..."}
    - limit>1: {"reports": [{"path": "...", "report": {...}}, ...]}
    """
    reports_dir = _Path(__file__).resolve().parent.parent.parent / "agent_reports"
    files = []
    if reports_dir.exists():
        files = sorted(reports_dir.glob("agent_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        # Graceful fallback: attempt to use latest AgentJob summary
        try:
            with SessionLocal() as session:
                job = session.query(AgentJob).order_by(AgentJob.created_at.desc()).first()
                if job:
                    skeleton = {
                        'path': None,
                        'report': {
                            'job_id': job.job_id,
                            'status': job.status,
                            'created_at': job.created_at.isoformat() if job.created_at else None,
                            'finished_at': job.finished_at.isoformat() if job.finished_at else None,
                            'duration_sec': job.duration_sec,
                            'stdout_tail': job.stdout_tail.split('\n') if job.stdout_tail else [],
                            'stderr_tail': job.stderr_tail.split('\n') if job.stderr_tail else [],
                            'fallback': 'agent_job_row_no_report_files'
                        }
                    }
                    if limit == 1:
                        return skeleton
                    return {"reports": [skeleton], "count": 1, "fallback": True}
        except Exception:
            pass
        # ultimate fallback empty structure
        empty = {'path': None, 'report': {'message': 'no reports yet', 'fallback': 'empty'}}
        if limit == 1:
            return empty
        return {"reports": [empty], "count": 1, "fallback": True}
    selected = files[:limit]
    out = []
    for f in selected:
        try:
            data = json.loads(f.read_text("utf-8"))
        except Exception as e:
            data = {"error": str(e)}
        entry = {"path": str(f.name), "report": data}
        if with_markdown:
            md_candidate = f.with_suffix('.md')
            if md_candidate.exists():
                try:
                    entry['markdown'] = md_candidate.read_text('utf-8')
                except Exception as e:
                    entry['markdown_error'] = str(e)
        out.append(entry)
    if limit == 1:
        return out[0]
    return {"reports": out, "count": len(out)}

@app.get("/api/agent/metrics/latest")
async def get_latest_agent_metrics():
    """返回最新的 agent 诊断指标 (JSON)。

    优先读取 agent_reports/agent_metrics_latest.json (原子替换保证无部分写入)。
    如果不存在，则扫描 agent_metrics_*.json 最新一个。
    若均不存在，尝试回退到最新 report 的 diagnostics 字段。
    """
    reports_dir = _Path(__file__).resolve().parent.parent.parent / "agent_reports"
    if not reports_dir.exists():
        raise HTTPException(status_code=404, detail="no reports directory")
    latest_path = reports_dir / "agent_metrics_latest.json"
    if latest_path.exists():
        try:
            return json.loads(latest_path.read_text('utf-8'))
        except Exception as e:
            logger.warning("failed reading metrics_latest: %s", e, exc_info=True)
    # fallback: scan timestamped metrics
    metric_files = sorted(reports_dir.glob("agent_metrics_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for mf in metric_files:
        try:
            return json.loads(mf.read_text('utf-8'))
        except Exception:
            continue
    # final fallback: latest report diagnostics
    report_files = sorted(reports_dir.glob("agent_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for rf in report_files:
        try:
            rpt = json.loads(rf.read_text('utf-8'))
            if isinstance(rpt, dict) and rpt.get('diagnostics'):
                return {
                    'timestamp': rpt.get('finished_at'),
                    'generated_from': rf.name,
                    'diagnostics': rpt['diagnostics'],
                    'version': 1,
                    'fallback': 'from_report'
                }
        except Exception:
            continue
    raise HTTPException(status_code=404, detail="no metrics found")

# =========================
# Knowledge Base Endpoints
# =========================

# NOTE: GET /api/stock-pool 已迁移至 routers/stock_pool.py

@app.get("/api/stock-profile/{symbol}")
def get_stock_profile(symbol: str):
    with SessionLocal() as session:
        prof = session.query(StockProfile).filter(StockProfile.symbol==symbol).first()
        if not prof:
            raise HTTPException(status_code=404, detail="profile not found")
        return {
            'symbol': prof.symbol,
            'company_name': prof.company_name,
            'industry': prof.industry,
            'sub_industry': prof.sub_industry,
            'products': prof.core_products,
            'competitors': prof.competitors,
            'risk_factors': prof.risk_factors,
            'business_summary': prof.business_summary,
            'strategic_keywords': prof.strategic_keywords if hasattr(prof, 'strategic_keywords') else None,
            'last_refreshed': prof.last_refreshed.isoformat() if prof.last_refreshed else None
        }

@app.get("/api/stock-profile/{symbol}/details")
def get_stock_profile_details(symbol: str):
    """获取完整的公司画像详情，包含数据分析和统计信息"""
    with SessionLocal() as session:
        prof = session.query(StockProfile).filter(StockProfile.symbol==symbol).first()
        if not prof:
            raise HTTPException(status_code=404, detail="profile not found")
        
        # 计算数据完整度
        fields = [
            prof.company_name,
            prof.industry,
            prof.sub_industry,
            prof.business_summary,
            prof.core_products,
            prof.competitors,
            prof.risk_factors,
        ]
        completeness = sum(1 for f in fields if f) / len(fields) * 100
        
        # 统计关键词、产品、竞争对手等数量
        products = [p.strip() for p in prof.core_products.split(',') if p.strip()] if prof.core_products else []
        competitors = [c.strip() for c in prof.competitors.split(',') if c.strip()] if prof.competitors else []
        risk_factors = [r.strip() for r in prof.risk_factors.split(',') if r.strip()] if prof.risk_factors else []
        keywords = [k.strip() for k in prof.strategic_keywords.split(',') if k.strip()] if hasattr(prof, 'strategic_keywords') and prof.strategic_keywords else []
        
        return {
            'symbol': prof.symbol,
            'company_name': prof.company_name,
            'industry': prof.industry,
            'sub_industry': prof.sub_industry,
            'business_summary': prof.business_summary,
            'strategic_keywords': prof.strategic_keywords if hasattr(prof, 'strategic_keywords') else None,
            'products': prof.core_products,
            'competitors': prof.competitors,
            'risk_factors': prof.risk_factors,
            'last_refreshed': prof.last_refreshed.isoformat() if prof.last_refreshed else None,
            
            # 数据分析
            'analysis': {
                'profile_completeness': round(completeness),
                'products_count': len(products),
                'competitors_count': len(competitors),
                'risk_factors_count': len(risk_factors),
                'keywords_count': len(keywords),
                'quality_score': round(50 + completeness / 2),  # 质量评分 50-100
                'data_sources': ['Company databases', 'Public records'],
            },
            
            # 行业分析（基于现有数据）
            'industry_analysis': {
                'industry': prof.industry,
                'market_position': 'Mid-market' if len(competitors) > 3 else 'Niche',
                'competition_level': len(competitors),
            }
        }

@app.post("/api/stock-profile/{symbol}/enrich")
async def enrich_stock_profile(
    symbol: str,
    force_refresh: bool = Query(False, description="是否强制刷新（忽略24小时缓存）")
):
    """
    异步富化股票画像 - 通过 SearXNG 搜索新闻 + LLM 分析
    
    流程：
    1. 搜索该股票/公司的相关新闻
    2. 使用 LLM 对新闻进行分析和结构化
    3. 存储结果到 StockProfile 表
    
    返回：
    {
        "status": "success|processing|failed",
        "symbol": "...",
        "company_name": "...",
        "industry": "...",
        "business_summary": "...",
        "analysis": {...},  # LLM 分析结果
        "last_refreshed": "ISO datetime"
    }
    """
    try:
        from .utils.stock_profile_enrichment import StockProfileEnricher
        
        db = SessionLocal()
        
        try:
            # 获取公司名称
            profile = db.query(StockProfile).filter_by(symbol=symbol).first()
            company_name = profile.company_name if profile else None
            
            if not company_name:
                # 尝试从 Watchlist 获取
                watch = db.query(Watchlist).filter_by(symbol=symbol).first()
                company_name = watch.name if watch else symbol
            
            # 执行富化
            enricher = StockProfileEnricher()
            updated_profile = await enricher.enrich_stock_profile(
                symbol=symbol,
                company_name=company_name,
                db=db,
                force_refresh=force_refresh
            )
            
            if not updated_profile:
                return {
                    "status": "failed",
                    "symbol": symbol,
                    "message": "Failed to enrich profile"
                }
            
            # 解析 profile_json 如果存在
            analysis = {}
            if updated_profile.profile_json:
                try:
                    analysis = json.loads(updated_profile.profile_json)
                except:
                    pass
            
            return {
                "status": "success",
                "symbol": updated_profile.symbol,
                "company_name": updated_profile.company_name,
                "industry": updated_profile.industry,
                "sub_industry": updated_profile.sub_industry,
                "business_summary": updated_profile.business_summary,
                "core_products": updated_profile.core_products,
                "competitors": updated_profile.competitors,
                "risk_factors": updated_profile.risk_factors,
                "strategic_keywords": updated_profile.strategic_keywords,
                "analysis": analysis,
                "last_refreshed": updated_profile.last_refreshed.isoformat() if updated_profile.last_refreshed else None
            }
        
        finally:
            db.close()
    
    except Exception as e:
        logger.error(f"Error enriching profile for {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "failed",
            "symbol": symbol,
            "message": str(e)
        }

@app.post("/api/stock-profile/{symbol}/refresh")
def refresh_stock_profile(symbol: str):
    # Invoke enrichment script synchronously (placeholder) to refresh timestamp / create if missing
    import subprocess, sys as _sys
    script_path = _Path(__file__).resolve().parent.parent / 'scripts' / 'enrich_stock_profile.py'
    if not script_path.exists():
        raise HTTPException(status_code=500, detail="enrichment script missing")
    rc = subprocess.call([_sys.executable, str(script_path), '--symbol', symbol])
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"enrichment script failed rc={rc}")
    # Return updated profile
    with SessionLocal() as session:
        prof = session.query(StockProfile).filter(StockProfile.symbol==symbol).first()
        if not prof:
            raise HTTPException(status_code=500, detail="enrichment produced no profile")
        return {
            'symbol': prof.symbol,
            'company_name': prof.company_name,
            'industry': prof.industry,
            'last_refreshed': prof.last_refreshed.isoformat() if prof.last_refreshed else None
        }

@app.get("/api/features/daily")
def get_daily_features(symbol: str = Query(...), start: Optional[str] = Query(None), end: Optional[str] = Query(None), limit: int = Query(500, le=2000)):
    with SessionLocal() as session:
        q = session.query(StockDailyFeature).filter(StockDailyFeature.symbol==symbol)
        if start:
            q = q.filter(StockDailyFeature.trade_date >= date.fromisoformat(start))
        if end:
            q = q.filter(StockDailyFeature.trade_date <= date.fromisoformat(end))
        q = q.order_by(StockDailyFeature.trade_date.desc()).limit(limit)
        rows = q.all()
        def row_to_dict(r: StockDailyFeature):
            return {
                'trade_date': r.trade_date.isoformat(),
                'pct_chg': r.pct_chg,
                'ret_1d_prev': r.ret_1d_prev,
                'ret_5d_prev': r.ret_5d_prev,
                'vol_5d_prev': r.vol_5d_prev,
                'fwd_ret_1d': r.fwd_ret_1d,
                'fwd_ret_5d': r.fwd_ret_5d,
                'fwd_ret_10d': r.fwd_ret_10d,
                'fwd_ret_20d': r.fwd_ret_20d,
                'news_count': r.news_count,
                'agent_score': r.agent_score,
                'agent_factor_count': r.agent_factor_count,
                'agent_risk_factors_count': r.agent_risk_factors_count,
                'agent_parse_mode': r.agent_parse_mode,
                'agent_sentiment_label': r.agent_sentiment_label,
                'macro_sentiment_index': r.macro_sentiment_index,
                'macro_risk_index': r.macro_risk_index,
            }
        return {'symbol': symbol, 'rows': [row_to_dict(r) for r in rows]}

@app.get("/api/features/correlations")
def get_feature_correlations(feature: Optional[str] = None, horizon: Optional[str] = None, metric_type: Optional[str] = None, limit: int = Query(200, le=1000)):
    with SessionLocal() as session:
        q = session.query(FeatureCorrelation).order_by(FeatureCorrelation.computed_at.desc())
        if feature:
            q = q.filter(FeatureCorrelation.feature_name==feature)
        if horizon:
            q = q.filter(FeatureCorrelation.horizon==horizon)
        if metric_type:
            q = q.filter(FeatureCorrelation.metric_type==metric_type)
        q = q.limit(limit)
        rows = q.all()
        return {'count': len(rows), 'rows': [
            {
                'feature': r.feature_name,
                'horizon': r.horizon,
                'metric_type': r.metric_type,
                'value': r.value,
                'sample_size': r.sample_size,
                'window': r.rolling_window,
                'computed_at': r.computed_at.isoformat()
            } for r in rows
        ]}

@app.get("/api/events")
def get_events(symbol: Optional[str] = None, event_type: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None, limit: int = Query(300, le=1000)):
    with SessionLocal() as session:
        q = session.query(StockEvent).order_by(StockEvent.trade_date.desc())
        if symbol:
            q = q.filter(StockEvent.symbol==symbol)
        if event_type:
            q = q.filter(StockEvent.event_type==event_type)
        if start:
            q = q.filter(StockEvent.trade_date >= date.fromisoformat(start))
        if end:
            q = q.filter(StockEvent.trade_date <= date.fromisoformat(end))
        q = q.limit(limit)
        rows = q.all()
        out = []
        for r in rows:
            out.append({
                'symbol': r.symbol,
                'trade_date': r.trade_date.isoformat(),
                'event_type': r.event_type,
                'severity': r.severity,
                'trigger_features': r.trigger_features,
                'description': r.description,
                'source': r.source,
            })
        return {'count': len(out), 'rows': out}

@app.get("/api/models/predict")
def model_predict(symbol: str = Query(..., description="股票代码，如 600519.SH"), horizons: str = Query("1d,5d", description="预测周期列表，逗号分隔: 1d,5d,10d,20d"), trade_date: Optional[str] = Query(None, description="可选，使用该交易日的特征行；为空时取最新")):
    """在线预测接口：

    返回：
    - direction_prob_up_1d: 下一交易日上涨概率（若分类模型激活）
    - expected_return_{hz}: 各 horizon 预期收益（若对应回归模型激活）
    - symbol, trade_date

    说明：
    - horizons 参数形如 1d,5d,10d,20d（任意子集）
    - 若模型尚未训练/激活，对应字段缺失。
    - trade_date 指定时必须已有特征行；否则返回最新可用行。
    """
    hz_list = [h.strip() for h in horizons.split(',') if h.strip()]
    tdate = None
    if trade_date:
        try:
            tdate = date.fromisoformat(trade_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="trade_date 格式需 YYYY-MM-DD")
    with SessionLocal() as session:
        result = _predict_symbol(session, symbol, hz_list, tdate)
    if 'error' in result:
        raise HTTPException(status_code=404, detail=result['error'])
    return result


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every incoming HTTP request with duration and status code."""
    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    except Exception:
        logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        status = getattr(response, "status_code", "error")
        logger.info(
            "%s %s -> %s (%.2f ms)",
            request.method,
            request.url.path,
            status,
            duration_ms,
        )

# Startup: DB init + optional scheduler (legacy single-process mode)
@app.on_event("startup")
async def _startup_attach_scheduler():
    """应用启动钩子：
    - 保证数据库 schema 存在（create_all）
    - 仅当 ENABLE_SCHEDULER=1 **且** 未使用独立 worker 时挂载调度器
    - 在后台线程预热 watchlist 的实时快照，避免首个请求出现空/null

    推荐架构：API 进程设 ENABLE_SCHEDULER=0，由独立 worker 进程运行调度器。
    """
    try:
        init_database()
        # 推荐架构: API 进程不跑调度器; 仅在显式开启且没有独立 worker 时启用
        _sched_enabled = os.getenv("ENABLE_SCHEDULER", "0").lower() in ("1", "true", "yes", "y")
        if _sched_enabled:
            logger.warning(
                "API 进程内启动调度器 (ENABLE_SCHEDULER=1)。"
                "建议使用独立 worker 进程以避免重型任务导致 API OOM。"
            )
            attach_scheduler(app)
        else:
            logger.info("调度器已禁用 — 请确保独立 worker 进程正在运行")
    # Pre-warm snapshot cache in background so first request is not empty/null
        async def _prewarm_snapshot():
            try:
                # tiny delay to ensure app ready
                await asyncio.sleep(0.5)
                with SessionLocal() as session:
                    rows = session.execute(text("SELECT symbol FROM stock_pool_members WHERE exit_date IS NULL")).fetchall()
                    symbols = [r.symbol for r in rows]
                if symbols:
                    # call once to fill caches; ignore result
                    try:
                        _ = get_spot_snapshot(symbols)
                    except Exception as e:
                        logger.warning("Pre-warm snapshot failed once: %s", e, exc_info=True)
                        # one retry after short wait
                        await asyncio.sleep(1.0)
                        try:
                            _ = get_spot_snapshot(symbols)
                        except Exception as e2:
                            logger.warning("Pre-warm snapshot second attempt failed: %s", e2, exc_info=True)
            except Exception as e:
                logger.warning("Pre-warm task error: %s", e, exc_info=True)
        # On Windows with reload/multiprocessing, creating asyncio tasks during startup can
        # occasionally trigger event loop lifecycle issues. Run prewarm in a daemon thread instead.
        try:
            import threading
            def _bg_prewarm():
                try:
                    time.sleep(0.4)
                    # 预热 watchlist snapshot (从统一股票池读取)
                    with SessionLocal() as session:
                        rows = session.execute(text("SELECT symbol FROM stock_pool_members WHERE exit_date IS NULL")).fetchall()
                        symbols = [r.symbol for r in rows]
                    if symbols:
                        try:
                            _ = get_spot_snapshot(symbols)
                        except Exception:
                            time.sleep(1.0)
                            try:
                                _ = get_spot_snapshot(symbols)
                            except Exception:
                                pass
                    # 预热 live_insight （全市场实时涨跌榜）
                    try:
                        warm_live_insight_cache()
                    except Exception:
                        pass
                except Exception:
                    pass
            threading.Thread(target=_bg_prewarm, daemon=True).start()
        except Exception:
            pass
    except Exception as e:
        logger.exception("Scheduler initialization failed on startup: %s", e)


# 注册信号处理器，确保优雅关闭
@app.on_event("startup")
async def _startup_signal_handlers():
    """注册 SIGTERM/SIGINT 处理器以确保子进程被清理。

    注意：必须把 *前一个* 处理器（通常是 uvicorn 自己的 handler）保存下来，
    清理完子进程后**链式调用**它，否则进程会吞掉 SIGINT 永远不退出 —— 这是
    之前用户按 Ctrl+C 多次也无法关闭后端的直接原因。
    """
    import signal as _signal

    _prev_sigterm = None
    _prev_sigint = None
    _SHUTDOWN_FLAG = {"count": 0}

    def _graceful_shutdown(signum, frame):
        sig_name = _signal.Signals(signum).name if hasattr(_signal, 'Signals') else str(signum)
        _SHUTDOWN_FLAG["count"] += 1
        logger.warning("收到信号 %s，正在执行优雅关闭...（第 %d 次）", sig_name, _SHUTDOWN_FLAG["count"])
        try:
            _cleanup_child_processes()
        except Exception as _e:
            logger.warning("清理子进程时出错: %s", _e)

        # 链式调用原处理器，触发 uvicorn / asyncio 真正退出
        prev = _prev_sigint if signum == _signal.SIGINT else _prev_sigterm
        try:
            if callable(prev) and prev not in (_signal.SIG_DFL, _signal.SIG_IGN):
                prev(signum, frame)
                return
        except Exception as _e:
            logger.warning("链式调用原信号处理器失败: %s", _e)

        # 兜底：连按两次直接强退；单次则恢复默认并重发，让内核处理
        if _SHUTDOWN_FLAG["count"] >= 2:
            logger.warning("二次信号，强制退出进程")
            os._exit(130 if signum == _signal.SIGINT else 143)
        try:
            _signal.signal(signum, _signal.SIG_DFL)
            os.kill(os.getpid(), signum)
        except Exception:
            os._exit(1)

    try:
        _prev_sigterm = _signal.signal(_signal.SIGTERM, _graceful_shutdown)
        _prev_sigint = _signal.signal(_signal.SIGINT, _graceful_shutdown)
    except (OSError, ValueError):
        # Windows 上不支持部分信号，或非主线程
        pass


# 内存监控后台线程
@app.on_event("startup")
async def _startup_memory_monitor():
    """定期记录进程内存使用，便于排查 OOM"""
    import threading

    def _monitor_loop():
        try:
            import psutil
        except ImportError:
            logger.info("psutil 未安装，跳过内存监控")
            return
        proc = psutil.Process()
        while True:
            try:
                mem = proc.memory_info()
                rss_mb = mem.rss / (1024 * 1024)
                if rss_mb > 1024:
                    logger.warning(
                        "内存使用偏高: RSS=%.0fMB (VMS=%.0fMB)，可能面临 OOM 风险",
                        rss_mb, mem.vms / (1024 * 1024),
                    )
                elif rss_mb > 512:
                    logger.info("内存使用: RSS=%.0fMB", rss_mb)
            except Exception:
                pass
            time.sleep(60)

    threading.Thread(target=_monitor_loop, daemon=True, name="mem-monitor").start()


# 启动后台任务调度器（仅在 ENABLE_SCHEDULER 开启时 — 即 legacy 单进程模式）
@app.on_event("startup")
async def _startup_init_task_scheduler():
    """仅在单进程模式下初始化画像调度器；推荐由独立 worker 运行。"""
    if os.getenv("ENABLE_SCHEDULER", "0").lower() not in ("1", "true", "yes", "y"):
        return
    try:
        from .tasks.task_scheduler import init_task_scheduler
        init_task_scheduler()
        logger.info("后台任务调度器已初始化（单进程模式）")
    except ImportError:
        logger.warning("APScheduler 未安装，跳过后台任务调度器初始化")
    except Exception as e:
        logger.error("初始化后台任务调度器失败: %s", e)


# 应用关闭时停止所有调度器和子进程
@app.on_event("shutdown")
async def _shutdown_all_schedulers():
    """应用关闭时关闭所有调度器并清理子进程"""
    # 1) 关闭主 AsyncIOScheduler
    try:
        sched = getattr(app.state, "scheduler", None)
        if sched and sched.running:
            sched.shutdown(wait=False)
            logger.info("主调度器 (AsyncIOScheduler) 已关闭")
    except Exception as e:
        logger.error("关闭主调度器失败: %s", e)

    # 2) 关闭 BackgroundScheduler (task_scheduler)
    try:
        from .tasks.task_scheduler import shutdown_task_scheduler
        shutdown_task_scheduler()
        logger.info("后台任务调度器 (BackgroundScheduler) 已关闭")
    except Exception as e:
        logger.error("关闭后台任务调度器失败: %s", e)

    # 3) 终止所有跟踪的子进程
    _cleanup_child_processes()


@app.on_event("startup")
async def _startup_stock_pool():
    """启动时：预加载 A 股名录 + 可选回填。"""
    try:
        from .services.stock_pool_service import preload_stock_list
        preload_stock_list()
    except Exception as e:
        logger.warning("股票名录预加载失败: %s", e)

    if os.getenv("STOCK_POOL_BACKFILL", "1").lower() in ("1", "true", "yes"):
        try:
            from .services.stock_pool_service import start_backfill_background
            start_backfill_background(months=6)
        except Exception as e:
            logger.warning("股票池回填启动失败: %s", e)
    else:
        logger.info("股票池回填已禁用 (STOCK_POOL_BACKFILL=0)")

    # 启动时自动检查 & 补全未完成画像
    if os.getenv("STOCK_POOL_AUTO_PROFILE", "1").lower() in ("1", "true", "yes"):
        def _delayed_profile_check():
            """延迟 30 秒后检查并启动画像补全，避免与回填任务冲突。"""
            import time as _t
            _t.sleep(30)
            try:
                from .services.stock_pool_service import check_pool_profile_status, start_profile_completion_background
                status = check_pool_profile_status()
                incomplete = status.get("incomplete", 0)
                if incomplete > 0:
                    logger.info("启动画像自动补全: %d 只股票画像未完成", incomplete)
                    start_profile_completion_background(batch_limit=0, delay=3.0, force=False)
                else:
                    logger.info("所有股票池画像已完成，无需补全")
            except Exception as e:
                logger.warning("启动画像自动补全失败: %s", e)
        import threading
        threading.Thread(target=_delayed_profile_check, daemon=True, name="pool-auto-profile").start()
    else:
        logger.info("画像自动补全已禁用 (STOCK_POOL_AUTO_PROFILE=0)")


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.on_event("startup")
def _agent_queue_recover():
    """Recover persisted agent jobs into in-memory mirrors and re-queue unfinished ones.
    - Any RUNNING jobs on previous shutdown become QUEUED again (they were interrupted).
    - Any QUEUED jobs are appended preserving created_at ordering.
    Then we dispatch up to concurrency limit.
    """
    try:
        with SessionLocal() as session:
            rows = session.query(AgentJob).order_by(AgentJob.created_at.asc()).all()
            with _AGENT_JOBS_LOCK:
                for r in rows:
                    if r.status in (AgentJobStatus.RUNNING.value, AgentJobStatus.QUEUED.value):
                        # reset RUNNING -> QUEUED
                        if r.status == AgentJobStatus.RUNNING.value:
                            r.status = AgentJobStatus.QUEUED.value
                            r.started_at = None
                            session.add(r)
                        _AGENT_QUEUE.append(r.job_id)
                        _AGENT_JOBS[r.job_id] = {
                            'status': 'queued',
                            'strict': r.strict_mode,
                            'created_at': r.created_at.isoformat() if r.created_at else None
                        }
                    elif r.status in (AgentJobStatus.FINISHED.value, AgentJobStatus.FAILED.value):
                        _AGENT_JOBS[r.job_id] = {
                            'status': 'finished' if r.status==AgentJobStatus.FINISHED.value else 'failed',
                            'strict': r.strict_mode,
                            'created_at': r.created_at.isoformat() if r.created_at else None,
                            'started_at': r.started_at.isoformat() if r.started_at else None,
                            'finished_at': r.finished_at.isoformat() if r.finished_at else None,
                            'return_code': r.return_code,
                            'duration_sec': r.duration_sec,
                        }
                session.commit()
        # After populating, attempt dispatch within concurrency limit
        _dispatch_next_agent_if_possible()
    except Exception:
        logger.exception("Agent queue recovery failed")

# Dependency
def get_db():
    """FastAPI 依赖注入：提供 SQLAlchemy Session，使用完毕自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class WatchItem(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    enabled: bool = True
    pinned: bool | None = None  # 首页看板展示

# 全局缓存股票基础数据
_stock_basic_cache = None
# 全局缓存：股票名称映射表（code/symbol → name）
_stock_name_map_cache: dict[str, str] | None = None
_stock_name_map_cache_ts: float = 0  # 缓存时间戳
# 全局缓存：新闻挖掘到的名称
_news_name_map_cache: dict[str, str] = {}
# 全局缓存：文章→股票索引（all_symbols, symbol_count, symbol_times）
_article_data_cache: dict | None = None
_article_data_cache_ts: float = 0  # 缓存时间戳（300s TTL）
# 全局缓存：名称回填完成标记
_name_backfill_done_ts: float = 0


def _backfill_stock_names_sync():
    """在后台线程中运行的名称回填任务。
    使用独立 DB Session，不阻塞 API 请求。
    加载 akshare/HK 名称 → Watchlist → 新闻挖掘 → 代码模式回退。
    """
    import time as _time
    import re as _re
    import json

    global _stock_name_map_cache, _stock_name_map_cache_ts
    global _news_name_map_cache, _name_backfill_done_ts

    _t0 = _time.time()
    logger.info("🔄 [后台] 开始股票名称回填任务...")

    try:
        db = SessionLocal()
        try:
            # 1. 提取所有新闻中的股票代码
            all_articles = db.query(
                NewsArticle.related_stocks
            ).filter(
                NewsArticle.related_stocks.isnot(None)
            ).all()

            all_symbols_set: set[str] = set()
            for row in all_articles:
                rs = row[0]
                if not rs:
                    continue
                try:
                    stocks = json.loads(rs) if isinstance(rs, str) else rs
                except:
                    continue
                if isinstance(stocks, list):
                    all_symbols_set.update(stocks)

            all_symbols_list = sorted(list(all_symbols_set))
            if not all_symbols_list:
                logger.info("ℹ️ [后台] 无新闻引用的股票代码，跳过回填")
                _name_backfill_done_ts = _time.time()
                return

            # 2. 批量查询所有 StockProfile
            all_profiles = db.query(StockProfile).filter(
                StockProfile.symbol.in_(all_symbols_list)
            ).all()
            profile_map = {p.symbol: p for p in all_profiles}

            # 3. 判断缺名的 symbols
            def _is_name_missing(sym: str, profile) -> bool:
                name = profile.company_name if profile else None
                if not name or not name.strip():
                    return True
                name_stripped = name.strip()
                if name_stripped == sym:
                    return True
                base = sym.replace(".SH", "").replace(".SZ", "").replace(".HK", "").replace(".BJ", "")
                if name_stripped == base:
                    return True
                return False

            symbols_missing_profile = [s for s in all_symbols_list if s not in profile_map]
            symbols_missing_name = [s for s, p in profile_map.items() if _is_name_missing(s, p)]
            symbols_needing_name = set(symbols_missing_profile + symbols_missing_name)

            if not symbols_needing_name:
                logger.info("✅ [后台] 所有股票已有名称，无需回填")
                _name_backfill_done_ts = _time.time()
                return

            logger.info(f"🔄 [后台] 发现 {len(symbols_needing_name)} 个股票需要名称回填")

            # ① A 股名称：ak.stock_info_a_code_name()
            _name_cache_age = _time.time() - _stock_name_map_cache_ts
            if _stock_name_map_cache is not None and _name_cache_age < 21600:
                stock_name_map = _stock_name_map_cache
                logger.info(f"✅ [后台] 使用缓存名称映射（{int(_name_cache_age)}s 前，{len(stock_name_map)} 条）")
            else:
                stock_name_map: dict[str, str] = {}
                try:
                    import akshare as _ak_lookup
                    _name_df = _ak_lookup.stock_info_a_code_name()
                    for _, _row in _name_df.iterrows():
                        _code = str(_row['code'])
                        _name = str(_row['name'])
                        stock_name_map[_code] = _name
                        if _code.startswith('6') or _code.startswith('9'):
                            stock_name_map[f"{_code}.SH"] = _name
                        if _code.startswith(('0', '1', '2', '3')):
                            stock_name_map[f"{_code}.SZ"] = _name
                        if _code.startswith(('4', '8', '9')):
                            stock_name_map[f"{_code}.BJ"] = _name
                    logger.info(f"✅ [后台] A 股名称映射已加载: {len(_name_df)} 条")
                except Exception as _e:
                    logger.warning(f"⚠️ [后台] 加载 A 股名称映射失败: {_e}")

                # ② 港股名称
                hk_needed = [s for s in symbols_needing_name if '.HK' in s.upper() or (len(s) == 5 and s.isdigit())]
                if hk_needed:
                    try:
                        _hk_df = _ak_lookup.stock_hk_spot_em()
                        for _, _row in _hk_df.iterrows():
                            _hk_code = str(_row.get('代码', ''))
                            _hk_name = str(_row.get('名称', ''))
                            if _hk_code and _hk_name:
                                stock_name_map[_hk_code] = _hk_name
                                stock_name_map[f"{_hk_code}.HK"] = _hk_name
                                stripped = _hk_code.lstrip('0')
                                if stripped:
                                    stock_name_map[stripped] = _hk_name
                                    stock_name_map[f"0{stripped}.HK"] = _hk_name
                                    stock_name_map[f"00{stripped}.HK"] = _hk_name
                        logger.info(f"✅ [后台] 港股名称映射已加载: {len(_hk_df)} 条")
                    except Exception as _e:
                        logger.warning(f"⚠️ [后台] 加载港股名称映射失败: {_e}")

                _stock_name_map_cache = stock_name_map
                _stock_name_map_cache_ts = _time.time()

            # ③ Watchlist 名称
            _wl_names = db.query(Watchlist.symbol, Watchlist.name).filter(
                Watchlist.symbol.in_(list(symbols_needing_name))
            ).all()
            wl_name_map = {r[0]: r[1] for r in _wl_names if r[1]}

            # ④ 新闻内容挖掘
            _unresolved_after_api = [
                s for s in symbols_needing_name
                if not stock_name_map.get(s)
                and not stock_name_map.get(s.replace(".SH","").replace(".SZ","").replace(".HK","").replace(".BJ",""))
                and not wl_name_map.get(s)
                and s not in _news_name_map_cache
            ]
            if _unresolved_after_api:
                try:
                    _news_rows = db.query(NewsArticle.title, NewsArticle.content).filter(
                        NewsArticle.related_stocks.isnot(None)
                    ).all()
                    _unresolved_bases = {}
                    for _s in _unresolved_after_api:
                        _b = _s.replace(".SH","").replace(".SZ","").replace(".HK","").replace(".BJ","").replace(".NQ","").replace(".OC","")
                        _unresolved_bases[_b] = _s
                    for _title, _content in _news_rows:
                        if not _unresolved_bases:
                            break
                        _text = (_title or '') + ' ' + ((_content or '')[:2000])
                        _found_bases = []
                        for _b, _sym in list(_unresolved_bases.items()):
                            _patterns = [
                                rf'([\u4e00-\u9fff]{{2,10}})\s*[\(\uff08]{_re.escape(_b)}',
                                rf'([\u4e00-\u9fffA-Za-z]{{2,15}}(?:ETF|LOF|基金|指数))\s*[\(\uff08]?{_re.escape(_b)}',
                                rf'{_re.escape(_b)}\s*[\)\uff09]\s*([\u4e00-\u9fff]{{2,10}})',
                            ]
                            for _pat in _patterns:
                                _m = _re.search(_pat, _text)
                                if _m:
                                    _extracted = _m.group(1).strip()
                                    if len(_extracted) >= 2:
                                        _news_name_map_cache[_sym] = _extracted
                                        _news_name_map_cache[_b] = _extracted
                                        _found_bases.append(_b)
                                        break
                        for _b in _found_bases:
                            del _unresolved_bases[_b]
                    logger.info(f"✅ [后台] 新闻挖掘名称: {len(_news_name_map_cache)} 条")
                except Exception as _e:
                    logger.warning(f"⚠️ [后台] 新闻挖掘名称失败: {_e}")

            # ⑤ 代码模式识别回退
            def _code_pattern_name(sym: str) -> str | None:
                base = sym.replace(".SH","").replace(".SZ","").replace(".HK","").replace(".BJ","")
                if not base.isdigit():
                    return None
                c = int(base)
                if (510000 <= c <= 520999 or 560000 <= c <= 563999 or 588000 <= c <= 588999):
                    return "ETF基金"
                if 513000 <= c <= 513999:
                    return "跨境ETF"
                if 518000 <= c <= 518999:
                    return "商品ETF"
                if 511000 <= c <= 511999:
                    return "债券ETF"
                if 159000 <= c <= 159999:
                    return "ETF基金"
                if 160000 <= c <= 169999:
                    return "LOF基金"
                if 501000 <= c <= 502999:
                    return "LOF基金"
                if 515000 <= c <= 516999:
                    return "ETF基金"
                if (200000 <= c <= 200999 or 900000 <= c <= 900999):
                    return "B股"
                if 880000 <= c <= 884999:
                    return "板块指数"
                if c >= 700000:
                    return "指数"
                return None

            # 名称解析函数
            def _resolve_name(sym: str) -> str | None:
                name = stock_name_map.get(sym)
                if name:
                    return name
                base = sym.replace(".SH","").replace(".SZ","").replace(".HK","").replace(".BJ","").replace(".NQ","").replace(".OC","")
                name = stock_name_map.get(base)
                if name:
                    return name
                if '.HK' in sym.upper():
                    stripped = base.lstrip('0')
                    for prefix in ['', '0', '00', '000', '0000']:
                        name = stock_name_map.get(f"{prefix}{stripped}")
                        if name:
                            return name
                        name = stock_name_map.get(f"{prefix}{stripped}.HK")
                        if name:
                            return name
                name = wl_name_map.get(sym)
                if name:
                    return name
                name = _news_name_map_cache.get(sym)
                if name:
                    return name
                name = _news_name_map_cache.get(base)
                if name:
                    return name
                return _code_pattern_name(sym)

            # 创建/更新 Profile
            created_count = 0
            for sym in symbols_missing_profile:
                resolved_name = _resolve_name(sym)
                if resolved_name:
                    new_profile = StockProfile(
                        symbol=sym,
                        company_name=resolved_name,
                        market=infer_market_from_symbol(sym),
                        is_valid=True,
                    )
                    db.add(new_profile)
                    created_count += 1

            updated_count = 0
            for sym in symbols_missing_name:
                resolved_name = _resolve_name(sym)
                if resolved_name and sym in profile_map:
                    profile_map[sym].company_name = resolved_name
                    updated_count += 1

            if created_count > 0 or updated_count > 0:
                try:
                    db.commit()
                    logger.info(f"✅ [后台] 名称补全完成：新建 {created_count} 条，回填 {updated_count} 条")
                except Exception as _commit_err:
                    db.rollback()
                    logger.error(f"❌ [后台] 名称补全提交失败: {_commit_err}")
            else:
                logger.info(f"ℹ️ [后台] {len(symbols_needing_name)} 个 symbol 无法从数据源解析到名称")

            _name_backfill_done_ts = _time.time()
            _elapsed = _time.time() - _t0
            logger.info(f"✅ [后台] 名称回填任务完成，耗时 {_elapsed:.1f}s")

        finally:
            db.close()
    except Exception as _e:
        logger.error(f"❌ [后台] 名称回填任务异常: {_e}", exc_info=True)


@app.on_event("startup")
def _startup_name_backfill():
    """启动时在后台线程中运行名称回填，不阻塞 API。"""
    import threading
    t = threading.Thread(target=_backfill_stock_names_sync, daemon=True, name="name-backfill")
    t.start()
    logger.info("🚀 [后台] 名称回填线程已启动")

def retry_with_backoff(max_retries=3, base_delay=1.0):
    """重试装饰器，支持指数退避。

    参数：
    - max_retries: 最大重试次数（默认 3 次）
    - base_delay: 初始等待秒数（默认 1.0 秒），实际为 base_delay * 2^attempt + 抖动

    典型使用：短期波动的第三方数据源调用；注意不要用于幂等性差的写操作。
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:  # 不是最后一次重试
                        # 指数退避 + 随机抖动
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                        print(f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {delay:.2f}s...")
                        time.sleep(delay)
                    else:
                        print(f"All {max_retries} attempts failed. Last error: {str(e)}")
            raise last_exception
        return wrapper
    return decorator

@retry_with_backoff(max_retries=3, base_delay=1.0)
def fetch_stock_basic_with_retry(data_source):
    """带重试机制的股票基础数据获取。

    - data_source=tushare 时：需要配置 TUSHARE_TOKEN；返回字段包含 ts_code/symbol/name/market
    - 否则默认使用 akshare：补齐 ts_code/market 以保持结构一致
    """
    if data_source == "tushare":
        token = os.getenv("TUSHARE_TOKEN")
        if not token or token == "your_tushare_token_here":
            raise HTTPException(status_code=500, detail="TUSHARE_TOKEN not configured. Please set your token in .env file")
        
        ts.set_token(token)
        pro = ts.pro_api()
        return pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,market')
    else:
        # 使用 akshare 作为默认数据源
        import akshare as ak
        # 获取A股股票基本信息
        df = ak.stock_info_a_code_name()
        # 重命名列以匹配 tushare 格式
        df = df.rename(columns={'code': 'symbol', 'name': 'name'})
        # 为了兼容，添加 ts_code 和 market 列
        df['ts_code'] = df['symbol'].apply(lambda x: f"{x}.SH" if x.startswith('6') else f"{x}.SZ")
        df['market'] = df['symbol'].apply(lambda x: 'SH' if x.startswith('6') else 'SZ')
        return df

def get_stock_basic():
    """获取股票基础信息（带缓存）。

    - 首次加载后缓存于进程内存，后续直接返回
    - 可通过 POST /cache/refresh 进行刷新
    """
    global _stock_basic_cache
    if _stock_basic_cache is not None:
        return _stock_basic_cache
    
    data_source = os.getenv("DATA_SOURCE", "akshare")
    
    try:
        _stock_basic_cache = fetch_stock_basic_with_retry(data_source)
        logger.info("Stock basic data loaded successfully using %s", data_source)
        return _stock_basic_cache
    except Exception as e:
        error_msg = f"{data_source.title()} API error: {str(e)}"
        if data_source == "tushare":
            error_msg += ". Try using akshare instead."
        raise HTTPException(status_code=500, detail=error_msg)

# 在线股票搜索接口
@app.get("/search_stock")
def search_stock(q: str = Query(..., description="股票代码或名称")):
    """模糊检索股票。

    - 支持在 ts_code/symbol/name 字段中匹配
    - 返回最多 20 条记录以避免过多结果
    - 对正则/特殊字符使用安全匹配
    """
    logger.info("Received stock search query: %s", q)
    try:
        # 输入验证：如果没有有效查询，则刷新缓存并返回状态
        if not q or len(q.strip()) < 1:
            data = get_stock_basic()
            return {
                "ok": True,
                "message": f"Stock cache refreshed successfully. Loaded {len(data)} stocks.",
                "data_source": os.getenv("DATA_SOURCE", "akshare")
            }

        data = get_stock_basic()
        q_norm = q.strip().lower()
        # 将 DataFrame 转为列表（预期 fetch_stock_basic_with_retry 返回 DataFrame）
        try:
            records = data.to_dict(orient='records')  # type: ignore
        except AttributeError:
            # 如果已经是列表
            records = list(data)

        results = []
        for r in records:
            name = str(r.get('name', '')).lower()
            symbol = str(r.get('symbol', '')).lower()
            ts_code = str(r.get('ts_code', '')).lower()
            if q_norm in name or q_norm in symbol or q_norm in ts_code:
                results.append({
                    "symbol": r.get('symbol'),
                    "name": r.get('name'),
                    "ts_code": r.get('ts_code'),
                    "market": r.get('market')
                })
            if len(results) >= 20:
                break

        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search stock: {str(e)}")

# 获取缓存状态
@app.get("/cache/status")
def cache_status():
    """返回基础数据缓存状态（是否已加载、条数、数据源）。"""
    global _stock_basic_cache
    return {
        "cache_loaded": _stock_basic_cache is not None,
        "cache_size": len(_stock_basic_cache) if _stock_basic_cache is not None else 0,
        "data_source": os.getenv("DATA_SOURCE", "akshare")
    }

@app.get("/watchlist")
def get_watchlist():
    """获取股票池列表（统一数据源：stock_pool_members），置顶状态从 watchlist 表读取。"""
    with SessionLocal() as session:
        rows = session.execute(text("""
            SELECT spm.symbol,
                   COALESCE(sp.company_name, w.name) AS name,
                   COALESCE(sp.industry, w.sector) AS sector,
                   COALESCE(w.pinned, false) AS pinned
            FROM stock_pool_members spm
            LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
            LEFT JOIN watchlist w ON spm.symbol = w.symbol
            WHERE spm.exit_date IS NULL
            ORDER BY COALESCE(w.pinned, false) DESC, spm.last_seen_date DESC
        """)).fetchall()
        return [
            {
                "symbol": r.symbol,
                "name": r.name,
                "sector": r.sector,
                "enabled": True,
                "pinned": bool(r.pinned),
            }
            for r in rows
        ]


@app.post("/watchlist")
def add_watch(item: WatchItem):
    """新增股票到统一股票池（stock_pool_members）。

    同时在 watchlist 表中创建记录以支持置顶(pin)功能。
    """
    sym = item.symbol.upper()
    today = datetime.now().date()
    with SessionLocal() as session:
        existing = session.execute(
            text("SELECT id, exit_date FROM stock_pool_members WHERE symbol = :sym"),
            {"sym": sym}
        ).fetchone()
        if existing:
            session.execute(
                text("UPDATE stock_pool_members SET exit_date = NULL, last_seen_date = :today WHERE symbol = :sym"),
                {"sym": sym, "today": today}
            )
        else:
            session.execute(
                text("""INSERT INTO stock_pool_members (symbol, first_seen_date, last_seen_date, source)
                        VALUES (:sym, :today, :today, 'manual')"""),
                {"sym": sym, "today": today}
            )
        wl_values = dict(symbol=sym, name=item.name, sector=item.sector, enabled=True)
        wl_update = {"name": item.name, "sector": item.sector, "enabled": True}
        if item.pinned is not None:
            wl_values["pinned"] = item.pinned
            wl_update["pinned"] = item.pinned
        stmt = pg_insert(Watchlist).values(**wl_values).on_conflict_do_update(
            index_elements=["symbol"],
            set_=wl_update,
        )
        session.execute(stmt)
        session.commit()
    return {"ok": True}


@app.get("/api/agent/report/latest.md")
async def download_latest_markdown():
    """Download latest finished agent markdown report."""
    with SessionLocal() as session:
        row = session.query(AgentJob).filter(AgentJob.status==AgentJobStatus.FINISHED.value).order_by(AgentJob.finished_at.desc()).first()
        if not row:
            raise HTTPException(status_code=404, detail="no finished report")
        paths = json.loads(row.reports_json) if row.reports_json else []
    md_path = None
    for p in paths:
        if p.endswith('.md'):
            md_path = p
            break
    if not md_path:
        raise HTTPException(status_code=404, detail="markdown report not found")
    reports_dir = _Path(__file__).resolve().parent.parent.parent / "agent_reports"
    from pathlib import Path as _P
    p_obj = _P(md_path)
    if not p_obj.is_absolute():
        p_obj = reports_dir / p_obj.name
    try:
        content = p_obj.read_text('utf-8')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file missing on disk")
    return Response(content=content, media_type='text/markdown')


@app.get("/api/agent/report/{job_id}.md")
async def download_job_markdown(job_id: str):
    """Download markdown report for a specific job id."""
    with SessionLocal() as session:
        row = session.query(AgentJob).filter(AgentJob.job_id==job_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="job not found")
        if row.status != AgentJobStatus.FINISHED.value:
            raise HTTPException(status_code=400, detail="job not finished")
        paths = json.loads(row.reports_json) if row.reports_json else []
    md_path = None
    for p in paths:
        if p.endswith('.md'):
            md_path = p
            break
    if not md_path:
        raise HTTPException(status_code=404, detail="markdown report not found")
    reports_dir = _Path(__file__).resolve().parent.parent.parent / "agent_reports"
    from pathlib import Path as _P
    p_obj = _P(md_path)
    if not p_obj.is_absolute():
        p_obj = reports_dir / p_obj.name
    try:
        content = p_obj.read_text('utf-8')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file missing on disk")
    return Response(content=content, media_type='text/markdown')

# 删除自选股接口
@app.delete("/watchlist/{symbol}")
def delete_watch(symbol: str):
    """从统一股票池中移除指定股票（软删除 stock_pool_members + 删除 watchlist 记录）。"""
    sym = symbol.upper()
    today = datetime.now().date()
    with SessionLocal() as session:
        session.execute(
            text("UPDATE stock_pool_members SET exit_date = :today WHERE symbol = :sym AND exit_date IS NULL"),
            {"sym": sym, "today": today}
        )
        session.execute(
            text("DELETE FROM watchlist WHERE symbol=:sym"),
            {"sym": sym}
        )
        session.commit()
    return {"ok": True}

@app.patch("/watchlist/{symbol}/pin")
def toggle_pin(symbol: str, pinned: bool = True):
    """切换股票在首页看板的展示状态（自动创建 watchlist 行以保存 pin 状态）。"""
    sym = symbol.upper()
    with SessionLocal() as session:
        pool_exists = session.execute(
            text("SELECT 1 FROM stock_pool_members WHERE symbol = :sym AND exit_date IS NULL"),
            {"sym": sym}
        ).fetchone()
        if not pool_exists:
            raise HTTPException(status_code=404, detail="symbol not in stock pool")
        stmt = pg_insert(Watchlist).values(symbol=sym, enabled=True, pinned=pinned).on_conflict_do_update(
            index_elements=["symbol"],
            set_={"pinned": pinned},
        )
        session.execute(stmt)
        session.commit()
    return {"ok": True, "symbol": sym, "pinned": pinned}

@app.post("/run/daily")
async def run_daily_now():
    """手动触发日常管道（抓取日线/信号/预测/资金流入等）。"""
    ok = await run_daily_pipeline()
    return {"ok": ok}

@app.get("/admin/scheduler/status")
def scheduler_status():
    """查询任务调度器状态与已注册作业。"""
    sched = getattr(app.state, "scheduler", None)
    if not sched:
        return {"enabled": False, "message": "Scheduler not attached"}
    jobs = []
    for j in sched.get_jobs():
        jobs.append({
            "id": j.id,
            "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
            "trigger": str(j.trigger)
        })
    return {
        "enabled": True,
        "timezone": os.getenv("TZ", "Asia/Taipei"),
        "jobs": jobs
    }


@app.post("/admin/scheduler/run-now")
def run_update_now(delay_between_stocks: float = 2.0):
    """
    立即执行一次股票信息更新任务（异步后台执行）
    
    参数：
        delay_between_stocks: 相邻两只股票更新之间的延迟时间（秒），默认 2 秒，避免爬虫被ban
    
    功能：
    - 立即在后台启动一次异步更新任务
    - 无需等待计划时间，可用于手动触发更新
    - 爬虫速率受限于 delay_between_stocks 参数（避免 IP 被ban）
    - 单个任务完成后下次任务才能执行
    
    示例：
        POST /admin/scheduler/run-now?delay_between_stocks=3.0
    """
    try:
        from .tasks.task_scheduler import get_task_manager
        
        manager = get_task_manager()
        
        if delay_between_stocks < 0.5:
            logger.warning(f"⚠️ 爬虫延迟过短 ({delay_between_stocks}s)，调整为最小值 0.5s 以避免被ban")
            delay_between_stocks = 0.5
        elif delay_between_stocks > 10:
            logger.warning(f"⚠️ 爬虫延迟过长 ({delay_between_stocks}s)，调整为最大值 10s")
            delay_between_stocks = 10
        
        result = manager.run_now_async(delay_between_stocks=delay_between_stocks)
        return result
    
    except Exception as e:
        logger.error(f"❌ 触发异步更新失败: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'message': '执行异步更新任务失败'
        }


@app.get("/admin/scheduler/task-stats")
def get_task_stats():
    """获取最后一次任务的执行统计信息"""
    try:
        from .tasks.task_scheduler import get_task_manager
        
        manager = get_task_manager()
        stats = manager.get_stats()
        
        return {
            'success': True,
            'stats': stats,
            'timestamp': datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ 获取任务统计失败: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


@app.get("/api/profile/update-progress")
def get_profile_update_progress():
    """
    获取实时的 Profile 更新进度
    
    返回当前任务的实时统计（如果任务正在运行）或最后一次任务的统计
    
    响应格式:
    {
        "is_running": bool,           # 是否正在运行
        "current_stock_index": int,   # 当前处理的股票序号
        "total_stocks": int,          # 总股票数
        "processed": int,             # 已处理数
        "successful": int,            # 成功数
        "failed": int,                # 失败数
        "progress_percentage": float, # 处理进度百分比
        "current_stock": str,         # 当前正在处理的股票代码
        "elapsed_time_seconds": int,  # 已耗时（秒）
        "estimated_remaining_seconds": int,  # 预计剩余时间（秒）
        "speed_stocks_per_minute": float,    # 处理速度（股/分钟）
        "last_update_at": str,        # 最后更新时间
        "timestamp": str              # 当前服务器时间 ISO 格式
        "queue_status": {             # 后台任务队列状态
            "queue_size": int,        # 队列中待处理任务数
            "running_tasks": int,     # 正在执行的任务数
            "max_workers": int        # 最大并发工作线程数
        }
    }
    """
    try:
        from .tasks.task_scheduler import get_task_manager
        from .utils.background_task_queue import get_background_queue
        
        manager = get_task_manager()
        progress = manager.get_progress()
        progress['timestamp'] = datetime.now().isoformat()
        
        # 添加任务队列状态
        task_queue = get_background_queue()
        progress['queue_status'] = task_queue.get_queue_status()
        
        # 返回 JSONResponse 并设置缓存控制头（确保总是获取最新进度）
        return JSONResponse(
            progress,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    
    except Exception as e:
        logger.error(f"❌ 获取 Profile 更新进度失败: {str(e)}", exc_info=True)
        # 返回初始状态
        result = {
            'is_running': False,
            'current_stock_index': 0,
            'total_stocks': 0,
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'progress_percentage': 0,
            'current_stock': None,
            'elapsed_time_seconds': 0,
            'estimated_remaining_seconds': 0,
            'speed_stocks_per_minute': 0,
            'last_update_at': None,
            'timestamp': datetime.now().isoformat(),
            'queue_status': {
                'is_running': False,
                'queue_size': 0,
                'running_tasks': 0,
                'max_workers': 0
            },
            'error': str(e)
        }
        
        return JSONResponse(
            result,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )


@app.post("/api/profile/enrich-all")
def trigger_profile_enrichment(
    batch_size: int = Query(100, ge=1, le=5000, description="本批次处理股票数量上限"),
    delay: float = Query(1.5, ge=0.5, le=10, description="每只股票之间的延迟(秒)"),
):
    """手动触发股票池全量 Profile 画像充填（后台执行）。"""
    from .tasks.task_scheduler import get_task_manager
    import threading

    manager = get_task_manager()
    if manager.is_running:
        return {
            "status": "already_running",
            "message": "画像充填任务已在运行中",
            "progress": manager.get_progress(),
        }

    def _run():
        manager.update_all_stock_profiles(delay_between_stocks=delay, batch_limit=batch_size)

    t = threading.Thread(target=_run, daemon=True, name="manual-enrich-all")
    t.start()

    return {
        "status": "started",
        "message": f"画像充填任务已启动，本批次上限 {batch_size} 只，间隔 {delay}s",
        "batch_size": batch_size,
    }


def _parse_observation_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


@app.get("/api/macro/overview")
async def macro_overview(limit: int = 8, model_limit: int = 5):
    """返回最新的宏观新闻观测摘要与模型训练结果。"""
    storage = await get_storage()
    if storage is None:
        raise HTTPException(status_code=503, detail="Macro storage not configured")

    observations = await storage.get_macro_observations(limit=limit)
    latest_by_topic: dict[str, dict[str, Any]] = {}
    latest_date: Optional[date] = None

    for item in observations:
        topic_key = item.get("topic") or "unknown"
        observation_date = _parse_observation_date(item.get("observation_date"))
        if observation_date and (latest_date is None or observation_date > latest_date):
            latest_date = observation_date

        existing = latest_by_topic.get(topic_key)
        if existing is None:
            latest_by_topic[topic_key] = item
            continue

        existing_date = _parse_observation_date(existing.get("observation_date"))
        if observation_date and (existing_date is None or observation_date >= existing_date):
            latest_by_topic[topic_key] = item

    topics_summary: list[dict[str, Any]] = []
    for topic_key, item in sorted(
        latest_by_topic.items(),
        key=lambda kv: kv[1].get("observation_date", ""),
        reverse=True,
    ):
        features = item.get("features", {}) or {}
        topics_summary.append(
            {
                "topic": topic_key,
                "topic_display": item.get("topic_display") or topic_key,
                "observation_date": item.get("observation_date"),
                "article_count": item.get("article_count"),
                "avg_sentiment": features.get("avg_sentiment"),
                "positive_ratio": features.get("positive_ratio"),
                "negative_ratio": features.get("negative_ratio"),
                "neutral_ratio": features.get("neutral_ratio"),
                "relevance_mean": features.get("relevance_mean"),
                "top_keywords": (item.get("top_keywords") or [])[:10],
                "top_entities": item.get("top_entities") or {},
                "summaries": (item.get("summaries") or [])[:5],
                "references": (item.get("references") or [])[:5],
            }
        )

    model_runs = await storage.get_macro_model_runs(limit=model_limit)
    model_summary: list[dict[str, Any]] = []
    for run in model_runs:
        run_date = run.get("run_date")
        if isinstance(run_date, datetime):
            run_iso = run_date.isoformat()
        elif isinstance(run_date, str):
            run_iso = run_date
        else:
            run_iso = None

        model_summary.append(
            {
                "model_name": run.get("model_name"),
                "run_date": run_iso,
                "metrics": run.get("metrics", {}),
                "coefficients": run.get("coefficients", {}),
                "calibration": run.get("calibration", {}),
                "notes": run.get("notes", []),
            }
        )

    return {
        "storage_available": True,
        "latest_observation_date": latest_date.isoformat() if latest_date else None,
        "topics": topics_summary,
        "model_runs": model_summary,
    }


@app.get("/api/macro/report")
async def macro_report(
    report_date: Optional[str] = Query(
        None,
        description="报告日期，ISO 格式 (YYYY-MM-DD)。留空时返回最新日报",
    ),
    refresh: bool = Query(
        False,
        description="如果没有现成的快照，是否尝试即时生成",
    ),
):
    """获取宏观日报快照，可按日期查询或请求最新报告。"""

    storage = await get_storage()
    if storage is None:
        raise HTTPException(status_code=503, detail="Macro storage not configured")

    target_date: Optional[date] = None
    report: Optional[dict[str, Any]] = None

    if report_date:
        try:
            target_date = datetime.fromisoformat(report_date).date()
        except ValueError as exc:  # noqa: PERF203 - explicit message for client
            raise HTTPException(status_code=400, detail="report_date must be ISO format YYYY-MM-DD") from exc
        report = await storage.get_macro_report_by_date(target_date)
    else:
        report = await storage.get_latest_macro_report()

    if refresh:
        # 支持强制重算：无论是否已有快照，都重新跑观测与报告生成。
        await run_macro_observation_pipeline(for_date=target_date)
        refreshed = await generate_and_store_macro_report(target_date=target_date)
        report = refreshed or (
            await storage.get_macro_report_by_date(target_date)
            if target_date
            else await storage.get_latest_macro_report()
        )

    # 自动触发：如果没有找到任何报告，自动运行流水线生成
    if report is None and not refresh:
        try:
            logger.info("No existing macro report found; auto-triggering pipeline")
            await run_macro_observation_pipeline(for_date=target_date)
            refreshed = await generate_and_store_macro_report(target_date=target_date)
            report = refreshed or (
                await storage.get_macro_report_by_date(target_date)
                if target_date
                else await storage.get_latest_macro_report()
            )
        except Exception as auto_exc:
            logger.warning("Auto-trigger macro pipeline failed: %s", auto_exc)

    if report is None:
        raise HTTPException(status_code=404, detail="Macro report not found")

    cleaned_report = dict(report)
    cleaned_report.pop("_id", None)

    generated_at = cleaned_report.get("generated_at")
    if isinstance(generated_at, datetime):
        cleaned_report["generated_at"] = generated_at.isoformat()

    report_date_val = cleaned_report.get("report_date")
    if isinstance(report_date_val, datetime):
        cleaned_report["report_date"] = report_date_val.date().isoformat()

    available_reports = await storage.get_macro_reports(limit=10)
    available_dates = []
    for item in available_reports:
        date_value = item.get("report_date") or item.get("_id")
        if isinstance(date_value, datetime):
            date_value = date_value.date().isoformat()
        elif hasattr(date_value, "isoformat"):
            date_value = date_value.isoformat()  # type: ignore[assignment]
        if isinstance(date_value, str):
            available_dates.append(date_value)

    return {
        "report": cleaned_report,
        "available_dates": available_dates,
    }

@app.get("/api/fundflow/latest")
def latest_fundflow(limit: int = 50):
    """获取最新交易日的个股资金流向 Top 列表。

    - limit: 限制行数（默认 50）
    - 输出字段单位为元/百分比；前端按需换算万/亿
    """
    from .core.models import FundFlowDaily
    with SessionLocal() as session:
        # 最新交易日
        latest_date = session.execute(text("SELECT max(trade_date) FROM fundflow_daily")).scalar()
        if not latest_date:
            return {"date": None, "rows": []}
        rows = session.execute(
            text(
                """
                SELECT f.symbol, f.trade_date, f.main_net, f.main_ratio, f.super_net, f.super_ratio,
                       f.large_net, f.large_ratio, f.medium_net, f.medium_ratio, f.small_net, f.small_ratio,
                       w.name AS stock_name
                FROM fundflow_daily f
                LEFT JOIN watchlist w ON f.symbol = w.symbol
                WHERE f.trade_date = :d
                ORDER BY COALESCE(f.main_net,0) DESC
                LIMIT :lim
                """
            ),
            {"d": latest_date, "lim": limit},
        ).fetchall()
        out = []
        for r in rows:
            stock_name = r.stock_name or ""
            sym = r.symbol
            display_name = f"{stock_name} ({sym})" if stock_name else sym
            out.append({
                "symbol": sym,
                "name": stock_name,
                "display_name": display_name,
                "trade_date": r.trade_date.isoformat(),
                "main_net": float(r.main_net) if r.main_net is not None else None,
                "main_ratio": float(r.main_ratio) if r.main_ratio is not None else None,
                "super_net": float(r.super_net) if r.super_net is not None else None,
                "super_ratio": float(r.super_ratio) if r.super_ratio is not None else None,
                "large_net": float(r.large_net) if r.large_net is not None else None,
                "large_ratio": float(r.large_ratio) if r.large_ratio is not None else None,
                "medium_net": float(r.medium_net) if r.medium_net is not None else None,
                "medium_ratio": float(r.medium_ratio) if r.medium_ratio is not None else None,
                "small_net": float(r.small_net) if r.small_net is not None else None,
                "small_ratio": float(r.small_ratio) if r.small_ratio is not None else None,
            })
        # 如果数据库中可用行数少于请求的 limit，则尝试回退到当日排行补齐（盘中口径）
        try:
            if len(out) < limit:
                try:
                    rdf = _ds_load_rank_today()
                except Exception:
                    rdf = None
                if rdf is not None and not rdf.empty:
                    # columns may be 中文 from akshare: '代码','名称','今日主力净流入-净额' etc.
                    code_col = '代码' if '代码' in rdf.columns else ('symbol' if 'symbol' in rdf.columns else None)
                    name_col = '名称' if '名称' in rdf.columns else ('name' if 'name' in rdf.columns else None)
                    val_col = None
                    for c in ['今日主力净流入-净额', '主力净流入-净额', 'main_net']:
                        if c in rdf.columns:
                            val_col = c
                            break

                    def _mk_symbol(code_val: Any) -> str:
                        try:
                            s = str(code_val).strip()
                            if s.endswith('.SH') or s.endswith('.SZ'):
                                return s.upper()
                            if s.startswith('6'):
                                return s + '.SH'
                            return s + '.SZ'
                        except Exception:
                            return str(code_val)

                    # iterate rank rows in descending inflow order and append until limit
                    for _, rr in rdf.iterrows():
                        if len(out) >= limit:
                            break
                        try:
                            codev = rr.get(code_col) if code_col else None
                            sym = _mk_symbol(codev)
                            # skip duplicates
                            if any(x.get('symbol') == sym for x in out):
                                continue
                            raw = rr.get(val_col) if val_col else None
                            try:
                                main_net_yuan = float(raw) * 1e4 if raw is not None else None
                            except Exception:
                                main_net_yuan = None
                            namev = rr.get(name_col) if name_col else None
                            name_str = namev or ''
                            display = f"{name_str} ({sym})" if name_str else sym
                            out.append({
                                'symbol': sym,
                                'name': name_str,
                                'display_name': display,
                                'trade_date': latest_date.isoformat(),
                                'main_net': main_net_yuan,
                                'main_ratio': None,
                                'super_net': None,
                                'super_ratio': None,
                                'large_net': None,
                                'large_ratio': None,
                                'medium_net': None,
                                'medium_ratio': None,
                                'small_net': None,
                                'small_ratio': None,
                            })
                        except Exception:
                            continue
        except Exception:
            # 保持向后兼容，若回退失败直接返回已有 DB 数据
            pass
        # 若仍然不足，则尝试从最近若干日的 DB 聚合中补齐（保守回退，不依赖外部 API）
        try:
            if len(out) < limit:
                from datetime import timedelta as _td
                # 尝试多阶段聚合回退：7天 -> 30天 -> 90天，以增加在 DB 中找到候选的概率
                for days in (7, 30, 90):
                    if len(out) >= limit:
                        break
                    min_dt = latest_date - _td(days=days)
                    agg_rows = session.execute(text(
                        """
                        SELECT f.symbol, MAX(f.trade_date) AS trade_date, MAX(f.main_net) AS main_net
                        FROM fundflow_daily f
                        WHERE f.trade_date >= :min_date
                        GROUP BY f.symbol
                        ORDER BY COALESCE(MAX(f.main_net),0) DESC
                        LIMIT :lim
                        """
                    ), {"min_date": min_dt, "lim": limit}).fetchall()
                    for r in agg_rows:
                        if len(out) >= limit:
                            break
                        sym = r.symbol
                        if any(x.get('symbol') == sym for x in out):
                            continue
                        display = sym
                        out.append({
                            "symbol": sym,
                            "name": "",
                            "display_name": display,
                            "trade_date": (r.trade_date.isoformat() if getattr(r, 'trade_date', None) is not None else latest_date.isoformat()),
                            "main_net": (float(r.main_net) if r.main_net is not None else None),
                            "main_ratio": None,
                            "super_net": None,
                            "super_ratio": None,
                            "large_net": None,
                            "large_ratio": None,
                            "medium_net": None,
                            "medium_ratio": None,
                            "small_net": None,
                            "small_ratio": None,
                        })
        except Exception:
            pass
        # Ensure display_name uses company name when available: fetch spot snapshot for missing names
        try:
            missing = [r['symbol'] for r in out if not r.get('name')]
            if missing:
                try:
                    from .data.data_source import get_spot_snapshot
                    snaps = get_spot_snapshot(missing) or {}
                    for row in out:
                        if not row.get('name'):
                            s = row.get('symbol')
                            info = snaps.get(s)
                            if info and info.get('name'):
                                row['name'] = info.get('name')
                                row['display_name'] = f"{info.get('name')} ({s})"
                            else:
                                # leave for next fallback
                                row['display_name'] = row.get('display_name') or None
                except Exception:
                    # ignore snapshot errors
                    pass
                # Fallback: try to read from local `stocks` table
                try:
                    from .core.models import Stock
                    for row in out:
                        if not row.get('name'):
                            s = row.get('symbol')
                            try:
                                rec = session.execute(text("SELECT name FROM stocks WHERE symbol = :s LIMIT 1"), {"s": s}).first()
                                if rec and rec[0]:
                                    row['name'] = rec[0]
                                    row['display_name'] = f"{rec[0]} ({s})"
                                else:
                                    row['display_name'] = row.get('display_name') or s
                            except Exception:
                                row['display_name'] = row.get('display_name') or s
                except Exception:
                    for row in out:
                        row['display_name'] = row.get('display_name') or row.get('symbol')
        except Exception:
            pass
        return {"date": latest_date.isoformat(), "rows": out}

# --- Watchlist Snapshot & Analysis ---
@app.get("/api/watchlist/snapshot")
def watchlist_snapshot(
    limit: int = Query(0, description="limit rows; 0 for all"),
    fundflow_prefer: str = Query("auto", description="Preferred fundflow source: auto|db|ak_today|eastmoney"),
    pinned_only: bool = Query(False, description="仅返回已置顶股票"),
    _force_recompute: bool = False,
):
    """自选股快照（组合实时/历史/资金流向）。

    包含：
    - 实时行情（优先 akshare，内部含多源回退与兜底）
    - 历史指标（如 3D/20D/YTD 变化）
    - 当日/最近的主力净流向

    参数说明：
    - limit: 返回前 n 条（0 表示全部）
    - fundflow_prefer: 资金流来源偏好 auto|db|ak_today|eastmoney
      auto：优先 DB（EOD），不足则回退到当日排行或东方财富
    - pinned_only: 仅返回已置顶(首页看板)的股票
    """
    # Simple fresh-cache fast path: try to return cached fresh snapshot
    cache_key = f"watchlist_snapshot:{limit}:{fundflow_prefer}:pinned={pinned_only}:v1"
    stale_key = cache_key + ":stale"
    try:
        cached = _redis_get(cache_key)
        if cached and not _force_recompute:
            try:
                return json.loads(cached)
            except Exception:
                pass
    except Exception:
        pass

    # if not fresh, attempt stale-while-revalidate: return stale immediately and trigger background refresh
    try:
        stale = _redis_get(stale_key)
        if stale and not _force_recompute:
            try:
                # attempt acquire lock to avoid stampede
                lock_key = cache_key + ":lock"
                if _acquire_refresh_lock(lock_key, ex=30):
                    async def _async_bg():
                        try:
                            # run the synchronous recompute in a thread to avoid blocking event loop
                            await asyncio.to_thread(watchlist_snapshot, limit, fundflow_prefer, pinned_only, True)
                        except Exception:
                            logger.exception("background watchlist refresh failed")
                        finally:
                            _release_refresh_lock(lock_key)

                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(_async_bg())
                    except RuntimeError:
                        # no running event loop (e.g., started outside async context) -> fallback to thread
                        def _bg():
                            try:
                                watchlist_snapshot(limit=limit, fundflow_prefer=fundflow_prefer, pinned_only=pinned_only, _force_recompute=True)
                            except Exception:
                                logger.exception("background watchlist refresh failed")
                            finally:
                                _release_refresh_lock(lock_key)

                        _threading.Thread(target=_bg, daemon=True).start()
                return json.loads(stale)
            except Exception:
                pass
    except Exception:
        pass

    from sqlalchemy import func
    from .core.models import FundFlowDaily
    # Cold-start protection: acquire a refresh lock so only one process recomputes.
    lock_key = cache_key + ":lock"
    lock_acquired = False
    try:
        lock_acquired = _acquire_refresh_lock(lock_key, ex=30)
        if not lock_acquired:
            # another worker is recomputing — wait briefly for cache to appear
            waited = 0.0
            while waited < 2.0:
                time.sleep(0.05)
                cached = _redis_get(cache_key)
                if cached:
                    try:
                        return json.loads(cached)
                    except Exception:
                        break
                stale = _redis_get(stale_key)
                if stale:
                    try:
                        return json.loads(stale)
                    except Exception:
                        break
                waited += 0.05
    except Exception:
        # best-effort; continue to compute if lock system fails
        lock_acquired = False
    with SessionLocal() as session:
        # Read from stock_pool_members (unified pool) + watchlist for pin state
        if pinned_only:
            watches = session.execute(text("""
                SELECT spm.symbol, COALESCE(sp.company_name, w.name) AS name, COALESCE(sp.industry, w.sector) AS sector,
                       COALESCE(w.pinned, false) AS pinned
                FROM stock_pool_members spm
                LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
                INNER JOIN watchlist w ON spm.symbol = w.symbol AND w.pinned = true
                WHERE spm.exit_date IS NULL
            """)).fetchall()
        else:
            watches = session.execute(text("""
                SELECT spm.symbol, COALESCE(sp.company_name, w.name) AS name, COALESCE(sp.industry, w.sector) AS sector,
                       COALESCE(w.pinned, false) AS pinned
                FROM stock_pool_members spm
                LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
                LEFT JOIN watchlist w ON spm.symbol = w.symbol
                WHERE spm.exit_date IS NULL
            """)).fetchall()
        if limit and limit>0:
            watches = watches[:limit]
        symbols = [w.symbol for w in watches]
        # spot
        spot = get_spot_snapshot(symbols)
        rows = []
        # Prepare intraday fund flow rank (today) map once if needed
        rank_today_map = None
        rank_today_date = None
        def get_today_rank_map():
            nonlocal rank_today_map, rank_today_date
            if rank_today_map is not None:
                return rank_today_map, rank_today_date
            try:
                rdf = _ds_load_rank_today()
                if rdf is None or rdf.empty:
                    rank_today_map = {}
                    rank_today_date = None
                    return rank_today_map, rank_today_date
                code_col = "代码" if "代码" in rdf.columns else ("symbol" if "symbol" in rdf.columns else None)
                if not code_col:
                    rank_today_map = {}
                    rank_today_date = None
                    return rank_today_map, rank_today_date
                m = {}
                # 兼容不同列名
                name_candidates = ["今日主力净流入-净额","主力净流入-净额","main_net"]
                for _, r in rdf.iterrows():
                    base = str(r[code_col])
                    val = None
                    for n in name_candidates:
                        if n in rdf.columns:
                            try:
                                val = r.get(n)
                            except Exception:
                                val = None
                            if val is not None:
                                break
                    try:
                        v = float(val) * 1e4 if (val is not None and n != "main_net") else (float(val) if val is not None else None)
                    except Exception:
                        v = None
                    m[base] = v
                rank_today_map = m
                from datetime import datetime as _dt
                rank_today_date = _dt.now().date().isoformat()
            except Exception:
                rank_today_map = {}
                rank_today_date = None
            return rank_today_map, rank_today_date

        def compute_radar_and_trend(symbol: str):
            try:
                # Pull last 40 trading days to compute light indicators
                qdf = pd.read_sql_query(
                    "SELECT trade_date, close FROM prices_daily WHERE symbol = %s ORDER BY trade_date DESC LIMIT 40",
                    con=engine,
                    params=(symbol,),
                )
                if qdf is None or qdf.empty:
                    return {"momentum": 0.0, "trend": 0.0, "volatility": 0.0, "recent_return": 0.0}, 0.0
                qdf = qdf.iloc[::-1].reset_index(drop=True)
                closes = qdf["close"].astype(float)
                # RSI(14)
                delta = closes.diff()
                gain = delta.clip(lower=0)
                loss = (-delta.clip(upper=0))
                roll = 14
                avg_gain = gain.rolling(roll, min_periods=roll).mean()
                avg_loss = loss.rolling(roll, min_periods=roll).mean()
                rsi = 100 - 100 / (1 + (avg_gain / (avg_loss.replace(0, pd.NA))))
                rsi_val = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 0.0
                # Trend: (MA5 - MA20) / MA20
                ma5 = closes.rolling(5, min_periods=5).mean()
                ma20 = closes.rolling(20, min_periods=20).mean()
                if pd.notna(ma20.iloc[-1]) and ma20.iloc[-1] != 0:
                    trend_val = float((ma5.iloc[-1] - ma20.iloc[-1]) / ma20.iloc[-1] * 100.0)
                else:
                    trend_val = 0.0
                # Volatility over last 10 returns
                rets = closes.pct_change()
                vol_val = float(rets.tail(10).std() * 100.0) if len(rets) >= 2 else 0.0
                # Recent return last 10
                if len(closes) >= 10 and closes.iloc[-10] not in (None, 0):
                    recent_ret = float((closes.iloc[-1] / closes.iloc[-10] - 1.0) * 100.0)
                else:
                    recent_ret = 0.0
                radar = {
                    "momentum": rsi_val,
                    "trend": trend_val,
                    "volatility": vol_val,
                    "recent_return": recent_ret,
                }
                return radar, trend_val
            except Exception:
                return {"momentum": 0.0, "trend": 0.0, "volatility": 0.0, "recent_return": 0.0}, 0.0
        def get_eastmoney_intraday(sym_full: str, base: str):
            try:
                mk = "1" if sym_full.endswith(".SH") else "0"
                url = "https://push2.eastmoney.com/api/qt/stock/get"
                params = {"secid": f"{mk}.{base}", "fields": "f62"}
                with httpx.Client(timeout=4.0) as client:
                    resp = client.get(url, params=params)
                    if resp.status_code == 200:
                        j = resp.json()
                        data = j.get("data") if isinstance(j, dict) else None
                        if data and (data.get("f62") is not None):
                            try:
                                return float(data.get("f62"))
                            except Exception:
                                return None
                return None
            except Exception:
                return None

        for w in watches:
            sym = w.symbol
            # historical metrics
            # Use added_at as baseline if available: first close on/after the added date
            if getattr(w, 'added_at', None):
                first_row = session.execute(
                    text("SELECT close, trade_date FROM prices_daily WHERE symbol=:s AND trade_date >= :d ORDER BY trade_date ASC LIMIT 1"),
                    {"s": sym, "d": w.added_at.date()},
                ).first()
                if not first_row:
                    # 若添加时间太近导致无匹配，回退到首条记录
                    first_row = session.execute(text("SELECT close, trade_date FROM prices_daily WHERE symbol=:s ORDER BY trade_date ASC LIMIT 1"), {"s": sym}).first()
            else:
                # fallback to first available record
                first_row = session.execute(text("SELECT close, trade_date FROM prices_daily WHERE symbol=:s ORDER BY trade_date ASC LIMIT 1"), {"s": sym}).first()
            last_row = session.execute(text("SELECT close, trade_date FROM prices_daily WHERE symbol=:s ORDER BY trade_date DESC LIMIT 1"), {"s": sym}).first()
            # near 3d & 20d
            d3 = session.execute(text("SELECT close FROM prices_daily WHERE symbol=:s ORDER BY trade_date DESC OFFSET 2 LIMIT 1"), {"s": sym}).scalar()
            d20 = session.execute(text("SELECT close FROM prices_daily WHERE symbol=:s ORDER BY trade_date DESC OFFSET 19 LIMIT 1"), {"s": sym}).scalar()
            # YTD: first close of this year
            ytd = session.execute(text("SELECT close FROM prices_daily WHERE symbol=:s AND EXTRACT(YEAR FROM trade_date)=EXTRACT(YEAR FROM CURRENT_DATE) ORDER BY trade_date ASC LIMIT 1"), {"s": sym}).scalar()
            latest_row = session.execute(text("SELECT trade_date, main_net FROM fundflow_daily WHERE symbol=:s ORDER BY trade_date DESC LIMIT 1"), {"s": sym}).first()
            # 资金流选择策略：优先使用 DB（EOD），必要时按偏好回退到“今日排行”或东方财富
            ff_val = None
            ff_date = None
            ff_source = None

            base = sym.replace('.SH','').replace('.SZ','')

            # 1) DB 优先（auto/db）
            if fundflow_prefer in ("auto", "db"):
                if latest_row and (latest_row.main_net is not None):
                    try:
                        ff_val = float(latest_row.main_net)
                        ff_date = latest_row.trade_date.isoformat() if latest_row.trade_date else None
                        ff_source = "db_latest"
                    except Exception:
                        ff_val = None

            # 2) 今日排行（akshare）作为回退（auto/ak_today）
            if ff_val is None and fundflow_prefer in ("auto", "ak_today"):
                rank_map, rank_date = get_today_rank_map()
                if rank_map:
                    v = rank_map.get(base)
                    if v is not None:
                        try:
                            ff_val = float(v)
                            ff_date = rank_date or datetime.now().date().isoformat()
                            ff_source = "ak_today"
                        except Exception:
                            ff_val = None

            # 3) 东方财富 push2（auto/eastmoney）
            if ff_val is None and fundflow_prefer in ("auto", "eastmoney"):
                em = get_eastmoney_intraday(sym, base)
                if em is not None:
                    ff_val = em
                    ff_date = datetime.now().date().isoformat()
                    ff_source = "eastmoney"

            sp = spot.get(sym, {})
            # non-null helper
            def nz(v):
                return v if v is not None else 0
            price = sp.get('price') if sp else (float(last_row.close) if last_row and last_row.close is not None else None)
            def pct(a,b):
                try:
                    if a is None or b is None or b==0: return None
                    return (a-b)/b*100.0
                except Exception:
                    return None
            since_watch = pct(price, float(first_row.close) if first_row and first_row.close is not None else None)
            near_3d = pct(price, float(d3) if d3 is not None else None)
            near_20d = pct(price, float(d20) if d20 is not None else None)
            ytd_chg = pct(price, float(ytd) if ytd is not None else None)
            radar, trend_val = compute_radar_and_trend(sym)
            rows.append({
                "name": sp.get('name') or w.name,
                "symbol": sym,
                "price": price,
                "change": nz(sp.get('change')),
                "pct_change": nz(sp.get('pct_change')),
                "since_watch_pct": since_watch,
                # placeholders for radar/speed; can compute via signals in analysis endpoint
                "radar": radar,
                "trend": trend_val,
                "speed": nz(sp.get('speed')),
                "volume": nz(sp.get('volume')),
                "amount": nz(sp.get('amount')),
                "spot_source": sp.get('spot_source'),
                "amount_unit": "yuan",  # 成交额统一为元
                "turnover_rate": nz(sp.get('turnover_rate')),
                "volume_ratio": nz(sp.get('volume_ratio')),
                "amplitude": nz(sp.get('amplitude')),
                "main_net": ff_val if ff_val is not None else None,
                "fundflow_unit": "yuan",  # 主力净流入统一为元
                "fundflow_date": ff_date,
                "fundflow_source": ff_source,
                "last_volume": nz(sp.get('last_volume')),
                "high": nz(sp.get('high')),
                "low": nz(sp.get('low')),
                "open": nz(sp.get('open')),
                "pre_close": nz(sp.get('pre_close')),
                "order_ratio": nz(sp.get('order_ratio')),
                "pe_ttm": nz(sp.get('pe_ttm')),
                "pb": nz(sp.get('pb')),
                "total_market_cap": nz(sp.get('total_market_cap')),
                "chg_3d_pct": near_3d,
                "chg_20d_pct": near_20d,
                "chg_ytd_pct": ytd_chg,
            })
        result = {"rows": rows, "count": len(rows)}
        try:
            _redis_set(cache_key, json.dumps(result, ensure_ascii=False), ex=WATCHLIST_FRESH_TTL)
            _redis_set(stale_key, json.dumps(result, ensure_ascii=False), ex=WATCHLIST_STALE_TTL)
        except Exception:
            pass
        finally:
            # release refresh lock if we acquired it
            try:
                if lock_acquired:
                    _release_refresh_lock(lock_key)
            except Exception:
                pass
        return result


# --- Watchlist Snapshot Streaming (NDJSON) ---
@app.get("/api/watchlist/snapshot/stream")
def watchlist_snapshot_stream(
    limit: int = Query(0, description="limit rows; 0 for all"),
    fundflow_prefer: str = Query("auto"),
    batch_size: int = Query(20, ge=5, le=50),
    pinned_only: bool = Query(False, description="仅返回已置顶股票"),
):
    """分批流式返回自选股快照，NDJSON 格式。

    每行一个 JSON 对象: {rows, progress, total, done}
    前端可边接收边渲染，加速首屏展示。
    """
    # Fast path: if fresh cache exists, return as single chunk
    cache_key = f"watchlist_snapshot:{limit}:{fundflow_prefer}:pinned={pinned_only}:v1"
    try:
        cached = _redis_get(cache_key)
        if cached:
            data = json.loads(cached)
            r_list = data.get("rows", [])
            t = len(r_list)
            def _one():
                yield json.dumps({"rows": r_list, "progress": t, "total": t, "done": True}, ensure_ascii=False) + "\n"
            return StreamingResponse(_one(), media_type="application/x-ndjson",
                                     headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})
    except Exception:
        pass

    def _generate():
        all_rows = []
        try:
            with SessionLocal() as session:
                if pinned_only:
                    watches_all = session.execute(text("""
                        SELECT spm.symbol, COALESCE(sp.company_name, w.name) AS name,
                               COALESCE(sp.industry, w.sector) AS sector, true AS pinned
                        FROM stock_pool_members spm
                        LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
                        INNER JOIN watchlist w ON spm.symbol = w.symbol AND w.pinned = true
                        WHERE spm.exit_date IS NULL
                    """)).fetchall()
                else:
                    watches_all = session.execute(text("""
                        SELECT spm.symbol, COALESCE(sp.company_name, w.name) AS name,
                               COALESCE(sp.industry, w.sector) AS sector,
                               COALESCE(w.pinned, false) AS pinned
                        FROM stock_pool_members spm
                        LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
                        LEFT JOIN watchlist w ON spm.symbol = w.symbol
                        WHERE spm.exit_date IS NULL
                    """)).fetchall()
                if limit and limit > 0:
                    watches_all = watches_all[:limit]
                total = len(watches_all)
                if total == 0:
                    yield json.dumps({"rows": [], "progress": 0, "total": 0, "done": True}, ensure_ascii=False) + "\n"
                    return

                # ★ Immediately yield meta chunk so frontend shows progress bar
                yield json.dumps({"rows": [], "progress": 0, "total": total, "done": False}, ensure_ascii=False) + "\n"

                # ★ Lazy fund flow rank: load once on first access (not blocking initial yield)
                _rank_loaded = [False]
                _rm: dict = {}
                _rd: Optional[str] = None

                def _get_rank():
                    nonlocal _rm, _rd
                    if not _rank_loaded[0]:
                        _rank_loaded[0] = True
                        try:
                            rdf = _ds_load_rank_today()
                            if rdf is not None and not rdf.empty:
                                cc = "代码" if "代码" in rdf.columns else ("symbol" if "symbol" in rdf.columns else None)
                                if cc:
                                    nc = ["今日主力净流入-净额", "主力净流入-净额", "main_net"]
                                    for _, rr in rdf.iterrows():
                                        b = str(rr[cc])
                                        val, matched_n = None, None
                                        for n in nc:
                                            if n in rdf.columns:
                                                try:
                                                    val = rr.get(n)
                                                except Exception:
                                                    val = None
                                                if val is not None:
                                                    matched_n = n
                                                    break
                                        try:
                                            v = float(val) * 1e4 if (val is not None and matched_n != "main_net") else (float(val) if val is not None else None)
                                        except Exception:
                                            v = None
                                        _rm[b] = v
                                    _rd = datetime.now().date().isoformat()
                        except Exception:
                            pass
                    return _rm, _rd

                def _compute_radar_from_closes(closes_list):
                    """Compute radar dict from a list of close prices (oldest-first, up to 40)."""
                    if not closes_list or len(closes_list) < 2:
                        return {"momentum": 0.0, "trend": 0.0, "volatility": 0.0, "recent_return": 0.0}, 0.0
                    closes = pd.Series([float(c) for c in closes_list])
                    delta = closes.diff()
                    avg_gain = delta.clip(lower=0).rolling(14, min_periods=14).mean()
                    avg_loss = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
                    rsi = 100 - 100 / (1 + (avg_gain / (avg_loss.replace(0, pd.NA))))
                    rsi_val = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 0.0
                    ma5 = closes.rolling(5, min_periods=5).mean()
                    ma20 = closes.rolling(20, min_periods=20).mean()
                    trend_val = float((ma5.iloc[-1] - ma20.iloc[-1]) / ma20.iloc[-1] * 100.0) if (pd.notna(ma20.iloc[-1]) and ma20.iloc[-1] != 0) else 0.0
                    rets = closes.pct_change()
                    vol_val = float(rets.tail(10).std() * 100.0) if len(rets) >= 2 else 0.0
                    recent_ret = float((closes.iloc[-1] / closes.iloc[-10] - 1.0) * 100.0) if (len(closes) >= 10 and closes.iloc[-10] not in (None, 0)) else 0.0
                    return {"momentum": rsi_val, "trend": trend_val, "volatility": vol_val, "recent_return": recent_ret}, trend_val

                _nz = lambda v: v if v is not None else 0

                def _pct(a, b):
                    try:
                        if a is None or b is None or b == 0:
                            return None
                        return (a - b) / b * 100.0
                    except Exception:
                        return None

                # Process in batches with BULK SQL queries per batch
                for bi in range(0, total, batch_size):
                    batch = watches_all[bi:bi + batch_size]
                    batch_syms = [w.symbol for w in batch]
                    rows = []

                    # ★ Per-batch spot snapshot (each batch ~20 symbols, single HTTP call)
                    try:
                        batch_spot = get_spot_snapshot(batch_syms)
                    except Exception as se:
                        logger.warning("stream: get_spot_snapshot batch failed: %s", se)
                        batch_spot = {}

                    try:
                        # --- BATCH QUERY 1: last 40 prices per symbol (for radar + d3/d20/last_row) ---
                        prices_q = session.execute(text("""
                            SELECT symbol, trade_date, close FROM (
                              SELECT symbol, trade_date, close,
                                     ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) as rn
                              FROM prices_daily WHERE symbol = ANY(:syms)
                            ) sub WHERE rn <= 40
                            ORDER BY symbol, trade_date ASC
                        """), {"syms": batch_syms}).fetchall()
                        # Build per-symbol price history: {sym: [(trade_date, close), ...]}  oldest-first
                        sym_prices: dict = {}
                        for pr in prices_q:
                            sym_prices.setdefault(pr.symbol, []).append((pr.trade_date, float(pr.close)))

                        # --- BATCH QUERY 2: first row per symbol (earliest price) ---
                        first_q = session.execute(text("""
                            SELECT DISTINCT ON (symbol) symbol, trade_date, close
                            FROM prices_daily WHERE symbol = ANY(:syms)
                            ORDER BY symbol, trade_date ASC
                        """), {"syms": batch_syms}).fetchall()
                        first_map = {r.symbol: r for r in first_q}

                        # --- BATCH QUERY 3: YTD first close per symbol ---
                        ytd_q = session.execute(text("""
                            SELECT DISTINCT ON (symbol) symbol, close
                            FROM prices_daily
                            WHERE symbol = ANY(:syms) AND EXTRACT(YEAR FROM trade_date)=EXTRACT(YEAR FROM CURRENT_DATE)
                            ORDER BY symbol, trade_date ASC
                        """), {"syms": batch_syms}).fetchall()
                        ytd_map = {r.symbol: float(r.close) for r in ytd_q}

                        # --- BATCH QUERY 4: latest fundflow per symbol ---
                        ff_q = session.execute(text("""
                            SELECT DISTINCT ON (symbol) symbol, trade_date, main_net
                            FROM fundflow_daily WHERE symbol = ANY(:syms)
                            ORDER BY symbol, trade_date DESC
                        """), {"syms": batch_syms}).fetchall()
                        ff_map = {r.symbol: r for r in ff_q}

                        # --- BATCH QUERY 5: first price after added_at (per-symbol fallback) ---
                        added_at_syms = [(w.symbol, w.added_at.date()) for w in batch if getattr(w, 'added_at', None)]
                        first_after_map: dict = {}
                        for s, d in added_at_syms:
                            try:
                                r = session.execute(text(
                                    "SELECT close FROM prices_daily WHERE symbol=:s AND trade_date >= :d ORDER BY trade_date ASC LIMIT 1"
                                ), {"s": s, "d": d}).scalar()
                                if r is not None:
                                    first_after_map[s] = float(r)
                            except Exception:
                                pass

                    except Exception as eq:
                        logger.warning("stream batch SQL failed: %s", eq)
                        try:
                            session.rollback()
                        except Exception:
                            pass
                        sym_prices, first_map, ytd_map, ff_map, first_after_map = {}, {}, {}, {}, {}

                    for w in batch:
                        try:
                            sym = w.symbol
                            base = sym.replace('.SH', '').replace('.SZ', '')
                            sp = batch_spot.get(sym, {})

                            # --- Extract per-stock data from batch results ---
                            price_hist = sym_prices.get(sym, [])  # oldest-first: [(date, close), ...]
                            closes_list = [c for _, c in price_hist]

                            # last_row (most recent price)
                            last_close = closes_list[-1] if closes_list else None
                            # d3 (3rd from latest = index -3)
                            d3 = closes_list[-3] if len(closes_list) >= 3 else None
                            # d20 (20th from latest = index -20)
                            d20 = closes_list[-20] if len(closes_list) >= 20 else None

                            # first_row: prefer after added_at, fallback to earliest
                            if sym in first_after_map:
                                first_close = first_after_map[sym]
                            elif sym in first_map:
                                first_close = float(first_map[sym].close) if first_map[sym].close is not None else None
                            else:
                                first_close = None

                            ytd_close = ytd_map.get(sym)

                            # Fund flow
                            ff_val, ff_date, ff_source = None, None, None
                            ff_row = ff_map.get(sym)
                            if fundflow_prefer in ("auto", "db") and ff_row and ff_row.main_net is not None:
                                try:
                                    ff_val = float(ff_row.main_net)
                                    ff_date = ff_row.trade_date.isoformat() if ff_row.trade_date else None
                                    ff_source = "db_latest"
                                except Exception:
                                    pass
                            if ff_val is None and fundflow_prefer in ("auto", "ak_today"):
                                rm, rd = _get_rank()
                                v = rm.get(base)
                                if v is not None:
                                    ff_val, ff_date, ff_source = float(v), rd or datetime.now().date().isoformat(), "ak_today"
                            # NOTE: Skip eastmoney HTTP fallback in streaming mode (too slow per-stock)

                            price = sp.get('price') if sp else (last_close if last_close is not None else None)
                            radar, trend_val = _compute_radar_from_closes(closes_list)
                            rows.append({
                                "name": sp.get('name') or w.name, "symbol": sym, "price": price,
                                "change": _nz(sp.get('change')), "pct_change": _nz(sp.get('pct_change')),
                                "since_watch_pct": _pct(price, first_close),
                                "radar": radar, "trend": trend_val,
                                "speed": _nz(sp.get('speed')), "volume": _nz(sp.get('volume')), "amount": _nz(sp.get('amount')),
                                "spot_source": sp.get('spot_source'), "amount_unit": "yuan",
                                "turnover_rate": _nz(sp.get('turnover_rate')), "volume_ratio": _nz(sp.get('volume_ratio')),
                                "amplitude": _nz(sp.get('amplitude')),
                                "main_net": ff_val, "fundflow_unit": "yuan", "fundflow_date": ff_date, "fundflow_source": ff_source,
                                "last_volume": _nz(sp.get('last_volume')),
                                "high": _nz(sp.get('high')), "low": _nz(sp.get('low')),
                                "open": _nz(sp.get('open')), "pre_close": _nz(sp.get('pre_close')),
                                "order_ratio": _nz(sp.get('order_ratio')),
                                "pe_ttm": _nz(sp.get('pe_ttm')), "pb": _nz(sp.get('pb')),
                                "total_market_cap": _nz(sp.get('total_market_cap')),
                                "chg_3d_pct": _pct(price, d3),
                                "chg_20d_pct": _pct(price, d20),
                                "chg_ytd_pct": _pct(price, ytd_close),
                            })
                        except Exception as e:
                            logger.warning("stream row %s failed: %s", w.symbol, e)
                            sp = batch_spot.get(w.symbol, {})
                            rows.append({"name": sp.get('name') or getattr(w, 'name', w.symbol), "symbol": w.symbol,
                                         "price": sp.get('price'), "change": 0, "pct_change": 0})

                    all_rows.extend(rows)
                    progress = min(bi + batch_size, total)
                    yield json.dumps({"rows": rows, "progress": progress, "total": total, "done": progress >= total}, ensure_ascii=False) + "\n"

            # Cache full result after streaming completes
            if all_rows:
                try:
                    full = {"rows": all_rows, "count": len(all_rows)}
                    _ck = f"watchlist_snapshot:{limit}:{fundflow_prefer}:v1"
                    _redis_set(_ck, json.dumps(full, ensure_ascii=False), ex=WATCHLIST_FRESH_TTL)
                    _redis_set(_ck + ":stale", json.dumps(full, ensure_ascii=False), ex=WATCHLIST_STALE_TTL)
                except Exception:
                    pass
        except Exception as e:
            logger.exception("watchlist_snapshot_stream error")
            yield json.dumps({"error": str(e), "done": True}, ensure_ascii=False) + "\n"

    return StreamingResponse(_generate(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})


# --- Fund Flow Diagnostics ---
@app.get("/api/fundflow/diagnostics")
def fundflow_diagnostics(
    symbol: str = Query(..., description="Symbol like 300251.SZ or 600519.SH"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today for rank, latest for DB"),
):
    """Return diagnostic comparison of fund flow main_net values from:
    - DB latest and DB on date (if provided)
    - Akshare individual history on date (if provided)
    - Akshare intraday rank (indicator=今日)

    All normalized to yuan with provenance and raw units.
    """
    sym = symbol.upper()
    base = sym.replace(".SH", "").replace(".SZ", "")
    out = {
        "symbol": sym,
        "base_code": base,
        "requested_date": date,
        "db_latest": None,
        "db_on_date": None,
        "ak_history_on_date": None,
        "ak_today_rank": None,
        "eastmoney_intraday": None,
        "eastmoney_eod": None,
        "sina_eod": None,
        "notes": [],
    }
    try:
        with SessionLocal() as session:
            latest_row = session.execute(text("SELECT trade_date, main_net FROM fundflow_daily WHERE symbol=:s ORDER BY trade_date DESC LIMIT 1"), {"s": sym}).first()
            if latest_row:
                out["db_latest"] = {
                    "trade_date": latest_row.trade_date.isoformat() if latest_row.trade_date else None,
                    "main_net": float(latest_row.main_net) if latest_row.main_net is not None else None,
                    "unit": "yuan",
                    "source": "db",
                }
            if date:
                row_on = session.execute(text("SELECT trade_date, main_net FROM fundflow_daily WHERE symbol=:s AND trade_date=:d LIMIT 1"), {"s": sym, "d": date}).first()
                if row_on:
                    out["db_on_date"] = {
                        "trade_date": row_on.trade_date.isoformat() if row_on.trade_date else date,
                        "main_net": float(row_on.main_net) if row_on.main_net is not None else None,
                        "unit": "yuan",
                        "source": "db",
                    }
    except Exception as e:
        out["notes"].append(f"DB error: {e}")
    # Akshare history on date
    if date:
        try:
            import akshare as ak
            hdf = ak.stock_individual_fund_flow(stock=base)
            if hdf is not None and not hdf.empty:
                # Expect columns like 日期, 主力净流入-净额 (万元)
                date_col = "日期" if "日期" in hdf.columns else ("date" if "date" in hdf.columns else None)
                val_cols = ["主力净流入-净额", "今日主力净流入-净额", "main_net"]
                vcol = None
                for c in val_cols:
                    if c in hdf.columns:
                        vcol = c
                        break
                if date_col and vcol:
                    row = hdf[hdf[date_col].astype(str) == str(date)]
                    if not row.empty:
                        raw = row.iloc[0][vcol]
                        try:
                            val_yuan = float(raw) * 1e4 if raw is not None else None  # 万元->元
                        except Exception:
                            val_yuan = None
                        out["ak_history_on_date"] = {
                            "trade_date": date,
                            "main_net": val_yuan,
                            "unit": "yuan",
                            "raw": raw,
                            "raw_unit": "万元",
                            "source": "akshare.stock_individual_fund_flow",
                        }
                    else:
                        out["notes"].append("Akshare history: no row for date")
                else:
                    out["notes"].append("Akshare history columns missing")
            else:
                out["notes"].append("Akshare history empty")
        except Exception as e:
            out["notes"].append(f"Akshare history error: {e}")
    # Akshare today rank (intraday)
    try:
        import akshare as ak
        rdf = ak.stock_individual_fund_flow_rank(indicator="今日")
        if rdf is not None and not rdf.empty:
            code_col = "代码" if "代码" in rdf.columns else ("symbol" if "symbol" in rdf.columns else None)
            val_col = None
            for c in ["今日主力净流入-净额", "主力净流入-净额"]:
                if c in rdf.columns:
                    val_col = c
                    break
            if code_col and val_col:
                r = rdf[rdf[code_col].astype(str) == base]
                if not r.empty:
                    raw = r.iloc[0][val_col]
                    try:
                        val_yuan = float(raw) * 1e4 if raw is not None else None
                    except Exception:
                        val_yuan = None
                    from datetime import datetime as _dt
                    out["ak_today_rank"] = {
                        "date": (_dt.now().date().isoformat()),
                        "main_net": val_yuan,
                        "unit": "yuan",
                        "raw": raw,
                        "raw_unit": "万元",
                        "source": "akshare.stock_individual_fund_flow_rank(今日)",
                    }
                else:
                    out["notes"].append("Akshare rank: symbol not found")
            else:
                out["notes"].append("Akshare rank columns missing")
        else:
            out["notes"].append("Akshare rank empty")
    except Exception as e:
        out["notes"].append(f"Akshare rank error: {e}")
    # Eastmoney push2 intraday main_net (f62)
    try:
        mk = "1" if sym.endswith(".SH") else "0"
        code = base
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": f"{mk}.{code}",
            "fields": "f58,f62",  # f58: name, f62: 主力净流入(元)
        }
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                j = resp.json()
                data = j.get("data") if isinstance(j, dict) else None
                if data:
                    name = data.get("f58")
                    f62 = data.get("f62")
                    try:
                        val = float(f62) if f62 is not None else None
                    except Exception:
                        val = None
                    out["eastmoney_intraday"] = {
                        "name": name,
                        "main_net": val,
                        "unit": "yuan",
                        "source": "eastmoney.push2.stock.get(f62)",
                    }
                else:
                    out["notes"].append("Eastmoney push2: empty data")
            else:
                out["notes"].append(f"Eastmoney push2 HTTP {resp.status_code}")
    except Exception as e:
        out["notes"].append(f"Eastmoney push2 error: {e}")
    # Eastmoney EOD (historical) via push2his daykline for fund flow
    if date:
        try:
            mk = "1" if sym.endswith(".SH") else "0"
            code = base
            url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
            params = {
                "secid": f"{mk}.{code}",
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56",  # date, main, super, large, medium, small
                "klt": "103",  # daily
                "lmt": "0",
            }
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    j = resp.json()
                    data = j.get("data") if isinstance(j, dict) else None
                    klines = data.get("klines") if data else None
                    if isinstance(klines, list):
                        # Find row for requested date
                        target = None
                        for item in klines:
                            # item like "YYYY-MM-DD,main,super,large,medium,small"
                            if isinstance(item, str) and item.startswith(date):
                                target = item
                                break
                        if target:
                            parts = target.split(",")
                            def _num(i):
                                try:
                                    return float(parts[i]) if len(parts) > i and parts[i] != "" else None
                                except Exception:
                                    return None
                            out["eastmoney_eod"] = {
                                "trade_date": parts[0] if parts else date,
                                "main_net": _num(1),
                                "super_net": _num(2),
                                "large_net": _num(3),
                                "medium_net": _num(4),
                                "small_net": _num(5),
                                "unit": "yuan",
                                "source": "eastmoney.push2his.fflow.daykline",
                            }
                        else:
                            out["notes"].append("Eastmoney EOD: date not found in klines")
                    else:
                        out["notes"].append("Eastmoney EOD: no klines")
                else:
                    out["notes"].append(f"Eastmoney EOD HTTP {resp.status_code}")
        except Exception as e:
            out["notes"].append(f"Eastmoney EOD error: {e}")
    # Sina EOD daily moneyflow (best effort, units often in 万元)
    if date:
        try:
            pre = "sh" if sym.endswith(".SH") else "sz"
            sina_symbol = f"{pre}{base}"
            url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssi_sshd_by_day"
            params = {"symbol": sina_symbol, "days": "90"}
            with httpx.Client(timeout=6.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    # Some Sina endpoints return JSON array text
                    try:
                        arr = resp.json()
                    except Exception:
                        import json as _json
                        arr = _json.loads(resp.text)
                    if isinstance(arr, list):
                        row = None
                        for it in arr:
                            d = str(it.get("date")) if isinstance(it, dict) else None
                            if d == date:
                                row = it
                                break
                        if row:
                            raw = row.get("netAmount")  # likely in 万元
                            try:
                                val_yuan = float(raw) * 1e4 if raw is not None else None
                            except Exception:
                                val_yuan = None
                            out["sina_eod"] = {
                                "trade_date": date,
                                "main_net_assumed": val_yuan,
                                "unit": "yuan",
                                "raw": raw,
                                "raw_unit": "万元 (assumed)",
                                "source": "sina.MoneyFlow.ssi_sshd_by_day",
                            }
                        else:
                            out["notes"].append("Sina EOD: date not found")
                    else:
                        out["notes"].append("Sina EOD: unexpected payload")
                else:
                    out["notes"].append(f"Sina EOD HTTP {resp.status_code}")
        except Exception as e:
            out["notes"].append(f"Sina EOD error: {e}")
    return out

class AnalysisRequest(BaseModel):
    days: int = Field(default=10, ge=5, le=30)
    pinned_only: bool = Field(default=False, description="仅分析置顶股票")
    symbols: list[str] = Field(default=[], description="指定分析的股票列表，为空则按 pinned_only 过滤")

@app.post("/api/watchlist/analysis")
def watchlist_analysis(req: AnalysisRequest):
    """Compute 1-2 week analysis per symbol: basic momentum, volatility, RSI and simple heuristic advice."""
    from .analysis.signals import compute_signals
    with SessionLocal() as session:
        if req.symbols:
            watches = session.execute(text("""
                SELECT spm.symbol, COALESCE(sp.company_name, w.name) AS name
                FROM stock_pool_members spm
                LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
                LEFT JOIN watchlist w ON spm.symbol = w.symbol
                WHERE spm.exit_date IS NULL AND spm.symbol = ANY(:syms)
            """), {"syms": [s.upper() for s in req.symbols]}).fetchall()
        elif req.pinned_only:
            watches = session.execute(text("""
                SELECT spm.symbol, COALESCE(sp.company_name, w.name) AS name
                FROM stock_pool_members spm
                LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
                INNER JOIN watchlist w ON spm.symbol = w.symbol AND w.pinned = true
                WHERE spm.exit_date IS NULL
            """)).fetchall()
        else:
            watches = session.execute(text("""
                SELECT spm.symbol, COALESCE(sp.company_name, w.name) AS name
                FROM stock_pool_members spm
                LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
                LEFT JOIN watchlist w ON spm.symbol = w.symbol
                WHERE spm.exit_date IS NULL
            """)).fetchall()
        out = []
        for w in watches:
            qdf = pd.read_sql_query(
                "SELECT trade_date, open, high, low, close, pct_chg, vol, amount FROM prices_daily WHERE symbol = %s ORDER BY trade_date",
                con=engine,
                params=(w.symbol,),
            )
            if len(qdf) < max(30, req.days+5):
                out.append({"symbol": w.symbol, "name": w.name, "enough_data": False})
                continue
            sig = compute_signals(qdf)
            tail = sig.tail(req.days)
            last_row = sig.iloc[-1] if len(sig) else None
            # simple radar-like scores
            momentum = float(tail['rsi'].mean()) if 'rsi' in tail else None
            trend = float((tail['ma_s'] - tail['ma_l']).mean()) if 'ma_s' in tail and 'ma_l' in tail else None
            volatility = float(tail['close'].pct_change().std()*100.0)
            macd_val = float(tail['macd'].mean()) if 'macd' in tail else None
            recent_return = float((tail['close'].iloc[-1] / tail['close'].iloc[0] - 1.0) * 100.0)
            # --- richer heuristic advice ---
            advice = []
            risk = []
            # RSI based
            if momentum is not None:
                if momentum > 70: advice.append("RSI超买(>{:.0f})，短线注意回调".format(momentum))
                elif momentum > 60: advice.append("动量偏强，关注突破机会")
                elif momentum > 40: advice.append("动量中性，可观望")
                else: advice.append("动量偏弱(RSI {:.0f})，谨慎追高".format(momentum))
            # Trend based
            if trend is not None:
                if trend > 0: advice.append("短期均线高于长期，趋势偏多")
                else: advice.append("短期弱于长期，等待企稳")
            # MACD based
            if last_row is not None:
                if 'macd_hist' in last_row.index:
                    hist_val = float(last_row['macd_hist']) if pd.notna(last_row['macd_hist']) else None
                    if hist_val is not None:
                        if hist_val > 0:
                            advice.append("MACD柱状线为正，多头动能延续")
                        else:
                            advice.append("MACD柱状线为负，空头动能占优")
                # signal_score / action from compute_signals
                if 'action' in last_row.index:
                    act = last_row['action']
                    if act == 'BUY': advice.append("信号打分: 买入信号")
                    elif act == 'TRIM': advice.append("信号打分: 减仓信号")
                    else: advice.append("信号打分: 持有观望")
            # Risk
            if volatility is not None and volatility > 3:
                risk.append("波动率较高({:.1f}%)，控制仓位".format(volatility))
            if recent_return > 5:
                risk.append("短期涨幅较大({:.1f}%)，警惕回撤".format(recent_return))
            elif recent_return < -5:
                risk.append("短期跌幅较大({:.1f}%)，注意止损".format(recent_return))
            if momentum is not None and momentum > 70:
                risk.append("RSI进入超买区间，回调风险增大")
            elif momentum is not None and momentum < 30:
                risk.append("RSI进入超卖区间，可能存在反弹机会")
            out.append({
                "symbol": w.symbol,
                "name": w.name,
                "days": req.days,
                "radar": {
                    "momentum": momentum,
                    "trend": trend,
                    "volatility": volatility,
                    "macd": macd_val,
                    "recent_return": recent_return,
                },
                "advice": advice,
                "risk": risk,
                "enough_data": True,
            })
        return {"items": out}

@app.get("/report/{symbol}")
async def get_report(symbol: str, version: int = Query(None, description="报告版本号，默认返回最新版本")):
    with SessionLocal() as session:
        sym = symbol.upper()
        
        # 查找报告
        if version:
            # 获取指定版本的报告
            report = session.execute(
                select(Report).where(
                    and_(Report.symbol == sym, Report.version == version)
                )
            ).scalar_one_or_none()
        else:
            # 获取最新版本的报告 - 按创建时间排序并取第一个
            result = session.execute(
                select(Report).where(
                    and_(Report.symbol == sym, Report.is_latest == True)
                ).order_by(Report.created_at.desc())
            ).first()
            
            report = result[0] if result else None
        
        if report:
            # 使用报告数据
            result = {
                "symbol": sym,
                "version": report.version,
                "created_at": report.created_at.isoformat(),
                "is_latest": report.is_latest,
                "data_quality_score": float(report.data_quality_score) if report.data_quality_score else None,
                "prediction_confidence": float(report.prediction_confidence) if report.prediction_confidence else None,
                "analysis_summary": report.analysis_summary
            }
            
            # 解析JSON数据
            if report.latest_price_data:
                result["latest"] = json.loads(report.latest_price_data)
            
            if report.signal_data:
                result["signal"] = json.loads(report.signal_data)
            
            if report.forecast_data:
                result["forecast"] = json.loads(report.forecast_data)
            
            return result
        
        # 如果没有报告，创建报告任务并返回传统数据
        await task_manager.create_report_task(sym, priority=1)
        
        # 返回传统方式查询的数据
        last = session.execute(
            text(
                "SELECT p.* FROM prices_daily p WHERE p.symbol=:sym ORDER BY p.trade_date DESC LIMIT 1"
            ),
            {"sym": sym},
        ).mappings().first()
        sig = session.execute(
            text(
                "SELECT * FROM signals WHERE symbol=:sym ORDER BY trade_date DESC LIMIT 1"
            ),
            {"sym": sym},
        ).mappings().first()
        fc = session.execute(
            text(
                "SELECT target_date, avg(yhat) yhat, avg(yhat_lower) yl, avg(yhat_upper) yu FROM forecasts WHERE symbol=:sym GROUP BY target_date ORDER BY target_date"
            ),
            {"sym": sym},
        ).mappings().all()
        
        if not last:
            raise HTTPException(status_code=404, detail="no data")
        
        return {
            "latest": dict(last),
            "signal": dict(sig) if sig else None,
            "forecast": [dict(r) for r in fc],
            "report_status": "generating",
            "message": "报告生成中，请稍后刷新"
        }

@app.get("/signals/today")
def signals_today():
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT * FROM signals WHERE trade_date=(SELECT max(trade_date) FROM signals) ORDER BY signal_score DESC"
            )
        ).mappings().all()
        return [dict(r) for r in rows]

@app.get("/api/signals/generate")
def api_generate_signals(
    top_n: int = Query(10, ge=1, le=50),
    buy_threshold: float = Query(0.65, ge=0.5, le=0.95),
    sell_threshold: float = Query(0.65, ge=0.5, le=0.95),
    min_holding_days: int = Query(3, ge=0, le=30),
):
    """手动触发交易信号生成（也可通过定时任务每日自动执行）"""
    try:
        from .prediction.services.signal_engine import generate_daily_signals
        report = generate_daily_signals(
            top_n=top_n,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            min_holding_days=min_holding_days,
        )
        return {
            "report_date": report.report_date.isoformat(),
            "total_scored": report.total_stocks_scored,
            "total_filtered": report.total_filtered,
            "buy": [
                {
                    "symbol": s.symbol, "name": s.name, "sector": s.sector,
                    "action": s.action, "composite_score": s.composite_score,
                    "predicted_return_5d": round(s.predicted_return_5d, 6),
                    "up_probability": round(s.up_probability, 4),
                    "confidence": round(s.model_confidence, 3),
                    "signal_strength": s.signal_strength,
                    "current_price": s.current_price,
                    "target_price": s.target_price,
                    "stop_loss_price": s.stop_loss_price,
                }
                for s in report.buy_signals
            ],
            "sell": [
                {
                    "symbol": s.symbol, "name": s.name,
                    "action": s.action, "composite_score": s.composite_score,
                    "predicted_return_5d": round(s.predicted_return_5d, 6),
                    "holding_days": s.holding_days,
                    "current_price": s.current_price,
                }
                for s in report.sell_signals
            ],
            "hold_count": len(report.hold_signals),
            "filters_applied": report.filters_applied,
        }
    except Exception as e:
        logger.error("Signal generation API error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/signals/latest")
def api_latest_signals(
    signal_type: Optional[str] = Query(None, description="buy/sell/hold"),
    limit: int = Query(50, ge=1, le=200),
):
    """查询最近的交易信号"""
    with SessionLocal() as session:
        q = session.query(TradingSignal).filter(
            TradingSignal.source == "signal_engine"
        ).order_by(TradingSignal.signal_date.desc(), TradingSignal.signal_strength.desc())

        if signal_type:
            q = q.filter(TradingSignal.signal_type == signal_type.lower())

        rows = q.limit(limit).all()
        return [
            {
                "symbol": r.symbol,
                "signal_date": r.signal_date.isoformat() if r.signal_date else None,
                "signal_type": r.signal_type,
                "signal_strength": float(r.signal_strength) if r.signal_strength else 0,
                "confidence": float(r.confidence) if r.confidence else 0,
                "trigger_price": float(r.trigger_price) if r.trigger_price else None,
                "target_price": float(r.target_price) if r.target_price else None,
                "stop_loss_price": float(r.stop_loss_price) if r.stop_loss_price else None,
                "strategy": r.strategy,
                "factors": json.loads(r.factors) if r.factors else None,
            }
            for r in rows
        ]


@app.get("/api/signals/positions")
def api_signal_positions():
    """查看信号引擎管理的持仓"""
    with SessionLocal() as session:
        rows = session.query(PositionManagement).filter(
            PositionManagement.portfolio_id == "signal_engine_default",
            PositionManagement.quantity > 0,
        ).all()
        return [
            {
                "symbol": r.symbol,
                "quantity": r.quantity,
                "avg_cost": float(r.avg_cost) if r.avg_cost else None,
                "current_price": float(r.current_price) if r.current_price else None,
                "market_value": float(r.market_value) if r.market_value else None,
                "unrealized_pnl": float(r.unrealized_pnl) if r.unrealized_pnl else None,
                "unrealized_pnl_pct": round(float(r.unrealized_pnl_pct), 2) if r.unrealized_pnl_pct else None,
                "holding_days": r.holding_days,
                "entry_date": r.entry_date.isoformat() if r.entry_date else None,
                "stop_loss_price": float(r.stop_loss_price) if r.stop_loss_price else None,
                "take_profit_price": float(r.take_profit_price) if r.take_profit_price else None,
                "weight": float(r.weight) if r.weight else None,
            }
            for r in rows
        ]


@app.get("/api/portfolio/optimize")
def api_optimize_portfolio(
    method: str = Query("risk_parity", description="equal_weight / risk_parity / return_weighted"),
    total_capital: float = Query(100000, ge=10000),
    max_single_weight: float = Query(0.20, ge=0.05, le=0.50),
    max_sector_weight: float = Query(0.40, ge=0.10, le=1.0),
):
    """手动触发投资组合优化"""
    try:
        from .prediction.services.portfolio_optimizer import PortfolioOptimizer, PORTFOLIO_ID
        with SessionLocal() as session:
            from .core.models import TradingSignal as TS
            today = date.today()
            lookback = today - timedelta(days=3)

            buy_rows = session.query(TS.symbol, TS.signal_strength, TS.factors).filter(
                TS.source == "signal_engine", TS.signal_type == "buy",
                TS.signal_date >= lookback,
            ).order_by(TS.signal_strength.desc()).limit(20).all()

            sell_rows = session.query(TS.symbol).filter(
                TS.source == "signal_engine", TS.signal_type == "sell",
                TS.signal_date >= lookback,
            ).all()

            buy_syms = [r.symbol for r in buy_rows]
            sell_syms = [r.symbol for r in sell_rows]
            pred_rets = {}
            sig_str = {}
            for r in buy_rows:
                if r.factors:
                    try:
                        f = json.loads(r.factors)
                        pred_rets[r.symbol] = f.get("predicted_return_5d", 0)
                    except Exception:
                        pass
                sig_str[r.symbol] = float(r.signal_strength or 0)

            optimizer = PortfolioOptimizer(
                session=session, total_capital=total_capital,
                method=method, max_single_weight=max_single_weight,
                max_sector_weight=max_sector_weight,
            )
            result = optimizer.optimize(buy_syms, sell_syms,
                                        predicted_returns=pred_rets, signal_strengths=sig_str)

        return {
            "method": result.method,
            "total_capital": result.total_capital,
            "cash": round(result.cash_amount, 2),
            "cash_weight": round(result.cash_weight, 4),
            "positions": [
                {
                    "symbol": a.symbol, "name": a.name, "sector": a.sector,
                    "weight": round(a.target_weight, 4),
                    "quantity": a.quantity, "price": a.current_price,
                    "market_value": round(a.market_value, 2),
                    "predicted_return": round(a.predicted_return, 6),
                    "volatility": round(a.annual_volatility, 4),
                }
                for a in result.assets if a.quantity > 0
            ],
            "risk": {
                "annual_volatility": round(result.risk.portfolio_annual_vol, 4),
                "max_drawdown": round(result.risk.max_drawdown, 4),
                "sharpe_ratio": result.risk.sharpe_ratio,
                "diversification_ratio": result.risk.diversification_ratio,
                "max_single_weight": round(result.risk.max_single_weight, 4),
                "max_sector_weight": round(result.risk.max_sector_weight, 4),
                "hhi": result.risk.hhi,
            },
            "rebalance_needed": result.needs_rebalance,
            "rebalance_actions": [
                {
                    "symbol": ra.symbol, "action": ra.action,
                    "current_weight": ra.current_weight,
                    "target_weight": ra.target_weight,
                    "quantity_delta": ra.quantity_delta,
                    "trade_value": ra.trade_value,
                }
                for ra in result.rebalance_actions if ra.action != "hold"
            ],
        }
    except Exception as e:
        logger.error("Portfolio optimization API error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/portfolio/summary")
def api_portfolio_summary():
    """查看当前投资组合概况"""
    with SessionLocal() as session:
        portfolio = session.query(Portfolio).filter(
            Portfolio.portfolio_id == "signal_engine_default"
        ).first()
        if not portfolio:
            return {"error": "No portfolio found. Run optimization first."}

        positions = session.query(PositionManagement).filter(
            PositionManagement.portfolio_id == "signal_engine_default",
            PositionManagement.quantity > 0,
        ).all()

        return {
            "portfolio_id": portfolio.portfolio_id,
            "name": portfolio.name,
            "initial_capital": float(portfolio.initial_capital) if portfolio.initial_capital else None,
            "cash": float(portfolio.cash) if portfolio.cash else None,
            "total_value": float(portfolio.total_value) if portfolio.total_value else None,
            "total_return": float(portfolio.total_return) if portfolio.total_return else None,
            "max_drawdown": float(portfolio.max_drawdown) if portfolio.max_drawdown else None,
            "sharpe_ratio": float(portfolio.sharpe_ratio) if portfolio.sharpe_ratio else None,
            "position_count": portfolio.position_count,
            "cash_ratio": float(portfolio.cash_ratio) if portfolio.cash_ratio else None,
            "strategy": portfolio.strategy,
            "risk_limits": {
                "max_single_position": float(portfolio.max_single_position) if portfolio.max_single_position else None,
                "max_sector_position": float(portfolio.max_sector_position) if portfolio.max_sector_position else None,
                "max_total_position": float(portfolio.max_total_position) if portfolio.max_total_position else None,
            },
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": float(p.avg_cost) if p.avg_cost else None,
                    "current_price": float(p.current_price) if p.current_price else None,
                    "market_value": float(p.market_value) if p.market_value else None,
                    "weight": float(p.weight) if p.weight else None,
                    "target_weight": float(p.target_weight) if p.target_weight else None,
                    "unrealized_pnl_pct": round(float(p.unrealized_pnl_pct), 2) if p.unrealized_pnl_pct else None,
                    "holding_days": p.holding_days,
                }
                for p in positions
            ],
            "updated_at": portfolio.updated_at.isoformat() if portfolio.updated_at else None,
        }


@app.get("/api/events/detect")
def api_detect_events(
    symbol: str = Query(..., description="股票代码"),
    days: int = Query(7, ge=1, le=90, description="回溯天数"),
):
    """检测指定股票的事件驱动因子"""
    try:
        from .prediction.framework.event_alpha import extract_events_from_db
        today = date.today()
        start = today - timedelta(days=days)
        with SessionLocal() as session:
            events, event_df = extract_events_from_db(
                session, [symbol.upper()], start, today,
            )
            return {
                "symbol": symbol.upper(),
                "period": f"{start} → {today}",
                "events_detected": len(events),
                "events": [
                    {
                        "date": e.event_date.isoformat(),
                        "category": e.category,
                        "sentiment": e.sentiment,
                        "sentiment_score": e.sentiment_score,
                        "impact_score": e.impact_score,
                        "confidence": e.confidence,
                        "keywords": e.keywords_matched,
                        "source": e.source_title[:80] if e.source_title else "",
                    }
                    for e in events[:50]
                ],
                "features": event_df.to_dict(orient="records") if not event_df.empty else [],
            }
    except Exception as e:
        logger.error("Event detect API error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/validate")
def api_validate_events(
    symbols: str = Query("", description="逗号分隔的股票代码，留空=全部活跃股"),
    days: int = Query(30, ge=7, le=365, description="验证期间天数"),
):
    """验证事件对股价的实际影响"""
    try:
        from .prediction.framework.event_validator import validate_events_from_db
        today = date.today()
        start = today - timedelta(days=days)
        with SessionLocal() as session:
            if symbols:
                sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
            else:
                from .core.models import Watchlist as WL
                sym_list = [r.symbol for r in session.query(WL.symbol).filter(WL.status == "active").limit(50).all()]

            report = validate_events_from_db(session, sym_list, start, today)

            return {
                "period": f"{start} → {today}",
                "total_events": report.total_events,
                "total_symbols": report.total_symbols,
                "overall_direction_accuracy": round(report.overall_direction_accuracy, 4),
                "avg_post_5d_return": round(report.avg_post_5d_return, 6),
                "positive_events_correct_pct": round(report.positive_events_correct_pct, 4),
                "negative_events_correct_pct": round(report.negative_events_correct_pct, 4),
                "category_stats": {
                    cat: {
                        "count": s.count,
                        "direction_accuracy": round(s.direction_accuracy, 4),
                        "avg_ret_day0": round(s.avg_ret_day0, 6),
                        "avg_ret_post_5d": round(s.avg_ret_post_5d, 6),
                        "positive_avg_ret_5d": round(s.positive_avg_ret_5d, 6),
                        "negative_avg_ret_5d": round(s.negative_avg_ret_5d, 6),
                        "significant_positive": s.significant_positive,
                        "significant_negative": s.significant_negative,
                    }
                    for cat, s in report.category_stats.items()
                },
            }
    except Exception as e:
        logger.error("Event validate API error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/paper-trading/run")
def api_run_paper_trading():
    """手动触发模拟实盘交易"""
    try:
        from .prediction.services.paper_trading import run_daily_paper_trading
        report = run_daily_paper_trading()
        result = {
            "date": report.run_date.isoformat(),
            "success": report.success,
            "buy_count": report.buy_count,
            "sell_count": report.sell_count,
            "total_commission": round(report.total_commission, 2),
            "orders": [
                {
                    "symbol": o.symbol, "action": o.action,
                    "quantity": o.quantity, "price": o.price,
                    "amount": round(o.amount, 2),
                    "commission": round(o.commission, 2),
                    "reason": o.reason,
                }
                for o in report.orders_executed
            ],
        }
        if report.snapshot:
            s = report.snapshot
            result["snapshot"] = {
                "total_value": round(s.total_value, 2),
                "cash": round(s.cash, 2),
                "market_value": round(s.market_value, 2),
                "nav": s.nav,
                "daily_return": round(s.daily_return, 6),
                "total_return": round(s.total_return, 6),
                "drawdown": round(s.drawdown, 6),
                "max_drawdown": round(s.max_drawdown, 6),
                "benchmark_return": round(s.benchmark_return, 6),
                "excess_return": round(s.excess_return, 6),
                "position_count": s.position_count,
            }
        if report.error_message:
            result["error"] = report.error_message
        return result
    except Exception as e:
        logger.error("Paper trading API error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/paper-trading/nav")
def api_paper_trading_nav(days: int = Query(365, ge=1, le=3650)):
    """获取模拟盘净值曲线（含基准对比）"""
    with SessionLocal() as session:
        cutoff = date.today() - timedelta(days=days)
        rows = (
            session.query(PaperTradingSnapshot)
            .filter(
                PaperTradingSnapshot.portfolio_id == "paper_trading_main",
                PaperTradingSnapshot.snapshot_date >= cutoff,
            )
            .order_by(PaperTradingSnapshot.snapshot_date)
            .all()
        )
        if not rows:
            return {"data": [], "stats": {}}

        data = []
        for r in rows:
            data.append({
                "date": r.snapshot_date.isoformat(),
                "nav": float(r.nav),
                "total_return": float(r.total_return or 0),
                "daily_return": float(r.daily_return or 0),
                "drawdown": float(r.drawdown or 0),
                "max_drawdown": float(r.max_drawdown or 0),
                "benchmark_return": float(r.benchmark_return or 0),
                "excess_return": float(r.excess_return or 0),
                "position_count": r.position_count,
                "total_value": float(r.total_value),
            })

        # 统计
        daily_rets = [float(r.daily_return or 0) for r in rows]
        total_ret = float(rows[-1].total_return or 0) if rows else 0
        max_dd = min(float(r.max_drawdown or 0) for r in rows) if rows else 0
        avg_ret = float(np.mean(daily_rets)) * 252 if daily_rets else 0
        std_ret = float(np.std(daily_rets)) * np.sqrt(252) if daily_rets else 0
        sharpe = (avg_ret - 0.02) / std_ret if std_ret > 0 else 0

        stats = {
            "total_return": round(total_ret, 6),
            "annualized_return": round(avg_ret, 6),
            "annualized_volatility": round(std_ret, 6),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(max_dd, 6),
            "benchmark_return": round(float(rows[-1].benchmark_return or 0), 6) if rows else 0,
            "excess_return": round(float(rows[-1].excess_return or 0), 6) if rows else 0,
            "trading_days": len(rows),
        }

        return {"data": data, "stats": stats}


@app.get("/api/paper-trading/positions")
def api_paper_trading_positions():
    """获取当前模拟盘持仓"""
    with SessionLocal() as session:
        positions = (
            session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == "paper_trading_main",
                PositionManagement.quantity > 0,
            )
            .all()
        )

        portfolio = session.query(Portfolio).filter(
            Portfolio.portfolio_id == "paper_trading_main"
        ).first()

        total_value = float(portfolio.total_value) if portfolio and portfolio.total_value else 0

        return {
            "portfolio": {
                "total_value": total_value,
                "cash": float(portfolio.cash) if portfolio and portfolio.cash else 0,
                "total_return": float(portfolio.total_return) if portfolio and portfolio.total_return else 0,
                "max_drawdown": float(portfolio.max_drawdown) if portfolio and portfolio.max_drawdown else 0,
                "sharpe_ratio": float(portfolio.sharpe_ratio) if portfolio and portfolio.sharpe_ratio else 0,
            } if portfolio else {},
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": round(float(p.avg_cost), 2) if p.avg_cost else None,
                    "current_price": round(float(p.current_price), 2) if p.current_price else None,
                    "market_value": round(float(p.market_value), 2) if p.market_value else None,
                    "weight": round(float(p.market_value) / total_value * 100, 1) if p.market_value and total_value > 0 else 0,
                    "unrealized_pnl": round(float(p.unrealized_pnl), 2) if p.unrealized_pnl else None,
                    "unrealized_pnl_pct": round(float(p.unrealized_pnl_pct), 2) if p.unrealized_pnl_pct else None,
                    "holding_days": p.holding_days,
                    "entry_date": p.entry_date.isoformat() if p.entry_date else None,
                }
                for p in positions
            ],
        }


@app.get("/api/paper-trading/trades")
def api_paper_trading_trades(
    days: int = Query(90, ge=1, le=365),
    symbol: str = Query("", description="按股票过滤"),
):
    """获取模拟盘交易记录"""
    with SessionLocal() as session:
        cutoff = date.today() - timedelta(days=days)
        q = (
            session.query(PaperTradeLog)
            .filter(
                PaperTradeLog.portfolio_id == "paper_trading_main",
                PaperTradeLog.trade_date >= cutoff,
            )
        )
        if symbol:
            q = q.filter(PaperTradeLog.symbol == symbol.upper())

        rows = q.order_by(PaperTradeLog.trade_date.desc()).limit(500).all()

        # 统计
        total_trades = len(rows)
        wins = sum(1 for r in rows if r.realized_pnl and r.realized_pnl > 0)
        losses = sum(1 for r in rows if r.realized_pnl and r.realized_pnl < 0)
        total_pnl = sum(float(r.realized_pnl) for r in rows if r.realized_pnl)
        total_commission = sum(float(r.commission or 0) for r in rows)

        return {
            "stats": {
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / (wins + losses), 4) if (wins + losses) > 0 else 0,
                "total_pnl": round(total_pnl, 2),
                "total_commission": round(total_commission, 2),
            },
            "trades": [
                {
                    "date": r.trade_date.isoformat(),
                    "symbol": r.symbol,
                    "action": r.action,
                    "quantity": r.quantity,
                    "price": round(float(r.price), 2),
                    "amount": round(float(r.amount), 2),
                    "commission": round(float(r.commission), 2) if r.commission else 0,
                    "realized_pnl": round(float(r.realized_pnl), 2) if r.realized_pnl else None,
                    "realized_pnl_pct": round(float(r.realized_pnl_pct), 2) if r.realized_pnl_pct else None,
                    "reason": r.reason,
                }
                for r in rows
            ],
        }


@app.get("/prices/{symbol}")
def get_prices(symbol: str, limit: int = Query(180, ge=1, le=1000)):
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT trade_date, close, open, high, low, vol FROM prices_daily WHERE symbol=:sym ORDER BY trade_date DESC LIMIT :lim"
            ),
            {"sym": symbol.upper(), "lim": limit},
        ).mappings().all()
        out = [dict(r) for r in rows][::-1]
        return out

# 任务管理API端点
@app.get("/tasks/pending")
async def get_pending_tasks():
    """获取待处理任务列表"""
    tasks = await task_manager.get_pending_tasks()
    return {"tasks": tasks}

@app.post("/tasks/create_report/{symbol}")
async def create_report_task(symbol: str, priority: int = Query(5, ge=1, le=10)):
    """为指定股票创建报告任务"""
    task_id = await task_manager.create_report_task(symbol.upper(), priority)
    return {"task_id": task_id, "symbol": symbol.upper()}

@app.post("/tasks/check_missing")
async def check_missing_report_tasks():
    """检查并创建缺失的报告任务"""
    created_tasks = await task_manager.check_and_create_missing_report_tasks()
    return {"created_tasks": created_tasks, "count": len(created_tasks)}

@app.get("/api/news/host-refs")
async def get_articles_by_host(
    host: str = Query(..., description="目标主机名，例如 tw.stock.yahoo.com"),
    include_content_refs: bool = Query(True, description="是否包含正文中包含该host的文章"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    validate: bool = Query(False, description="是否同时校验链接可用性"),
    concurrency: int = Query(5, ge=1, le=20),
    timeout: int = Query(15, ge=3, le=60),
):
    """列出引用指定主机的文章，并可选对这些URL进行联网校验。

    - host: 例如 'tw.stock.yahoo.com'
    - include_content_refs: 也匹配正文包含该host的文章
    - validate: 若为 true，将对匹配到的 url 逐个进行HTTP校验（HEAD或GET）
    """
    try:
        with SessionLocal() as session:
            from sqlalchemy import or_
            pattern = f"%://{host}/%"
            q = select(NewsArticle).where(NewsArticle.url.like(pattern))
            if include_content_refs:
                q = q.union_all(
                    select(NewsArticle).where(NewsArticle.content.ilike(f"%{host}%"))
                )
            q = q.order_by(NewsArticle.published_at.desc().nullslast()).offset(offset).limit(limit)
            arts = session.execute(q).scalars().all()

        # 基本列表
        out_articles = [
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "source": a.source.name if a.source else None,
            }
            for a in arts
        ]

        result = {
            "host": host,
            "count": len(out_articles),
            "articles": out_articles,
        }

        if not validate or not out_articles:
            return result

        # 校验URL有效性
        headers_base = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip, deflate, br",
        }
        ua_pool = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        ]

        uniq_urls = []
        seen = set()
        for a in out_articles:
            u = a.get("url")
            if isinstance(u, str) and u not in seen:
                seen.add(u)
                uniq_urls.append(u)

        sem = asyncio.Semaphore(concurrency)

        async def check_url(i: int, url: str):
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}/"
            headers = dict(headers_base)
            headers["User-Agent"] = ua_pool[i % len(ua_pool)]
            headers["Referer"] = origin
            try:
                async with sem:
                    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
                        # Try HEAD first
                        try:
                            r = await client.head(url)
                            if r.status_code in (200, 301, 302, 303, 307, 308):
                                return {"url": url, "status": r.status_code, "ok": True, "final_url": str(r.url)}
                            # Some hosts block HEAD; fall back to GET
                        except Exception:
                            pass
                        r = await client.get(url)
                        ok = 200 <= r.status_code < 400
                        return {"url": url, "status": r.status_code, "ok": ok, "final_url": str(r.url)}
            except Exception as e:
                return {"url": url, "status": None, "ok": False, "error": str(e)}

        tasks = [check_url(i, u) for i, u in enumerate(uniq_urls)]
        validations = await asyncio.gather(*tasks)
        result["validation"] = validations
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"host refs inspection failed: {e}")

# ───────── 预测复盘 API ─────────

_PREDICTION_EVAL_REFRESH_CACHE: dict[str, float] = {}
_PREDICTION_EVAL_REFRESH_LOCK = _threading.Lock()


def _maybe_refresh_prediction_evaluations(
    session: Session,
    symbol: str | None = None,
    lookback_days: int = 14,
    ttl_seconds: int = 60,
) -> dict:
    """短 TTL 同步 forecasts → prediction_evaluations 并回填 actuals。

    /api/report/{symbol}/full 和 /api/predictions/history 都会触发这个轻量刷新，
    这样用户打开图表时能看到刚生成的预测在历史复盘层里逐步沉淀。
    """
    key = (symbol or "*").upper()
    now = time.monotonic()
    with _PREDICTION_EVAL_REFRESH_LOCK:
        last = _PREDICTION_EVAL_REFRESH_CACHE.get(key)
        if last is not None and now - last < ttl_seconds:
            return {"skipped": True, "reason": "ttl"}
        _PREDICTION_EVAL_REFRESH_CACHE[key] = now

    try:
        from .prediction.services.prediction_service import PredictionService

        svc = PredictionService(session)
        synced = svc.sync_forecasts(lookback_days=max(lookback_days, 7), symbol=symbol)
        backfilled = svc.backfill_actuals(symbol=symbol)
        return {"skipped": False, "forecasts_synced": synced, "actuals_backfilled": backfilled}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.debug("prediction evaluation refresh skipped for %s: %s", key, exc)
        return {"skipped": True, "reason": "error", "error": str(exc)[:200]}


def _prediction_direction_color_value(value: Optional[bool]) -> Optional[bool]:
    return value if value is not None else None


def _persist_iteration_bundle_safe(
    session: Session,
    *,
    symbol: str,
    lookback_days: int,
    feature_snapshot: Optional[dict],
    failure_analysis: Optional[dict],
    agent_review: Optional[dict],
) -> dict:
    try:
        from .prediction.services.agent_iteration_persistence_service import persist_agent_iteration_bundle

        return persist_agent_iteration_bundle(
            session,
            symbol=symbol,
            lookback_days=lookback_days,
            feature_snapshot=feature_snapshot,
            failure_analysis=failure_analysis,
            agent_review=agent_review,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent iteration persistence unavailable for %s: %s", symbol, exc)
        return {"status": "failed", "reason": str(exc)[:200]}


@app.get("/api/predictions/history")
def prediction_history(
    symbol: str = Query(..., description="股票代码，如 300750.SZ"),
    lookback_days: int = Query(60, ge=5, le=365, description="回看自然日窗口"),
    refresh: bool = Query(True, description="是否先同步 forecasts 并回填 actuals"),
):
    """返回历史预测 vs 实际收盘的图表契约。

    rows 按 target_date 聚合，优先输出 D-1 / D-5（按交易日间隔计算）的历史预测，
    stats 用于前端展示 30 日 MAPE、方向准确率和区间命中率。
    """
    sym = symbol.upper()
    cutoff = date.today() - timedelta(days=lookback_days)

    with SessionLocal() as session:
        from .prediction.services.prediction_service import (
            aggregate_stock_evaluation_summary,
            build_deviation_cases,
            build_evaluation_availability,
            build_prediction_quality,
            classify_deviation_level,
        )
        from .prediction.services.failure_analysis_service import build_failure_analysis
        from .prediction.services.agent_review_service import build_agent_review
        from .prediction.services.agent_verification_service import build_agent_verification
        from .prediction.services.feature_snapshot_service import load_stock_feature_snapshot

        refresh_meta = None
        if refresh:
            refresh_meta = _maybe_refresh_prediction_evaluations(
                session,
                symbol=sym,
                lookback_days=lookback_days + 10,
            )

        recent_forecasts = list(session.execute(
            select(Forecast)
            .where(
                Forecast.symbol == sym,
                Forecast.run_at >= datetime.combine(cutoff - timedelta(days=10), datetime.min.time()),
            )
            .order_by(Forecast.run_at.desc())
            .limit(300)
        ).scalars().all())

        latest_pipeline_run = session.execute(
            select(PipelineRun)
            .where(
                PipelineRun.symbol == sym,
                PipelineRun.run_type.in_(["fetch_daily", "predict", "daily_pipeline", "full_report"]),
            )
            .order_by(PipelineRun.run_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        evals = list(session.execute(
            select(PredictionEvaluation)
            .where(
                PredictionEvaluation.symbol == sym,
                PredictionEvaluation.target_date >= cutoff,
            )
            .order_by(PredictionEvaluation.target_date.asc(), PredictionEvaluation.prediction_date.desc())
        ).scalars().all())

        if not evals:
            price_rows_empty = list(session.execute(
                select(PriceDaily)
                .where(
                    PriceDaily.symbol == sym,
                    PriceDaily.trade_date >= cutoff - timedelta(days=10),
                    PriceDaily.trade_date <= date.today(),
                )
                .order_by(PriceDaily.trade_date.asc())
            ).scalars().all())
            summary = aggregate_stock_evaluation_summary([], {})
            availability = build_evaluation_availability(
                sym,
                [],
                recent_forecasts,
                price_rows_empty,
                latest_pipeline_run=latest_pipeline_run,
                supported_record_count=0,
            )
            quality = build_prediction_quality(sym, summary, availability, [])
            failure_analysis = build_failure_analysis(sym, [])
            try:
                feature_snapshot = load_stock_feature_snapshot(session, sym)
            except Exception:
                feature_snapshot = None
            agent_review = build_agent_review(sym, failure_analysis=failure_analysis, feature_snapshot=feature_snapshot)
            verification = build_agent_verification(agent_review, failure_analysis=failure_analysis, feature_snapshot=feature_snapshot)
            agent_review["verification_status"] = verification["verification_status"]
            agent_review["verification_checks"] = verification["checks"]
            agent_review["gate_result"] = verification["gate_result"]
            persistence = _persist_iteration_bundle_safe(
                session,
                symbol=sym,
                lookback_days=lookback_days,
                feature_snapshot=feature_snapshot,
                failure_analysis=failure_analysis,
                agent_review=agent_review,
            )
            return {
                "symbol": sym,
                "lookback_days": lookback_days,
                "rows": [],
                "stats": {
                    "total_records": 0,
                    "evaluated_records": 0,
                    "mape": None,
                    "direction_accuracy": None,
                    "interval_hit_rate": None,
                    "d1_mape": None,
                    "d5_mape": None,
                    "d1_count": 0,
                    "d5_count": 0,
                },
                "summary": summary,
                "availability": availability,
                "quality": quality,
                "deviation_cases": [],
                "failure_analysis": failure_analysis,
                "agent_review": agent_review,
                "persistence": persistence,
                "diagnostics": {
                    "forecast_records": len(recent_forecasts),
                    "evaluation_records": 0,
                    "price_records": len(price_rows_empty),
                },
                "refresh": refresh_meta,
            }

        target_dates = {e.target_date for e in evals}
        min_date = min(min(e.prediction_date, e.target_date) for e in evals) - timedelta(days=10)
        max_date = max(e.target_date for e in evals)

        price_rows = list(session.execute(
            select(PriceDaily)
            .where(
                PriceDaily.symbol == sym,
                PriceDaily.trade_date >= min_date,
                PriceDaily.trade_date <= max_date,
            )
            .order_by(PriceDaily.trade_date.asc())
        ).scalars().all())
        trading_dates = [p.trade_date for p in price_rows]
        price_map = {p.trade_date: float(p.close) for p in price_rows if p.close is not None}

        forecast_rows = list(session.execute(
            select(Forecast)
            .where(
                Forecast.symbol == sym,
                Forecast.target_date.in_(target_dates),
                Forecast.run_at >= datetime.combine(min_date, datetime.min.time()),
            )
            .order_by(Forecast.run_at.desc())
        ).scalars().all())
        forecast_by_key: dict[tuple, Forecast] = {}
        forecast_by_date_target: dict[tuple, Forecast] = {}
        for fc in forecast_rows:
            pred_date = fc.run_at.date() if isinstance(fc.run_at, datetime) else fc.run_at
            key = (pred_date, fc.target_date, fc.model)
            forecast_by_key.setdefault(key, fc)
            forecast_by_date_target.setdefault((pred_date, fc.target_date), fc)
        for fc in recent_forecasts:
            pred_date = fc.run_at.date() if isinstance(fc.run_at, datetime) else fc.run_at
            forecast_by_key.setdefault((pred_date, fc.target_date, fc.model), fc)
            forecast_by_date_target.setdefault((pred_date, fc.target_date), fc)

        def trading_gap(prediction_date: date, target_date: date) -> int:
            dates = [d for d in trading_dates if prediction_date < d <= target_date]
            if dates:
                return len(dates)
            return max((target_date - prediction_date).days, 0)

        def attach_prefix(row: dict, prefix: str, pe: PredictionEvaluation, fc: Forecast | None) -> None:
            predicted = float(pe.predicted_price) if pe.predicted_price is not None else None
            actual = row.get("actual")
            lower = float(fc.yhat_lower) if fc is not None and fc.yhat_lower is not None else None
            upper = float(fc.yhat_upper) if fc is not None and fc.yhat_upper is not None else None
            error_pct = float(pe.error_pct) if pe.error_pct is not None else None
            signed_error_pct = None
            if predicted is not None and actual is not None and float(actual) > 0:
                signed_error_pct = (predicted - float(actual)) / float(actual) * 100.0
                if error_pct is None:
                    error_pct = abs(signed_error_pct)
            if predicted is None:
                status = "invalid_prediction_data"
            elif actual is None and pe.target_date > date.today():
                status = "pending_target_date"
            elif actual is None:
                status = "missing_actual_price"
            else:
                status = "evaluated"
            row[f"{prefix}_prediction_date"] = pe.prediction_date.isoformat()
            row[f"{prefix}_model"] = pe.model_name
            row[f"{prefix}_predicted"] = round(predicted, 2) if predicted is not None else None
            row[f"{prefix}_lower"] = round(lower, 2) if lower is not None else None
            row[f"{prefix}_upper"] = round(upper, 2) if upper is not None else None
            row[f"{prefix}_error_pct"] = round(error_pct, 2) if error_pct is not None else None
            row[f"{prefix}_signed_error_pct"] = round(signed_error_pct, 2) if signed_error_pct is not None else None
            row[f"{prefix}_direction_ok"] = _prediction_direction_color_value(pe.direction_correct)
            if actual is not None and lower is not None and upper is not None:
                row[f"{prefix}_interval_hit"] = lower <= float(actual) <= upper
            else:
                row[f"{prefix}_interval_hit"] = None
            row[f"{prefix}_status"] = status
            row[f"{prefix}_deviation_level"] = classify_deviation_level(
                error_pct,
                pe.direction_correct,
                row.get(f"{prefix}_interval_hit"),
            )

        rows_by_date: dict[date, dict] = {}
        stat_errors: list[float] = []
        stat_dir: list[bool] = []
        stat_interval: list[bool] = []
        d1_errors: list[float] = []
        d5_errors: list[float] = []

        for pe in evals:
            target_d = pe.target_date
            actual = pe.actual_price if pe.actual_price is not None else price_map.get(target_d)
            row = rows_by_date.setdefault(target_d, {
                "date": target_d.isoformat(),
                "actual": round(float(actual), 2) if actual is not None else None,
            })
            if row.get("actual") is None and actual is not None:
                row["actual"] = round(float(actual), 2)

            fc = forecast_by_key.get((pe.prediction_date, pe.target_date, pe.model_name)) \
                or forecast_by_date_target.get((pe.prediction_date, pe.target_date))
            gap = trading_gap(pe.prediction_date, pe.target_date)
            prefix = "d1" if gap == 1 else "d5" if gap == 5 else None
            if prefix is None:
                continue
            if row.get(f"{prefix}_predicted") is not None:
                continue
            attach_prefix(row, prefix, pe, fc)

            if pe.actual_price is not None and pe.error_pct is not None:
                stat_errors.append(float(pe.error_pct))
                if prefix == "d1":
                    d1_errors.append(float(pe.error_pct))
                elif prefix == "d5":
                    d5_errors.append(float(pe.error_pct))
            if pe.direction_correct is not None:
                stat_dir.append(bool(pe.direction_correct))
            hit_value = row.get(f"{prefix}_interval_hit")
            if hit_value is not None:
                stat_interval.append(bool(hit_value))

        chart_rows = [r for _, r in sorted(rows_by_date.items()) if r.get("d1_predicted") is not None or r.get("d5_predicted") is not None]
        evaluated_records = sum(1 for e in evals if e.actual_price is not None)
        stats = {
            "total_records": len(evals),
            "evaluated_records": evaluated_records,
            "mape": round(sum(stat_errors) / len(stat_errors), 2) if stat_errors else None,
            "direction_accuracy": round(sum(1 for ok in stat_dir if ok) / len(stat_dir) * 100, 1) if stat_dir else None,
            "interval_hit_rate": round(sum(1 for ok in stat_interval if ok) / len(stat_interval) * 100, 1) if stat_interval else None,
            "d1_mape": round(sum(d1_errors) / len(d1_errors), 2) if d1_errors else None,
            "d5_mape": round(sum(d5_errors) / len(d5_errors), 2) if d5_errors else None,
            "d1_count": sum(1 for r in chart_rows if r.get("d1_predicted") is not None),
            "d5_count": sum(1 for r in chart_rows if r.get("d5_predicted") is not None),
        }
        forecast_lookup = {**forecast_by_date_target, **forecast_by_key}
        summary = aggregate_stock_evaluation_summary(evals, forecast_lookup)
        availability = build_evaluation_availability(
            sym,
            evals,
            recent_forecasts,
            price_rows,
            latest_pipeline_run=latest_pipeline_run,
            supported_record_count=stats["d1_count"] + stats["d5_count"],
        )
        deviation_cases = build_deviation_cases(
            evals,
            forecast_lookup,
            limit=8,
            horizon_resolver=trading_gap,
        )
        quality = build_prediction_quality(sym, summary, availability, deviation_cases)
        failure_analysis = build_failure_analysis(sym, deviation_cases, quality=quality)
        try:
            feature_snapshot = load_stock_feature_snapshot(session, sym)
        except Exception:
            feature_snapshot = None
        agent_review = build_agent_review(sym, failure_analysis=failure_analysis, feature_snapshot=feature_snapshot)
        verification = build_agent_verification(agent_review, failure_analysis=failure_analysis, feature_snapshot=feature_snapshot)
        agent_review["verification_status"] = verification["verification_status"]
        agent_review["verification_checks"] = verification["checks"]
        agent_review["gate_result"] = verification["gate_result"]
        persistence = _persist_iteration_bundle_safe(
            session,
            symbol=sym,
            lookback_days=lookback_days,
            feature_snapshot=feature_snapshot,
            failure_analysis=failure_analysis,
            agent_review=agent_review,
        )
        return {
            "symbol": sym,
            "lookback_days": lookback_days,
            "rows": chart_rows,
            "stats": stats,
            "summary": summary,
            "availability": availability,
            "quality": quality,
            "deviation_cases": deviation_cases,
            "failure_analysis": failure_analysis,
            "agent_review": agent_review,
            "persistence": persistence,
            "diagnostics": {
                "forecast_records": len(recent_forecasts),
                "evaluation_records": len(evals),
                "chart_records": len(chart_rows),
                "price_records": len(price_rows),
                "supported_records": stats["d1_count"] + stats["d5_count"],
            },
            "refresh": refresh_meta,
        }


@app.get("/api/stocks/{symbol}/prediction-quality")
def stock_prediction_quality(
    symbol: str,
    lookback_days: int = Query(60, ge=5, le=365, description="回看自然日窗口"),
    refresh: bool = Query(True, description="是否先同步 forecasts 并回填 actuals"),
):
    """返回单只股票预测质量摘要，供交易辅助和模型复盘使用。"""
    history = prediction_history(symbol=symbol, lookback_days=lookback_days, refresh=refresh)
    quality = history.get("quality") or {}
    quality["lookback_days"] = lookback_days
    quality["availability"] = history.get("availability")
    quality["summary"] = history.get("summary")
    quality["diagnostics"] = history.get("diagnostics")
    return quality


@app.get("/api/stocks/{symbol}/failure-analysis")
def stock_failure_analysis(
    symbol: str,
    lookback_days: int = Query(60, ge=5, le=365, description="回看自然日窗口"),
    refresh: bool = Query(True, description="是否先同步 forecasts 并回填 actuals"),
):
    """返回单只股票预测失败归因；只生成复盘建议，不自动修改模型。"""
    history = prediction_history(symbol=symbol, lookback_days=lookback_days, refresh=refresh)
    analysis = history.get("failure_analysis") or {}
    try:
        from .prediction.services.failure_analysis_service import build_failure_analysis
        from .prediction.services.feature_snapshot_service import load_stock_feature_snapshot

        with SessionLocal() as session:
            feature_snapshot = load_stock_feature_snapshot(session, symbol.upper())
        analysis = build_failure_analysis(
            symbol.upper(),
            history.get("deviation_cases") or [],
            quality=history.get("quality") or {},
            feature_snapshot=feature_snapshot,
        )
        analysis["feature_snapshot"] = feature_snapshot
    except Exception as exc:
        logger.debug("failure analysis feature snapshot unavailable for %s: %s", symbol, exc)
    analysis["lookback_days"] = lookback_days
    analysis["availability"] = history.get("availability")
    return analysis


@app.get("/api/stocks/{symbol}/agent-review")
def stock_agent_review(
    symbol: str,
    lookback_days: int = Query(60, ge=5, le=365, description="回看自然日窗口"),
    refresh: bool = Query(True, description="是否先同步 forecasts 并回填 actuals"),
):
    """返回 Agent 复盘受控迭代建议；不会自动修改模型、阈值或交易动作。"""
    history = prediction_history(symbol=symbol, lookback_days=lookback_days, refresh=refresh)
    failure_analysis = history.get("failure_analysis") or {}
    feature_snapshot = None
    try:
        from .prediction.services.feature_snapshot_service import load_stock_feature_snapshot

        with SessionLocal() as session:
            feature_snapshot = load_stock_feature_snapshot(session, symbol.upper())
    except Exception as exc:
        logger.debug("agent review feature snapshot unavailable for %s: %s", symbol, exc)
    from .prediction.services.agent_review_service import build_agent_review
    from .prediction.services.agent_verification_service import build_agent_verification

    review = build_agent_review(symbol.upper(), failure_analysis=failure_analysis, feature_snapshot=feature_snapshot)
    verification = build_agent_verification(review, failure_analysis=failure_analysis, feature_snapshot=feature_snapshot)
    review["verification_status"] = verification["verification_status"]
    review["verification_checks"] = verification["checks"]
    review["gate_result"] = verification["gate_result"]
    review["lookback_days"] = lookback_days
    review["availability"] = history.get("availability")
    try:
        with SessionLocal() as session:
            review["persistence"] = _persist_iteration_bundle_safe(
                session,
                symbol=symbol.upper(),
                lookback_days=lookback_days,
                feature_snapshot=feature_snapshot,
                failure_analysis=failure_analysis,
                agent_review=review,
            )
    except Exception as exc:
        logger.debug("agent review persistence unavailable for %s: %s", symbol, exc)
        review["persistence"] = {"status": "failed", "reason": str(exc)[:200]}
    return review


@app.get("/api/forecast/review")
def forecast_review(
    symbol: str = Query(None, description="股票代码，为空则返回所有置顶股票"),
    limit: int = Query(30, ge=1, le=200, description="每只股票最多返回条数"),
):
    """
    将已过期的预测记录与实际收盘价比对，计算 MAPE 等误差指标。
    """
    from datetime import date as _date
    today = _date.today()
    with SessionLocal() as session:
        # 确定要查询的 symbol 列表
        if symbol:
            syms = [symbol.upper()]
        else:
            # 置顶股票（从统一股票池 + watchlist pin 状态）
            rows = session.execute(text("""
                SELECT spm.symbol FROM stock_pool_members spm
                INNER JOIN watchlist w ON spm.symbol = w.symbol AND w.pinned = true
                WHERE spm.exit_date IS NULL
            """)).fetchall()
            syms = [r.symbol for r in rows] if rows else []
        if not syms:
            return {"items": [], "summary": None}

        items_out = []
        for sym in syms:
            sql = text("""
                SELECT f.target_date, f.model, f.run_at,
                       f.yhat, f.yhat_lower, f.yhat_upper,
                       p.close AS actual_close
                FROM forecasts f
                LEFT JOIN prices_daily p ON f.symbol = p.symbol AND f.target_date = p.trade_date
                WHERE f.symbol = :sym AND f.target_date <= :today
                ORDER BY f.target_date DESC, f.run_at DESC
                LIMIT :lim
            """)
            rows = session.execute(sql, {"sym": sym, "today": today, "lim": limit}).mappings().all()
            if not rows:
                continue

            # 按 target_date 去重（取最新 run_at 的那条）
            seen_dates: dict = {}
            for r in rows:
                td = str(r["target_date"])
                if td not in seen_dates:
                    seen_dates[td] = r

            records = []
            total_err = 0.0
            matched = 0
            direction_hit = 0
            direction_total = 0
            prev_actual = None

            # 按日期升序处理
            for td in sorted(seen_dates.keys()):
                r = seen_dates[td]
                yhat = float(r["yhat"]) if r["yhat"] is not None else None
                actual = float(r["actual_close"]) if r["actual_close"] is not None else None
                err_pct = None
                direction_ok = None

                if yhat is not None and actual is not None and actual > 0:
                    err_pct = round(abs(yhat - actual) / actual * 100, 2)
                    total_err += err_pct
                    matched += 1

                    # 方向准确性：预测涨跌方向是否与实际一致
                    if prev_actual is not None:
                        pred_dir = 1 if yhat >= prev_actual else -1
                        actual_dir = 1 if actual >= prev_actual else -1
                        direction_ok = pred_dir == actual_dir
                        direction_total += 1
                        if direction_ok:
                            direction_hit += 1

                if actual is not None:
                    prev_actual = actual

                records.append({
                    "date": str(r["target_date"]),
                    "model": r["model"],
                    "predicted": round(yhat, 2) if yhat is not None else None,
                    "lower": round(float(r["yhat_lower"]), 2) if r["yhat_lower"] is not None else None,
                    "upper": round(float(r["yhat_upper"]), 2) if r["yhat_upper"] is not None else None,
                    "actual": round(actual, 2) if actual is not None else None,
                    "error_pct": err_pct,
                    "direction_ok": direction_ok,
                })

            # 获取股票名称
            w = session.execute(
                select(Watchlist.name).where(Watchlist.symbol == sym)
            ).scalar_one_or_none()

            avg_mape = round(total_err / matched, 2) if matched > 0 else None
            dir_accuracy = round(direction_hit / direction_total * 100, 1) if direction_total > 0 else None

            items_out.append({
                "symbol": sym,
                "name": w or sym,
                "records": records,
                "stats": {
                    "total_forecasts": len(records),
                    "matched": matched,
                    "unmatched": len(records) - matched,
                    "avg_mape": avg_mape,
                    "direction_accuracy": dir_accuracy,
                    "direction_total": direction_total,
                },
            })

        return {"items": items_out}


@app.get("/api/models/lifecycle")
def model_lifecycle(
    symbol: str | None = Query(None, description="股票代码；不传则返回全局最近事件"),
    limit: int = Query(20, ge=1, le=100, description="最多返回事件数"),
):
    """返回模型生命周期事件，用于解释重训触发、模型切换和停滞。"""
    import json as _json

    sym = symbol.upper() if symbol else None
    with SessionLocal() as session:
        query = select(ModelLifecycleEvent).order_by(ModelLifecycleEvent.created_at.desc()).limit(limit)
        if sym:
            query = query.where(ModelLifecycleEvent.symbol == sym)
        rows = session.execute(
            query
        ).scalars().all()

        items = []
        latest_by_type = {}
        for event in rows:
            details = None
            if event.details_json:
                try:
                    details = _json.loads(event.details_json)
                except Exception:
                    details = {"raw": event.details_json}
            item = {
                "id": event.id,
                "symbol": event.symbol,
                "event_type": event.event_type,
                "trigger_reason": event.trigger_reason,
                "model_name": event.model_name,
                "score_before": event.score_before,
                "score_after": event.score_after,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "details": details,
            }
            items.append(item)
            latest_by_type.setdefault(event.event_type, item)

        last_event = items[0] if items else None
        last_completed = latest_by_type.get("retrain_completed")
        last_triggered = latest_by_type.get("retrain_triggered") or latest_by_type.get("failure_detected")
        last_stagnated = latest_by_type.get("retrain_stagnated")

        active_status = "unknown"
        active_reason = "暂无生命周期记录"
        if last_stagnated and (not last_completed or last_stagnated["created_at"] >= last_completed["created_at"]):
            active_status = "stagnated"
            active_reason = "连续再训练未达到切换阈值"
        elif last_completed:
            details = last_completed.get("details") or {}
            improved = details.get("improved")
            activated = details.get("activated")
            active_status = "optimized" if activated or improved else "retained"
            active_reason = "新模型已激活" if active_status == "optimized" else "新模型未达阈值，保留旧模型"
        elif last_triggered:
            active_status = "needs_retrain"
            active_reason = last_triggered.get("trigger_reason") or "监控触发再训练"

        return {
            "symbol": sym,
            "count": len(items),
            "summary": {
                "latest_event_type": last_event.get("event_type") if last_event else None,
                "latest_event_at": last_event.get("created_at") if last_event else None,
                "latest_retrain_at": last_completed.get("created_at") if last_completed else None,
                "latest_trigger_at": last_triggered.get("created_at") if last_triggered else None,
                "latest_stagnation_at": last_stagnated.get("created_at") if last_stagnated else None,
                "active_status": active_status,
                "active_reason": active_reason,
            },
            "items": items,
        }


@app.get("/api/stocks/{symbol}/iteration-records")
def stock_iteration_records(
    symbol: str,
    limit: int = Query(10, ge=1, le=50, description="每类记录最多返回条数"),
):
    """返回已持久化的特征快照、失败归因和 Agent 复盘记录，用于回放查询。"""
    from sqlalchemy import inspect as _inspect
    from .core.models import AgentReviewRun, AgentVerificationCheck, FailureAnalysisRecord, FeatureSnapshot
    from .prediction.services.agent_iteration_persistence_service import (
        serialize_agent_review,
        serialize_failure_analysis,
        serialize_feature_snapshot,
    )

    sym = symbol.upper()
    with SessionLocal() as session:
        inspector = _inspect(session.get_bind())
        missing = [
            table for table in ["feature_snapshots", "failure_analyses", "agent_review_runs", "agent_verification_checks"]
            if not inspector.has_table(table)
        ]
        if missing:
            return {
                "symbol": sym,
                "persistence_status": "migration_not_applied",
                "missing_tables": missing,
                "feature_snapshots": [],
                "failure_analyses": [],
                "agent_reviews": [],
            }

        snapshots = list(session.execute(
            select(FeatureSnapshot)
            .where(FeatureSnapshot.symbol == sym)
            .order_by(FeatureSnapshot.created_at.desc())
            .limit(limit)
        ).scalars().all())
        failures = list(session.execute(
            select(FailureAnalysisRecord)
            .where(FailureAnalysisRecord.symbol == sym)
            .order_by(FailureAnalysisRecord.created_at.desc())
            .limit(limit)
        ).scalars().all())
        reviews = list(session.execute(
            select(AgentReviewRun)
            .where(AgentReviewRun.symbol == sym)
            .order_by(AgentReviewRun.created_at.desc())
            .limit(limit)
        ).scalars().all())
        review_ids = [item.review_id for item in reviews]
        checks_by_review: dict[str, list] = {review_id: [] for review_id in review_ids}
        if review_ids:
            checks = list(session.execute(
                select(AgentVerificationCheck)
                .where(AgentVerificationCheck.review_id.in_(review_ids))
                .order_by(AgentVerificationCheck.created_at.asc())
            ).scalars().all())
            for check in checks:
                checks_by_review.setdefault(check.review_id, []).append(check)

        return {
            "symbol": sym,
            "persistence_status": "ready",
            "feature_snapshots": [serialize_feature_snapshot(item) for item in snapshots],
            "failure_analyses": [serialize_failure_analysis(item) for item in failures],
            "agent_reviews": [serialize_agent_review(item, checks_by_review.get(item.review_id, [])) for item in reviews],
        }


@app.get("/api/feature-snapshots/{snapshot_id}")
def feature_snapshot_replay(snapshot_id: str):
    """按 snapshot_id 回放单个特征快照。"""
    from sqlalchemy import inspect as _inspect
    from .core.models import FeatureSnapshot
    from .prediction.services.agent_iteration_persistence_service import serialize_feature_snapshot

    with SessionLocal() as session:
        if not _inspect(session.get_bind()).has_table("feature_snapshots"):
            raise HTTPException(status_code=404, detail="feature_snapshots migration not applied")
        record = session.execute(
            select(FeatureSnapshot).where(FeatureSnapshot.snapshot_id == snapshot_id)
        ).scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="feature snapshot not found")
        return serialize_feature_snapshot(record)


@app.get("/api/agent/reviews/{review_id}")
def agent_review_replay(review_id: str):
    """按 review_id 回放单个 Agent 复盘与自动核实记录。"""
    from sqlalchemy import inspect as _inspect
    from .core.models import AgentReviewRun, AgentVerificationCheck
    from .prediction.services.agent_iteration_persistence_service import serialize_agent_review

    with SessionLocal() as session:
        inspector = _inspect(session.get_bind())
        if not inspector.has_table("agent_review_runs"):
            raise HTTPException(status_code=404, detail="agent_review_runs migration not applied")
        record = session.execute(
            select(AgentReviewRun).where(AgentReviewRun.review_id == review_id)
        ).scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="agent review not found")
        checks = []
        if inspector.has_table("agent_verification_checks"):
            checks = list(session.execute(
                select(AgentVerificationCheck)
                .where(AgentVerificationCheck.review_id == review_id)
                .order_by(AgentVerificationCheck.created_at.asc())
            ).scalars().all())
        return serialize_agent_review(record, checks)


@app.get("/api/models/{symbol}/strategy-backtest")
def model_strategy_backtest(
    symbol: str,
    lookback_days: int = Query(120, ge=20, le=365, description="回放窗口"),
    buy_threshold_pct: float = Query(0.3, ge=-5, le=10, description="预测收益触发买入阈值"),
    position_pct: float = Query(0.2, ge=0.01, le=1.0, description="单次虚拟仓位比例"),
):
    """运行预测信号的保守多头回放，并输出 promotion gate。"""
    from .prediction.services.promotion_gate_service import build_prediction_replay_backtest

    with SessionLocal() as session:
        return build_prediction_replay_backtest(
            session,
            symbol.upper(),
            lookback_days=lookback_days,
            buy_threshold_pct=buy_threshold_pct,
            position_pct=position_pct,
        )


@app.get("/api/models/{symbol}/promotion-gate")
def model_promotion_gate(
    symbol: str,
    lookback_days: int = Query(120, ge=20, le=365, description="回放窗口"),
):
    """返回模型候选晋级门禁，不会自动上线模型。"""
    with SessionLocal() as session:
        from .prediction.services.promotion_gate_service import build_prediction_replay_backtest

        replay = build_prediction_replay_backtest(session, symbol.upper(), lookback_days=lookback_days)
        return {
            "symbol": symbol.upper(),
            "lookback_days": lookback_days,
            "metrics": replay.get("metrics"),
            "gate_result": replay.get("gate_result"),
            "latest_agent_gate": replay.get("latest_agent_gate"),
            "disclaimer": replay.get("disclaimer"),
        }


@app.get("/api/models/center")
def model_center(
    symbol: str | None = Query(None, description="可选股票代码"),
    limit: int = Query(20, ge=1, le=100, description="最近记录数量"),
):
    """模型中心聚合视图：模型、生命周期、复盘记录、门禁和迁移状态。"""
    from sqlalchemy import inspect as _inspect
    from .core.models import AgentReviewRun, FailureAnalysisRecord, FeatureSnapshot, ModelRegistry

    sym = symbol.upper() if symbol else None
    with SessionLocal() as session:
        inspector = _inspect(session.get_bind())
        tables = set(inspector.get_table_names())
        migration_rows = []
        if "schema_migrations" in tables:
            migration_rows = [row[0] for row in session.execute(text("SELECT version FROM schema_migrations ORDER BY version ASC")).fetchall()]

        lifecycle_query = select(ModelLifecycleEvent).order_by(ModelLifecycleEvent.created_at.desc()).limit(limit)
        if sym:
            lifecycle_query = lifecycle_query.where(ModelLifecycleEvent.symbol == sym)
        lifecycle_events = list(session.execute(lifecycle_query).scalars().all())

        registry_items = []
        if "model_registry" in tables:
            registry_query = select(ModelRegistry).order_by(ModelRegistry.created_at.desc()).limit(limit)
            if sym:
                registry_query = registry_query.where(ModelRegistry.model_name.ilike(f"%{sym}%"))
            registry_items = list(session.execute(registry_query).scalars().all())

        qe_models = []
        if "qe_stock_models" in tables:
            try:
                from .quant_engine.models import QEStockModel

                qe_query = select(QEStockModel).order_by(QEStockModel.updated_at.desc().nullslast(), QEStockModel.created_at.desc()).limit(limit)
                if sym:
                    qe_query = qe_query.where(QEStockModel.symbol == sym)
                qe_models = list(session.execute(qe_query).scalars().all())
            except Exception as exc:
                logger.debug("qe model center aggregation skipped: %s", exc)

        recent_reviews = []
        if "agent_review_runs" in tables:
            review_query = select(AgentReviewRun).order_by(AgentReviewRun.created_at.desc()).limit(limit)
            if sym:
                review_query = review_query.where(AgentReviewRun.symbol == sym)
            recent_reviews = list(session.execute(review_query).scalars().all())

        recent_failures = []
        if "failure_analyses" in tables:
            failure_query = select(FailureAnalysisRecord).order_by(FailureAnalysisRecord.created_at.desc()).limit(limit)
            if sym:
                failure_query = failure_query.where(FailureAnalysisRecord.symbol == sym)
            recent_failures = list(session.execute(failure_query).scalars().all())

        snapshot_count = 0
        if "feature_snapshots" in tables:
            count_query = select(func.count()).select_from(FeatureSnapshot)
            if sym:
                count_query = count_query.where(FeatureSnapshot.symbol == sym)
            snapshot_count = int(session.execute(count_query).scalar() or 0)

        symbols = OrderedDict()
        for item in qe_models:
            symbols.setdefault(item.symbol, {"symbol": item.symbol})
        for item in recent_reviews:
            symbols.setdefault(item.symbol, {"symbol": item.symbol})
        for item in recent_failures:
            symbols.setdefault(item.symbol, {"symbol": item.symbol})
        if sym:
            symbols.setdefault(sym, {"symbol": sym})

        latest_review_by_symbol = {}
        for review in recent_reviews:
            latest_review_by_symbol.setdefault(review.symbol, review)
        latest_failure_by_symbol = {}
        for failure in recent_failures:
            latest_failure_by_symbol.setdefault(failure.symbol, failure)
        model_by_symbol = {}
        for model in qe_models:
            model_by_symbol.setdefault(model.symbol, model)

        items = []
        for item_symbol in list(symbols.keys())[:limit]:
            review = latest_review_by_symbol.get(item_symbol)
            failure = latest_failure_by_symbol.get(item_symbol)
            model = model_by_symbol.get(item_symbol)
            gate = review.gate_result if review else None
            items.append({
                "symbol": item_symbol,
                "model_status": model.status if model else "unknown",
                "task": model.task if model else None,
                "algo": model.algo if model else None,
                "active_version": model.active_version if model else None,
                "review_status": review.status if review else None,
                "verification_status": review.verification_status if review else None,
                "gate_status": (gate or {}).get("status") if gate else None,
                "failure_severity": failure.severity if failure else None,
                "high_deviation_count": failure.high_deviation_count if failure else 0,
                "updated_at": review.created_at.isoformat() if review and review.created_at else None,
            })

        return {
            "symbol": sym,
            "migration_status": {
                "schema_table": "schema_migrations" in tables,
                "applied_versions": migration_rows,
                "agent_iteration_ready": all(table in tables for table in ["feature_snapshots", "failure_analyses", "agent_review_runs", "agent_verification_checks"]),
            },
            "summary": {
                "qe_model_count": len(qe_models),
                "registry_model_count": len(registry_items),
                "recent_lifecycle_count": len(lifecycle_events),
                "recent_review_count": len(recent_reviews),
                "recent_failure_count": len(recent_failures),
                "feature_snapshot_count": snapshot_count,
            },
            "items": items,
            "recent_lifecycle_events": [
                {
                    "id": event.id,
                    "symbol": event.symbol,
                    "event_type": event.event_type,
                    "trigger_reason": event.trigger_reason,
                    "model_name": event.model_name,
                    "score_before": event.score_before,
                    "score_after": event.score_after,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
                for event in lifecycle_events
            ],
            "recent_agent_reviews": [
                {
                    "review_id": review.review_id,
                    "symbol": review.symbol,
                    "status": review.status,
                    "priority": review.priority,
                    "verification_status": review.verification_status,
                    "gate_status": (review.gate_result or {}).get("status") if review.gate_result else None,
                    "created_at": review.created_at.isoformat() if review.created_at else None,
                }
                for review in recent_reviews
            ],
            "disclaimer": "模型中心仅用于模型复盘、自动核实和门禁观察，不构成投资建议，也不会自动上线模型或执行交易。",
        }

@app.get("/api/report/{symbol}/full")
async def get_full_report(
    symbol: str,
    timeRange: str = Query('5d', description="时间区间: 5d, 1m, 3m, 6m, 1y, all"),
    showDiagnostics: bool = Query(False, description="返回诊断信息"),
    allowStale: bool = Query(True, description="若窗口内无数据，允许返回更旧的最近数据")
):
    """
    获取完整的股票报告，包含历史价格走势和预测数据
    支持不同时间区间：5d, 1m, 3m, 6m, 1y, all
    """
    import time as _time_mod
    from .tasks.pipeline_recorder import persist_pipeline_run as _persist_pipeline_run

    _full_started = _time_mod.monotonic()
    _full_status = "success"
    _full_message: str | None = None
    _full_error: str | None = None

    with SessionLocal() as session:
        sym = symbol.upper()
        
        try:
            # 获取最新报告
            report = session.execute(
                select(Report).where(
                    and_(Report.symbol == sym, Report.is_latest == True)
                ).order_by(Report.created_at.desc())
            ).scalar_one_or_none()
            
            # 根据时间区间获取历史价格数据
            if timeRange == 'all':
                # 获取所有可用数据
                historical_prices = session.execute(
                    text(
                        "SELECT trade_date, open, high, low, close, vol, pct_chg "
                        "FROM prices_daily WHERE symbol=:sym "
                        "ORDER BY trade_date DESC"
                    ),
                    {"sym": sym}
                ).mappings().all()
            else:
                # 根据时间区间过滤数据
                if timeRange == '5d':
                    days_back = 7  # 多取几天以确保有5个工作日
                elif timeRange == '1m':
                    days_back = 35  # 一个月加几天buffer
                elif timeRange == '3m':
                    days_back = 95  # 三个月加几天buffer
                elif timeRange == '6m':
                    days_back = 185  # 六个月加几天buffer
                elif timeRange == '1y':
                    days_back = 370  # 一年加几天buffer
                
                historical_prices = session.execute(
                    text(
                        "SELECT trade_date, open, high, low, close, vol, pct_chg "
                        "FROM prices_daily WHERE symbol=:sym "
                        "AND trade_date >= CURRENT_DATE - INTERVAL '{} days' "
                        "ORDER BY trade_date DESC".format(days_back)
                    ),
                    {"sym": sym}
                ).mappings().all()
            
            diagnostics: dict | None = {"time_range": timeRange} if showDiagnostics else None
            # On-demand fetch if empty OR stale (latest price older than the last
            # trading day on or before today — uses unified trading calendar so it
            # correctly handles weekends and registered holidays).
            need_fetch = not historical_prices
            if historical_prices and not need_fetch:
                from datetime import date as _date_cls
                _latest_date = historical_prices[0]["trade_date"]  # DESC order, first = newest
                _today = _date_cls.today()
                _last_trading = _calendar_last_trading_day_on_or_before(_today)
                if _latest_date < _last_trading:
                    need_fetch = True
                    if diagnostics is not None:
                        diagnostics["stale_gap_days"] = (_today - _latest_date).days
                        diagnostics["last_trading_day"] = _last_trading.isoformat()
                        diagnostics["latest_in_db"] = _latest_date.isoformat()
            if need_fetch:
                if diagnostics is not None:
                    diagnostics.update({"pre_fetch_rows": len(historical_prices) if historical_prices else 0})
                try:
                    import pandas as _pd
                    from datetime import date as _date_cls2, timedelta as _td
                    import asyncio as _aio
                    # 计算 start_date：若 DB 有数据则从最新日期往前推7天开始；否则取最近180天
                    if historical_prices:
                        _sd = historical_prices[0]["trade_date"] - _td(days=7)
                    else:
                        _sd = _date_cls2.today() - _td(days=180)
                    _start_str = _sd.strftime("%Y%m%d")
                    _base_sym = sym.replace(".SH", "").replace(".SZ", "")
                    # 优先走 data/data_source.fetch_daily（统一入口，遵守 DATA_SOURCE 开关），
                    # 失败或空结果时回退到腾讯源子进程（proxy/eastmoney 不可达时的最后一根稻草）。
                    df = _pd.DataFrame()
                    try:
                        df_direct = await _aio.to_thread(fetch_daily, sym, _start_str)
                        if df_direct is not None and not df_direct.empty:
                            df_direct = df_direct.copy()
                            if "trade_date" in df_direct.columns:
                                df_direct["trade_date"] = _pd.to_datetime(df_direct["trade_date"], errors="coerce").dt.date
                            if "symbol" not in df_direct.columns:
                                df_direct["symbol"] = sym
                            _keep = ["symbol","trade_date","open","high","low","close","pct_chg","vol","amount"]
                            for _c in _keep:
                                if _c not in df_direct.columns:
                                    df_direct[_c] = None
                            df = df_direct[_keep].dropna(subset=["close"])
                            if diagnostics is not None:
                                diagnostics["external_fetch_rows_primary"] = int(len(df))
                                diagnostics["external_fetch_source"] = "data_source.fetch_daily"
                    except Exception as _e_primary:
                        if diagnostics is not None:
                            diagnostics["primary_fetch_error"] = str(_e_primary)[:200]
                        logger.warning("primary fetch_daily failed for %s: %s", sym, _e_primary)

                    # 腾讯源子进程仅作为主通道失败时的回退
                    # 使用 stock_zh_a_hist_tx（腾讯数据源）替代 stock_zh_a_hist（eastmoney），
                    # 因 push2his.eastmoney.com 在部分网络环境下不可达
                    _tx_prefix = "sh" if sym.endswith(".SH") else "sz"
                    _tx_symbol = f"{_tx_prefix}{_base_sym}"
                    _fetch_script = (
                        "import os\n"
                        "for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy','ALL_PROXY','all_proxy','NO_PROXY','no_proxy']:\n"
                        "    os.environ.pop(k,None)\n"
                        "import requests\n"
                        "_orig_get=requests.get\n"
                        "def _noproxy_get(*a,**kw):\n"
                        "    kw['proxies']={'http':None,'https':None}\n"
                        "    s=requests.Session()\n"
                        "    s.trust_env=False\n"
                        "    return s.get(*a,**kw)\n"
                        "requests.get=_noproxy_get\n"
                        f"import akshare,json,sys\n"
                        f"df=akshare.stock_zh_a_hist_tx(symbol='{_tx_symbol}',start_date='{_start_str}')\n"
                        f"if df is not None and not df.empty:\n"
                        f"    df.columns=[str(c).strip() for c in df.columns]\n"
                        f"    if 'date' in df.columns:\n"
                        f"        df['date']=df['date'].astype(str)\n"
                        f"    print(df.to_json(orient='records',force_ascii=False))\n"
                        f"else:\n"
                        f"    print('[]')\n"
                    )
                    _primary_ok = df is not None and not df.empty
                    _proc_rc: int | None = None
                    _stdout = b""
                    _stderr = b""
                    if not _primary_ok:
                        # 改用阻塞式 subprocess.run 放到线程池执行。
                        # 原因：Windows 下 uvicorn 默认 SelectorEventLoop 不支持
                        # asyncio.create_subprocess_exec，会抛 NotImplementedError；
                        # 使用 subprocess.run + asyncio.to_thread 兼容所有平台。
                        import subprocess as _sp
                        def _run_fallback() -> tuple[int, bytes, bytes]:
                            try:
                                cp = _sp.run(
                                    [sys.executable, "-c", _fetch_script],
                                    capture_output=True,
                                    timeout=45,
                                    check=False,
                                )
                                return cp.returncode, cp.stdout or b"", cp.stderr or b""
                            except _sp.TimeoutExpired:
                                return -1, b"", b"fallback subprocess timed out"
                            except Exception as _e_sub:  # noqa: BLE001
                                return -2, b"", f"fallback launch error: {_e_sub}".encode("utf-8", "replace")
                        _proc_rc, _stdout, _stderr = await _aio.to_thread(_run_fallback)
                        df = _pd.DataFrame()
                    if not _primary_ok and _proc_rc == 0 and _stdout:
                        _out_str = _stdout.decode("utf-8", errors="replace").strip()
                        try:
                            _rows_raw = json.loads(_out_str)
                            if _rows_raw:
                                df = _pd.DataFrame(_rows_raw)
                                # 腾讯源列名: date, open, close, high, low, amount（无 vol、无 pct_chg）
                                # eastmoney 列名(中文): 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 涨跌幅
                                _rn = {"日期":"trade_date","开盘":"open","收盘":"close","最高":"high","最低":"low","成交量":"vol","成交额":"amount","涨跌幅":"pct_chg",
                                       "date":"trade_date"}
                                df = df.rename(columns=_rn)
                                if "trade_date" in df.columns:
                                    df["trade_date"] = _pd.to_datetime(df["trade_date"], errors="coerce").dt.date
                                if "vol" in df.columns:
                                    df["vol"] = _pd.to_numeric(df["vol"], errors="coerce").astype("Int64")
                                else:
                                    df["vol"] = None
                                for _c in ["open","high","low","close","amount"]:
                                    if _c in df.columns:
                                        df[_c] = _pd.to_numeric(df[_c], errors="coerce")
                                    else:
                                        df[_c] = None
                                # 推算 pct_chg（若源数据不含）
                                if "pct_chg" not in df.columns or df["pct_chg"].isna().all():
                                    df = df.sort_values("trade_date").reset_index(drop=True)
                                    df["pct_chg"] = df["close"].pct_change() * 100.0
                                else:
                                    df["pct_chg"] = _pd.to_numeric(df["pct_chg"], errors="coerce")
                                df["symbol"] = sym
                                df = df[["symbol","trade_date","open","high","low","close","pct_chg","vol","amount"]].dropna(subset=["close"])
                        except Exception as _je:
                            logger.warning("on-demand fetch JSON parse error for %s: %s", sym, _je)
                    elif not _primary_ok and _proc_rc is not None:
                        _stderr_msg = (_stderr.decode("utf-8", errors="replace") if _stderr else "")[:200]
                        logger.warning("on-demand fetch subprocess failed for %s (rc=%s): %s", sym, _proc_rc, _stderr_msg)
                    if diagnostics is not None:
                        diagnostics["external_fetch_rows"] = int(len(df)) if df is not None and not df.empty else 0
                        diagnostics["fetch_start_date"] = _start_str
                    if df is not None and not df.empty:
                        df = df.sort_values('trade_date').tail(180)
                        existing_dates = set(r[0] for r in session.execute(
                            text("SELECT trade_date FROM prices_daily WHERE symbol=:sym AND trade_date >= :start"),
                            {"sym": sym, "start": df['trade_date'].min()}
                        ).fetchall())
                        to_insert = [
                            {
                                'symbol': sym,
                                'trade_date': r.trade_date,
                                'open': r.open,
                                'high': r.high,
                                'low': r.low,
                                'close': r.close,
                                'pct_chg': r.pct_chg,
                                'vol': int(r.vol) if _pd.notna(r.vol) else None,
                                'amount': r.amount
                            }
                            for r in df.itertuples() if r.trade_date not in existing_dates
                        ]
                        if to_insert:
                            session.execute(text(
                                "INSERT INTO prices_daily (symbol, trade_date, open, high, low, close, pct_chg, vol, amount) VALUES (:symbol, :trade_date, :open, :high, :low, :close, :pct_chg, :vol, :amount)"
                            ), to_insert)
                            session.commit()
                            logger.info("on-demand fetch: inserted %d new price rows for %s", len(to_insert), sym)
                        if diagnostics is not None:
                            diagnostics["inserted_rows"] = len(to_insert)
                        _persist_pipeline_run(
                            symbol=sym,
                            run_type="fetch_daily",
                            status="success",
                            trigger="on_demand_full",
                            message=f"inserted_rows={len(to_insert)} fetched_rows={len(df)}",
                        )
                        # re-query
                        if timeRange == 'all':
                            historical_prices = session.execute(text(
                                "SELECT trade_date, open, high, low, close, vol, pct_chg FROM prices_daily WHERE symbol=:sym ORDER BY trade_date DESC"
                            ), {"sym": sym}).mappings().all()
                        else:
                            historical_prices = session.execute(text(
                                "SELECT trade_date, open, high, low, close, vol, pct_chg FROM prices_daily WHERE symbol=:sym AND trade_date >= CURRENT_DATE - INTERVAL '{} days' ORDER BY trade_date DESC".format(days_back)
                            ), {"sym": sym}).mappings().all()
                except Exception as _e_fd:
                    session.rollback()  # 防止 InFailedSqlTransaction 级联
                    if diagnostics is not None:
                        diagnostics["fetch_error"] = str(_e_fd)
                    # 回退抓取异常一律降噪：不打印 traceback，避免噪声淹没真实 500。
                    # 该分支本身已被 try/except 吞掉，不影响 /full 正常返回。
                    logger.warning("on-demand price fetch fallback skipped for %s: %s", sym, _e_fd)
                    _persist_pipeline_run(
                        symbol=sym,
                        run_type="fetch_daily",
                        status="failed",
                        trigger="on_demand_full",
                        error_message=str(_e_fd),
                        message="on-demand fetch failed",
                    )
            # Stale fallback: if still empty but allowStale, try latest older rows
            stale_used = False
            if not historical_prices and allowStale:
                older = session.execute(text(
                    "SELECT trade_date, open, high, low, close, vol, pct_chg FROM prices_daily WHERE symbol=:sym ORDER BY trade_date DESC LIMIT 30"
                ), {"sym": sym}).mappings().all()
                if older:
                    historical_prices = older
                    stale_used = True
            if diagnostics is not None:
                diagnostics["final_row_count"] = len(historical_prices) if historical_prices else 0
                diagnostics["stale_used"] = stale_used
            if not historical_prices:
                out_diag = diagnostics if diagnostics is not None else None
                base = {
                    "symbol": sym,
                    "price_data": [],
                    "predictions": [],
                    "dates": [],
                    "predictions_mean": [],
                    "predictions_upper": [],
                    "predictions_lower": [],
                    "latest_price": None,
                    "latest": None,
                    "data_updated": None,
                    "analysis_summary": f"No price data available for {sym}",
                }
                if out_diag is not None:
                    base["diagnostics"] = out_diag | {"reason": "no_price_data"}
                return base
            
            # 转换历史价格数据
            price_data = []
            for i, price in enumerate(reversed(historical_prices)):
                price_data.append({
                    "date": price["trade_date"].isoformat(),
                    "open": float(price["open"]) if price["open"] else None,
                    "high": float(price["high"]) if price["high"] else None,
                    "low": float(price["low"]) if price["low"] else None,
                    "close": float(price["close"]) if price["close"] else None,
                    "volume": int(price["vol"]) if price["vol"] else 0,
                    "pct_change": float(price["pct_chg"]) if price["pct_chg"] else 0,
                    "pct_chg": float(price["pct_chg"]) if price["pct_chg"] else 0,  # 前端兼容
                    "type": "historical"
                })
            
            # 获取预测数据
            predictions = []
            prediction_dates = []
            prediction_mean = []
            prediction_upper = []
            prediction_lower = []
            
            # 兼容旧数据库：有些旧的 reports 行可能尚未添加 forecast_data 等列，使用 getattr 安全访问
            forecast_data_loaded = False
            from datetime import datetime, timedelta, date as _today_date_type
            _today_for_pred = _today_date_type.today()

            def _status_for(target_d, today_d, last_hist_d):
                """依据预测日与今日 / 最后历史日的关系返回 future | today | today_evaluated | expired。

                - target <= last_hist  -> today_evaluated（已有真实收盘可对比）
                - target == today      -> today（今日开盘后但尚无收盘）
                - target >  today      -> future
                - last_hist < target < today -> expired（保留并前端淡色标示）

                'today_evaluated' 用来避免和 historical 收盘行在同一 X 轴位置叠加，
                同时方便后续 prediction_evaluations 自动落库（Phase 2）。
                """
                if last_hist_d is not None and target_d <= last_hist_d:
                    return "today_evaluated"
                if target_d == today_d:
                    return "today"
                if target_d > today_d:
                    return "future"
                return "expired"

            if report and getattr(report, "forecast_data", None) and historical_prices:
                try:
                    forecast_data = json.loads(report.forecast_data)
                    # forecast_data 是一个列表，直接处理
                    if isinstance(forecast_data, list) and len(forecast_data) > 0:
                        # 使用最新的历史价格日期作为基准（historical_prices是按日期降序排列的）
                        last_date = historical_prices[0]["trade_date"]
                        _cursor = last_date
                        for pred in forecast_data[:10]:
                            _cursor = _calendar_next_trading_day(_cursor)
                            target_date = _cursor
                            # 保留目标日 >= 最后历史日 的预测点；早于最后历史日的丢弃
                            if target_date < last_date:
                                continue
                            _st = _status_for(target_date, _today_for_pred, last_date)
                            # today_evaluated（target == last_hist）只保留在 predictions[]
                            # 中供前端按需展示历史对比，不进入 future 序列扁平数组。
                            if _st != "today_evaluated":
                                prediction_dates.append(target_date.isoformat())
                                prediction_mean.append(pred["yhat"])
                                prediction_upper.append(pred["yhat_upper"])
                                prediction_lower.append(pred["yhat_lower"])
                            predictions.append({
                                "date": target_date.isoformat(),
                                "predicted_price": pred["yhat"],
                                "upper_bound": pred["yhat_upper"],
                                "lower_bound": pred["yhat_lower"],
                                "type": "prediction",
                                "status": _st,
                            })
                        forecast_data_loaded = bool(predictions)
                    # 兼容旧格式（包含 "predictions" 键的格式）
                    elif isinstance(forecast_data, dict) and "predictions" in forecast_data:
                        last_date = historical_prices[0]["trade_date"]
                        _cursor2 = last_date
                        for pred in forecast_data["predictions"]:
                            _cursor2 = _calendar_next_trading_day(_cursor2)
                            target_date = _cursor2
                            if target_date < last_date:
                                continue
                            _st = _status_for(target_date, _today_for_pred, last_date)
                            if _st != "today_evaluated":
                                prediction_dates.append(target_date.isoformat())
                                prediction_mean.append(pred["predicted_price"])
                                prediction_upper.append(pred["upper_bound"])
                                prediction_lower.append(pred["lower_bound"])
                            predictions.append({
                                "date": target_date.isoformat(),
                                "predicted_price": pred["predicted_price"],
                                "upper_bound": pred["upper_bound"],
                                "lower_bound": pred["lower_bound"],
                                "type": "prediction",
                                "status": _st,
                            })
                        forecast_data_loaded = bool(predictions)
                except Exception as e:
                    print(f"Error parsing forecast data: {e}")
                    # 即使预测数据解析失败，也要继续返回历史数据
            
            # 如果 Report 中没有 forecast_data，直接从 Forecast 表查询
            if not forecast_data_loaded:
                try:
                    # 取最新批次 run_at；保留批次内全部点，不再强制 run_at ≤ 2 天，
                    # 也不再强制 target_date ≥ today，过期点通过 status=expired 在前端区分。
                    latest_run = session.execute(
                        select(func.max(Forecast.run_at)).where(Forecast.symbol == sym)
                    ).scalar()

                    if latest_run:
                        _last_hist = historical_prices[0]["trade_date"] if historical_prices else _today_for_pred
                        _last_close_for_snr = float(historical_prices[0]["close"]) if historical_prices and historical_prices[0]["close"] else None
                        forecasts = session.execute(
                            select(Forecast).where(
                                and_(
                                    Forecast.symbol == sym,
                                    Forecast.run_at == latest_run,
                                    Forecast.target_date >= _last_hist,
                                )
                            ).order_by(Forecast.target_date)
                        ).scalars().all()

                        for f in forecasts:
                            _st = _status_for(f.target_date, _today_for_pred, _last_hist)
                            _yhat_v = float(f.yhat) if f.yhat is not None else None
                            _lo_v = float(f.yhat_lower) if f.yhat_lower is not None else None
                            _hi_v = float(f.yhat_upper) if f.yhat_upper is not None else None
                            # 方向信号强度：SNR = |yhat - prev_close| / half_interval_width
                            # SNR≥1.0 → strong(69.6%命中), SNR≥0.7 → moderate(62.1%命中), <0.7 → neutral
                            _dir_snr = None
                            _dir_grade = "neutral"
                            if _yhat_v is not None and _lo_v is not None and _hi_v is not None and _last_close_for_snr:
                                _half_w = (_hi_v - _lo_v) / 2.0
                                if _half_w > 0:
                                    _dir_snr = round(abs(_yhat_v - _last_close_for_snr) / _half_w, 3)
                                    if _dir_snr >= 1.0:
                                        _dir_grade = "strong"
                                    elif _dir_snr >= 0.7:
                                        _dir_grade = "moderate"
                            
                            # 五档信号分级：基于方向(涨/跌) + 强度(SNR)
                            # strong_bullish/weak_bullish/neutral/weak_bearish/strong_bearish
                            _signal_level = "neutral"
                            if _yhat_v is not None and _last_close_for_snr and _dir_snr is not None:
                                if _yhat_v > _last_close_for_snr:
                                    if _dir_snr >= 1.0:
                                        _signal_level = "strong_bullish"
                                    elif _dir_snr >= 0.7:
                                        _signal_level = "weak_bullish"
                                elif _yhat_v < _last_close_for_snr:
                                    if _dir_snr >= 1.0:
                                        _signal_level = "strong_bearish"
                                    elif _dir_snr >= 0.7:
                                        _signal_level = "weak_bearish"
                            
                            pred_item = {
                                "date": f.target_date.isoformat(),
                                "predicted_price": _yhat_v,
                                "upper_bound": _hi_v,
                                "lower_bound": _lo_v,
                                "type": "prediction",
                                "status": _st,
                                "direction_snr": _dir_snr,
                                "direction_grade": _dir_grade,
                                "signal_level": _signal_level,
                            }
                            predictions.append(pred_item)
                            if _st != "today_evaluated":
                                prediction_dates.append(f.target_date.isoformat())
                                prediction_mean.append(float(f.yhat) if f.yhat is not None else None)
                                prediction_upper.append(float(f.yhat_upper) if f.yhat_upper is not None else None)
                                prediction_lower.append(float(f.yhat_lower) if f.yhat_lower is not None else None)
                        forecast_data_loaded = bool(predictions)
                except Exception as e:
                    print(f"Error loading forecasts from Forecast table: {e}")

            # ── 实时预测兜底：
            # 触发条件：缓存预测为空，OR 缓存预测未覆盖到今天 / 未来交易日（即全是 expired 点）。
            _need_realtime = (not forecast_data_loaded and historical_prices) or (
                historical_prices
                and predictions
                and not any((p.get("status") in {"future", "today"}) for p in predictions)
            )
            if _need_realtime:
                try:
                    import pandas as _pd
                    # 若已有 expired 预测，先清空，统一由实时重算覆盖
                    if predictions and not any(p.get("status") in {"future", "today"} for p in predictions):
                        predictions = []
                        prediction_dates = []
                        prediction_mean = []
                        prediction_upper = []
                        prediction_lower = []
                    # 独立查询 180 天历史数据用于预测（不受前端 timeRange 限制）
                    _pred_hist_rows = session.execute(text(
                        "SELECT trade_date, open, high, low, close, vol, pct_chg "
                        "FROM prices_daily WHERE symbol=:sym "
                        "AND trade_date >= CURRENT_DATE - INTERVAL '180 days' "
                        "ORDER BY trade_date ASC"
                    ), {"sym": sym}).mappings().all()
                    rows = [
                        {
                            "trade_date": p["trade_date"],
                            "open": float(p["open"]) if p["open"] else None,
                            "high": float(p["high"]) if p["high"] else None,
                            "low": float(p["low"]) if p["low"] else None,
                            "close": float(p["close"]) if p["close"] else None,
                            "vol": float(p["vol"]) if p["vol"] else 0,
                            "pct_chg": float(p["pct_chg"]) if p["pct_chg"] else 0,
                        }
                        for p in _pred_hist_rows
                    ]
                    df_hist = _pd.DataFrame(rows).sort_values("trade_date")
                    df_hist = df_hist.dropna(subset=["close"])

                    if len(df_hist) >= 30:
                        result_pred = predict_stock_price(df_hist, sym, ahead_days=5)
                        pred_list = result_pred.get("predictions", [])
                        if pred_list:
                            last_date = df_hist["trade_date"].iloc[-1]
                            # 用统一交易日历递推，避免节假日/周末错位
                            _cursor_date = last_date
                            _now = datetime.utcnow()
                            _fresh_forecast_rows: list[dict] = []
                            for pred in pred_list:
                                _cursor_date = _calendar_next_trading_day(_cursor_date)
                                target_date = _cursor_date
                                _st = _status_for(target_date, _today_for_pred, last_date)
                                date_str = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
                                yhat = pred.get("predicted_price", pred.get("yhat"))
                                upper = pred.get("upper_bound", pred.get("yhat_upper"))
                                lower = pred.get("lower_bound", pred.get("yhat_lower"))

                                prediction_dates.append(date_str)
                                prediction_mean.append(yhat)
                                prediction_upper.append(upper)
                                prediction_lower.append(lower)
                                predictions.append({
                                    "date": date_str,
                                    "predicted_price": yhat,
                                    "upper_bound": upper,
                                    "lower_bound": lower,
                                    "type": "prediction",
                                    "status": _st,
                                })
                                _fresh_forecast_rows.append({
                                    "symbol": sym,
                                    "target_date": target_date,
                                    "yhat": yhat,
                                    "yhat_upper": upper,
                                    "yhat_lower": lower,
                                    "run_at": _now,
                                    "model": result_pred.get("method", "realtime"),
                                })
                            # 将实时计算结果写回 Forecast（UPSERT by symbol+target_date+run_at），
                            # 后续请求与调度器都能看到最新批次。
                            try:
                                for _row in _fresh_forecast_rows:
                                    session.execute(text(
                                        "INSERT INTO forecasts (symbol, target_date, yhat, yhat_upper, yhat_lower, run_at, model) "
                                        "SELECT :symbol, :target_date, :yhat, :yhat_upper, :yhat_lower, :run_at, :model "
                                        "WHERE NOT EXISTS (SELECT 1 FROM forecasts WHERE symbol=:symbol AND target_date=:target_date AND run_at=:run_at)"
                                    ), _row)
                                session.commit()
                            except Exception as _e_ins:
                                session.rollback()
                                logger.debug("persist realtime forecast failed for %s: %s", sym, _e_ins)
                            logger.info("Real-time forecast computed for %s (%s, %d pts)",
                                        sym, result_pred.get("method", "?"), len(pred_list))
                            _persist_pipeline_run(
                                symbol=sym,
                                run_type="predict",
                                status="success",
                                trigger="on_demand_full",
                                message=f"recomputed_points={len(pred_list)} method={result_pred.get('method', 'unknown')}",
                            )
                except Exception as e:
                    logger.warning("Real-time forecast failed for %s: %s", sym, e, exc_info=True)
                    _persist_pipeline_run(
                        symbol=sym,
                        run_type="predict",
                        status="failed",
                        trigger="on_demand_full",
                        error_message=str(e),
                        message="realtime predict failed",
                    )

            # Phase 2: 图表打开时顺手同步预测评估层，供 /api/predictions/history
            # 展示历史预测 vs 实际收盘。短 TTL 避免频繁刷新时重复写库。
            _prediction_refresh_meta = _maybe_refresh_prediction_evaluations(
                session,
                symbol=sym,
                lookback_days=14,
            )
            
            # 构建响应
            result = {
                "symbol": sym,
                "data_updated": report.created_at.isoformat() if report else None,
                "data_quality_score": float(report.data_quality_score) if report and report.data_quality_score else None,
                "prediction_confidence": float(report.prediction_confidence) if report and report.prediction_confidence else None,
                "analysis_summary": report.analysis_summary if report else None,
                
                # 价格数据（过去和预测）
                "price_data": price_data,
                "predictions": predictions,
                
                # 前端兼容的格式
                "dates": prediction_dates,
                "predictions_mean": prediction_mean,
                "predictions_upper": prediction_upper,
                "predictions_lower": prediction_lower,
                
                # 最新价格和信号
                "latest_price": price_data[-1] if price_data else None,
                
                # 前端兼容字段
                "latest": price_data[-1] if price_data else None,  # 向后兼容
            }
            if showDiagnostics:
                result["prediction_evaluation_refresh"] = _prediction_refresh_meta
            
            # 添加技术指标信号
            signal_loaded = False
            if report and getattr(report, "signal_data", None):
                try:
                    signal_data = json.loads(report.signal_data)
                    result["signal"] = signal_data
                    signal_loaded = True
                except Exception as e:
                    print(f"Error parsing signal data: {e}")
            
            # 如果 Report 中没有 signal_data，直接从 Signal 表查询最新信号
            if not signal_loaded:
                try:
                    latest_signal = session.execute(
                        select(Signal).where(Signal.symbol == sym)
                        .order_by(Signal.trade_date.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    
                    if latest_signal:
                        result["signal"] = {
                            "trade_date": latest_signal.trade_date.isoformat(),
                            "ma_short": float(latest_signal.ma_short) if latest_signal.ma_short is not None else None,
                            "ma_long": float(latest_signal.ma_long) if latest_signal.ma_long is not None else None,
                            "rsi": float(latest_signal.rsi) if latest_signal.rsi is not None else None,
                            "macd": float(latest_signal.macd) if latest_signal.macd is not None else None,
                            "signal_score": float(latest_signal.signal_score) if latest_signal.signal_score is not None else None,
                            "action": latest_signal.action
                        }
                except Exception as e:
                    print(f"Error loading signal from Signal table: {e}")
            
            # 尝试附加 AI 量化引擎洞察摘要（轻量，不影响原有逻辑）
            try:
                from .quant_engine.models import QESignal as _QES, QEPrediction as _QEP
                qe_signal = session.execute(
                    select(_QES).where(_QES.symbol == sym)
                    .order_by(_QES.signal_date.desc()).limit(1)
                ).scalar_one_or_none()
                qe_pred = session.execute(
                    select(_QEP).where(_QEP.symbol == sym)
                    .order_by(_QEP.predict_date.desc()).limit(1)
                ).scalar_one_or_none()
                if qe_signal or qe_pred:
                    result["ai_insight"] = {
                        "action": (qe_signal.action.value if hasattr(qe_signal.action, 'value') else qe_signal.action) if qe_signal else None,
                        "score": float(qe_signal.score) if qe_signal and qe_signal.score else None,
                        "risk_score": float(qe_signal.risk_score) if qe_signal and qe_signal.risk_score else None,
                        "direction_prob_up": float(qe_pred.direction_prob_up) if qe_pred and qe_pred.direction_prob_up else None,
                        "predicted_return": float(qe_pred.predicted_return) if qe_pred and qe_pred.predicted_return else None,
                        "confidence": float(qe_pred.confidence) if qe_pred and qe_pred.confidence else None,
                        "signal_date": qe_signal.signal_date.isoformat() if qe_signal and qe_signal.signal_date else None,
                    }
            except Exception as e:
                logger.debug("AI insight attach skipped for %s: %s", sym, e)

            if stale_used:
                result["stale"] = True
            if diagnostics is not None:
                result["diagnostics"] = diagnostics
            _full_message = (
                f"prices={len(price_data)} predictions={len(predictions)} timeRange={timeRange}"
            )
            _persist_pipeline_run(
                symbol=sym,
                run_type="full_report",
                status=_full_status,
                trigger="on_demand_full",
                duration_ms=int((_time_mod.monotonic() - _full_started) * 1000),
                message=_full_message,
            )
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            _full_status = "failed"
            _full_error = str(e)
            session.rollback()  # 防止 InFailedSqlTransaction 级联到后续请求
            print(f"Error in get_full_report: {e}")
            _persist_pipeline_run(
                symbol=sym,
                run_type="full_report",
                status=_full_status,
                trigger="on_demand_full",
                duration_ms=int((_time_mod.monotonic() - _full_started) * 1000),
                message=_full_message,
                error_message=_full_error,
            )
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/api/report/{symbol}/insight")
async def get_stock_insight(symbol: str):
    """
    获取 AI 量化引擎对单只股票的综合洞察：
    - 方向概率 & 预期收益率
    - 操作信号 (strong_buy / buy / hold / sell / strong_sell)
    - 多维因子评分（技术面/资金面/情绪面/宏观）
    - 特征重要性 Top-N
    - 模型评估指标（准确率/置信度）
    """
    from .quant_engine.models import QESignal, QEPrediction, QEStockModel, QEModelVersion, QEEvaluationMetric
    from .prediction.services.factor_context_service import load_stock_factor_context
    from .prediction.services.feature_snapshot_service import build_feature_snapshot
    from .prediction.services.trade_decision_service import build_trade_decision
    with SessionLocal() as session:
        sym = symbol.upper()
        try:
            # 1. 最新信号
            latest_signal = session.execute(
                select(QESignal).where(QESignal.symbol == sym)
                .order_by(QESignal.signal_date.desc())
                .limit(1)
            ).scalar_one_or_none()

            # 2. 最新预测
            latest_pred = session.execute(
                select(QEPrediction).where(QEPrediction.symbol == sym)
                .order_by(QEPrediction.predict_date.desc())
                .limit(1)
            ).scalar_one_or_none()

            latest_price = session.execute(
                select(PriceDaily).where(PriceDaily.symbol == sym)
                .order_by(PriceDaily.trade_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            current_price = float(latest_price.close) if latest_price and latest_price.close is not None else None

            # 3. 模型信息与评估
            stock_model = session.execute(
                select(QEStockModel).where(QEStockModel.symbol == sym)
                .limit(1)
            ).scalar_one_or_none()

            model_metrics = {}
            feature_importance = []
            if stock_model and stock_model.active_version:
                active_ver = session.execute(
                    select(QEModelVersion).where(QEModelVersion.id == stock_model.active_version)
                ).scalar_one_or_none()
                if active_ver and active_ver.metrics_json:
                    model_metrics = active_ver.metrics_json if isinstance(active_ver.metrics_json, dict) else json.loads(active_ver.metrics_json)

            # 特征重要性：优先从最新预测的 explanation_json 获取
            if latest_pred and latest_pred.explanation_json:
                exp = latest_pred.explanation_json if isinstance(latest_pred.explanation_json, dict) else json.loads(latest_pred.explanation_json)
                fi_raw = exp.get("feature_importance", {})
                if isinstance(fi_raw, dict):
                    feature_importance = sorted(
                        [{"feature": k, "importance": float(v)} for k, v in fi_raw.items()],
                        key=lambda x: x["importance"], reverse=True
                    )[:15]

            # 4. 预测准确率（最近 30 条已验证的预测）
            verified = session.execute(
                select(QEPrediction).where(
                    and_(QEPrediction.symbol == sym, QEPrediction.actual_direction.isnot(None))
                ).order_by(QEPrediction.predict_date.desc())
                .limit(30)
            ).scalars().all()

            accuracy = None
            if verified:
                correct = sum(
                    1 for p in verified
                    if (p.direction_prob_up > 0.5) == (p.actual_direction == 1)
                )
                accuracy = round(correct / len(verified) * 100, 1)

            # 5. 构建因子分解
            factors = {}
            if latest_signal and latest_signal.factors_json:
                fj = latest_signal.factors_json if isinstance(latest_signal.factors_json, dict) else json.loads(latest_signal.factors_json)
                factors = fj

            factor_context = None
            try:
                factor_context = load_stock_factor_context(session, sym, factors=factors, window_days=7)
            except Exception as context_exc:
                logger.debug("factor context unavailable for %s: %s", sym, context_exc)

            feature_snapshot = None
            try:
                feature_snapshot = build_feature_snapshot(
                    sym,
                    prediction=latest_pred,
                    signal=latest_signal,
                    latest_price=latest_price,
                    factor_context=factor_context,
                    factors=factors,
                    model_metrics=model_metrics,
                )
            except Exception as snapshot_exc:
                logger.debug("feature snapshot unavailable for %s: %s", sym, snapshot_exc)

            trade_decision = None
            if latest_signal or latest_pred:
                trade_decision = build_trade_decision(
                    symbol=sym,
                    signal=latest_signal,
                    prediction=latest_pred,
                    current_price=current_price,
                    factors=factors,
                    model_accuracy=accuracy,
                )

            # 6. 生成解释文本
            explanations = []
            if latest_signal:
                score = float(latest_signal.score) if latest_signal.score else 0
                prob = float(latest_signal.direction_prob_up) if latest_signal.direction_prob_up else 0
                risk = float(latest_signal.risk_score) if latest_signal.risk_score else 0

                if prob > 0.6:
                    explanations.append(f"AI模型预测上涨概率 {prob*100:.1f}%，看多信号较强")
                elif prob < 0.4:
                    explanations.append(f"AI模型预测上涨概率仅 {prob*100:.1f}%，看空信号较强")
                else:
                    explanations.append(f"AI模型预测上涨概率 {prob*100:.1f}%，方向不明确")

                # 从因子中提取关键信息
                tech_score = factors.get("momentum_score") or factors.get("technical_score")
                fund_score = factors.get("fund_flow_score")
                sentiment_score = factors.get("sentiment_score")

                if tech_score is not None:
                    ts = float(tech_score)
                    if ts > 0.6:
                        explanations.append("技术面：动量指标偏多，趋势向上")
                    elif ts < 0.4:
                        explanations.append("技术面：动量指标偏空，趋势向下")
                if fund_score is not None:
                    fs = float(fund_score)
                    if fs > 0.6:
                        explanations.append("资金面：主力资金净流入，买盘活跃")
                    elif fs < 0.4:
                        explanations.append("资金面：主力资金净流出，卖压明显")
                if sentiment_score is not None:
                    ss = float(sentiment_score)
                    if ss > 0.6:
                        explanations.append("情绪面：市场情绪偏乐观")
                    elif ss < 0.4:
                        explanations.append("情绪面：市场情绪偏悲观")

                if risk > 70:
                    explanations.append(f"⚠️ 风险评分较高({risk:.0f})，建议控制仓位")

            # 7. 构建响应
            result = {
                "symbol": sym,
                "has_data": latest_signal is not None or latest_pred is not None,
                "prediction": {
                    "direction_prob_up": float(latest_pred.direction_prob_up) if latest_pred and latest_pred.direction_prob_up else None,
                    "direction_prob_down": float(latest_pred.direction_prob_down) if latest_pred and latest_pred.direction_prob_down else None,
                    "predicted_return": float(latest_pred.predicted_return) if latest_pred and latest_pred.predicted_return else None,
                    "confidence": float(latest_pred.confidence) if latest_pred and latest_pred.confidence else None,
                    "predict_date": latest_pred.predict_date.isoformat() if latest_pred and latest_pred.predict_date else None,
                    "target_date": latest_pred.target_date.isoformat() if latest_pred and latest_pred.target_date else None,
                    "horizon": latest_pred.horizon if latest_pred else None,
                } if latest_pred else None,
                "signal": {
                    "action": latest_signal.action.value if latest_signal and hasattr(latest_signal.action, 'value') else (latest_signal.action if latest_signal else None),
                    "score": float(latest_signal.score) if latest_signal and latest_signal.score else None,
                    "risk_score": float(latest_signal.risk_score) if latest_signal and latest_signal.risk_score else None,
                    "signal_date": latest_signal.signal_date.isoformat() if latest_signal and latest_signal.signal_date else None,
                } if latest_signal else None,
                "factors": factors,
                "feature_importance": feature_importance,
                "model_accuracy": accuracy,
                "model_metrics": model_metrics,
                "explanations": explanations,
                "factor_context": factor_context,
                "feature_snapshot": feature_snapshot,
                "trade_decision": trade_decision,
            }
            return result

        except Exception as e:
            logger.warning("Error in get_stock_insight for %s: %s", sym, e, exc_info=True)
            return {
                "symbol": sym,
                "has_data": False,
                "prediction": None,
                "signal": None,
                "factors": {},
                "feature_importance": [],
                "model_accuracy": None,
                "model_metrics": {},
                "explanations": [],
                "factor_context": None,
                "feature_snapshot": None,
                "trade_decision": None,
            }


@app.get("/api/stocks/{symbol}/feature-snapshot")
async def get_stock_feature_snapshot(symbol: str, window_days: int = Query(7, ge=1, le=30)):
    """返回最新预测/信号可见的特征快照；用于复盘，不构成投资建议。"""
    from .prediction.services.feature_snapshot_service import load_stock_feature_snapshot

    sym = symbol.upper()
    with SessionLocal() as session:
        return load_stock_feature_snapshot(session, sym, window_days=window_days)


@app.get("/api/stocks/{symbol}/factor-context")
async def get_stock_factor_context(symbol: str, window_days: int = Query(7, ge=1, le=30)):
    """返回新闻、宏观和量化因子的解释上下文。"""
    from .quant_engine.models import QESignal
    from .prediction.services.factor_context_service import load_stock_factor_context

    sym = symbol.upper()
    with SessionLocal() as session:
        factors = {}
        try:
            latest_signal = session.execute(
                select(QESignal).where(QESignal.symbol == sym)
                .order_by(QESignal.signal_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_signal and latest_signal.factors_json:
                factors = latest_signal.factors_json if isinstance(latest_signal.factors_json, dict) else json.loads(latest_signal.factors_json)
        except Exception:
            factors = {}
        return load_stock_factor_context(session, sym, factors=factors, window_days=window_days)


@app.get("/api/stocks/{symbol}/trade-decision")
async def get_stock_trade_decision(symbol: str):
    """返回统一交易辅助建议；仅用于辅助分析，不构成投资建议。"""
    from .quant_engine.models import QESignal, QEPrediction
    from .prediction.services.trade_decision_service import build_trade_decision

    sym = symbol.upper()
    with SessionLocal() as session:
        try:
            latest_signal = session.execute(
                select(QESignal).where(QESignal.symbol == sym)
                .order_by(QESignal.signal_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            latest_pred = session.execute(
                select(QEPrediction).where(QEPrediction.symbol == sym)
                .order_by(QEPrediction.predict_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            latest_price = session.execute(
                select(PriceDaily).where(PriceDaily.symbol == sym)
                .order_by(PriceDaily.trade_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            current_price = float(latest_price.close) if latest_price and latest_price.close is not None else None

            verified = session.execute(
                select(QEPrediction).where(
                    and_(QEPrediction.symbol == sym, QEPrediction.actual_direction.isnot(None))
                ).order_by(QEPrediction.predict_date.desc())
                .limit(30)
            ).scalars().all()
            model_accuracy = None
            if verified:
                correct = sum(
                    1 for p in verified
                    if p.direction_prob_up is not None and (p.direction_prob_up > 0.5) == (p.actual_direction == 1)
                )
                model_accuracy = round(correct / len(verified) * 100, 1)

            factors = {}
            if latest_signal and latest_signal.factors_json:
                factors = latest_signal.factors_json if isinstance(latest_signal.factors_json, dict) else json.loads(latest_signal.factors_json)

            return build_trade_decision(
                symbol=sym,
                signal=latest_signal,
                prediction=latest_pred,
                current_price=current_price,
                factors=factors,
                model_accuracy=model_accuracy,
            )
        except Exception as e:
            logger.warning("Error in get_stock_trade_decision for %s: %s", sym, e, exc_info=True)
            return build_trade_decision(symbol=sym)


@app.get("/api/stocks/{stockCode}/retail-decision")
def get_stock_retail_decision(stockCode: str, db: Session = Depends(get_db)):
    """返回散户友好的短线买卖辅助卡片；不构成投资建议。"""
    try:
        from .services.retail_decision_service import build_stock_retail_decision

        return build_stock_retail_decision(db, stockCode)
    except Exception as e:
        logger.warning("retail decision failed for %s: %s", stockCode, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/stocks/{stockCode}/trade-playbook")
def get_stock_trade_playbook(stockCode: str, db: Session = Depends(get_db)):
    """返回个股短线交易剧本；不构成投资建议。"""
    try:
        from .services.trade_playbook_service import build_stock_trade_playbook

        return build_stock_trade_playbook(db, stockCode)
    except Exception as e:
        logger.warning("trade playbook failed for %s: %s", stockCode, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/reports/{symbol}/regenerate")
async def regenerate_report(symbol: str):
    """重新生成指定股票的报告"""
    try:
        sym = symbol.upper()
        # 创建高优先级任务来重新生成报告
        task_id = await task_manager.create_report_task(sym, priority=1)
        return {"message": f"Report regeneration task created for {sym}", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating regeneration task: {str(e)}")

@app.get("/reports/{symbol}/history")
def get_report_history(symbol: str, limit: int = Query(10, ge=1, le=50)):
    """获取股票报告历史版本"""
    with SessionLocal() as session:
        reports = session.execute(
            select(Report).where(Report.symbol == symbol.upper())
            .order_by(Report.version.desc())
            .limit(limit)
        ).scalars().all()
        
        return {
            "symbol": symbol.upper(),
            "reports": [
                {
                    "version": r.version,
                    "created_at": r.created_at.isoformat(),
                    "is_latest": r.is_latest,
                    "data_quality_score": float(r.data_quality_score) if r.data_quality_score else None,
                    "prediction_confidence": float(r.prediction_confidence) if r.prediction_confidence else None,
                    "analysis_summary": r.analysis_summary
                }
                for r in reports
            ]
        }

@app.get("/tasks/status")
async def get_task_status():
    """获取任务系统状态"""
    with SessionLocal() as session:
        # 统计各状态的任务数量
        pending_count = session.execute(
            select(Task).where(Task.status == TaskStatus.PENDING)
        ).scalars().all()
        
        running_count = session.execute(
            select(Task).where(Task.status == TaskStatus.RUNNING)
        ).scalars().all()
        
        completed_count = session.execute(
            select(Task).where(Task.status == TaskStatus.COMPLETED)
        ).scalars().all()
        
        failed_count = session.execute(
            select(Task).where(Task.status == TaskStatus.FAILED)
        ).scalars().all()
        
        # 统计报告数量
        total_reports = session.execute(select(Report)).scalars().all()
        latest_reports = session.execute(
            select(Report).where(Report.is_latest == True)
        ).scalars().all()
        
        return {
            "tasks": {
                "pending": len(pending_count),
                "running": len(running_count),
                "completed": len(completed_count),
                "failed": len(failed_count)
            },
            "reports": {
                "total": len(total_reports),
                "latest": len(latest_reports)
            },
            "task_manager": {
                "running_tasks": len(task_manager.running_tasks),
                "max_concurrent": task_manager.max_concurrent_tasks
            }
        }

@app.get("/api/dashboard/reports")
def get_reports_dashboard(db: Session = Depends(get_db)):
    """获取报告仪表板数据 - 按股票统计"""
    try:
        # 获取所有股票的最新报告和任务状态
        query = """
        WITH latest_reports AS (
            SELECT DISTINCT ON (symbol) 
                symbol, version, created_at, is_latest,
                data_quality_score, prediction_confidence, analysis_summary
            FROM reports 
            ORDER BY symbol, version DESC
        ),
        latest_tasks AS (
            SELECT DISTINCT ON (symbol, task_type) 
                symbol, task_type, status, created_at as task_created_at,
                started_at, completed_at, error_message, priority
            FROM tasks 
            WHERE task_type = 'generate_report'
            ORDER BY symbol, task_type, created_at DESC
        )
        SELECT 
            spm.symbol,
            COALESCE(sp.company_name, wl.name) AS name,
            COALESCE(sp.industry, wl.sector) AS sector,
            lr.version as latest_report_version,
            lr.created_at as latest_report_date,
            lr.data_quality_score,
            lr.prediction_confidence,
            lr.analysis_summary,
            lt.status as task_status,
            lt.task_created_at,
            lt.started_at,
            lt.completed_at,
            lt.error_message,
            lt.priority
        FROM stock_pool_members spm
        LEFT JOIN stock_profiles sp ON spm.symbol = sp.symbol
        LEFT JOIN watchlist wl ON spm.symbol = wl.symbol
        LEFT JOIN latest_reports lr ON spm.symbol = lr.symbol
        LEFT JOIN latest_tasks lt ON spm.symbol = lt.symbol
        WHERE spm.exit_date IS NULL
        ORDER BY spm.symbol
        """
        
        result = db.execute(text(query)).fetchall()
        
        dashboard_data = []
        for row in result:
            dashboard_data.append({
                "symbol": row.symbol,
                "name": row.name,
                "sector": row.sector,
                "latest_report": {
                    "version": str(row.latest_report_version) if row.latest_report_version else None,
                    "created_at": row.latest_report_date.isoformat() if row.latest_report_date else None,
                    "data_quality_score": float(row.data_quality_score) if row.data_quality_score else 0.0,
                    "prediction_confidence": float(row.prediction_confidence) if row.prediction_confidence else 0.0,
                    "analysis_summary": row.analysis_summary
                } if row.latest_report_version else None,
                "current_task": {
                    "status": row.task_status,
                    "created_at": row.task_created_at.isoformat() if row.task_created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "error_message": row.error_message,
                    "priority": row.priority
                } if row.task_status else None
            })
        
        return {
            "stocks": dashboard_data,
            "summary": {
                "total_stocks": len(dashboard_data),
                "with_reports": len([s for s in dashboard_data if s["latest_report"]]),
                "pending_tasks": len([s for s in dashboard_data if s["current_task"] and s["current_task"]["status"] == "pending"]),
                "running_tasks": len([s for s in dashboard_data if s["current_task"] and s["current_task"]["status"] == "running"]),
                "failed_tasks": len([s for s in dashboard_data if s["current_task"] and s["current_task"]["status"] == "failed"])
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/api/dashboard/decision-summary")
def get_decision_summary(
    symbol: str | None = Query(None, description="可选股票代码；提供后返回该股票为选中项"),
    limit: int = Query(20, ge=1, le=100, description="最多扫描股票数"),
    lookback_days: int = Query(60, ge=5, le=365, description="预测质量回看自然日窗口"),
    pinned_only: bool = Query(True, description="不传 symbol 时是否只扫描首页置顶股票"),
    refresh: bool = Query(False, description="保留参数：后续用于触发轻量刷新，当前不执行写入刷新"),
    db: Session = Depends(get_db),
):
    """返回首页一屏式买卖辅助决策摘要。"""
    try:
        from .services.decision_summary_service import build_decision_summary

        return build_decision_summary(
            db,
            symbol=symbol,
            limit=limit,
            lookback_days=lookback_days,
            pinned_only=pinned_only,
            refresh=refresh,
        )
    except Exception as e:
        logger.warning("decision summary failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/dashboard/tomorrow-retail-actions")
def get_tomorrow_retail_actions(
    limit: int = Query(12, ge=1, le=50, description="最多扫描股票数"),
    db: Session = Depends(get_db),
):
    """返回明日小散操作清单，按买入/观察/减仓/规避分组。"""
    try:
        from .services.retail_decision_service import build_tomorrow_retail_actions

        return build_tomorrow_retail_actions(db, limit=limit)
    except Exception as e:
        logger.warning("tomorrow retail actions failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/dashboard/tomorrow-playbook")
def get_tomorrow_playbook(
    limit: int = Query(12, ge=1, le=50, description="最多扫描股票数"),
    db: Session = Depends(get_db),
):
    """返回首页明日交易剧本清单，按可执行/等回调/等突破/持有/减卖/规避分组。"""
    try:
        from .services.trade_playbook_service import build_tomorrow_playbook

        return build_tomorrow_playbook(db, limit=limit)
    except Exception as e:
        logger.warning("tomorrow playbook failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/api/dashboard/tasks")
def get_tasks_dashboard(db: Session = Depends(get_db)):
    """获取任务仪表板数据"""
    try:
        # 任务状态统计
        status_stats = db.execute(text("""
            SELECT status, COUNT(*) as count
            FROM tasks
            GROUP BY status
        """)).fetchall()
        
        # 最近24小时任务
        recent_tasks = db.execute(text("""
            SELECT symbol, task_type, status, created_at, completed_at, error_message
            FROM tasks
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
            LIMIT 50
        """)).fetchall()
        
        # 任务类型统计
        type_stats = db.execute(text("""
            SELECT task_type, COUNT(*) as count
            FROM tasks
            GROUP BY task_type
        """)).fetchall()
        
        return {
            "status_statistics": {row.status: row.count for row in status_stats},
            "type_statistics": {row.task_type: row.count for row in type_stats},
            "recent_tasks": [
                {
                    "symbol": row.symbol,
                    "task_type": row.task_type,
                    "status": row.status,
                    "created_at": row.created_at.isoformat(),
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "error_message": row.error_message
                }
                for row in recent_tasks
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/api/tasks/report/{symbol}")
def create_report_task_api(symbol: str, priority: int = 5):
    """手动创建报告生成任务"""
    try:
        task_id = task_manager.create_task(
            task_type=TaskType.GENERATE_REPORT,
            symbol=symbol,
            priority=priority
        )
        return {"message": "Task created", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/api/tasks", response_model=List[dict])
def list_tasks_api(status: Optional[str] = None, symbol: Optional[str] = None, db: Session = Depends(get_db)):
    """列出任务"""
    try:
        query = select(Task)
        
        if status:
            query = query.where(Task.status == status)
        if symbol:
            query = query.where(Task.symbol == symbol)
            
        query = query.order_by(Task.priority.asc(), Task.created_at.asc())
        
        tasks = db.execute(query).scalars().all()
        
        return [
            {
                "id": task.id,
                "task_type": task.task_type,
                "symbol": task.symbol,
                "status": task.status,
                "created_at": task.created_at.isoformat(),
                "priority": task.priority
            }
            for task in tasks
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ================ NEWS API ENDPOINTS ================

from .news.news_service import NewsSearchService, NewsProcessor, NewsScheduler
from .core.models import NewsArticle, NewsSource, SearchLog, NewsCategory, SentimentType, NewsURLPattern
from .analysis.stock_manager import StockListManager
from .news.enhanced_news_scheduler import EnhancedNewsScheduler
from .news.news_deduplication import NewsDeduplicator
from .news.llm_processor import LLMNewsProcessor
from .utils.mongo_storage import get_storage
from .utils.metrics import NewsMetrics

# Initialize news services
news_search_service = NewsSearchService()
news_processor = NewsProcessor()
news_scheduler = NewsScheduler()
enhanced_news_scheduler = EnhancedNewsScheduler()
stock_list_manager = StockListManager()

class NewsSearchRequest(BaseModel):
    query: str
    category: Optional[str] = "news"
    time_range: Optional[str] = "week"
    max_results: Optional[int] = 20

class NewsResponse(BaseModel):
    articles: List[dict]
    total_count: int
    query: str
    processing_time: float

class StockManagementRequest(BaseModel):
    symbol: str
    name: Optional[str] = None

# --- Ensure-min per symbol API for immediate top-up ---
@app.post('/api/news/collect/ensure_min/{symbol}')
async def api_news_topup_symbol(symbol: str, min_required: int = Query(5, ge=1, le=50), wait_seconds: int = Query(0, ge=0, le=60)):
    """对指定股票执行补齐，确保当天至少 min_required 条。可选等待 wait_seconds 观察是否达标。
    返回：{"symbol","status","today_saved","needed","saved_total"}
    """
    try:
        scheduler = EnhancedNewsScheduler()
        result = await scheduler.run_topup_for_symbol(symbol, min_required=min_required)
        # 可选短等待以提高达标概率
        if wait_seconds > 0 and isinstance(result, dict) and int(result.get('needed', 0) or 0) > 0:
            import asyncio as _aio
            await _aio.sleep(min(wait_seconds, 60))
            result = await scheduler.run_topup_for_symbol(symbol, min_required=min_required, max_attempts=1)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ensuring min news for {symbol}: {str(e)}")

# --- Proxy stock news with optional ensure_min before returning ---
@app.get('/api/news/stock_with_ensure/{symbol}')
async def api_get_stock_news_with_ensure(
    symbol: str,
    ensure_min: int = Query(5, ge=0, le=50),
    fallback_days: int = Query(60, ge=1, le=365),
    min_content: int = Query(0, ge=0, le=10000),
    limit: int = Query(20, ge=1, le=100),
    wait_seconds: int = Query(5, ge=0, le=30),
    trigger_topup: bool = Query(True, description="If true, trigger top-up when below ensure_min"),
    allow_placeholder: bool = Query(True, description="Allow synthesizing placeholder items when sources are scarce to reach ensure_min"),
    extra_keywords: Optional[str] = Query(None, description="Comma-separated extra keywords to expand search"),
):
    """在返回个股新闻前，若数量不足 ensure_min 则尝试立即补齐并短暂等待，尽量避免 0 新闻。"""
    try:
        # 先调用基础 DB 查询（避免完全空）—正确注入 DB 会话，避免直接调用带 Depends 的默认参数
        from .routers.news import get_stock_news as _get_stock_news
        # Open session explicitly for direct function invocation
        with SessionLocal() as session:
            base = await _get_stock_news(
                symbol=symbol,
                limit=limit,
                days=7,
                ensure_min=max(0, ensure_min),
                fallback_days=fallback_days,
                include_content=True,
                min_content=min_content,
                trigger_topup=trigger_topup,
                wait_seconds=wait_seconds,
                extra_keywords=extra_keywords,
                allow_placeholder=allow_placeholder,
                db=session,
            )
        count0 = int(base.get('total_count', 0) or 0)
        if ensure_min > 0 and count0 < ensure_min:
            scheduler = EnhancedNewsScheduler()
            await scheduler.run_topup_for_symbol(symbol, min_required=ensure_min)
            if wait_seconds > 0:
                import asyncio as _aio
                await _aio.sleep(wait_seconds)
            # 再取一次（仍需注入 DB 会话）
            with SessionLocal() as session:
                base = await _get_stock_news(
                    symbol=symbol,
                    limit=limit,
                    days=7,
                    ensure_min=max(0, ensure_min),
                    fallback_days=fallback_days,
                    include_content=True,
                    min_content=min_content,
                    trigger_topup=False,
                    wait_seconds=0,
                    extra_keywords=extra_keywords,
                    allow_placeholder=allow_placeholder,
                    db=session,
                )
        return base
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching ensured stock news: {str(e)}")
    sector: Optional[str] = None
    enabled: bool = True

@app.delete("/api/news/cleanup/non-articles")
def cleanup_non_article_entries(
    host: Optional[str] = Query(None, description="可选，仅清理该主机名下的非文章链接"),
    pattern: Optional[str] = Query(None, description="可选，LIKE 模式，例如 '%/equities/%' 或 '%/quote/%'"),
    dry_run: bool = Query(True, description="默认试运行，只返回将删除的数量和样例；设为false才真正删除"),
    limit: int = Query(500, ge=1, le=5000, description="最大处理数量（试运行时返回样例数量）"),
):
    """清理明显的非新闻文章记录（如 /equities/、/quote/ 等）。

    用例：
    - 按 host 清理：/api/news/cleanup/non-articles?host=cn.investing.com
    - 按路径模式清理：/api/news/cleanup/non-articles?pattern=%/equities/%
    - 干跑：默认 true；确认无误后 dry_run=false 执行
    """
    from sqlalchemy import or_
    with SessionLocal() as session:
        # 构造条件：常见的非文章路径
        conditions = [
            NewsArticle.url.ilike("%/quote/%"),
            NewsArticle.url.ilike("%/quotes/%"),
            NewsArticle.url.ilike("%/equities/%"),
            NewsArticle.url.ilike("%/keywords/%"),
            NewsArticle.url.ilike("%/tag/%"),
            NewsArticle.url.ilike("%/category/%"),
            NewsArticle.url.ilike("%/search%"),
            NewsArticle.url.ilike("%/sitemap%"),
            NewsArticle.url.ilike("%/index%"),
            NewsArticle.url.ilike("%/topic%"),
            NewsArticle.url.ilike("%/list%"),
            NewsArticle.url.ilike("%/stocks/%"),
        ]
        if host:
            conditions.append(NewsArticle.url.ilike(f"%://{host}/%"))
        if pattern:
            conditions.append(NewsArticle.url.ilike(pattern))

        q = select(NewsArticle).where(or_(*conditions)).limit(limit)
        rows = session.execute(q).scalars().all()
        count = len(rows)
        sample = [
            {"id": r.id, "url": r.url, "title": r.title}
            for r in rows[: min(20, count)]
        ]
        if dry_run or count == 0:
            return {"dry_run": True, "matched": count, "sample": sample}
        # 真正删除
        ids = [r.id for r in rows]
        session.execute(text("DELETE FROM news_articles WHERE id = ANY(:ids)"), {"ids": ids})
        session.commit()
        return {"dry_run": False, "deleted": count}

@app.post("/api/news/search")
async def search_news(request: NewsSearchRequest):
    """
    Search news using SearXNG
    """
    try:
        start_time = time.time()
        
        results = await news_search_service.search_news(
            query=request.query,
            category=request.category,
            time_range=request.time_range,
            max_results=request.max_results
        )
        
        processing_time = time.time() - start_time
        
        return NewsResponse(
            articles=results,
            total_count=len(results),
            query=request.query,
            processing_time=processing_time
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"News search failed: {str(e)}")


@app.get("/api/news/stocks")
async def get_stocks_news_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    获取股票资讯列表 - 返回所有股票和其最新资讯状态
    
    参数：
        page: 页码（从1开始）
        page_size: 每页数量
        q: 搜索关键词（按代码或名称）
    
    返回：
        {
            "items": [
                {
                    "symbol": "600519.SH",
                    "name": "贵州茅台",
                    "start_date": "2025-01-01",
                    "article_count": 42,
                    "last_updated_at": "2025-10-17T15:30:45",
                    "is_updated": true  // 根据 last_updated_at 判断：14天内为true
                }
            ],
            "total": 150,
            "page": 1,
            "page_size": 20
        }
    """
    try:
        from datetime import datetime, timedelta
        from sqlalchemy import func
        
        # 获取所有 Watchlist 中的股票
        query = db.query(Watchlist)
        
        # 搜索过滤
        if q:
            q_lower = q.lower()
            query = query.filter(
                (Watchlist.symbol.ilike(f"%{q}%")) |
                (Watchlist.name.ilike(f"%{q}%"))
            )
        
        # 获取总数
        total = query.count()
        
        # 分页
        offset = (page - 1) * page_size
        stocks = query.offset(offset).limit(page_size).all()
        
        # 获取新闻文章统计（从 NewsArticle 表统计）
        news_counts = {}
        try:
            if stocks:
                symbols = [s.symbol for s in stocks]
                # 统计每只股票的新闻数量
                article_counts = db.query(
                    NewsArticle.related_stocks,
                    func.count(NewsArticle.id)
                ).filter(
                    NewsArticle.related_stocks.isnot(None)
                ).group_by(
                    NewsArticle.related_stocks
                ).all()
                
                for related_stocks, count in article_counts:
                    if related_stocks and isinstance(related_stocks, list):
                        for symbol in related_stocks:
                            if symbol not in news_counts:
                                news_counts[symbol] = 0
                            news_counts[symbol] += count
        except Exception as e:
            logger.warning(f"⚠️  获取新闻统计失败: {e}")
        
        # 构建返回数据
        items = []
        now = datetime.now()
        fourteen_days_ago = now - timedelta(days=14)
        
        for stock in stocks:
            last_updated_at = stock.last_updated_at
            article_count = news_counts.get(stock.symbol, 0)
            
            # 判断是否已更新：
            # 1. 如果 last_updated_at 不为空且在14天内，则为已更新
            # 2. 或者如果有文章且 last_updated_at 为空（迁移期间的历史数据），则认为已更新
            is_updated = (
                (last_updated_at is not None and last_updated_at >= fourteen_days_ago) or
                (last_updated_at is None and article_count > 0)  # 有文章但未记录时间戳，认为已更新
            )
            
            items.append({
                "symbol": stock.symbol,
                "name": stock.name or "-",
                "start_date": stock.added_at.date().isoformat() if stock.added_at else None,
                "article_count": article_count,
                "last_updated_at": last_updated_at.isoformat() if last_updated_at else None,
                "is_updated": is_updated
            })
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size
        }
        
    except Exception as e:
        logger.error(f"❌ 获取股票新闻列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get stocks news list: {str(e)}")


def infer_market_from_symbol(symbol: str) -> str:
    """
    根据股票符号的格式推断其所属市场
    
    逻辑：
    - 以 .SH 结尾 -> A股（上海）
    - 以 .SZ 结尾 -> A股（深圳）
    - 6 位纯数字 (000xxx, 002xxx, 300xxx) -> A股（中国证券交易所标准编码）
    - 以 .HK 结尾或 5 位数字、$开头 -> 港股
    - 全是字母 (3-6 位) -> 美股
    - profile.market 非空且有效 -> 返回 profile.market
    
    Args:
        symbol: 股票代码（如 '600000.SH', '000858.SZ', '002268', 'WMT', '05', etc）
    
    Returns:
        市场标签: 'A股'|'港股'|'美股'
    """
    if not symbol:
        return "美股"  # 默认
    
    symbol = symbol.strip().upper()
    
    # A股：以 .SH 或 .SZ 结尾
    if symbol.endswith(".SH") or symbol.endswith(".SZ"):
        return "A股"
    
    # A股：6 位数字（中国证券代码标准格式）
    # 000xxx / 001xxx (深圳) 或 600xxx / 605xxx (上海)
    if len(symbol) == 6 and symbol.isdigit():
        first_three = symbol[:3]
        # 深圳：000-003, 030, 039, 08, 09, 12, 16-19, 200-203, 300, 301, 834-837, 900-903, 916-919, 930-939
        # 上海：600-605, 606-607, 673-679, 811-819
        if first_three in ("000", "001", "002", "003", "030", "039") or first_three.startswith(("08", "09", "12", "16", "17", "18", "19")):
            return "A股"
        if first_three in ("600", "601", "602", "603", "604", "605", "606", "607") or first_three.startswith(("673", "674", "675", "676", "677", "678", "679", "811", "812", "813", "814", "815", "816", "817", "818", "819")):
            return "A股"
        # 其他6位数字可能是基金等，也算 A股
        return "A股"
    
    # 港股：以 .HK 结尾、5 位数字、$ 开头等特征
    if symbol.endswith(".HK") or symbol.startswith("$"):
        return "港股"
    
    # 港股的5位数字代码（如 01810, 09988）
    if len(symbol) == 5 and symbol.isdigit():
        return "港股"
    
    # 美股：3-6 位字母（如 AAPL, WMT, QCOM, NVDA）
    if 1 <= len(symbol) <= 6 and symbol.isalpha():
        return "美股"
    
    # 其他：默认美股
    return "美股"

@app.get("/api/news/stocks/progress")
async def get_stocks_update_progress(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    show_invalid: bool = Query(False),
    q: str = Query(None),
    market: str = Query("A股", description="股票市场过滤：A股/港股/美股/全部"),
    db: Session = Depends(get_db)
):
    """
    获取资讯列表中所有股票的 Profile 完成度进度
    
    参数:
    - show_invalid: 是否显示被标记为无效的股票（默认 false）
    - q: 搜索关键词（按代码或公司名搜索）
    - market: 股票市场过滤（A股/港股/美股/全部，默认 A股）
    
    优化：使用批量查询和缓存策略来避免N+1查询问题
    """
    try:
        import json
        import time as _time
        from sqlalchemy import func, case
        
        _t0 = _time.time()
        
        # 定义 Profile 字段
        profile_fields = [
            'industry', 'business_summary', 'core_products', 'competitive_position',
            'competitors', 'strategic_keywords', 'risk_factors', 'history_highlights', 'profile_json'
        ]
        total_profile_fields = len(profile_fields)
        
        # ═══════════════════════════════════════════════════
        # ✨ 优化核心：使用缓存的文章数据索引（300s TTL）
        # 一次查询构建 all_symbols + symbol_count + symbol_times
        # ═══════════════════════════════════════════════════
        global _article_data_cache, _article_data_cache_ts
        
        _cache_age = _time.time() - _article_data_cache_ts
        if _article_data_cache is not None and _cache_age < 300:
            all_symbols_set = _article_data_cache["all_symbols"]
            symbol_count_map = _article_data_cache["symbol_count"]
            symbol_times_map = _article_data_cache["symbol_times"]
            logger.debug(f"✅ 使用缓存的文章索引（{int(_cache_age)}s 前，{len(all_symbols_set)} symbols）")
        else:
            # 一次查询拿到 related_stocks + published_at，单遍历构建三个索引
            all_articles = db.query(
                NewsArticle.related_stocks, NewsArticle.published_at
            ).filter(
                NewsArticle.related_stocks.isnot(None)
            ).all()
            
            all_symbols_set: set[str] = set()
            symbol_count_map: dict[str, int] = {}
            symbol_times_map: dict[str, dict] = {}
            
            for row in all_articles:
                rs, pub_date = row
                if not rs:
                    continue
                try:
                    stocks = json.loads(rs) if isinstance(rs, str) else rs
                except:
                    continue
                if not isinstance(stocks, list):
                    continue
                for sym in stocks:
                    all_symbols_set.add(sym)
                    symbol_count_map[sym] = symbol_count_map.get(sym, 0) + 1
                    if pub_date:
                        if sym not in symbol_times_map:
                            symbol_times_map[sym] = {"min_date": pub_date, "max_date": pub_date}
                        else:
                            t = symbol_times_map[sym]
                            if t["min_date"] is None or pub_date < t["min_date"]:
                                t["min_date"] = pub_date
                            if t["max_date"] is None or pub_date > t["max_date"]:
                                t["max_date"] = pub_date
            
            _article_data_cache = {
                "all_symbols": all_symbols_set,
                "symbol_count": symbol_count_map,
                "symbol_times": symbol_times_map,
            }
            _article_data_cache_ts = _time.time()
            logger.info(f"✅ 文章索引已构建：{len(all_symbols_set)} symbols，{len(all_articles)} articles，耗时 {_time.time()-_t0:.1f}s")
        
        all_symbols_list = sorted(list(all_symbols_set))
        total_stocks = len(all_symbols_list)
        
        if total_stocks == 0:
            return {
                "total_stocks": 0,
                "completed_profiles": 0,
                "progress_percentage": 0.0,
                "average_completion": 0.0,
                "stocks_detail": [],
                "page": page,
                "page_size": page_size,
                "total_pages": 0
            }
        
        # ✨ 批量查询所有相关的 StockProfile
        all_profiles = db.query(StockProfile).filter(
            StockProfile.symbol.in_(all_symbols_list)
        ).all()
        profile_map = {p.symbol: p for p in all_profiles}
        
        # 名称回填由后台线程 _backfill_stock_names_sync() 在启动时执行
        # API 端点只读取已有的 DB 数据，不做任何重型处理
        
        # 🔧 过滤：只保留有有效Profile的symbols
        valid_symbols = []
        for symbol in all_symbols_list:
            profile = profile_map.get(symbol)
            # 必须有profile存在
            if not profile:
                continue
            # 如果show_invalid=False，还要检查is_valid标志
            if not show_invalid and not profile.is_valid:
                continue
            # 市场过滤：根据符号格式推断市场
            # 注意：profile.market 默认值是 "A股"，所以我们优先使用 infer_market_from_symbol()
            # 这样才能正确识别美股、港股等
            inferred_market = infer_market_from_symbol(symbol)
            if market != "全部" and inferred_market != market:
                continue
            valid_symbols.append(symbol)
        
        all_symbols_list = valid_symbols
        total_stocks = len(all_symbols_list)
        
        # ✨ 优化第三步：计算完成度（在内存中）
        all_stocks_completion = {}
        global_completed_count = 0
        global_total_completion = 0.0
        
        for symbol in all_symbols_list:
            profile = profile_map.get(symbol)
            filled_count = 0
            
            if profile:
                for field in profile_fields:
                    value = getattr(profile, field, None)
                    if value and (isinstance(value, str) and value.strip() or isinstance(value, dict)):
                        filled_count += 1
            
            completion_pct = (filled_count / total_profile_fields) * 100 if total_profile_fields > 0 else 0
            global_total_completion += completion_pct
            all_stocks_completion[symbol] = {
                "filled": filled_count,
                "completion_pct": completion_pct
            }
            
            if completion_pct >= 50:
                global_completed_count += 1
        
        # ✨ 优化第四步：排序
        # 🔍 搜索过滤：如果提供了搜索关键词 q
        if q:
            q_lower = q.lower().strip()
            # 首先按符号过滤
            filtered_symbols = [s for s in all_symbols_list if q_lower in s.lower()]
            
            # 如果按符号没有找到，使用已有的 profile_map 按公司名过滤（无需再次查 DB）
            if not filtered_symbols:
                filtered_symbols = [
                    s for s in all_symbols_list 
                    if s in profile_map and profile_map[s].company_name and q_lower in profile_map[s].company_name.lower()
                ]
            
            all_symbols_list = filtered_symbols
        
        sorted_symbols = sorted(
            all_symbols_list,
            key=lambda s: (all_stocks_completion[s]["completion_pct"], s),
            reverse=True
        )
        
        # ✨ 优化第五步：分页 + 批量获取名称
        offset = (page - 1) * page_size
        end_offset = offset + page_size
        page_symbols = sorted_symbols[offset:end_offset]
        
        # 批量查询 Watchlist 和 StockProfile 名称
        watchlist_items = db.query(Watchlist.symbol, Watchlist.name).filter(
            Watchlist.symbol.in_(page_symbols)
        ).all()
        watchlist_map = {item[0]: item[1] for item in watchlist_items}
        
        # ✨ 直接使用缓存的文章索引（无需再次查询 NewsArticle）
        article_count_map = {sym: symbol_count_map.get(sym, 0) for sym in page_symbols}
        
        stocks_detail = []
        # 使用 naive datetime 以避免时区比较问题
        fourteen_days_ago = datetime.now() - timedelta(days=14)
        
        # ✨ 直接使用缓存的 symbol_times_map（无需再次查询）
        symbol_times = symbol_times_map
        
        for symbol in page_symbols:
            profile = profile_map.get(symbol)
            
            # profile 应该始终存在（已在前面过滤过）
            if not profile:
                continue
            
            # ✅ 防御性检查：company_name 可能为空
            if profile.company_name:
                stock_name = profile.company_name
            else:
                # 回退方案：从 Watchlist 或使用符号
                # 注意：watchlist_map.get(symbol) 可能返回 None（key存在但值为空）
                watchlist_name = watchlist_map.get(symbol)
                stock_name = watchlist_name if watchlist_name else symbol
                logger.warning(f"⚠️ Profile {symbol} 缺少 company_name，使用回退值: {stock_name}")
            
            comp_data = all_stocks_completion[symbol]
            completion_pct = comp_data["completion_pct"]
            filled_count = comp_data["filled"]
            status = "completed" if completion_pct >= 50 else "incomplete"
            
            # 从新闻文章中获取时间戳
            times_info = symbol_times.get(symbol, {})
            start_date = times_info.get("min_date").date().isoformat() if times_info.get("min_date") else None
            last_updated_at = times_info.get("max_date")
            article_count = article_count_map.get(symbol, 0)
            
            # 移除时区信息以进行比较
            cmp_last_updated = last_updated_at.replace(tzinfo=None) if last_updated_at else None
            
            # 1. 如果 last_updated_at 不为空且在14天内，则为已更新
            # 2. 或者如果有文章且 last_updated_at 为空，则认为已更新
            is_updated = (
                (cmp_last_updated is not None and cmp_last_updated >= fourteen_days_ago) or
                (cmp_last_updated is None and article_count > 0)

            )
            
            stocks_detail.append({
                "symbol": symbol,
                "name": stock_name or 'N/A',
                "market": profile.market,  # ✨ 添加市场字段
                "completion_percentage": round(completion_pct, 1),
                "fields_filled": filled_count,
                "total_fields": total_profile_fields,
                "status": status,
                "article_count": article_count_map.get(symbol, 0),  # 文章数
                "start_date": start_date,
                "last_updated_at": last_updated_at.isoformat() if last_updated_at else None,
                "is_updated": is_updated
            })
        
        # 计算全局进度
        progress_percentage = (global_completed_count / total_stocks * 100) if total_stocks > 0 else 0
        average_completion = (global_total_completion / total_stocks) if total_stocks > 0 else 0
        total_pages = (total_stocks + page_size - 1) // page_size
        
        result = {
            "total_stocks": total_stocks,
            "completed_profiles": global_completed_count,
            "progress_percentage": round(progress_percentage, 1),
            "average_completion": round(average_completion, 1),
            "stocks_detail": stocks_detail,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }
        
        _elapsed = _time.time() - _t0
        logger.info(f"GET /api/news/stocks/progress -> 200 ({_elapsed*1000:.0f} ms, {total_stocks} stocks)")
        
        return JSONResponse(
            result,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ 获取Profile完成度进度失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get profile progress: {str(e)}")


@app.get("/api/news/stock/{symbol}")
async def get_stock_news(symbol: str, limit: int = Query(20, ge=1, le=100)):
    """
    Get news for specific stock symbol
    """
    try:
        print(f"🔍 API called for stock: {symbol}")
        
        # Get stock info first (tolerate network failures)
        stock_info = get_stock_info(symbol)
        fallback_name = None
        if not stock_info:
            # Try to get a name from watchlist as a best-effort fallback
            try:
                with SessionLocal() as session:
                    w = session.execute(select(Watchlist).where(Watchlist.symbol == symbol.upper())).scalar_one_or_none()
                    if w and getattr(w, 'name', None):
                        fallback_name = w.name
            except Exception as e:
                print(f"⚠️ Fallback watchlist lookup failed: {e}")
            print(f"⚠️ Stock info unavailable for {symbol}. Continuing with symbol only.")
        else:
            print(f"📊 Stock info: {stock_info.get('name')}")
        
        # Initialize services
        news_search_service = NewsSearchService()
        news_processor = NewsProcessor()
        
        # Search news for this stock
        print(f"🔎 Searching news...")
        results = await news_search_service.search_stock_news(
            symbol=symbol,
            company_name=(stock_info.get('name') if stock_info else fallback_name)
        )
        
        print(f"🔎 Found {len(results)} search results")
        
        # Process and save articles
        print(f"📝 Processing articles...")
        articles = await news_processor.process_search_results(results, symbol)
        
        print(f"📝 Processed {len(articles)} articles")
        
        # Format response articles list
        response_articles = []
        
        # Save to database and build response
        session = SessionLocal()
        try:
            for i, article in enumerate(articles[:limit]):
                try:
                    print(f"💾 Processing article {i+1}: {article.title[:50]}...")
                    
                    # Check if article exists
                    existing = session.execute(
                        select(NewsArticle).where(NewsArticle.url == article.url)
                    ).scalar_one_or_none()
                    
                    current_article = None
                    if not existing:
                        print(f"  ✅ New article, saving...")
                        session.add(article)
                        session.commit()
                        session.refresh(article)
                        current_article = article
                    else:
                        print(f"  ♻️ Article exists, using existing...")
                        current_article = existing
                    
                    # Build article response data
                    source_name = "Unknown"
                    if current_article.source_id:
                        if hasattr(current_article, 'source') and current_article.source:
                            source_name = current_article.source.name
                        else:
                            # Load source if not loaded
                            session.refresh(current_article)
                            if hasattr(current_article, 'source') and current_article.source:
                                source_name = current_article.source.name
                    
                    article_data = {
                        "id": current_article.id,
                        "title": current_article.title,
                        "url": current_article.url,
                        "summary": current_article.summary or "",
                        "published_at": current_article.published_at.isoformat() if current_article.published_at else None,
                        "source": source_name,
                        "sentiment_type": current_article.sentiment_type,
                        "sentiment_score": current_article.sentiment_score,
                        "relevance_score": current_article.relevance_score,
                        "related_stocks": current_article.related_stocks or []
                    }
                    
                    response_articles.append(article_data)
                    print(f"  📄 Added to response")
                    
                except Exception as e:
                    print(f"❌ Error processing article: {e}")
                    session.rollback()
                    continue
                    
        finally:
            session.close()
        
        print(f"✅ Completed! Returning {len(response_articles)} articles")
        
        # Return response
        return {
            "symbol": symbol,
            "company_name": (stock_info.get('name') if stock_info else fallback_name),
            "articles": response_articles,
            "total_count": len(response_articles)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ API Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching stock news: {str(e)}")

@app.get("/api/news/articles")
async def get_news_articles(
    db: Session = Depends(get_db),
    category: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_content: bool = Query(False, description="是否包含全文内容")
):
    # Build base query
    query = select(NewsArticle).join(NewsSource)

    # Apply filters
    if category:
        query = query.where(NewsArticle.category == category)
    if sentiment:
        query = query.where(NewsArticle.sentiment_type == sentiment)
    if symbol:
        query = query.where(NewsArticle.related_stocks.contains([symbol]))

    # Order by published date, most recent first
    query = query.order_by(NewsArticle.published_at.desc().nullslast())
    # Apply pagination
    query = query.offset(offset).limit(limit)

    articles = db.execute(query).scalars().all()

    return {
        "articles": [
            {
                "id": article.id,
                "title": article.title,
                "url": article.url,
                "summary": article.summary,
                **({"content": article.content} if include_content else {}),
                "published_at": article.published_at.isoformat() if article.published_at else None,
                # Alias for clients expecting published_dt
                "published_dt": article.published_at.isoformat() if article.published_at else None,
                "source": article.source.name,
                "category": article.category,
                # Include bookmark/read flags for client state and filtering
                "is_bookmarked": getattr(article, "is_bookmarked", None),
                "is_read": getattr(article, "is_read", None),
                "sentiment_type": article.sentiment_type,
                "sentiment_score": article.sentiment_score,
                "relevance_score": article.relevance_score,
                "related_stocks": article.related_stocks,
                "keywords": article.keywords,
                # Expose structured analysis bundle for richer rendering
                "analysis": {
                    "companies": (article.entities or {}).get("companies") if isinstance(article.entities, dict) else [],
                    "people": (article.entities or {}).get("people") if isinstance(article.entities, dict) else [],
                    "locations": (article.entities or {}).get("locations") if isinstance(article.entities, dict) else [],
                    "stock_symbols": article.related_stocks or [],
                    "financial_metrics": (article.entities or {}).get("financial_metrics") if isinstance(article.entities, dict) else {},
                    "main_topics": (article.entities or {}).get("main_topics") if isinstance(article.entities, dict) else ((article.keywords or [])[:3] if article.keywords else []),
                    "market_impact": (article.entities or {}).get("market_impact") if isinstance(article.entities, dict) else None,
                    "time_references": (article.entities or {}).get("time_references") if isinstance(article.entities, dict) else [],
                    "reliability_assessment": (article.entities or {}).get("reliability_assessment") if isinstance(article.entities, dict) else None,
                    "sentiment": {
                        "type": article.sentiment_type,
                        "score": article.sentiment_score,
                    }
                }
            }
            for article in articles
        ],
        "limit": limit,
        "offset": offset,
        "total_count": len(articles)
    }

@app.get("/api/news/audit")
async def audit_news_quality(
    db: Session = Depends(get_db),
    sample_limit: int = Query(5, ge=1, le=50),
    short_content_threshold: int = Query(60, ge=20, le=300),
    mismatch_threshold: float = Query(0.25, ge=0.0, le=1.0, description="摘要与正文的一致性最低大ram-Jaccard阈值，低于则视为不一致"),
    content_sample_len: int = Query(220, ge=50, le=1000, description="计算一致性的正文抽样长度（取前N字符）"),
):
    """
    审计新闻数据质量：统计摘要缺失/占位符、内容缺失/过短，以及LLM扩展字段覆盖率，并返回样本。
    """
    try:
        articles = db.execute(select(NewsArticle)).scalars().all()
        total = len(articles)

        placeholder_markers = [
            "请启用javascript", "enable javascript", "document", "cookie", "隐私", "验证码", "正在跳转", "安全验证"
        ]

        def is_empty(s: str | None) -> bool:
            return (s is None) or (isinstance(s, str) and len(s.strip()) == 0)

        def has_placeholder(s: str | None) -> bool:
            if not s:
                return False
            lower = s.strip().lower()
            return any(m in lower for m in placeholder_markers)

        # Helpers for mismatch detection (bigram Jaccard)
        def _bigrams(text: str) -> set:
            t = (text or "").lower()
            # Keep letters/numbers/CJK; collapse spaces
            import re
            t = re.sub(r"\s+", " ", t)
            # build bigrams over characters to be language-agnostic
            return {t[i:i+2] for i in range(len(t)-1)} if len(t) >= 2 else set()

        def jaccard(a: str, b: str) -> float:
            A, B = _bigrams(a), _bigrams(b)
            if not A or not B:
                return 0.0
            inter = len(A & B)
            union = len(A | B)
            return (inter / union) if union else 0.0

        # Metrics
        summary_empty = []
        summary_placeholder = []
        content_empty = []
        content_too_short = []
        mismatch_summary_content = []
        llm_enriched = 0

        for a in articles:
            if is_empty(a.summary):
                summary_empty.append(a)
            elif has_placeholder(a.summary):
                summary_placeholder.append(a)

            if is_empty(a.content):
                content_empty.append(a)
            elif isinstance(a.content, str) and len(a.content.strip()) < short_content_threshold:
                content_too_short.append(a)

            # Mismatch detection
            if isinstance(a.summary, str) and isinstance(a.content, str):
                content_slice = a.content.strip()[:content_sample_len]
                sim = jaccard(a.summary.strip(), content_slice)
                if sim < mismatch_threshold:
                    mismatch_summary_content.append({
                        "id": a.id,
                        "title": a.title,
                        "url": a.url,
                        "sim": sim,
                    })

            ents = a.entities if isinstance(a.entities, dict) else {}
            if isinstance(ents, dict) and (
                ents.get("financial_metrics") or ents.get("main_topics") or ents.get("companies")
            ):
                llm_enriched += 1

        def sample(items):
            return [
                {"id": x.id, "title": x.title, "url": x.url, "source": (x.source.name if x.source else None)}
                for x in items[:sample_limit]
            ]

        def sample_m(items):
            return items[:sample_limit]

        return {
            "total": total,
            "summary_empty_count": len(summary_empty),
            "summary_placeholder_count": len(summary_placeholder),
            "content_empty_count": len(content_empty),
            "content_too_short_count": len(content_too_short),
            "mismatch_count": len(mismatch_summary_content),
            "llm_enriched_ratio": (llm_enriched / total) if total else 0.0,
            "samples": {
                "summary_empty": sample(summary_empty),
                "summary_placeholder": sample(summary_placeholder),
                "content_empty": sample(content_empty),
                "content_too_short": sample(content_too_short),
                "mismatch_summary_content": sample_m(mismatch_summary_content),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error auditing news: {str(e)}")

@app.get("/api/news/sources")
async def get_news_sources(db: Session = Depends(get_db)):
    """
    Get all news sources
    """
    try:
        sources = db.execute(select(NewsSource)).scalars().all()
        
        return {
            "sources": [
                {
                    "id": source.id,
                    "name": source.name,
                    "domain": source.domain,
                    "category": source.category,
                    "reliability_score": source.reliability_score,
                    "language": source.language,
                    "enabled": source.enabled
                }
                for source in sources
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching sources: {str(e)}")

@app.post("/api/news/collect/{symbol}")
async def collect_news_for_stock(symbol: str, db: Session = Depends(get_db)):
    """
    Manually trigger news collection for a specific stock
    """
    try:
        # Get stock info (tolerate network issues with fallback)
        stock_info = get_stock_info(symbol)
        company_name = None
        if not stock_info:
            # Try to fallback to watchlist stored name
            try:
                w = db.execute(select(Watchlist).where(Watchlist.symbol == symbol.upper())).scalar_one_or_none()
                if w and getattr(w, 'name', None):
                    company_name = w.name
            except Exception as e:
                print(f"⚠️ collect fallback watchlist lookup failed: {e}")
            if not company_name:
                company_name = symbol.upper()
        else:
            company_name = stock_info.get('name')
        
        # Add news collection task
        task = Task(
            task_type=TaskType.FETCH_NEWS.value,
            symbol=symbol,
            status=TaskStatus.PENDING.value,
            priority=3,
            task_metadata=json.dumps({
                "company_name": company_name,
                "manual_trigger": True
            })
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
        
        return {
            "message": f"News collection task created for {symbol}",
            "symbol": symbol,
            "company_name": company_name,
            "task_id": task_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating news collection task: {str(e)}")

@app.post("/api/news/collect/intelligent")
async def run_intelligent_news_collection():
    """
    Manually trigger intelligent news collection based on watchlist strategies
    """
    try:
        result = await enhanced_news_scheduler.run_intelligent_news_collection()
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running intelligent news collection: {str(e)}")

@app.post("/api/news/collect/daily")
async def run_daily_news_collection():
    """
    Manually trigger daily news collection for all enabled stocks
    """
    try:
        result = await enhanced_news_scheduler.run_daily_news_collection()
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running daily news collection: {str(e)}")

@app.post("/api/news/collect/ensure_min")
async def run_news_topup_ensure_min():
    """
    Trigger rolling top-up to ensure minimum per-stock daily articles.
    Uses NEWS_DAILY_MIN_PER_STOCK (default 5).
    """
    try:
        scheduler = EnhancedNewsScheduler()
        result = await scheduler.run_rolling_topup_collection()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running news top-up ensure_min: {str(e)}")

@app.get("/api/news/collection/status")
async def get_news_collection_status():
    """
    Get current news collection status and statistics
    """
    try:
        status = await enhanced_news_scheduler.get_collection_status()
        return status
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting collection status: {str(e)}")

# ================ STOCK MANAGEMENT API ENDPOINTS ================

@app.post("/api/stocks/add")
async def add_stock_to_watchlist(request: StockManagementRequest):
    """
    Add a stock to the monitoring watchlist
    """
    try:
        stock = await stock_list_manager.add_stock(
            symbol=request.symbol,
            name=request.name,
            sector=request.sector,
            enabled=request.enabled
        )
        
        return {
            "message": f"Stock {request.symbol} added successfully",
            "stock": {
                "symbol": stock.symbol,
                "name": stock.name,
                "sector": stock.sector,
                "enabled": stock.enabled
            }
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding stock: {str(e)}")

@app.delete("/api/stocks/{symbol}")
async def remove_stock_from_watchlist(symbol: str):
    """
    Remove a stock from the monitoring watchlist
    """
    try:
        success = await stock_list_manager.remove_stock(symbol)
        
        if success:
            return {"message": f"Stock {symbol} removed successfully"}
        else:
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error removing stock: {str(e)}")

@app.put("/api/stocks/{symbol}")
async def update_stock_in_watchlist(symbol: str, request: StockManagementRequest):
    """
    Update a stock in the monitoring watchlist
    """
    try:
        update_data = {}
        if request.name is not None:
            update_data['name'] = request.name
        if request.sector is not None:
            update_data['sector'] = request.sector
        update_data['enabled'] = request.enabled
        
        stock = await stock_list_manager.update_stock(symbol, **update_data)
        
        if stock:
            return {
                "message": f"Stock {symbol} updated successfully",
                "stock": {
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "sector": stock.sector,
                    "enabled": stock.enabled
                }
            }
        else:
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating stock: {str(e)}")

@app.get("/api/stocks")
async def list_stocks(
    enabled_only: bool = Query(False, description="只返回启用的股票"),
    sector: Optional[str] = Query(None, description="按行业筛选"),
    limit: int = Query(100, ge=1, le=1000, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """
    Get list of stocks in the monitoring watchlist
    """
    try:
        stocks = await stock_list_manager.list_stocks(
            enabled_only=enabled_only,
            sector=sector,
            limit=limit,
            offset=offset
        )
        
        return {
            "stocks": [
                {
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "sector": stock.sector,
                    "enabled": stock.enabled
                }
                for stock in stocks
            ],
            "count": len(stocks),
            "filters": {
                "enabled_only": enabled_only,
                "sector": sector
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing stocks: {str(e)}")

@app.get("/api/stocks/statistics")
async def get_stocks_statistics():
    """
    Get statistics about the stock monitoring system
    """
    try:
        stats = await stock_list_manager.get_stock_statistics()
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting statistics: {str(e)}")

@app.get("/api/stocks/sectors")
async def get_stock_sectors():
    """
    Get all available stock sectors
    """
    try:
        sectors = await stock_list_manager.get_sectors()
        return {"sectors": sectors}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting sectors: {str(e)}")

@app.post("/api/stocks/{symbol}/enable")
async def enable_stock_monitoring(symbol: str):
    """
    Enable monitoring for a specific stock
    """
    try:
        success = await stock_list_manager.enable_stock(symbol)
        
        if success:
            return {"message": f"Stock {symbol} monitoring enabled"}
        else:
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error enabling stock: {str(e)}")

@app.post("/api/stocks/{symbol}/disable")
async def disable_stock_monitoring(symbol: str):
    """
    Disable monitoring for a specific stock
    """
    try:
        success = await stock_list_manager.disable_stock(symbol)
        
        if success:
            return {"message": f"Stock {symbol} monitoring disabled"}
        else:
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error disabling stock: {str(e)}")

@app.post("/api/stocks/batch/enable")
async def batch_enable_stocks(symbols: List[str]):
    """
    Batch enable monitoring for multiple stocks
    """
    try:
        count = await stock_list_manager.batch_update_enabled(symbols, enabled=True)
        return {
            "message": f"Enabled monitoring for {count} stocks",
            "symbols": symbols,
            "updated_count": count
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error batch enabling stocks: {str(e)}")

@app.post("/api/stocks/batch/disable")
async def batch_disable_stocks(symbols: List[str]):
    """
    Batch disable monitoring for multiple stocks
    """
    try:
        count = await stock_list_manager.batch_update_enabled(symbols, enabled=False)
        return {
            "message": f"Disabled monitoring for {count} stocks",
            "symbols": symbols,
            "updated_count": count
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error batch disabling stocks: {str(e)}")

# ================ NEWS DEDUPLICATION API ENDPOINTS ================

@app.get("/api/news/deduplication/stats")
async def get_deduplication_stats():
    """
    Get news deduplication statistics
    """
    try:
        deduplicator = NewsDeduplicator()
        stats = await deduplicator.get_deduplication_stats()
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting deduplication stats: {str(e)}")

@app.post("/api/news/deduplication/clean")
async def clean_duplicate_news(dry_run: bool = Query(True, description="预览模式，不实际删除")):
    """
    Clean duplicate news articles
    """
    try:
        deduplicator = NewsDeduplicator()
        result = await deduplicator.clean_duplicates(dry_run=dry_run)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cleaning duplicates: {str(e)}")

# ================ LLM PROCESSING API ENDPOINTS ================

@app.post("/api/news/analyze")
async def analyze_news_content(
    title: str = Form(..., description="新闻标题"),
    content: str = Form(..., description="新闻内容"),
    url: Optional[str] = Form(None, description="新闻URL")
):
    """
    Analyze news content using LLM
    """
    try:
        async with LLMNewsProcessor() as llm_processor:
            result = await llm_processor.analyze_news(title, content, url)
            
            if result:
                return {
                    "status": "success",
                    "analysis": llm_processor.to_dict(result)
                }
            else:
                return {
                    "status": "failed",
                    "message": "Analysis failed"
                }
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing news: {str(e)}")

@app.post("/api/news/backfill")
async def backfill_news_content(
    limit: int = Query(50, ge=1, le=500, description="每次处理的最大文章数"),
    only_missing_summary: bool = Query(True, description="仅处理缺少摘要的文章"),
    only_missing_content: bool = Query(True, description="仅处理缺少内容的文章"),
    concurrency: int = Query(5, ge=1, le=20, description="并发抓取与分析的协程数上限"),
    refresh_placeholders: bool = Query(True, description="如果摘要或正文包含占位符/垃圾文本则强制重抓与重生"),
    force_refresh: bool = Query(False, description="即使已存在也强制刷新摘要与结构化分析"),
    offset: int = Query(0, ge=0, description="当 force_refresh=true 时支持分页处理的偏移量"),
    fix_mismatches: bool = Query(True, description="检测到摘要与正文不一致时自动重生摘要/重抓内容"),
    mismatch_threshold: float = Query(0.25, ge=0.0, le=1.0, description="摘要与正文的一致性最低大ram-Jaccard阈值"),
    content_sample_len: int = Query(220, ge=50, le=1000, description="计算一致性的正文抽样长度（取前N字符）"),
    short_content_threshold: int = Query(60, ge=20, le=300, description="如果正文长度低于该值将视为需要重抓"),
    ids: Optional[str] = Query(None, description="可选，逗号分隔的文章ID列表，仅处理这些ID"),
    skip_non_article: bool = Query(True, description="跳过非新闻文章URL（如/quote、/equities等）。设为false则强制尝试处理"),
    use_llm: bool = Query(False, description="是否在补齐时调用 LLM 生成摘要与结构化分析（默认关闭以加速并避免请求超时）"),
    # 控制整体执行时长与 HTTP 超时，避免长时间阻塞
    max_duration_sec: int = Query(20, ge=5, le=120, description="本次补齐的最大执行时长（秒），达到后提前返回"),
    request_timeout_sec: float = Query(10.0, ge=3.0, le=60.0, description="抓取单条内容时的 HTTP 请求超时（秒）")
):
    """
    Backfill existing news articles with missing content/summary using crawler + LLM (if enabled).
    """
    try:
        session = next(get_db())
        processed = 0
        updated_summary = 0
        updated_content = 0
        skipped = 0

        # Build base query
        q = select(NewsArticle).order_by(NewsArticle.published_at.desc().nullslast())
        conditions = []
        # Filter by IDs if provided
        if ids:
            try:
                id_list = [int(x.strip()) for x in ids.split(',') if x.strip().isdigit()]
                if id_list:
                    from sqlalchemy import or_
                    conditions.append(NewsArticle.id.in_(id_list))
            except Exception:
                pass
        if only_missing_summary and not force_refresh:
            conditions.append((NewsArticle.summary.is_(None)) | (NewsArticle.summary == ""))
        if only_missing_content and not force_refresh:
            conditions.append((NewsArticle.content.is_(None)) | (NewsArticle.content == ""))
        if conditions:
            from sqlalchemy import or_
            q = q.where(or_(*conditions))

        # 支持分页（主要用于 force_refresh 扫描全库场景）
        q = q.offset(offset).limit(limit)

        articles = session.execute(q).scalars().all()
        if not articles:
            return {"status": "ok", "processed": 0, "message": "没有需要补充的文章"}

        # 配置本次处理的 HTTP 超时
        processor = NewsProcessor()
        try:
            processor._http_timeout = float(request_timeout_sec)
        except Exception:
            pass
        # 覆盖默认的 LLM 行为：本端点缺省不使用 LLM，除非显式传入 use_llm=true
        try:
            processor._use_llm = bool(use_llm)
        except Exception:
            pass
        import time as _time
        started_ts = _time.time()

        # Helpers for mismatch detection
        def _bigrams(text: str) -> set:
            t = (text or "").lower()
            import re
            t = re.sub(r"\s+", " ", t)
            return {t[i:i+2] for i in range(len(t)-1)} if len(t) >= 2 else set()

        def jaccard(a: str, b: str) -> float:
            A, B = _bigrams(a), _bigrams(b)
            if not A or not B:
                return 0.0
            inter = len(A & B)
            union = len(A | B)
            return (inter / union) if union else 0.0

        # Process concurrently with semaphore
        import asyncio as _asyncio
        sem = _asyncio.Semaphore(concurrency)

        placeholder_markers = [
            "请启用javascript", "enable javascript", "document", "cookie", "隐私", "验证码", "正在跳转", "安全验证"
        ]

        def has_placeholder(s: str | None) -> bool:
            if not s:
                return False
            lower = s.strip().lower()
            return any(m in lower for m in placeholder_markers)

        def is_empty(s: str | None) -> bool:
            return (s is None) or (isinstance(s, str) and len(s.strip()) == 0)

        async def handle_article(art):
            nonlocal updated_content, updated_summary, processed, skipped
            async with sem:
                try:
                    # 退出条件：达到本次最大执行时长
                    import time as __t
                    if (__t.time() - started_ts) >= max_duration_sec:
                        return
                    # Skip non-article-like URLs to avoid empty content/summary loops
                    if skip_non_article and not processor._is_article_like_url(art.url or ""):
                        skipped += 1
                        return
                    # Fetch content if missing
                    need_content = (
                        (only_missing_content and (not art.content or not art.content.strip()))
                        or (not only_missing_content and not art.content)
                        or (force_refresh)
                        or (refresh_placeholders and (has_placeholder(art.content) or (isinstance(art.content, str) and len(art.content.strip()) < short_content_threshold)))
                    )
                    if need_content:
                        soup = await processor._fetch_soup(art.url)
                        content = await processor._extract_content(art.url, soup)
                        if content:
                            # Repair potential mojibake to improve CN ratio/readability
                            try:
                                content = processor._maybe_fix_mojibake(content)
                            except Exception:
                                pass
                            art.content = content
                            updated_content += 1

                    # Generate/refresh summary (and structured fields) if missing or if content updated
                    need_summary = (
                        (only_missing_summary and (not art.summary or not art.summary.strip()))
                        or (not only_missing_summary and not art.summary)
                        or force_refresh
                        or (refresh_placeholders and has_placeholder(art.summary))
                    )
                    # Also trigger refresh when mismatch detected
                    if fix_mismatches and isinstance(art.summary, str) and isinstance(art.content, str):
                        try:
                            content_slice = art.content.strip()[:content_sample_len]
                            sim = jaccard(art.summary.strip(), content_slice)
                            if sim < mismatch_threshold:
                                need_summary = True
                                if len(content_slice) < short_content_threshold:
                                    try:
                                        soup = await processor._fetch_soup(art.url)
                                        content2 = await processor._extract_content(art.url, soup)
                                        if content2 and content2.strip() != (art.content or "").strip():
                                            art.content = content2
                                            updated_content += 1
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    if need_summary or need_content:
                        llm_summary = None
                        if getattr(processor, "_use_llm", False):
                            try:
                                from .news.llm_processor import LLMNewsProcessor
                                async with LLMNewsProcessor() as llm:
                                    res = await llm.analyze_news(title=art.title or "", content=art.content or "", url=art.url)
                                    if res:
                                        # Persist extended analysis
                                        llm_summary = res.summary or None
                                        # Sentiment
                                        art.sentiment_type = res.sentiment_type or art.sentiment_type
                                        art.sentiment_score = res.sentiment_score or art.sentiment_score
                                        art.sentiment_confidence = res.sentiment_confidence or art.sentiment_confidence
                                        # Keywords
                                        art.keywords = (res.keywords or [])[:15]
                                        # Entities bundle (store extended fields inside entities JSON)
                                        art.entities = {
                                            "companies": res.companies or [],
                                            "people": res.people or [],
                                            "locations": res.locations or [],
                                            "financial_metrics": res.financial_metrics or {},
                                            "main_topics": (res.main_topics or [])[:5],
                                            "time_references": res.time_references or [],
                                            "reliability_assessment": res.reliability_assessment or None,
                                            "market_impact": res.market_impact or None,
                                        }
                                        # Related stocks merge
                                        merged = set(art.related_stocks or [])
                                        for s in (res.stock_symbols or []):
                                            merged.add(s)
                                        art.related_stocks = list(merged) if merged else None
                                        # Category & quality & relevance
                                        art.category = res.category or art.category
                                        art.relevance_score = res.relevance_score or art.relevance_score
                                        art.content_quality = res.content_quality or art.content_quality
                            except Exception as _e:
                                llm_summary = None
                        art.summary = llm_summary or processor._generate_summary(art.content or "")
                        updated_summary += 1
                except Exception as e:
                    print(f"Backfill failed for {art.id} {art.url}: {e}")
                finally:
                    processed += 1

        await _asyncio.gather(*(handle_article(a) for a in articles))

        session.commit()

        return {
            "status": "ok",
            "processed": processed,
            "updated_content": updated_content,
            "updated_summary": updated_summary,
            "skipped": skipped,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error backfilling news: {str(e)}")

@app.get("/api/news/metrics")
def get_news_metrics(db: Session = Depends(get_db)):
    """Return runtime counters and basic DB aggregates for news quality/volume."""
    try:
        runtime = NewsMetrics.snapshot()
        # DB aggregates
        # Note: simple counts; avoid heavy queries
        totals = {
            "articles_total": db.execute(text("SELECT COUNT(*) FROM news_articles")).scalar() or 0,
            "articles_with_content": db.execute(text("SELECT COUNT(*) FROM news_articles WHERE content IS NOT NULL AND length(trim(content)) > 0")).scalar() or 0,
            "articles_with_summary": db.execute(text("SELECT COUNT(*) FROM news_articles WHERE summary IS NOT NULL AND length(trim(summary)) > 0")).scalar() or 0,
            "articles_duplicates": db.execute(text("SELECT COUNT(*) FROM news_articles WHERE is_duplicate = TRUE")).scalar() or 0,
            "sources_total": db.execute(text("SELECT COUNT(*) FROM news_sources")).scalar() or 0,
        }
        return {"runtime": runtime, "totals": totals}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"metrics error: {e}")

class URLPatternIn(BaseModel):
    kind: str  # 'block' or 'allow'
    scope: str = "substring"  # 'substring' or 'regex' (only 'substring' supported in processor)
    pattern: str
    host: Optional[str] = None
    enabled: bool = True
    notes: Optional[str] = None

@app.get("/api/news/url-filters")
def list_url_filters(db: Session = Depends(get_db)):
    try:
        rows = db.execute(select(NewsURLPattern).order_by(NewsURLPattern.id.desc())).scalars().all()
        return {
            "filters": [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "scope": r.scope,
                    "host": r.host,
                    "pattern": r.pattern,
                    "enabled": r.enabled,
                    "notes": r.notes,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list url filters error: {e}")

@app.post("/api/news/url-filters")
def create_url_filter(payload: URLPatternIn, db: Session = Depends(get_db)):
    try:
        item = NewsURLPattern(
            kind=payload.kind,
            scope=payload.scope,
            host=(payload.host.strip() if payload.host else None),
            pattern=payload.pattern.strip(),
            enabled=payload.enabled,
            notes=payload.notes,
            updated_at=datetime.utcnow(),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        # Warm reload for processors
        try:
            news_processor.reload_url_filters(force=True)
        except Exception:
            pass
        return {"ok": True, "id": item.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"create url filter error: {e}")

@app.put("/api/news/url-filters/{item_id}")
def update_url_filter(item_id: int, payload: URLPatternIn, db: Session = Depends(get_db)):
    try:
        item = db.get(NewsURLPattern, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="not found")
        item.kind = payload.kind
        item.scope = payload.scope
        item.host = payload.host.strip() if payload.host else None
        item.pattern = payload.pattern.strip()
        item.enabled = payload.enabled
        item.notes = payload.notes
        item.updated_at = datetime.utcnow()
        db.commit()
        # Reload
        try:
            news_processor.reload_url_filters(force=True)
        except Exception:
            pass
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"update url filter error: {e}")

@app.delete("/api/news/url-filters/{item_id}")
def delete_url_filter(item_id: int, db: Session = Depends(get_db)):
    try:
        item = db.get(NewsURLPattern, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="not found")
        db.delete(item)
        db.commit()
        try:
            news_processor.reload_url_filters(force=True)
        except Exception:
            pass
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"delete url filter error: {e}")

class CleanupRequest(BaseModel):
    """Cleanup request payload for article auditing and correction."""
    symbol: str = Field(..., description="指定股票代码，例如 300251.SZ")
    company_name: Optional[str] = Field(None, description="可选，公司名称，帮助提升相关性判断")
    dry_run: bool = Field(True, description="预览模式，仅返回将执行的操作，不更改数据库")
    limit: int = Field(100, ge=1, le=1000, description="每次处理的文章数量上限")
    offset: int = Field(0, ge=0, description="分页偏移")
    blacklist_non_cn: bool = Field(True, description="将非中文文章加入URL黑名单")
    blacklist_unrelated: bool = Field(True, description="将与指定股票无关的文章加入URL黑名单")
    delete_blacklisted: bool = Field(True, description="对判定为黑名单的文章从库中删除")
    refresh_relevant: bool = Field(True, description="对相关文章重新抓取内容并用LLM重生摘要/结构化字段")
    check_summary_match: bool = Field(True, description="校验摘要与正文一致性，不一致则重生摘要")
    max_concurrency: int = Field(5, ge=1, le=20, description="并发处理上限")

@app.post("/api/news/cleanup")
async def cleanup_news(payload: CleanupRequest, db: Session = Depends(get_db)):
    """清理与指定股票无关或低质量的新闻，并刷新相关新闻的内容与摘要。

    步骤：
    - 选择一批文章（按发布时间倒序，分页）
    - 语言检测（中文占比）与A股相关性判断；不合格加入URL黑名单（可选）并删除（可选）
    - 对相关文章：必要时重抓正文；可选校验摘要与正文一致性；用LLM提取结构化观点并更新摘要
    - 支持dry_run预览
    """
    try:
        symbol = payload.symbol.upper().strip()
        company_name = (payload.company_name or "").strip()

        # 选取待处理文章（最新优先）
        q = select(NewsArticle).order_by(NewsArticle.published_at.desc().nullslast())
        q = q.offset(payload.offset).limit(payload.limit)
        rows: list[NewsArticle] = db.execute(q).scalars().all()
        if not rows:
            return {"status": "ok", "processed": 0, "blacklisted": 0, "deleted": 0, "refreshed": 0}

        processor = NewsProcessor()

        # Helpers
        def _bigrams(text: str) -> set[str]:
            t = (text or "").lower()
            import re as _re
            t = _re.sub(r"\s+", " ", t)
            return {t[i:i+2] for i in range(len(t)-1)} if len(t) >= 2 else set()

        def jaccard(a: str, b: str) -> float:
            A, B = _bigrams(a), _bigrams(b)
            if not A or not B:
                return 0.0
            inter = len(A & B)
            union = len(A | B)
            return (inter / union) if union else 0.0

        def looks_related(a: NewsArticle, content_text: str) -> bool:
            # 强相关：related_stocks包含；标题/正文含有 6位代码或symbol或公司名
            try:
                if a.related_stocks and isinstance(a.related_stocks, list) and symbol in a.related_stocks:
                    return True
            except Exception:
                pass
            import re as _re
            base = symbol.replace(".SH", "").replace(".SZ", "")
            text = f"{a.title or ''} {content_text or ''}".lower()
            if base and _re.search(rf"\b{_re.escape(base)}\b", text):
                return True
            if symbol.lower() in text:
                return True
            if company_name and company_name.lower() in text:
                return True
            # fallback到A股通用相关性判断
            return processor._is_relevant_to_a_share(a.title or "", content_text or "", a.url or "", hint_symbol=symbol)

        # 并发处理
        import asyncio as _asyncio
        sem = _asyncio.Semaphore(payload.max_concurrency)

        actions = {"blacklisted": [], "deleted": [], "refreshed": [], "kept": []}

        async def handle_article(a: NewsArticle):
            async with sem:
                nonlocal db
                url = a.url or ""
                title = a.title or ""
                # 语言与相关性预判（使用已有正文或标题）
                content_text = a.content or ""
                cn_ratio = processor._chinese_ratio(f"{title} {content_text}")
                relevant = looks_related(a, content_text)

                to_blacklist = False
                reason = None
                if payload.blacklist_non_cn and (cn_ratio < processor._min_cn_ratio) and not processor._force_allow_non_cn:
                    to_blacklist = True
                    reason = "non_chinese"
                elif payload.blacklist_unrelated and not relevant:
                    to_blacklist = True
                    reason = "unrelated"

                # Blacklist + optional delete
                if to_blacklist:
                    if not payload.dry_run:
                        # Insert URL block pattern (exact URL as substring)
                        try:
                            host = urlparse(url).netloc if url else None
                            blk = NewsURLPattern(
                                kind="block",
                                scope="substring",
                                host=host,
                                pattern=url,
                                enabled=True,
                                notes=f"auto-cleanup: {reason} for {symbol}"
                            )
                            db.add(blk)
                            db.commit()
                        except Exception:
                            db.rollback()
                    actions["blacklisted"].append({"id": a.id, "url": url, "reason": reason})
                    if payload.delete_blacklisted and not payload.dry_run:
                        try:
                            db.delete(a)
                            db.commit()
                        except Exception:
                            db.rollback()
                    if payload.delete_blacklisted:
                        actions["deleted"].append({"id": a.id, "url": url})
                    return

                # 对相关文章进行刷新（抓取内容+LLM重生）
                if payload.refresh_relevant:
                    try:
                        soup = await processor._fetch_soup(url)
                        new_content = await processor._extract_content(url, soup)
                        # 保留与股票更相关的段落（简单段落筛选）
                        if new_content:
                            paragraphs = [p.strip() for p in new_content.split("\n") if p.strip()]
                            base = symbol.replace(".SH", "").replace(".SZ", "")
                            def _keep(p: str) -> bool:
                                low = p.lower()
                                if symbol.lower() in low:
                                    return True
                                if company_name and company_name.lower() in low:
                                    return True
                                import re as _re
                                if base and _re.search(rf"\b{_re.escape(base)}\b", low):
                                    return True
                                return False
                            filtered = "\n".join([p for p in paragraphs if _keep(p)])
                            # 若筛选后过短，退回完整正文
                            if filtered and len(filtered) >= 60:
                                a.content = filtered[:8000]
                            elif new_content and len(new_content) >= 60:
                                a.content = new_content[:8000]
                        # 摘要匹配或重生
                        need_summary = payload.check_summary_match
                        if payload.check_summary_match and isinstance(a.summary, str) and isinstance(a.content, str):
                            sim = jaccard(a.summary.strip(), a.content.strip()[:220])
                            if sim >= 0.25:
                                need_summary = False
                        # 使用LLM生成/刷新
                        llm_summary = None
                        if getattr(processor, "_use_llm", False):
                            try:
                                from .news.llm_processor import LLMNewsProcessor
                                async with LLMNewsProcessor() as llm:
                                    res = await llm.analyze_news(title=title, content=a.content or new_content or "", url=url)
                                    if res:
                                        llm_summary = res.summary or None
                                        a.sentiment_type = res.sentiment_type or a.sentiment_type
                                        a.sentiment_score = res.sentiment_score or a.sentiment_score
                                        a.sentiment_confidence = res.sentiment_confidence or a.sentiment_confidence
                                        a.keywords = (res.keywords or [])[:15]
                                        a.entities = {
                                            "companies": res.companies or [],
                                            "people": res.people or [],
                                            "locations": res.locations or [],
                                            "financial_metrics": res.financial_metrics or {},
                                            "main_topics": (res.main_topics or [])[:5],
                                            "time_references": res.time_references or [],
                                            "reliability_assessment": res.reliability_assessment or None,
                                            "market_impact": res.market_impact or None,
                                        }
                                        merged = set(a.related_stocks or [])
                                        for s in (res.stock_symbols or []):
                                            merged.add(s)
                                        a.related_stocks = list(merged) if merged else None
                                        a.category = res.category or a.category
                                        a.relevance_score = res.relevance_score or a.relevance_score
                                        a.content_quality = res.content_quality or a.content_quality
                            except Exception:
                                llm_summary = None
                        if need_summary or (llm_summary is not None):
                            a.summary = llm_summary or processor._generate_summary(a.content or new_content or "")
                        if not payload.dry_run:
                            db.add(a)
                            db.commit()
                        actions["refreshed"].append({"id": a.id, "url": url})
                    except Exception:
                        # 忽略单条错误以便继续批处理
                        if not payload.dry_run:
                            db.rollback()
                        actions["kept"].append({"id": a.id, "url": url, "note": "refresh_failed"})
                        return
                else:
                    actions["kept"].append({"id": a.id, "url": url})

        await _asyncio.gather(*(handle_article(a) for a in rows))

        # 变更URL过滤器缓存
        try:
            news_processor.reload_url_filters(force=True)
        except Exception:
            pass

        return {
            "status": "ok",
            "processed": len(rows),
            "blacklisted": len(actions["blacklisted"]),
            "deleted": len(actions["deleted"]),
            "refreshed": len(actions["refreshed"]),
            "kept": len(actions["kept"]),
            "actions": actions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cleanup error: {e}")

@app.get("/api/news/categories")
async def get_news_categories():
    """
    Get all available news categories
    """
    return {
        "categories": [category.value for category in NewsCategory]
    }

@app.get("/api/news/sentiment-types")
async def get_sentiment_types():
    """
    Get all available sentiment types
    """
    return {
        "sentiment_types": [sentiment.value for sentiment in SentimentType]
    }

@app.get("/api/news/strategies/test")
async def test_strategies():
    """
    Test endpoint for strategies generation
    """
    try:
        from .news.news_strategy import IntelligentNewsCollector
        
        collector = IntelligentNewsCollector()
        strategies = await collector.generate_strategies()
        
        return {
            "message": "Test successful",
            "strategies_count": len(strategies),
            "strategies": [s.name for s in strategies]
        }
        
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.get("/api/news/strategies")
async def get_news_strategies():
    """
    Get available news collection strategies
    """
    try:
        from .news.news_strategy import IntelligentNewsCollector
        
        collector = IntelligentNewsCollector()
        strategies = await collector.generate_strategies()
        
        return {
            "strategies": [
                {
                    "name": strategy.name,
                    "keywords": strategy.keywords,
                    "frequency_hours": strategy.search_frequency,
                    "priority": strategy.priority,
                    "category": strategy.category,
                    "search_params": strategy.search_params
                }
                for strategy in strategies
            ],
            "total_strategies": len(strategies)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching strategies: {str(e)}")

@app.post("/api/news/strategies/execute/{strategy_name}")
async def execute_news_strategy(strategy_name: str):
    """
    Execute a specific news strategy by name
    """
    try:
        from .news.news_strategy import IntelligentNewsCollector
        
        collector = IntelligentNewsCollector()
        strategies = await collector.generate_strategies()
        
        # Find the strategy
        target_strategy = None
        for strategy in strategies:
            if strategy.name == strategy_name:
                target_strategy = strategy
                break
        
        if not target_strategy:
            raise HTTPException(status_code=404, detail=f"Strategy '{strategy_name}' not found")
        
        result = await collector.execute_strategy(target_strategy)
        
        return {
            "message": f"Strategy '{strategy_name}' executed",
            "result": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing strategy: {str(e)}")

@app.get("/api/news/sentiment/{symbol}")
async def get_stock_sentiment(symbol: str, db: Session = Depends(get_db), days: int = Query(7, ge=1, le=30)):
    """
    Get sentiment analysis for a stock over time
    """
    try:
        from datetime import datetime, timedelta
        
        since_date = datetime.utcnow() - timedelta(days=days)
        
        query = select(NewsArticle).where(
            and_(
                NewsArticle.related_stocks.contains([symbol]),
                NewsArticle.published_at >= since_date,
                NewsArticle.sentiment_score.isnot(None)
            )
        ).order_by(NewsArticle.published_at.desc())
        
        articles = db.execute(query).scalars().all()
        
        if not articles:
            return {
                "symbol": symbol,
                "period_days": days,
                "sentiment_summary": {
                    "average_score": 0,
                    "positive_count": 0,
                    "negative_count": 0,
                    "neutral_count": 0,
                    "total_articles": 0
                },
                "daily_sentiment": []
            }
        
        # Calculate sentiment metrics
        positive_count = sum(1 for a in articles if a.sentiment_type == SentimentType.POSITIVE.value)
        negative_count = sum(1 for a in articles if a.sentiment_type == SentimentType.NEGATIVE.value)
        neutral_count = sum(1 for a in articles if a.sentiment_type == SentimentType.NEUTRAL.value)
        
        avg_score = sum(a.sentiment_score for a in articles if a.sentiment_score) / len(articles)
        
        # Group by day
        daily_sentiment = {}
        for article in articles:
            if article.published_at:
                day = article.published_at.date().isoformat()
                if day not in daily_sentiment:
                    daily_sentiment[day] = []
                daily_sentiment[day].append(article.sentiment_score)
        
        # Calculate daily averages
        daily_data = []
        for day, scores in daily_sentiment.items():
            avg_day_score = sum(score for score in scores if score is not None) / len(scores)
            daily_data.append({
                "date": day,
                "average_sentiment": avg_day_score,
                "article_count": len(scores)
            })
        
        daily_data.sort(key=lambda x: x["date"])
        
        return {
            "symbol": symbol,
            "period_days": days,
            "sentiment_summary": {
                "average_score": round(avg_score, 3),
                "positive_count": positive_count,
                "negative_count": negative_count,
                "neutral_count": neutral_count,
                "total_articles": len(articles)
            },
            "daily_sentiment": daily_data,
            "recent_articles": [
                {
                    "title": article.title,
                    "sentiment_type": article.sentiment_type,
                    "sentiment_score": article.sentiment_score,
                    "published_at": article.published_at.isoformat() if article.published_at else None,
                    "url": article.url
                }
                for article in articles[:10]
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing sentiment: {str(e)}")

# ================ MONGODB STORAGE API ENDPOINTS ================

class MongoNewsRequest(BaseModel):
    stock_symbol: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: Optional[int] = 100
    min_relevance: Optional[float] = 0.0

@app.get("/api/storage/stock-news/{stock_symbol}")
async def get_stock_news_from_mongo(
    stock_symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    min_relevance: float = Query(0.0, ge=0.0, le=1.0)
):
    """
    Get stock-specific news from MongoDB archive
    获取特定股票的新闻存档
    """
    try:
        storage = await get_storage()
        if storage is None:
            raise HTTPException(status_code=503, detail="MongoDB storage is not available")
        
        # Parse dates
        start_dt = datetime.fromisoformat(start_date) if start_date else None
        end_dt = datetime.fromisoformat(end_date) if end_date else None
        
        news_data = await storage.get_stock_news(
            stock_symbol=stock_symbol,
            start_date=start_dt,
            end_date=end_dt,
            limit=limit,
            min_relevance=min_relevance
        )
        
        return {
            "status": "success",
            "stock_symbol": stock_symbol.upper(),
            "count": len(news_data),
            "news": news_data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving stock news: {str(e)}")

@app.get("/api/storage/stock-statistics/{stock_symbol}")
async def get_stock_news_statistics(
    stock_symbol: str,
    days: int = Query(30, ge=1, le=365)
):
    """
    Get stock news statistics from MongoDB
    获取股票新闻统计信息
    """
    try:
        storage = await get_storage()
        if storage is None:
            raise HTTPException(status_code=503, detail="MongoDB storage is not available")
        
        statistics = await storage.get_stock_statistics(
            stock_symbol=stock_symbol,
            days=days
        )
        
        return {
            "status": "success",
            "statistics": statistics
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving statistics: {str(e)}")

@app.post("/api/storage/cleanup")
async def cleanup_old_data(
    days_to_keep: int = Query(90, ge=7, le=365)
):
    """
    Clean up old data from MongoDB
    清理MongoDB中的旧数据
    """
    try:
        storage = await get_storage()
        if storage is None:
            raise HTTPException(status_code=503, detail="MongoDB storage is not available")
        
        success = await storage.cleanup_old_data(days_to_keep=days_to_keep)
        
        return {
            "status": "success" if success else "failed",
            "message": f"Cleanup completed for data older than {days_to_keep} days"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during cleanup: {str(e)}")

@app.get("/api/storage/check-duplicate")
async def check_news_duplicate(
    url: Optional[str] = Query(None),
    content_hash: Optional[str] = Query(None)
):
    """
    Check if content is duplicate in MongoDB
    检查内容是否为重复
    """
    try:
        if not url and not content_hash:
            raise HTTPException(status_code=400, detail="Either url or content_hash must be provided")
        
        storage = await get_storage()
        if storage is None:
            raise HTTPException(status_code=503, detail="MongoDB storage is not available")
        
        is_duplicate = await storage.check_duplicate(
            url=url,
            content_hash=content_hash
        )
        
        return {
            "status": "success",
            "is_duplicate": is_duplicate,
            "url": url,
            "content_hash": content_hash
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error checking duplicate: {str(e)}")


# ========================
# Stock Profile 验证 API
# ========================

@app.get("/api/profile/validate/{symbol}")
async def validate_stock_profile(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    验证单个股票的 Profile
    检查公司是否仍存在、是否正常运营、是否存在风险
    """
    try:
        from backend.app.stock_profile_validator import StockProfileValidator
        
        # 查询 Profile
        query = select(StockProfile).where(StockProfile.symbol == symbol)
        profile = db.execute(query).scalar_one_or_none()
        
        if not profile:
            raise HTTPException(status_code=404, detail=f"Profile not found for {symbol}")
        
        # 执行验证
        validator = StockProfileValidator(db)
        status, reason = validator.validate_profile(profile)
        
        # 更新数据库
        profile.validation_status = status
        profile.validation_reason = reason
        profile.last_validated_at = datetime.utcnow()
        profile.is_valid = (status == "valid")
        
        db.add(profile)
        db.commit()
        
        return {
            "status": "success",
            "symbol": symbol,
            "validation_status": status,
            "is_valid": profile.is_valid,
            "validation_reason": reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Profile 验证失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Validation error: {str(e)}")


@app.post("/api/profile/validate-batch")
async def validate_batch_profiles(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    批量验证 Profiles
    可指定验证数量和起始位置
    """
    try:
        from backend.app.stock_profile_validator import StockProfileValidator
        
        # 查询需要验证的 Profiles
        query = select(StockProfile).limit(limit).offset(offset)
        profiles = db.execute(query).scalars().all()
        
        if not profiles:
            raise HTTPException(status_code=404, detail="No profiles found")
        
        # 批量验证
        validator = StockProfileValidator(db)
        results = validator.batch_validate_profiles(profiles, update_db=True)
        
        return {
            "status": "success",
            "results": results,
            "profiles_validated": len(profiles)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 批量验证失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch validation error: {str(e)}")


@app.get("/api/profile/invalid-list")
async def get_invalid_profiles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    获取所有被标记为无效（is_valid=false）的 Profiles
    用于前端展示需要清理的股票列表
    """
    try:
        from sqlalchemy import func
        
        # 查询无效的 Profiles
        query = select(StockProfile).where(StockProfile.is_valid == False)
        
        # 获取总数
        total_query = select(func.count(StockProfile.id)).where(StockProfile.is_valid == False)
        total = db.execute(total_query).scalar() or 0
        
        # 分页查询
        offset = (page - 1) * page_size
        profiles = db.execute(query.offset(offset).limit(page_size)).scalars().all()
        
        invalid_list = []
        for profile in profiles:
            invalid_list.append({
                "symbol": profile.symbol,
                "company_name": profile.company_name,
                "validation_status": profile.validation_status,
                "validation_reason": profile.validation_reason,
                "last_validated_at": profile.last_validated_at.isoformat() if profile.last_validated_at else None,
                "industry": profile.industry
            })
        
        return {
            "status": "success",
            "page": page,
            "page_size": page_size,
            "total": total,
            "count": len(profiles),
            "invalid_profiles": invalid_list
        }
        
    except Exception as e:
        logger.error(f"❌ 获取无效 Profiles 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/profile/mark-invalid")
async def mark_profile_invalid(
    request: dict,
    db: Session = Depends(get_db)
):
    """
    手动标记一个或多个 Profile 为无效
    
    请求体:
    {
        "symbols": ["600519.SH", "000001.SZ", ...],
        "reason": "公司已停止运营"
    }
    """
    try:
        from backend.app.stock_profile_validator import StockProfileValidator
        
        symbols = request.get("symbols", [])
        reason = request.get("reason", "未指定原因")
        
        if not symbols:
            raise HTTPException(status_code=400, detail="symbols list is required")
        
        validator = StockProfileValidator(db)
        results = {
            "success": [],
            "failed": []
        }
        
        for symbol in symbols:
            try:
                success = validator.mark_invalid(symbol, reason)
                if success:
                    results["success"].append(symbol)
                else:
                    results["failed"].append({"symbol": symbol, "error": "Profile not found"})
            except Exception as e:
                results["failed"].append({"symbol": symbol, "error": str(e)})
        
        return {
            "status": "success",
            "marked_invalid": len(results["success"]),
            "failed": len(results["failed"]),
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 标记失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/profile/restore")
async def restore_profile(
    request: dict,
    db: Session = Depends(get_db)
):
    """
    恢复被标记为无效的 Profile
    
    请求体:
    {
        "symbols": ["600519.SH", "000001.SZ", ...]
    }
    """
    try:
        from backend.app.stock_profile_validator import StockProfileValidator
        
        symbols = request.get("symbols", [])
        
        if not symbols:
            raise HTTPException(status_code=400, detail="symbols list is required")
        
        validator = StockProfileValidator(db)
        results = {
            "success": [],
            "failed": []
        }
        
        for symbol in symbols:
            try:
                success = validator.restore_profile(symbol)
                if success:
                    results["success"].append(symbol)
                else:
                    results["failed"].append({"symbol": symbol, "error": "Profile not found"})
            except Exception as e:
                results["failed"].append({"symbol": symbol, "error": str(e)})
        
        return {
            "status": "success",
            "restored": len(results["success"]),
            "failed": len(results["failed"]),
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 恢复失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.delete("/api/profile/delete-invalid")
async def delete_invalid_profiles(
    request: dict,
    db: Session = Depends(get_db)
):
    """
    删除被标记为无效的 Profiles（只能删除 is_valid=false 的）
    只有标记为无效的 Profile 才可以被删除
    
    请求体:
    {
        "symbols": ["600519.SH", "000001.SZ", ...],
        "confirm": true  // 必须明确确认
    }
    """
    try:
        symbols = request.get("symbols", [])
        confirm = request.get("confirm", False)
        
        if not symbols or not confirm:
            raise HTTPException(status_code=400, detail="symbols list and confirm flag are required")
        
        deleted_count = 0
        failed_list = []
        
        for symbol in symbols:
            try:
                # 查询 Profile
                query = select(StockProfile).where(StockProfile.symbol == symbol)
                profile = db.execute(query).scalar_one_or_none()
                
                if not profile:
                    failed_list.append({"symbol": symbol, "error": "Profile not found"})
                    continue
                
                # 检查是否为无效状态
                if profile.is_valid:
                    failed_list.append({"symbol": symbol, "error": "Profile is still valid, cannot delete"})
                    continue
                
                # 删除 Profile
                db.delete(profile)
                deleted_count += 1
                
            except Exception as e:
                failed_list.append({"symbol": symbol, "error": str(e)})
        
        # 提交删除
        db.commit()
        
        return {
            "status": "success",
            "deleted": deleted_count,
            "failed": len(failed_list),
            "failed_list": failed_list,
            "message": f"Successfully deleted {deleted_count} profiles"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 删除失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
