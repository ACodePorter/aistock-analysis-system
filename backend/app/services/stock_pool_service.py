"""
股票池管理服务

提供股票池的增删查改、自动化 Top20 入池、历史回填与 Profile 自动充填功能。
"""

import logging
import threading
import time as _time
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..core.models import StockPoolMember, StockProfile, PriceDaily
from ..data.data_source import normalize_symbol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 股票名录缓存（避免每次搜索都调 AKShare 远程）
# ---------------------------------------------------------------------------

_stock_list_cache: dict = {"data": None, "ts": 0.0, "ttl": 3600}  # 1 小时 TTL


_stock_list_loading = threading.Event()


def _get_stock_list():
    """获取全量 A 股代码 + 名称列表（带缓存）。

    优先从 AKShare 加载，失败时从数据库 StockProfile 表读取作为后备。
    若后台正在加载，最多等待 35 秒。
    """
    # 若有缓存且未过期，直接返回
    now = _time.time()
    if _stock_list_cache["data"] is not None and (now - _stock_list_cache["ts"]) < _stock_list_cache["ttl"]:
        return _stock_list_cache["data"]

    # 若后台正在加载，等待完成
    if _stock_list_loading.is_set():
        logger.info("[StockPool] waiting for background stock list load...")
        for _ in range(35):
            _time.sleep(1)
            if _stock_list_cache["data"] is not None:
                return _stock_list_cache["data"]

    _stock_list_loading.set()
    try:
        records = _fetch_stock_list_akshare()
        if records:
            _stock_list_cache["data"] = records
            _stock_list_cache["ts"] = _time.time()
            logger.info("[StockPool] stock list cached from AKShare: %d entries", len(records))
            return records

        records = _fetch_stock_list_from_db()
        if records:
            _stock_list_cache["data"] = records
            _stock_list_cache["ts"] = _time.time()
            logger.info("[StockPool] stock list cached from DB: %d entries", len(records))
            return records
    finally:
        _stock_list_loading.clear()

    return _stock_list_cache["data"] or []


def _fetch_stock_list_akshare() -> list[dict]:
    """从 AKShare 获取 A 股名录，最长等 120 秒。

    策略：优先 stock_info_a_code_name()，失败则分别从沪/深/北三所拉取并合并。
    """
    result_box: list[list] = [[]]

    def _worker():
        from ..data.data_source import ak
        import re

        # Strategy 1: unified API
        try:
            df = ak.stock_info_a_code_name()
            if df is not None and len(df) > 1000:
                recs = []
                for _, row in df.iterrows():
                    recs.append({
                        "symbol": normalize_symbol(row["code"]),
                        "name": row["name"],
                        "code": row["code"],
                    })
                result_box[0] = recs
                logger.info("[StockPool] stock_info_a_code_name OK: %d", len(recs))
                return
        except Exception as e:
            logger.warning("[StockPool] stock_info_a_code_name failed: %s", e)

        # Strategy 2: merge SH + SZ + BSE
        seen = set()
        recs = []

        for board in ("主板A股", "科创板"):
            try:
                df = ak.stock_info_sh_name_code(symbol=board)
                for _, row in df.iterrows():
                    code = str(row["证券代码"]).strip()
                    if not re.fullmatch(r"\d{6}", code) or code in seen:
                        continue
                    seen.add(code)
                    recs.append({"symbol": normalize_symbol(code), "name": row.get("证券简称", ""), "code": code})
                logger.info("[StockPool] SH %s: %d", board, len(df))
            except Exception as e:
                logger.warning("[StockPool] SH %s failed: %s", board, e)

        try:
            df = ak.stock_info_sz_name_code(symbol="A股列表")
            for _, row in df.iterrows():
                code = str(row["A股代码"]).strip()
                if not re.fullmatch(r"\d{6}", code) or code in seen:
                    continue
                seen.add(code)
                recs.append({"symbol": normalize_symbol(code), "name": row.get("A股简称", ""), "code": code})
            logger.info("[StockPool] SZ A股列表: %d", len(df))
        except Exception as e:
            logger.warning("[StockPool] SZ A股列表 failed: %s", e)

        try:
            df = ak.stock_info_bj_name_code()
            for _, row in df.iterrows():
                code = str(row["证券代码"]).strip()
                if not re.fullmatch(r"\d{6}", code) or code in seen:
                    continue
                seen.add(code)
                recs.append({"symbol": normalize_symbol(code), "name": row.get("证券简称", ""), "code": code})
            logger.info("[StockPool] BSE: %d", len(df))
        except Exception as e:
            logger.warning("[StockPool] BSE failed: %s", e)

        if recs:
            result_box[0] = recs
            logger.info("[StockPool] merged stock list: %d entries", len(recs))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=120)
    return result_box[0]


def preload_stock_list():
    """启动时预加载 A 股名录到缓存（在后台线程执行）。"""
    def _run():
        _time.sleep(2)
        lst = _get_stock_list()
        logger.info("[StockPool] preload complete: %d entries", len(lst))
    threading.Thread(target=_run, daemon=True, name="pool-preload").start()


def _fetch_stock_list_from_db() -> list[dict]:
    """从数据库 StockProfile 表读取已有的股票列表。"""
    try:
        with SessionLocal() as session:
            profiles = session.query(StockProfile.symbol, StockProfile.company_name).all()
            return [
                {"symbol": p.symbol, "name": p.company_name or "", "code": p.symbol.replace(".SH", "").replace(".SZ", "")}
                for p in profiles
            ]
    except Exception as e:
        logger.warning("[StockPool] DB stock list fallback failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _safe_get_stock_info(symbol: str) -> Optional[dict]:
    """安全获取单只股票基本信息，失败返回 None（不抛异常）。"""
    try:
        from ..data.data_source import get_stock_info
        return get_stock_info(symbol)
    except Exception:
        return None


def _ensure_profile_stub(session: Session, symbol: str, company_name: Optional[str] = None):
    """确保 StockProfile 行存在（不存在则创建占位行）。同时修正无效名称。"""
    import re
    prof = session.query(StockProfile).filter(StockProfile.symbol == symbol).first()
    if prof:
        old_name = prof.company_name or ""
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', old_name))
        name_is_bad = not old_name or not has_chinese or '?' in old_name
        if company_name and name_is_bad:
            prof.company_name = company_name
        return prof
    prof = StockProfile(
        symbol=symbol,
        company_name=company_name,
        market="A股",
        created_at=datetime.utcnow(),
    )
    session.add(prof)
    session.flush()
    return prof


def _trigger_profile_enrichment_background(symbol: str, company_name: Optional[str] = None):
    """在后台线程中触发 Profile 充填（不阻塞、不崩溃）。"""
    def _run():
        try:
            from ..utils.stock_profile_enrichment import StockProfileEnricher
            enricher = StockProfileEnricher()
            with SessionLocal() as db:
                enricher.enrich_stock_profile_sync(symbol, company_name or symbol, db, force_refresh=False)
            logger.info("[StockPool] profile enrichment done: %s", symbol)
        except Exception as e:
            logger.warning("[StockPool] profile enrichment failed for %s: %s", symbol, e)

    t = threading.Thread(target=_run, daemon=True, name=f"pool-enrich-{symbol}")
    t.start()


# ---------------------------------------------------------------------------
# 核心服务函数
# ---------------------------------------------------------------------------

def add_to_pool(
    symbol: str,
    source: str = "manual",
    company_name: Optional[str] = None,
    notes: Optional[str] = None,
    session: Optional[Session] = None,
    enrich: bool = True,
) -> dict:
    """添加一只股票到股票池。

    Returns: {"action": "created"|"updated", "symbol": ..., "company_name": ...}
    """
    symbol = normalize_symbol(symbol)
    today = date.today()
    own_session = session is None
    if own_session:
        session = SessionLocal()

    try:
        existing = session.query(StockPoolMember).filter(StockPoolMember.symbol == symbol).first()

        if existing:
            existing.last_seen_date = today
            if existing.exit_date is not None:
                existing.exit_date = None
            if notes:
                existing.notes = notes
            session.commit()
            # 从 profile 拿名称用于返回
            if not company_name:
                prof = session.query(StockProfile).filter(StockProfile.symbol == symbol).first()
                if prof:
                    company_name = prof.company_name
            return {"action": "updated", "symbol": symbol, "company_name": company_name}

        # --- 新建 ---
        if not company_name:
            info = _safe_get_stock_info(symbol)
            if info:
                company_name = info.get("name") or info.get("company_name")

        # 尝试包含 source 字段；若数据库列尚未迁移，回退到不带 source 的写法
        try:
            member = StockPoolMember(
                symbol=symbol,
                first_seen_date=today,
                last_seen_date=today,
                source=source,
                notes=notes,
            )
            session.add(member)
            session.flush()
        except Exception:
            session.rollback()
            session.execute(
                text(
                    "INSERT INTO stock_pool_members (symbol, first_seen_date, last_seen_date, notes) "
                    "VALUES (:sym, :fs, :ls, :notes) ON CONFLICT DO NOTHING"
                ),
                {"sym": symbol, "fs": today, "ls": today, "notes": notes},
            )

        _ensure_profile_stub(session, symbol, company_name)
        session.commit()

        if enrich:
            _trigger_profile_enrichment_background(symbol, company_name)

        return {"action": "created", "symbol": symbol, "company_name": company_name}
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        raise
    finally:
        if own_session:
            session.close()


def remove_from_pool(symbol: str) -> bool:
    """将股票标记退出股票池（设置 exit_date）。仅对当前在池中的标的生效。"""
    symbol = normalize_symbol(symbol)
    with SessionLocal() as session:
        member = (
            session.query(StockPoolMember)
            .filter(StockPoolMember.symbol == symbol, StockPoolMember.exit_date.is_(None))
            .first()
        )
        if not member:
            return False
        member.exit_date = date.today()
        session.commit()
        return True


def search_stocks(query: str, limit: int = 20) -> list[dict]:
    """搜索 A 股股票（代码或名称），返回 [{symbol, name, code, in_pool}, ...]。

    搜索策略：
    1. 尝试从缓存的全量 A 股名录中匹配。
    2. 若名录为空，回退到数据库 StockProfile 表搜索。
    3. 若仍无结果且搜索词像股票代码，构造一个基本结果方便用户直接添加。
    """
    q_lower = query.lower().strip()
    if not q_lower:
        return []

    all_stocks = _get_stock_list()
    results: list[dict] = []

    if all_stocks:
        for s in all_stocks:
            if q_lower in s["code"].lower() or q_lower in (s.get("name") or "").lower():
                results.append(dict(s))
                if len(results) >= limit:
                    break

    # 回退：从 StockProfile DB 搜索
    if not results:
        try:
            with SessionLocal() as session:
                from sqlalchemy import or_
                db_results = (
                    session.query(StockProfile.symbol, StockProfile.company_name)
                    .filter(or_(
                        StockProfile.symbol.ilike(f"%{query}%"),
                        StockProfile.company_name.ilike(f"%{query}%"),
                    ))
                    .limit(limit)
                    .all()
                )
                for p in db_results:
                    results.append({
                        "symbol": p.symbol,
                        "name": p.company_name or "",
                        "code": p.symbol.replace(".SH", "").replace(".SZ", ""),
                    })
        except Exception:
            pass

    # 最后手段：若搜索词是纯数字（像股票代码），构造候选
    if not results and q_lower.replace(".", "").isdigit() and len(q_lower) >= 4:
        code = q_lower.replace(".", "")
        sym = normalize_symbol(code)
        info = _safe_get_stock_info(sym)
        name = ""
        if info:
            name = info.get("name") or info.get("company_name") or ""
        results.append({"symbol": sym, "name": name, "code": code})

    if not results:
        return []

    # 批量查询已在池中的标的
    symbols = [r["symbol"] for r in results]
    try:
        with SessionLocal() as session:
            in_pool_rows = (
                session.query(StockPoolMember.symbol)
                .filter(StockPoolMember.symbol.in_(symbols), StockPoolMember.exit_date.is_(None))
                .all()
            )
            in_pool_set = {r.symbol for r in in_pool_rows}
    except Exception:
        in_pool_set = set()

    for r in results:
        r["in_pool"] = r["symbol"] in in_pool_set
    return results


def get_pool_stats() -> dict:
    """返回股票池统计概览。"""
    with SessionLocal() as session:
        total = session.query(func.count(StockPoolMember.id)).filter(StockPoolMember.exit_date.is_(None)).scalar() or 0

        # source 列可能不存在，安全处理
        manual_count = 0
        try:
            manual_count = (
                session.query(func.count(StockPoolMember.id))
                .filter(StockPoolMember.exit_date.is_(None), StockPoolMember.source == "manual")
                .scalar() or 0
            )
        except Exception:
            pass

        auto_count = total - manual_count

        with_profile = (
            session.query(func.count(StockProfile.id))
            .join(StockPoolMember, StockPoolMember.symbol == StockProfile.symbol)
            .filter(StockPoolMember.exit_date.is_(None), StockProfile.business_summary.isnot(None))
            .scalar() or 0
        )
        latest_date = (
            session.query(func.max(StockPoolMember.last_seen_date))
            .filter(StockPoolMember.exit_date.is_(None))
            .scalar()
        )
    return {
        "total_active": total,
        "manual_count": manual_count,
        "auto_count": auto_count,
        "with_profile": with_profile,
        "profile_rate": round(with_profile / total * 100, 1) if total else 0,
        "latest_update": latest_date.isoformat() if latest_date else None,
    }


# ---------------------------------------------------------------------------
# 自动化：每日 Top20 入池
# ---------------------------------------------------------------------------

def _get_spot_snapshot():
    """获取全 A 股实时行情 DataFrame（代码/名称/涨跌幅）。

    尝试顺序: stock_zh_a_spot_em (fast) -> stock_zh_a_spot (slow but reliable)。
    """
    import pandas as pd
    from ..data.data_source import ak

    df = None
    for fn_name in ("stock_zh_a_spot_em", "stock_zh_a_spot"):
        try:
            fn = getattr(ak, fn_name)
            df = fn()
            if df is not None and not df.empty:
                logger.info("[StockPool] snapshot from %s: %d rows", fn_name, len(df))
                break
            df = None
        except Exception as e:
            logger.warning("[StockPool] %s failed: %s", fn_name, e)
            df = None

    if df is None or df.empty:
        return None

    # 统一列名
    col_map = {"代码": "code", "名称": "name", "涨跌幅": "pct_chg",
               "symbol": "code", "changepercent": "pct_chg", "trade": "close"}
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "pct_chg" not in df.columns:
        for c in df.columns:
            if "涨跌幅" in str(c) or "change" in str(c).lower() or "pct" in str(c).lower():
                df = df.rename(columns={c: "pct_chg"})
                break
    if "code" not in df.columns:
        for c in df.columns:
            if "代码" in str(c) or "symbol" in str(c).lower() or "code" in str(c).lower():
                df = df.rename(columns={c: "code"})
                break
    if "name" not in df.columns:
        for c in df.columns:
            if "名称" in str(c) or "name" in str(c).lower():
                df = df.rename(columns={c: "name"})
                break

    if "pct_chg" not in df.columns or "code" not in df.columns:
        logger.error("[StockPool] snapshot 缺少必需列: %s", list(df.columns))
        return None

    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df = df.dropna(subset=["pct_chg"])
    return df


def daily_top_to_pool(top_n: int = 10):
    """获取当日 A 股涨跌幅 Top N 并入池。"""
    logger.info("[StockPool] daily_top_to_pool 开始 (top_n=%d)", top_n)
    try:
        df = _get_spot_snapshot()
    except Exception as e:
        logger.error("[StockPool] 获取全市场 snapshot 失败: %s", e)
        return {"error": str(e)}

    if df is None:
        return {"added": 0, "error": "empty snapshot"}

    import pandas as pd
    top_gainers = df.nlargest(top_n, "pct_chg")
    top_losers = df.nsmallest(top_n, "pct_chg")
    combined = pd.concat([top_gainers, top_losers]).drop_duplicates(subset=["code"])

    added = 0
    for _, row in combined.iterrows():
        raw_code = str(row.get("code", "")).strip()
        name = str(row.get("name", "")) if "name" in row.index else None
        if not raw_code:
            continue
        import re
        # 清理 SH/SZ/BJ 前缀（部分 AKShare 接口返回 SZ301226 格式）
        m = re.search(r'(\d{6})', raw_code)
        if not m:
            continue
        code = m.group(1)
        symbol = normalize_symbol(code)
        try:
            result = add_to_pool(symbol, source="top_movers", company_name=name, enrich=False)
            if result["action"] == "created":
                added += 1
        except Exception as e:
            logger.warning("[StockPool] add %s failed: %s", symbol, e)

    logger.info("[StockPool] daily_top_to_pool 完成, 新增 %d", added)
    return {"added": added, "total_candidates": len(combined)}


# 保持向后兼容
def daily_top20_to_pool():
    return daily_top_to_pool(top_n=10)


# ---------------------------------------------------------------------------
# 历史回填
# ---------------------------------------------------------------------------

_backfill_status = {"running": False, "progress": 0, "total": 0, "added": 0, "error": None}


def get_backfill_status() -> dict:
    return dict(_backfill_status)


def backfill_top_history(months: int = 6, top_n: int = 10):
    """回填过去 N 个月每日涨跌 Top N 到股票池。

    策略：
    1. 优先从 prices_daily 表计算历史 Top N（如果有足够数据）。
    2. 同时获取当日全市场实时 Top N 入池。
    """
    if _backfill_status["running"]:
        logger.info("[StockPool] backfill already running, skip")
        return

    _backfill_status.update(running=True, progress=0, total=0, added=0, error=None)
    logger.info("[StockPool] backfill_top_history 开始 (months=%d, top_n=%d)", months, top_n)

    total_added = 0

    try:
        # Phase 1: 从 prices_daily 表回填历史
        cutoff = date.today() - timedelta(days=months * 30)

        with SessionLocal() as session:
            trade_dates = (
                session.query(PriceDaily.trade_date)
                .filter(PriceDaily.trade_date >= cutoff)
                .distinct()
                .order_by(PriceDaily.trade_date.asc())
                .all()
            )
            trade_dates = [r[0] for r in trade_dates]

        if trade_dates:
            _backfill_status["total"] = len(trade_dates) + 1

            for i, td in enumerate(trade_dates):
                _backfill_status["progress"] = i + 1
                try:
                    with SessionLocal() as session:
                        rows = (
                            session.query(PriceDaily.symbol, PriceDaily.pct_chg)
                            .filter(PriceDaily.trade_date == td, PriceDaily.pct_chg.isnot(None))
                            .all()
                        )
                        if len(rows) < top_n:
                            continue

                        sorted_rows = sorted(rows, key=lambda r: float(r.pct_chg or 0))
                        candidates = sorted_rows[:top_n] + sorted_rows[-top_n:]
                        candidate_syms = {r.symbol for r in candidates}

                        for sym in candidate_syms:
                            existing = session.query(StockPoolMember).filter(StockPoolMember.symbol == sym).first()
                            if existing:
                                if existing.first_seen_date and existing.first_seen_date > td:
                                    existing.first_seen_date = td
                                if existing.last_seen_date and existing.last_seen_date < td:
                                    existing.last_seen_date = td
                                if existing.exit_date is not None:
                                    existing.exit_date = None
                            else:
                                try:
                                    member = StockPoolMember(
                                        symbol=sym, first_seen_date=td, last_seen_date=td, source="backfill",
                                    )
                                    session.add(member)
                                    session.flush()
                                except Exception:
                                    session.rollback()
                                    session.execute(
                                        text(
                                            "INSERT INTO stock_pool_members (symbol, first_seen_date, last_seen_date) "
                                            "VALUES (:sym, :fs, :ls) ON CONFLICT DO NOTHING"
                                        ),
                                        {"sym": sym, "fs": td, "ls": td},
                                    )
                                _ensure_profile_stub(session, sym)
                                total_added += 1
                        session.commit()
                except Exception as e:
                    logger.warning("[StockPool] backfill date %s error: %s", td, e)
        else:
            _backfill_status["total"] = 1

        # Phase 2: 当日实时 Top N
        _backfill_status["progress"] = _backfill_status["total"]
        try:
            result = daily_top_to_pool(top_n=top_n)
            total_added += result.get("added", 0)
        except Exception as e:
            logger.warning("[StockPool] live top after backfill failed: %s", e)

        _backfill_status["added"] = total_added
        logger.info("[StockPool] backfill 完成: %d 个交易日 + 当日, 新增 %d 只",
                     len(trade_dates) if trade_dates else 0, total_added)
    except Exception as e:
        logger.error("[StockPool] backfill error: %s", e, exc_info=True)
        _backfill_status["error"] = str(e)
    finally:
        _backfill_status["running"] = False


# 向后兼容
def backfill_top20_history(months: int = 6):
    return backfill_top_history(months=months, top_n=10)


def start_backfill_background(months: int = 6, top_n: int = 10):
    """在后台线程启动回填任务。"""
    t = threading.Thread(
        target=backfill_top_history, args=(months, top_n), daemon=True, name="pool-backfill"
    )
    t.start()
    logger.info("[StockPool] backfill 后台线程已启动 (months=%d, top_n=%d)", months, top_n)


# ---------------------------------------------------------------------------
# 全量 A 股导入
# ---------------------------------------------------------------------------

_import_all_status = {"running": False, "progress": 0, "total": 0, "added": 0, "skipped": 0, "error": None}


def get_import_all_status() -> dict:
    return dict(_import_all_status)


def import_all_a_stocks():
    """将全部 A 股股票导入股票池（批量高效写入，不触发 Profile 充填）。"""
    if _import_all_status["running"]:
        logger.info("[StockPool] import_all already running, skip")
        return

    _import_all_status.update(running=True, progress=0, total=0, added=0, skipped=0, error=None)
    logger.info("[StockPool] import_all_a_stocks 开始")

    try:
        stock_list = _get_stock_list()
        if not stock_list:
            _import_all_status["error"] = "无法获取 A 股名录"
            logger.error("[StockPool] import_all: stock list empty")
            return

        total = len(stock_list)
        _import_all_status["total"] = total
        logger.info("[StockPool] import_all: 共 %d 只 A 股", total)

        today = date.today()
        added = 0
        skipped = 0
        batch_size = 200

        with SessionLocal() as session:
            all_existing = session.execute(
                text("SELECT symbol, exit_date FROM stock_pool_members")
            ).fetchall()
            active_syms = set(r.symbol for r in all_existing if r.exit_date is None)
            exited_syms = set(r.symbol for r in all_existing if r.exit_date is not None)

            # Reactivate exited stocks
            if exited_syms:
                session.execute(
                    text("UPDATE stock_pool_members SET exit_date = NULL, last_seen_date = :today WHERE exit_date IS NOT NULL"),
                    {"today": today},
                )
                session.commit()
                reactivated = len(exited_syms)
                logger.info("[StockPool] import_all: reactivated %d exited stocks", reactivated)
                active_syms.update(exited_syms)

            for i in range(0, total, batch_size):
                batch = stock_list[i:i + batch_size]
                new_members = []
                new_profiles = []

                for s in batch:
                    sym = s["symbol"]
                    name = s.get("name") or ""

                    if sym in active_syms:
                        skipped += 1
                        continue

                    new_members.append({
                        "symbol": sym,
                        "first_seen_date": today,
                        "last_seen_date": today,
                        "source": "bulk_import",
                    })
                    active_syms.add(sym)

                    new_profiles.append({
                        "symbol": sym,
                        "company_name": name or None,
                        "market": "A股",
                        "created_at": datetime.utcnow(),
                    })

                if new_members:
                    for m in new_members:
                        session.execute(
                            text(
                                "INSERT INTO stock_pool_members (symbol, first_seen_date, last_seen_date, source) "
                                "VALUES (:symbol, :first_seen_date, :last_seen_date, :source)"
                            ),
                            m,
                        )
                    added += len(new_members)

                if new_profiles:
                    for p in new_profiles:
                        existing_prof = session.execute(
                            text("SELECT 1 FROM stock_profiles WHERE symbol = :symbol"),
                            {"symbol": p["symbol"]},
                        ).fetchone()
                        if existing_prof:
                            session.execute(
                                text(
                                    "UPDATE stock_profiles SET "
                                    "company_name = COALESCE(NULLIF(company_name, ''), :company_name) "
                                    "WHERE symbol = :symbol"
                                ),
                                p,
                            )
                        else:
                            session.execute(
                                text(
                                    "INSERT INTO stock_profiles (symbol, company_name, market, created_at, is_valid) "
                                    "VALUES (:symbol, :company_name, :market, :created_at, true)"
                                ),
                                p,
                            )

                session.commit()
                _import_all_status["progress"] = min(i + batch_size, total)
                _import_all_status["added"] = added
                _import_all_status["skipped"] = skipped
                logger.info("[StockPool] import_all progress: %d/%d, added=%d",
                            min(i + batch_size, total), total, added)

        _import_all_status["progress"] = total
        _import_all_status["added"] = added
        _import_all_status["skipped"] = skipped
        logger.info("[StockPool] import_all 完成: 总计 %d, 新增 %d, 跳过 %d", total, added, skipped)

    except Exception as e:
        logger.error("[StockPool] import_all error: %s", e, exc_info=True)
        _import_all_status["error"] = str(e)
    finally:
        _import_all_status["running"] = False


def start_import_all_background():
    """在后台线程启动全量导入任务。"""
    t = threading.Thread(target=import_all_a_stocks, daemon=True, name="pool-import-all")
    t.start()
    logger.info("[StockPool] import_all 后台线程已启动")


# ---------------------------------------------------------------------------
# 画像状态检测 & 补全
# ---------------------------------------------------------------------------

PROFILE_FIELDS = [
    "industry", "business_summary", "core_products",
    "competitive_position", "competitors", "strategic_keywords",
    "risk_factors", "history_highlights", "profile_json",
]

_PROFILE_COMPLETION_THRESHOLD = 50  # 完成度 ≥ 50% 视为已完成

# LLM 经常在信息不足时生成的占位文本关键词
_PLACEHOLDER_STARTS = (
    "暂无", "待补充", "待完善", "待更新", "待补全",
    "未找到", "未提供", "未获得", "未检索", "未搜索",
    "无法基于", "无法判断", "无法概述", "无法提炼",
    "信息不足", "缺少", "缺乏",
    "不可用", "不详",
    "当前未提供", "当前无法", "目前未提供", "目前仅提供",
    "相关新闻摘要为", "截至目前未提供",
    "(未获得LLM分析)", "（未获得LLM分析）",
    "N/A", "n/a", "none", "unknown",
    "—", "——",
)

# 值中包含这些关键短语（且值较短）则判定为无效
_PLACEHOLDER_CONTAINS = (
    "待补充公开资料", "待补充公司公告", "待补充公开",
    "待补充公司", "待补充信息", "待补充",
    "无法基于给定信息", "无法基于信息源", "无法基于材料",
    "无法基于现有信息", "无法基于有效信息",
    "未找到相关新闻",
)


def _is_meaningful_value(value) -> bool:
    """判断 profile 字段值是否包含真正有用的信息（排除 LLM 占位文本）。"""
    if value is None:
        return False
    s = str(value).strip()
    if not s or len(s) < 4:
        return False
    # 整个值或开头就是占位词
    for kw in _PLACEHOLDER_STARTS:
        if s == kw or s.startswith(kw):
            return False
    # 包含占位短语且整体字数不多（真正有效的长文本不会被误杀）
    if len(s) < 200:
        for kw in _PLACEHOLDER_CONTAINS:
            if kw in s:
                return False
    # profile_json 特殊处理：内部 3 个以上字段是"暂无"/"待补充"则判无效
    if s.startswith("{"):
        placeholder_hits = sum(1 for pw in ("暂无", "待补充", "待完善") if pw in s)
        if placeholder_hits >= 3:
            return False
    return True


def _is_meaningful_field(field: str, value) -> bool:
    """字段级别的“有意义”判定（比 _is_meaningful_value 更严格）。

    目的：避免 business_summary 只有公司名、history_highlights 为空等情况仍被计入完成度。
    """
    if not _is_meaningful_value(value):
        return False

    s = str(value).strip()
    f = (field or "").strip()

    # 业务概述：必须足够具体
    if f == "business_summary":
        # 太短基本不可能包含有效业务描述
        if len(s) < 40:
            return False
        # 必须至少包含“业务/主营/产品/服务/收入/客户”中的一个信号词
        if not any(k in s for k in ("主营", "业务", "产品", "服务", "收入", "客户", "解决方案")):
            return False
        return True

    # 历史亮点：需要可验证的事件/时间线线索
    if f == "history_highlights":
        if len(s) < 20:
            return False
        # 没有时间线线索通常意味着泛泛而谈
        if not any(k in s for k in ("年", "月", "上市", "成立", "并购", "重组", "投产", "扩产", "获批", "发布")) and not any(
            ch.isdigit() for ch in s
        ):
            return False
        return True

    # 核心产品/竞争对手：至少应有分隔或多个实体（单一极短词容易是噪声）
    if f in ("core_products", "competitors"):
        if len(s) < 6:
            return False
        return True

    return True


def _calc_profile_completion(profile: Optional[StockProfile]) -> float:
    """计算单个 StockProfile 的完成度百分比 (0~100)。
    只计入包含真实有效信息的字段，排除 LLM 占位文本。"""
    if profile is None:
        return 0.0
    filled = sum(
        1 for f in PROFILE_FIELDS
        if _is_meaningful_field(f, getattr(profile, f, None))
    )
    return round(filled / len(PROFILE_FIELDS) * 100, 1)


def check_pool_profile_status() -> dict:
    """扫描股票池所有活跃股票的画像完成度，返回概览 + 未完成列表。"""
    with SessionLocal() as session:
        members = (
            session.query(StockPoolMember)
            .filter(StockPoolMember.exit_date.is_(None))
            .order_by(StockPoolMember.symbol)
            .all()
        )
        if not members:
            return {
                "total_active": 0,
                "completed": 0,
                "incomplete": 0,
                "avg_completion": 0,
                "incomplete_stocks": [],
            }

        symbols = [m.symbol for m in members]
        profiles_map: dict[str, StockProfile] = {}
        for p in session.query(StockProfile).filter(StockProfile.symbol.in_(symbols)).all():
            profiles_map[p.symbol] = p

        completed_count = 0
        incomplete_list: list[dict] = []

        for m in members:
            prof = profiles_map.get(m.symbol)
            pct = _calc_profile_completion(prof)
            if pct >= _PROFILE_COMPLETION_THRESHOLD:
                completed_count += 1
            else:
                incomplete_list.append({
                    "symbol": m.symbol,
                    "company_name": (prof.company_name if prof else None) or m.symbol,
                    "completion_pct": pct,
                    "has_profile_row": prof is not None,
                    "last_refreshed": (
                        prof.last_refreshed.isoformat() if prof and prof.last_refreshed else None
                    ),
                })

        # 按完成度升序，优先处理完成度最低的
        incomplete_list.sort(key=lambda x: x["completion_pct"])

        total = len(members)
        avg = round(
            sum(_calc_profile_completion(profiles_map.get(m.symbol)) for m in members) / total,
            1,
        ) if total else 0

        return {
            "total_active": total,
            "completed": completed_count,
            "incomplete": len(incomplete_list),
            "avg_completion": avg,
            "incomplete_stocks": incomplete_list,
        }


# --- 后台画像补全任务 ---

_profile_completion_status = {
    "running": False,
    "total": 0,
    "processed": 0,
    "successful": 0,
    "failed": 0,
    "skipped": 0,
    "current_symbol": None,
    "error": None,
    "started_at": None,
    "finished_at": None,
}


def get_profile_completion_status() -> dict:
    return dict(_profile_completion_status)


def _resolve_company_name(symbol: str, fallback: str) -> str:
    """从名录缓存查找正确的公司名称；无效时回退到 fallback。"""
    import re
    if fallback and re.search(r'[\u4e00-\u9fff]', fallback) and '?' not in fallback:
        return fallback
    stock_list = _get_stock_list()
    if stock_list:
        for rec in stock_list:
            if rec.get("symbol") == symbol:
                return rec.get("name") or fallback
    return fallback


def _run_profile_completion(batch_limit: int = 0, delay: float = 3.0, force: bool = False):
    """逐只为未完成画像的股票池成员执行 Profile 富化（同步，运行在后台线程中）。"""
    if _profile_completion_status["running"]:
        logger.info("[StockPool] profile completion already running, skip")
        return

    _profile_completion_status.update(
        running=True, total=0, processed=0, successful=0, failed=0, skipped=0,
        current_symbol=None, error=None,
        started_at=datetime.utcnow().isoformat(), finished_at=None,
    )

    try:
        from ..utils.stock_profile_enrichment import StockProfileEnricher
        enricher = StockProfileEnricher()

        # 预加载名录以修正无效名称
        stock_list = _get_stock_list()
        name_lookup: dict[str, str] = {}
        if stock_list:
            for rec in stock_list:
                name_lookup[rec.get("symbol", "")] = rec.get("name", "")

        # 1) 获取未完成股票列表
        with SessionLocal() as session:
            members = (
                session.query(StockPoolMember)
                .filter(StockPoolMember.exit_date.is_(None))
                .order_by(StockPoolMember.symbol)
                .all()
            )
            symbols = [m.symbol for m in members]
            profiles_map: dict[str, StockProfile] = {}
            for p in session.query(StockProfile).filter(StockProfile.symbol.in_(symbols)).all():
                profiles_map[p.symbol] = p

            todo: list[tuple[str, str]] = []  # (symbol, company_name)
            for m in members:
                prof = profiles_map.get(m.symbol)
                pct = _calc_profile_completion(prof)
                if pct < _PROFILE_COMPLETION_THRESHOLD:
                    raw_name = (prof.company_name if prof else None) or ""
                    name = _resolve_company_name(m.symbol, raw_name)
                    if not name or name == m.symbol:
                        name = name_lookup.get(m.symbol, m.symbol)
                    todo.append((m.symbol, name))

        # 按完成度升序（完成度最低的先处理）
        # 重新排序需要完成度信息，已在上面收集时按 symbol 顺序；
        # 为简洁起见直接使用当前列表（已按 symbol 排序）
        if batch_limit > 0:
            todo = todo[:batch_limit]

        _profile_completion_status["total"] = len(todo)
        logger.info("[StockPool] profile completion: %d stocks to enrich", len(todo))

        if not todo:
            logger.info("[StockPool] all pool stocks already have sufficient profiles")
            return

        # 2) 逐只富化
        import time as _t
        for idx, (symbol, company_name) in enumerate(todo, 1):
            _profile_completion_status["current_symbol"] = symbol
            _profile_completion_status["processed"] = idx
            logger.info("[StockPool] profile completion [%d/%d] %s (%s)",
                        idx, len(todo), symbol, company_name)
            t0 = _t.monotonic()
            try:
                with SessionLocal() as db:
                    _ensure_profile_stub(db, symbol, company_name)
                    db.commit()
                    enricher.enrich_stock_profile_sync(
                        symbol, company_name, db, force_refresh=force,
                    )
                elapsed = _t.monotonic() - t0
                _profile_completion_status["successful"] += 1
                logger.info("[StockPool] profile completion OK: %s (%.1fs)", symbol, elapsed)
            except Exception as e:
                elapsed = _t.monotonic() - t0
                _profile_completion_status["failed"] += 1
                logger.warning("[StockPool] profile completion FAIL %s (%.1fs): %s", symbol, elapsed, e)

            if idx < len(todo):
                _t.sleep(delay)

    except Exception as e:
        logger.error("[StockPool] profile completion error: %s", e, exc_info=True)
        _profile_completion_status["error"] = str(e)
    finally:
        _profile_completion_status["running"] = False
        _profile_completion_status["current_symbol"] = None
        _profile_completion_status["finished_at"] = datetime.utcnow().isoformat()
        logger.info(
            "[StockPool] profile completion finished: success=%d fail=%d",
            _profile_completion_status["successful"],
            _profile_completion_status["failed"],
        )


def start_profile_completion_background(
    batch_limit: int = 0, delay: float = 3.0, force: bool = False,
):
    """在后台线程启动画像补全任务。"""
    t = threading.Thread(
        target=_run_profile_completion,
        kwargs={"batch_limit": batch_limit, "delay": delay, "force": force},
        daemon=True,
        name="pool-profile-completion",
    )
    t.start()
    logger.info("[StockPool] profile completion 后台线程已启动 (batch_limit=%d, delay=%.1f)",
                batch_limit, delay)
