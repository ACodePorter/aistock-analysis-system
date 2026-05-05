"""
模块说明
--------
此模块提供面向 A 股的数据源抽象与多重回退策略，封装了通过 akshare、tushare、东方财富、新浪等渠道获取日线、资金流与实时快照的常用工具函数。
设计目标是：
- 提供统一的返回格式与单位（尽量将金额统一为“元”、成交量以“股”为单位等）；
- 在不同数据源间自动回退以提高可用性；
- 通过短期缓存（可选 Redis、进程内内存回退）与“粘性回填”机制减少临时数据缺失对上层调用的影响；
- 对第三方库与接口的字段差异做兼容性处理，并对异常与异常值做防护性清洗。
环境变量
- DATA_SOURCE: 优先数据源，可选 'tushare'（小写），默认 'akshare'。当设置为 'tushare' 且配置了 TUSHARE_TOKEN 时会优先尝试 tushare。
- TUSHARE_TOKEN: 使用 Tushare API 时必须提供的 token。
主要函数接口（摘要）
- normalize_symbol(symbol: str) -> str
    将传入的代码标准化为大写并附加后缀 .SH 或 .SZ（若已带后缀则保持），便于在不同接口间统一使用。
- fetch_daily_akshare(symbol: str, start_date: Optional[str] = None) -> pandas.DataFrame
    使用 akshare 获取单只股票的日线（前复权），返回 DataFrame，列顺序为:
    ['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'pct_chg', 'vol', 'amount']。
    - start_date: 可为 YYYYMMDD 字符串或 None（使用 akshare 默认）。
    - 数值字段尽量转为数值类型；vol 使用 pandas 'Int64' 可空整型；amount 与价格为浮点数。
    - 返回会丢弃缺失收盘价的记录。
- fetch_daily_tushare(symbol: str, start_date: Optional[str] = None) -> pandas.DataFrame
    使用 Tushare 获取日线：
    - 需要设置 TUSHARE_TOKEN，否则抛出 RuntimeError。
    - 返回列与 akshare 统一，注意 Tushare 的 amount 单位为“千元”，此处已转换为“元”（×1000）。
    - 若接口字段缺失（如 amount、pct_chg 等），模块做兼容性填充与类型转换。
    - start_date 若为 None，默认为近三年开始（以 Asia/Taipei 时区计算）。
- fetch_daily(symbol: str, start_date: Optional[str] = None) -> pandas.DataFrame
    日线入口：根据 DATA_SOURCE 与 TUSHARE_TOKEN 决定优先使用 tushare 或 akshare，并在 tushare 出错时回退到 akshare。
- fetch_fund_flow_daily(symbol: str, start_date: Optional[str] = None, include_today_rank: bool = False) -> pandas.DataFrame
    获取单只股票每日资金流明细（主力/超大/大/中/小 单位净流入与占比）。
    - 返回列: ['symbol','trade_date','main_net','main_ratio','super_net','super_ratio','large_net','large_ratio','medium_net','medium_ratio','small_net','small_ratio']。
    - 金额字段统一换算为“元”（akshare 历史接口多以万元返回，此处乘以 1e4）。
    - 若 akshare 的 per-stock 历史明细不可用且 include_today_rank=True，则回退到“今日排行”接口（注意该接口为盘中快照口径，做日终入库时应禁止使用以防混入盘中数据）。
    - 对字段缺失做容错处理并返回空的 DataFrame（列名一致）作为失败兜底。
- search_stocks(query: str) -> list[dict]
    基于 akshare 的股票代码/名称表搜索匹配项（最多返回 20 条），每项包含 { 'symbol', 'name', 'code' }。
- get_stock_info(symbol: str) -> Optional[dict]
    返回单只股票的基础信息（symbol/name/code），若找不到返回 None。
- get_realtime_stock(symbol: str) -> Optional[dict]
    从 akshare 的快照表读取单只实时 L1 行情并返回结构化字典（包含 name, price, change, pct_change, volume, amount 等），找不到或异常则返回 None。
- get_spot_snapshot(symbols: list[str]) -> Dict[str, dict]
    批量获取 A 股实时快照，返回以标准化 symbol（例如 '600000.SH', '002594.SZ'）为键的字典，值为包含丰富字段的字典（常见字段见函数顶部注释）。
    主要特性与行为：
    - 首选 akshare 提供的批量快照（ak.stock_zh_a_spot_em），对不同 akshare 版本的列名做别名映射与单位识别（手/股/万元/亿元 等）。
    - 对缺失或明显异常的关键字段，采用多层回退：
        1. 对 individual 标的（缺失较多字段）尝试从新浪（hq.sinajs.cn）回补；
        2. 对在 akshare 中完全未命中的标的，优先尝试东方财富 push2 接口批量补回，再用新浪补充；
        3. 若委比缺失，尝试基于五档盘口（ak.stock_bid_ask_em）估算委比；
        4. 若现量（last_volume）缺失或异常，优先尝试基于成交量增量的短期缓存估算，必要时调用东方财富明细接口获取最新一笔成交量作为兜底；
        5. 若 pre_close 缺失，尝试从本地数据库 prices_daily 中读取最近一条日线收盘价回填（批量查询优先，失败后逐个查询）。
    - 缓存与粘性回填：
        - 可选 Redis 支持（通过本模块尝试导入 .db.get_redis_client），若不可用则使用进程内字典作为回退缓存。
        - 对每个标的维护短期“last_item”缓存（JSON 包含 ts），用于“粘性回填”——在新快照字段缺失时优先保留上一次的非空值，减少字段回退。
        - 对部分估算结果（如委比、last_trade_volume）作短 TTL 缓存以降低接口压力。
    - 数值清洗与约束：
        - 对估值类字段（pe_ttm、pb）和涨速（speed）进行合理性检查，剔除明显离谱值并置为 None。
        - 最终返回时，为便于 UI 展示，会将仍为 None 的数值字段以 0 作为兜底（可在上层按需再区分 0 与缺失）。
    - 出错处理与限频日志：当 akshare 主流程整体异常时，会通过节流日志记录警告并进入全量回退（东方财富 + 新浪），若回退也失败则返回空字典。
异常与日志策略
- 绝大多数网络/解析异常会被捕获并在内部触发回退路径，减少对上游调用者的中断；当为必须的配置缺失（如 TUSHARE_TOKEN 使用 tushare）会抛出明确异常。
- 使用 _log_throttled 进行节流日志（同一 key 在一定时间窗口内只打印一次），以避免日志泛滥。若 logging 未配置，降级为 print。
注意事项与建议
- 数据口径注意事项：
    - akshare/tushare/东方财富/新浪在字段命名与单位上存在差异，模块尽量做兼容与统一，但上层使用者仍应留意来源差异（如 amount 单位、成交量单位）。
    - fetch_fund_flow_daily 的 include_today_rank 为 True 时会使用盘中排行口径，仅适合展示/盘中分析；进行日终入库请保持 False。
- 性能与频率控制：
    - get_spot_snapshot 在高并发场景下应配合外部缓存（Redis）以避免频繁调用外部 API。模块内部仅做短期缓存与限频保护，不能替代系统级限流。
- 可测试性：
    - 模块内部对外部依赖（akshare、tushare、requests、数据库、Redis）均为运行时导入，便于在测试环境以 mock 替换实现隔离测试。
- 返回值契约：
    - 大多数函数在异常或无数据时返回空的 DataFrame、空列表、空字典或 None，调用方需对这些情况进行判断处理。
版本与兼容性
- 该模块尽量兼容不同版本的 akshare 与第三方接口字段差异，但若上游 API 调整较大仍可能需要更新字段映射与解析逻辑。

"""

import os
import time
import json
import threading
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import re
from dateutil.tz import gettz
import logging
import requests

DATA_SOURCE = os.getenv("DATA_SOURCE", "akshare").lower()
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Safe akshare proxy: run akshare calls inside a dedicated worker thread
# with a fresh event loop to avoid interfering with the main ASGI loop.
# This wraps akshare callables so existing code can call `ak.foo(...)`
# while the actual execution happens in an isolated thread/loop.
# ------------------------------------------------------------------
class _AkProxy:
    def __init__(self):
        self._mod = None

    def _load(self):
        if self._mod is None:
            import importlib
            try:
                self._mod = importlib.import_module("akshare")
            except Exception as e:
                # re-raise later when attempted to call
                self._mod = None
                raise

    def __getattr__(self, name):
        # Lazily load akshare module; attribute access returns a wrapper
        def _run_in_thread(fn, *a, **kw):
            result = {}
            def target():
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        val = fn(*a, **kw)
                        result['ok'] = True
                        result['val'] = val
                    finally:
                        try:
                            loop.run_until_complete(loop.shutdown_asyncgens())
                        except Exception:
                            pass
                except Exception as e:
                    result['ok'] = False
                    result['val'] = e
                finally:
                    try:
                        asyncio.set_event_loop(None)
                    except Exception:
                        pass
                    try:
                        loop.close()
                    except Exception:
                        pass

            th = threading.Thread(target=target)
            th.daemon = True
            th.start()
            th.join()
            if result.get('ok'):
                return result.get('val')
            raise result.get('val')

        # ensure module is importable
        try:
            self._load()
        except Exception as e:
            raise RuntimeError("akshare module not available") from e

        attr = getattr(self._mod, name)
        if callable(attr):
            return lambda *a, **kw: _run_in_thread(attr, *a, **kw)
        return attr

# Global ak proxy instance
ak = _AkProxy()


# ============================================================================
# 代理禁用配置（解决 AKShare 连接 eastmoney.com 的代理问题）
# ============================================================================
_original_requests_get = None
_proxy_disabled = False

def _disable_proxy_for_akshare():
    """
    完全禁用 requests 库的代理设置，解决 AKShare 访问 eastmoney.com 时的代理错误。
    
    采用的策略：
    1. 清空所有环境变量中的代理配置
    2. Monkey patch requests.get 方法，强制所有请求禁用代理
    
    注意：此函数应在首次调用 akshare 之前执行，且只执行一次。
    """
    global _original_requests_get, _proxy_disabled
    
    if _proxy_disabled:
        return  # 已经禁用过，避免重复执行
    
    # 1. 清空环境变量中的代理设置
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
        os.environ.pop(key, None)
        os.environ[key] = ''
    
    # 2. Monkey patch requests.get 强制禁用代理
    _original_requests_get = requests.get
    
    def patched_get(*args, **kwargs):
        """禁用代理的 requests.get 包装函数"""
        kwargs['proxies'] = {'http': None, 'https': None}
        return _original_requests_get(*args, **kwargs)
    
    requests.get = patched_get
    _proxy_disabled = True
    
    logger.info("已禁用 requests 代理设置，确保 AKShare 可正常访问 eastmoney.com")

# 模块加载时立即禁用代理
_disable_proxy_for_akshare()

# 日志节流状态（用来降低重复日志的频率）
_last_log_ts: Dict[str, float] = {}

# fund flow rank 缓存（盘中“今日排行”接口可能频繁被调用，加入进程内短期缓存与互斥）
_fund_flow_rank_cache: Dict[str, Any] = {"ts": 0.0, "records": None}
_fund_flow_rank_lock = threading.Lock()

def _log_throttled(key: str, level: int, msg: str, interval_sec: int = 60):
    """节流打印日志：同一 key 在 interval_sec 秒内只打印一次。

    参数:
    - key: 唯一键，用于区分不同的日志来源
    - level: 日志级别（logging.INFO 等）
    - msg: 日志内容
    - interval_sec: 节流时间窗口，单位秒
    """
    now = time.time()
    prev = _last_log_ts.get(key, 0)
    if now - prev >= interval_sec:
        _last_log_ts[key] = now
        try:
            logger.log(level, msg)
        except Exception:
            # 若 logging 尚未配置，降级为 print 输出
            print(msg)

def normalize_symbol(symbol: str) -> str:
    """标准化证券代码：
    - 若末尾带 .SH/.SZ 则直接返回大写
    - 若不带后缀，则以首位是否为“6”推断上交所/深交所后缀
    """
    s = symbol.upper().strip()
    if s.endswith(".SH") or s.endswith(".SZ"):
        return s
    if s.startswith("6"):
        return f"{s}.SH"
    return f"{s}.SZ"

def _fetch_daily_akshare_tx(symbol: str, start_date: str = None) -> pd.DataFrame:
    """使用 akshare 的腾讯数据源获取日 K 线数据（前复权）。

    腾讯源 (stock_zh_a_hist_tx) 不依赖 eastmoney.com，
    当 eastmoney 不可达时可作为备用数据源。

    注意: 腾讯源返回列为 [date, open, close, high, low, amount]，
    无 vol（成交量手数） 和 pct_chg（涨跌幅）。
    pct_chg 由 close 推算；vol 从 amount 估算或置 None。
    """
    _EMPTY = pd.DataFrame(columns=["symbol","trade_date","open","high","low","close","pct_chg","vol","amount"])
    sym = normalize_symbol(symbol)
    base = sym.replace(".SH", "").replace(".SZ", "")
    # 腾讯源 symbol 格式: sz002594 / sh600519
    tx_prefix = "sh" if sym.endswith(".SH") else "sz"
    tx_symbol = f"{tx_prefix}{base}"
    try:
        kwargs = {"symbol": tx_symbol}
        if start_date:
            kwargs["start_date"] = start_date
        kwargs["end_date"] = pd.Timestamp.now().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist_tx(**kwargs)
    except Exception as e:
        logger.warning(f"ak.stock_zh_a_hist_tx failed for {sym}: {e}")
        return _EMPTY
    if df is None or df.empty:
        return _EMPTY
    # 列名清洗
    df.columns = [str(c).strip() for c in df.columns]
    # 重命名
    df = df.rename(columns={"date": "trade_date"})
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    # 数值转换
    for col in ["open", "high", "low", "close", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = None
    # 推算 pct_chg (涨跌幅 %)
    if "close" in df.columns:
        df = df.sort_values("trade_date").reset_index(drop=True)
        df["pct_chg"] = df["close"].pct_change() * 100.0
    else:
        df["pct_chg"] = None
    # 腾讯源无 vol 列，置空
    if "vol" not in df.columns:
        df["vol"] = None
    else:
        df["vol"] = pd.to_numeric(df["vol"], errors="coerce").astype("Int64")
    df["symbol"] = sym
    cols = ["symbol","trade_date","open","high","low","close","pct_chg","vol","amount"]
    out = df[cols].dropna(subset=["close"]).reset_index(drop=True)
    if not out.empty:
        logger.info(f"[TX fallback] fetched {len(out)} rows for {sym} via Tencent source")
    return out


def fetch_daily_akshare(symbol: str, start_date: str = None) -> pd.DataFrame:
    """使用 akshare 获取日 K 线数据（前复权）。

    入参:
    - symbol: 股票代码（可带或不带 .SH/.SZ 后缀）
    - start_date: 起始日期（YYYYMMDD），或 None 表示接口默认

    返回:
    - 含列 [symbol, trade_date, open, high, low, close, pct_chg, vol, amount] 的 DataFrame
    - 数值字段尽量转换为数值类型，缺失值以 None/NA 处理
    """
    # Use global `ak` proxy to run akshare calls in an isolated thread/loop
    sym = normalize_symbol(symbol)
    base = sym.replace(".SH", "").replace(".SZ", "")
    try:
        df = ak.stock_zh_a_hist(symbol=base, period="daily", start_date=start_date, adjust="qfq")
    except Exception as e:
        logger.warning(f"ak.stock_zh_a_hist (eastmoney) failed for {sym}: {e}, trying Tencent source...")
        return _fetch_daily_akshare_tx(symbol, start_date)
    if df is None or df.empty:
        logger.info(f"ak.stock_zh_a_hist returned empty for {sym}, trying Tencent source...")
        return _fetch_daily_akshare_tx(symbol, start_date)
    # 清洗列名
    df.columns = [str(c).strip().replace("\n", "").replace("\r", "") for c in df.columns]
    # 重命名核心列
    rename_map = {
        "日期": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "vol",
        "成交额": "amount",
        "涨跌幅": "pct_chg",
    }
    df = df.rename(columns=rename_map)
    # 日期列
    if "trade_date" not in df.columns:
        if "date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        else:
            return pd.DataFrame(columns=["symbol","trade_date","open","high","low","close","pct_chg","vol","amount"])
    else:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    # 数值转换
    if "vol" in df.columns:
        df["vol"] = pd.to_numeric(df["vol"], errors="coerce").astype("Int64")
    for col in ["open","high","low","close","pct_chg","amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = None
    df["symbol"] = sym
    cols = ["symbol","trade_date","open","high","low","close","pct_chg","vol","amount"]
    out = df[cols].dropna(subset=["close"]).reset_index(drop=True)
    if out.empty:
        logger.warning(
            "fetch_daily_akshare cleaned empty for %s; original_rows=%s close_na=%s columns=%s", 
            sym, len(df), df['close'].isna().sum(), df.columns.tolist()
        )
    return out

def fetch_daily_tushare(symbol: str, start_date: str = None) -> pd.DataFrame:
    """使用 Tushare 获取日 K 线数据（若需要请配置 TUSHARE_TOKEN）。

    返回列与 akshare 路径保持一致：[symbol, trade_date, open, high, low, close, pct_chg, vol, amount]
    注意：tushare 的 amount 单位为千元，此处统一换算为“元”。
    """
    import tushare as ts
    if not TUSHARE_TOKEN:
        raise RuntimeError("TUSHARE_TOKEN must be set to use Tushare")
    
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    sym = normalize_symbol(symbol)
    ts_code = sym
    
    if start_date is None:
        dt = datetime.now(gettz("Asia/Taipei")) - timedelta(days=365*3)
        start_date = dt.strftime("%Y%m%d")
    
    try:
        df = pro.daily(ts_code=ts_code, start_date=start_date)
    except Exception as e:
        error_msg = str(e)
        # 检测权限错误
        if "权限" in error_msg or "积分" in error_msg or "没有接口访问权限" in error_msg:
            _log_throttled(
                "tushare_permission_error",
                logging.WARNING,
                f"Tushare token 权限不足，无法访问日线行情接口: {error_msg[:150]}。建议访问 https://tushare.pro/document/1?doc_id=108 查看权限详情",
                300  # 5分钟内只打印一次
            )
            raise PermissionError(f"Tushare token 权限不足: {error_msg}") from e
        else:
            # 其他错误正常抛出
            raise
    
    if df is None or df.empty:
        return pd.DataFrame(columns=["symbol","trade_date","open","high","low","close","pct_chg","vol","amount"])
    
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    # 修复：amount字段可能不存在
    if "amount" in df.columns:
        df = df.rename(columns={"amount": "amount_x"})
        df["amount"] = df["amount_x"] * 1000.0
    else:
        df["amount"] = None
    out = df.rename(columns={"vol": "vol_x"})
    out["vol"] = pd.to_numeric(out.get("vol_x", pd.Series([None]*len(out))), errors="coerce").astype("Int64")
    out["symbol"] = sym
    # 修复：pct_chg字段可能不存在
    out["pct_chg"] = pd.to_numeric(out.get("pct_chg", pd.Series([None]*len(out))), errors="coerce")
    return out[["symbol", "trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount"]].dropna(subset=["close"])

def fetch_daily(symbol: str, start_date: str | None = None) -> pd.DataFrame:
    """获取日 K 线数据。

    优先级策略:
    - 若 DATA_SOURCE 为 'tushare' 且已配置令牌，先尝试 tushare；若失败则回退 akshare
    - 其他情况默认使用 akshare
    - 若 Tushare 返回 PermissionError（权限不足），直接跳过不再尝试
    """
    # 首选策略
    if DATA_SOURCE == "tushare" and TUSHARE_TOKEN:
        try:
            df = fetch_daily_tushare(symbol, start_date)
            if df is not None and not df.empty:
                return df
        except PermissionError as e:
            # Tushare token 权限不足，直接跳过，不打印额外日志（已在 fetch_daily_tushare 中记录）
            pass
        except Exception as e:
            _log_throttled(
                f"tushare_fetch_error_{symbol}",
                logging.WARNING,
                f"[fetch_daily] Tushare primary failed for {symbol}: {e}",
                120
            )
        # 回退 akshare
        df2 = fetch_daily_akshare(symbol, start_date)
        if (df2 is None or df2.empty) and DATA_SOURCE != "akshare":
            logger.warning(f"[fetch_daily] Both tushare and akshare empty for {symbol}")
        return df2
    else:
        # DATA_SOURCE 默认 akshare
        df = fetch_daily_akshare(symbol, start_date)
        # 若 akshare 失败且可用 tushare token，则尝试 tushare 作为二级回退
        if (df is None or df.empty) and TUSHARE_TOKEN:
            try:
                df2 = fetch_daily_tushare(symbol, start_date)
                if df2 is not None and not df2.empty:
                    logger.info(f"[fetch_daily] akshare empty; tushare fallback succeeded for {symbol}")
                    return df2
            except PermissionError:
                # Tushare token 权限不足，直接跳过
                pass
            except Exception as e:
                _log_throttled(
                    f"tushare_fallback_error_{symbol}",
                    logging.WARNING,
                    f"[fetch_daily] tushare fallback failed for {symbol}: {e}",
                    120
                )
        return df


def _load_fund_flow_rank_today(max_age_sec: int = 20, retries: int = 3, backoff_base: float = 0.6) -> pd.DataFrame:
    """获取并缓存“今日资金流排行” DataFrame（盘中口径）。

    设计修复：
    - 旧实现引用未定义变量 sym/cols，导致 NameError 覆盖真实异常；现已移除。
    - 增加指数退避重试与缓存兜底，避免日志风暴。
    - 永远返回 DataFrame；失败则返回空列 DataFrame（调用方自行判断）。
    """
    cols_min = []  # 仅用于空返回
    now = time.time()
    with _fund_flow_rank_lock:
        cached_records = _fund_flow_rank_cache.get("records")
        cached_ts = _fund_flow_rank_cache.get("ts", 0.0)
    if cached_records is not None and now - cached_ts <= max_age_sec:
        return pd.DataFrame(cached_records)

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            # Use global `ak` proxy to run akshare calls in an isolated thread/loop
            rdf = ak.stock_individual_fund_flow_rank(indicator="今日")
            if rdf is None or rdf.empty:
                raise RuntimeError("fund flow rank interface returned empty dataframe")
            # 缓存
            with _fund_flow_rank_lock:
                _fund_flow_rank_cache["records"] = rdf.to_dict(orient="records")
                _fund_flow_rank_cache["ts"] = time.time()
            return rdf
        except Exception as e:  # 记录后退避
            last_err = e
            wait = backoff_base * (2 ** attempt)
            _log_throttled(
                "fund_flow_rank_retry",
                logging.WARNING,
                f"fund flow rank attempt {attempt+1}/{retries} failed: {e}",
                30,
            )
            time.sleep(min(wait, 3.0))
            continue

    # 重试失败，若旧缓存 <=5 分钟仍可用则返回缓存
    with _fund_flow_rank_lock:
        cached_records = _fund_flow_rank_cache.get("records")
        cached_ts = _fund_flow_rank_cache.get("ts", 0.0)
    if cached_records is not None and now - cached_ts <= 300:
        _log_throttled(
            "fund_flow_rank_cache_use",
            logging.INFO,
            "Using stale fund flow rank cache after retries failed.",
            60,
        )
        return pd.DataFrame(cached_records)

    if last_err:
        _log_throttled(
            "fund_flow_rank_fail_final",
            logging.ERROR,
            f"fund flow rank unavailable after retries: {last_err}",
            60,
        )
    # 最后的兜底：尝试使用东方财富单票/批量回退构建今日排行（按成交额挑选候选票并逐票查询 f62）
    try:
        try:
            spot = ak.stock_zh_a_spot_em()
        except Exception:
            spot = None
        candidates = []
        if spot is not None and not spot.empty:
            # 兼容不同列名的成交额识别
            amt_col = None
            for c in ['成交额', '成交额(万元)', 'amount', 'amount_x']:
                if c in spot.columns:
                    amt_col = c
                    break
            if amt_col:
                try:
                    spot[amt_col] = pd.to_numeric(spot.get(amt_col), errors='coerce').fillna(0)
                except Exception:
                    pass
            # 按成交额选取前 N 个候选
            try:
                top = spot.sort_values(by=amt_col if amt_col else spot.columns[0], ascending=False).head(200)
                for _, row in top.iterrows():
                    code = str(row.get('代码') or row.get('code') or '')
                    name = row.get('名称') or row.get('name') or ''
                    if not code:
                        continue
                    candidates.append((code, name))
            except Exception:
                candidates = []
        records = []
        for code, name in candidates:
            try:
                rec = _fetch_fund_flow_intraday_eastmoney(code)
                if rec and rec.get('main_net') is not None:
                    records.append({
                        '代码': code,
                        '名称': name,
                        '今日主力净流入-净额': rec.get('main_net') / 1e4 if rec.get('main_net') is not None else None,
                        '主力净流入-净额': rec.get('main_net') / 1e4 if rec.get('main_net') is not None else None,
                    })
            except Exception:
                continue
        if records:
            rdf2 = pd.DataFrame.from_records(records)
            with _fund_flow_rank_lock:
                _fund_flow_rank_cache['records'] = rdf2.to_dict(orient='records')
                _fund_flow_rank_cache['ts'] = time.time()
            return rdf2
    except Exception:
        pass
    return pd.DataFrame(columns=cols_min)


def _fetch_fund_flow_intraday_eastmoney(sym: str) -> Optional[dict]:
    """调用东方财富 push2 接口获取单只股票的盘中资金流数据。"""
    try:
        sym_std = normalize_symbol(sym)
        base = sym_std.replace(".SH", "").replace(".SZ", "")
        mk = "1" if sym_std.endswith(".SH") else "0"
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": f"{mk}.{base}",
            "fields": "f62,f184,f66,f69,f72,f75,f78,f81,f84,f87",
        }
        resp = requests.get(url, params=params, timeout=4.0)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None

        def _to_float(val):
            try:
                return float(val) if val is not None else None
            except Exception:
                return None

        result = {
            "symbol": sym_std,
            "trade_date": datetime.now(gettz("Asia/Taipei")).date(),
            "main_net": _to_float(data.get("f62")),
            "main_ratio": _to_float(data.get("f184")),
            "super_net": _to_float(data.get("f66")),
            "super_ratio": _to_float(data.get("f69")),
            "large_net": _to_float(data.get("f72")),
            "large_ratio": _to_float(data.get("f75")),
            "medium_net": _to_float(data.get("f78")),
            "medium_ratio": _to_float(data.get("f81")),
            "small_net": _to_float(data.get("f84")),
            "small_ratio": _to_float(data.get("f87")),
        }

        if result["main_net"] is None:
            return None
        return result
    except Exception:
        return None


def fetch_fund_flow_daily(symbol: str, start_date: str | None = None, include_today_rank: bool = False) -> pd.DataFrame:
    """使用 akshare 获取单只股票资金流每日明细。

    返回列:
    - symbol, trade_date,
      main_net, main_ratio,
      super_net, super_ratio,
      large_net, large_ratio,
      medium_net, medium_ratio,
      small_net, small_ratio

    注意:
    - 金额类字段统一换算为“元”（akshare 多以“万元”为单位返回，此处乘以 1e4）
    - include_today_rank=True 时，若历史接口不可用，将回退使用“今日排行”的即时口径；
      做日终（EOD）入库时请保持 False，避免将盘中口径混入日线表
    """
    # 统一输出列
    cols = [
        "symbol","trade_date","main_net","main_ratio","super_net","super_ratio",
        "large_net","large_ratio","medium_net","medium_ratio","small_net","small_ratio"
    ]
    # 快速熔断开关：允许关闭所有资金流抓取
    if os.getenv("FUND_FLOW_DISABLE", "false").lower() in ("1","true","yes"):
        return pd.DataFrame(columns=cols)

    # EOD 场景优先使用东方财富历史接口，规避部分环境下 akshare 异步清理导致的
    # "RuntimeError: Event loop is closed" 噪声。
    prefer_em_eod = os.getenv("FUND_FLOW_PREFER_EASTMONEY_EOD", "true").lower() in ("1", "true", "yes")
    try_ak_on_eod_miss = os.getenv("FUND_FLOW_TRY_AK_ON_EOD_MISS", "true").lower() in ("1", "true", "yes")
    if not include_today_rank and prefer_em_eod:
        em_hist = fetch_fund_flow_eod_history_eastmoney(symbol, start_date=start_date)
        if em_hist is not None and not em_hist.empty:
            return em_hist
        if not try_ak_on_eod_miss:
            _log_throttled(
                f"ff_hist_all_fail:{normalize_symbol(symbol).replace('.SH','').replace('.SZ','')}",
                logging.WARNING,
                f"Fund flow history unavailable for {normalize_symbol(symbol)} via eastmoney EOD.",
                300,
            )
            return pd.DataFrame(columns=cols)

    # Use global `ak` proxy to run akshare calls in an isolated thread/loop
    sym = normalize_symbol(symbol)
    base = sym.replace(".SH", "").replace(".SZ", "")
    # akshare 接口：stock_individual_fund_flow 明细按日（有时不可用）
    df = None
    try:
        df = ak.stock_individual_fund_flow(stock=base)
    except Exception as e:
        _log_throttled(
            f"ff_hist_ak_fail:{base}",
            logging.WARNING,
            f"akshare.stock_individual_fund_flow for {sym} failed: {e}",
            120,
        )

    if df is not None and not df.empty:
        # 主接口成功，进行数据处理
        rename_map = {
            "日期": "trade_date",
            "主力净流入-净额": "main_net",
            "主力净流入-净占比": "main_ratio",
            "超大单净流入-净额": "super_net",
            "超大单净流入-净占比": "super_ratio",
            "大单净流入-净额": "large_net",
            "大单净流入-净占比": "large_ratio",
            "中单净流入-净额": "medium_net",
            "中单净流入-净占比": "medium_ratio",
            "小单净流入-净额": "small_net",
            "小单净流入-净占比": "small_ratio",
        }
        df = df.rename(columns=rename_map)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        # 标准化单位：将净额类字段统一转换为“元”
        # Akshare 通常以“万元”为单位返回该接口，这里统一乘以 1e4
        for col in ["main_net","super_net","large_net","medium_net","small_net"]:
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
            if col in df.columns:
                df[col] = df[col] * 1e4
        for col in ["main_ratio","super_ratio","large_ratio","medium_ratio","small_ratio"]:
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        df["symbol"] = sym
        
        # 如果指定了 start_date，则进行过滤
        if start_date:
            df = df[df.trade_date >= pd.to_datetime(start_date).date()]

        return df[cols].drop_duplicates(subset=["symbol","trade_date"]).reset_index(drop=True)

    # 主接口失败或返回空，执行回退策略
    # 注意：include_today_rank 参数决定是否执行“今日排行”盘中口径；EOD任务应设为False。
    if not include_today_rank:
        # 在 EOD 场景，优先尝试东方财富历史日线资金流作为回退
        em_hist = fetch_fund_flow_eod_history_eastmoney(sym, start_date=start_date)
        if em_hist is not None and not em_hist.empty:
            return em_hist
        _log_throttled(
            f"ff_hist_all_fail:{base}",
            logging.WARNING,
            f"Fund flow history unavailable for {sym} via akshare and eastmoney EOD.",
            300,
        )
        return pd.DataFrame(columns=cols)
        
    logger.info(f"Fallback for {sym}: trying stock_individual_fund_flow_rank.")
    try:
        rdf = _load_fund_flow_rank_today()
        if rdf is None or rdf.empty:
            _log_throttled(
                "fund_flow_rank_empty",
                logging.WARNING,
                "Fund flow rank fallback returned empty dataframe.",
                60,
            )
            raise RuntimeError("rank dataframe empty")
        code_col = "代码" if "代码" in rdf.columns else ("symbol" if "symbol" in rdf.columns else None)
        if code_col is None:
            raise RuntimeError("rank dataframe missing code column")
        try:
            row = rdf[rdf[code_col].astype(str) == base]
        except Exception:
            row = pd.DataFrame()
        if row.empty:
            logger.warning(f"Fallback for {sym}: symbol not found in rank data.")
            raise RuntimeError("symbol not in rank")
        r = row.iloc[0]
        def pick(names: list[str]):
            for name in names:
                if name in r.index:
                    return r[name]
            return None
        def safe_mul(val, scale):
            try:
                v = pd.to_numeric(val, errors="coerce")
                return float(v) * scale if pd.notna(v) else None
            except Exception:
                return None
        out = {
            "symbol": sym,
            "trade_date": datetime.now(gettz("Asia/Taipei")).date(),
            "main_net": safe_mul(pick(["今日主力净流入-净额","主力净流入-净额"]), 1e4),
            "main_ratio": pd.to_numeric(pick(["今日主力净流入-净占比","主力净流入-净占比"]), errors="coerce"),
            "super_net": safe_mul(pick(["今日超大单净流入-净额","超大单净流入-净额"]), 1e4),
            "super_ratio": pd.to_numeric(pick(["今日超大单净流入-净占比","超大单净流入-净占比"]), errors="coerce"),
            "large_net": safe_mul(pick(["今日大单净流入-净额","大单净流入-净额"]), 1e4),
            "large_ratio": pd.to_numeric(pick(["今日大单净流入-净占比","大单净流入-净占比"]), errors="coerce"),
            "medium_net": safe_mul(pick(["今日中单净流入-净额","中单净流入-净额"]), 1e4),
            "medium_ratio": pd.to_numeric(pick(["今日中单净流入-净占比","中单净流入-净占比"]), errors="coerce"),
            "small_net": safe_mul(pick(["今日小单净流入-净额","小单净流入-净额"]), 1e4),
            "small_ratio": pd.to_numeric(pick(["今日小单净流入-净占比","小单净流入-净占比"]), errors="coerce"),
        }
        return pd.DataFrame([out], columns=cols)
    except Exception as e2:
        # 继续回退东方财富 push2 单票接口
        alt = _fetch_fund_flow_intraday_eastmoney(sym)
        if alt:
            for k in [
                "main_net","super_net","large_net","medium_net","small_net",
                "main_ratio","super_ratio","large_ratio","medium_ratio","small_ratio",
            ]:
                try:
                    alt[k] = float(alt.get(k)) if alt.get(k) is not None else None
                except Exception:
                    alt[k] = None
            return pd.DataFrame([alt], columns=cols)
        _log_throttled(
            f"fund_flow_fallback_error:{sym}",
            logging.WARNING,
            f"All fund flow fallbacks failed for {sym}: {e2}",
            60,
        )
        return pd.DataFrame(columns=cols)


def fetch_fund_flow_eod_history_eastmoney(symbol: str, start_date: str | None = None) -> pd.DataFrame:
    """使用东方财富 push2his 接口获取历史日度资金流（单位：元）。

    返回列与 fetch_fund_flow_daily 一致；失败返回空 DataFrame。
    """
    cols = [
        "symbol","trade_date","main_net","main_ratio","super_net","super_ratio",
        "large_net","large_ratio","medium_net","medium_ratio","small_net","small_ratio"
    ]
    try:
        sym = normalize_symbol(symbol)
        base = sym.replace(".SH", "").replace(".SZ", "")
        mk = "1" if sym.endswith(".SH") else "0"
        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        params = {
            "secid": f"{mk}.{base}",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56",  # date, main, super, large, medium, small
            "klt": "103",
            "lmt": "0",
        }
        resp = requests.get(url, params=params, timeout=6.0)
        if resp.status_code != 200:
            return pd.DataFrame(columns=cols)
        j = resp.json()
        data = j.get("data") if isinstance(j, dict) else None
        kl = data.get("klines") if data else None
        if not isinstance(kl, list):
            return pd.DataFrame(columns=cols)
        records = []
        for item in kl:
            if not isinstance(item, str):
                continue
            parts = item.split(",")
            if len(parts) < 6:
                continue
            dt = parts[0]
            if start_date:
                try:
                    # start_date 形如 YYYYMMDD；将 dt 转为同格式比较
                    if dt.replace("-", "") < str(start_date):
                        continue
                except Exception:
                    pass
            def _num(s):
                try:
                    return float(s) if s != "" else None
                except Exception:
                    return None
            records.append({
                "symbol": sym,
                "trade_date": pd.to_datetime(dt).date(),
                "main_net": _num(parts[1]),
                "super_net": _num(parts[2]),
                "large_net": _num(parts[3]),
                "medium_net": _num(parts[4]),
                "small_net": _num(parts[5]),
                # 比例字段无历史接口，置为 None
                "main_ratio": None,
                "super_ratio": None,
                "large_ratio": None,
                "medium_ratio": None,
                "small_ratio": None,
            })
        if not records:
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame.from_records(records)
        return df[cols]
    except Exception:
        return pd.DataFrame(columns=cols)

def search_stocks(query: str):
    """搜索股票，返回匹配的股票列表"""
    # Use global `ak` proxy to run akshare calls in an isolated thread/loop
    try:
        # 使用akshare搜索股票
        df = ak.stock_info_a_code_name()
        
        # 过滤匹配的股票
        mask = (
            df['code'].str.contains(query, case=False, na=False) |
            df['name'].str.contains(query, case=False, na=False)
        )
        results = df[mask].head(20)  # 限制返回20个结果
        
        # 转换为字典列表
        stocks = []
        for _, row in results.iterrows():
            stocks.append({
                'symbol': normalize_symbol(row['code']),
                'name': row['name'],
                'code': row['code']
            })
        
        return stocks
    except Exception as e:
        print(f"Error searching stocks: {e}")
        return []

def get_stock_info(symbol: str):
    """获取股票基本信息
    Uses global `ak` proxy to isolate akshare calls.
    """
    try:
        sym = normalize_symbol(symbol)
        base = sym.replace(".SH", "").replace(".SZ", "")
        
        # 获取股票信息
        stock_detail = ak.stock_individual_info_em(symbol=base)
        
        if stock_detail.empty:
            return None

        detail_dict = {}
        for _, detail_row in stock_detail.iterrows():
            detail_dict[detail_row['item']] = detail_row['value']

        stock_dict = {
                'symbol': sym,
                'name': detail_dict.get('股票简称'),
                'code': detail_dict.get('股票代码'),
                'industry': detail_dict.get('行业'),
                'total_shares': detail_dict.get('总股本'),
                'float_shares': detail_dict.get('流通股'),
                'float_market_cap': detail_dict.get('流通市值'),
                'online_date': detail_dict.get('上市日期'),
            }
        
        return stock_dict

    except Exception as e:
        print(f"Error getting stock info: {e}")
        return None

def get_realtime_stock(symbol: str):
    """获取股票实时数据
    Uses global `ak` proxy to isolate akshare calls.
    """
    try:
        sym = normalize_symbol(symbol)
        base = sym.replace(".SH", "").replace(".SZ", "")
        
        # 获取实时数据
        df = ak.stock_zh_a_spot_em()
        stock_data = df[df['代码'] == base]
        
        if stock_data.empty:
            return None
            
        row = stock_data.iloc[0]
        return {
            'symbol': sym,
            'name': row['名称'],
            'price': float(row['最新价']),
            'change': float(row['涨跌额']),
            'pct_change': float(row['涨跌幅']),
            'volume': int(row['成交量']),
            'amount': float(row['成交额'])
        }
    except Exception as e:
        print(f"Error getting realtime stock data: {e}")
        return None


def get_spot_snapshot(symbols: list[str]):
    """批量获取A股实时快照信息，返回按symbol键的字典。
    字段包含：name, symbol, price, change, pct_change, volume, amount,
    turnover_rate, volume_ratio, amplitude, pe_ttm, pb, total_market_cap,
    high, low, open, pre_close, order_ratio(optional), last_volume(optional)
    """
    if not symbols:
        return {}
    # Use global `ak` proxy to run akshare calls in an isolated thread/loop
    # 惰性获取 Redis 客户端用于轻量缓存（可选）
    try:
        from ..core.db import get_redis_client  # local import to avoid hard dependency at import time
        _rc = get_redis_client()
    except Exception:
        _rc = None

    # 当 Redis 不可用时，使用进程内内存作为本地缓存回退
    if not hasattr(get_spot_snapshot, "_mem_cache"):
        get_spot_snapshot._mem_cache = {}
    _MEM: Dict[str, Any] = getattr(get_spot_snapshot, "_mem_cache")

    def _cache_get(key: str) -> Optional[str]:
        try:
            if _rc is not None:
                val = _rc.get(key)
                if isinstance(val, bytes):
                    try:
                        return val.decode("utf-8", errors="ignore")
                    except Exception:
                        return str(val)
                return val
            # 内存回退缓存
            rec = _MEM.get(key)
            if not rec:
                return None
            expires_at, value = rec
            if time.time() > expires_at:
                _MEM.pop(key, None)
                return None
            return value
        except Exception:
            return None

    def _cache_setex(key: str, ttl_sec: int, value: str) -> None:
        try:
            if _rc is not None:
                _rc.setex(key, ttl_sec, value)
                return
            # 内存回退缓存
            _MEM[key] = (time.time() + ttl_sec, value)
        except Exception:
            return

    # 工具函数：在 akshare 失败时，其他回退路径也可以复用
    def to_float(v):
        try:
            if v is None:
                return None
            if isinstance(v, str):
                v = v.strip().replace(',', '')
                if v.endswith('万'):
                    try:
                        return float(v[:-1]) * 1e4
                    except Exception:
                        pass
                if v.endswith('亿'):
                    try:
                        return float(v[:-1]) * 1e8
                    except Exception:
                        pass
                if v.endswith('%'):
                    v = v[:-1]
                if v in ('-', '--', '—', ''):
                    return None
            return float(v)
        except Exception:
            return None

    def to_int(v):
        f = to_float(v)
        try:
            return int(f) if f is not None else None
        except Exception:
            return None

    def _compute_order_ratio_via_bid_ask(base_code: str) -> Optional[float]:
        """当快照中缺失“委比”时，基于 L1 五档盘口估算委比。

        定义：委比 = (Σ买量 - Σ卖量) / (Σ买量 + Σ卖量) * 100
        结果做短期缓存以降低请求频率。
        """
        cache_key = f"spot:order_ratio:{base_code}"
        cached = _cache_get(cache_key)
        if cached is not None:
            try:
                return float(cached)
            except Exception:
                pass
        try:
            df_book = ak.stock_bid_ask_em(symbol=base_code)
            if df_book is None or df_book.empty:
                return None
            # 聚合五档：将所有匹配“买一量..买五量 / 卖一量..卖五量”或同义列名的数量求和
            buy_vol = 0.0
            sell_vol = 0.0
            for col in df_book.columns:
                col_s = str(col)
                try:
                    series = df_book[col]
                except Exception:
                    continue
                # 识别买量列
                if re.search(r"买[一二三四五].*量|bid\d+_?vol|申买.*量", col_s):
                    try:
                        buy_vol += float(pd.to_numeric(series, errors="coerce").fillna(0).sum())
                    except Exception:
                        pass
                # 识别卖量列
                if re.search(r"卖[一二三四五].*量|ask\d+_?vol|申卖.*量", col_s):
                    try:
                        sell_vol += float(pd.to_numeric(series, errors="coerce").fillna(0).sum())
                    except Exception:
                        pass
            denom = buy_vol + sell_vol
            if denom <= 0:
                return None
            ratio = (buy_vol - sell_vol) / denom * 100.0
            # 缓存约 30 秒
            try:
                _cache_setex(cache_key, 30, str(ratio))
            except Exception:
                pass
            return ratio
        except Exception:
            return None

    def _fetch_spot_from_sina(missing_bases: list[str]) -> Dict[str, Dict[str, Any]]:
        """回退方案：从新浪获取一批基础代码（不带后缀）的实时 L1 行情。

        返回：以标准化 symbol 为键的字典（例如 600000.SH, 002594.SZ）。
        字段包含：name, symbol, price, change, pct_change, volume, amount,
        high, low, open, pre_close, order_ratio（基于五档估算）, last_volume（基于成交量增量缓存推断）, amplitude。
        """
        if not missing_bases:
            return {}
        import requests
        out: Dict[str, Dict[str, Any]] = {}
        # 构造查询参数：以上海/深圳前缀区分（6 开头为上交所 sh，否则为 sz）
        codes = []
        for b in missing_bases:
            prefix = 'sh' if b.startswith('6') else 'sz'
            codes.append(f"{prefix}{b}")
        url = f"http://hq.sinajs.cn/list={','.join(codes)}"
        try:
            resp = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn/",
            }, timeout=5)
            resp.encoding = 'gbk'  # 新浪返回 GBK 编码
            text = resp.text
        except Exception:
            return {}
        for line in text.splitlines():
            if not line.strip().startswith("var hq_str_"):
                continue
            # 行示例：var hq_str_sz002594="比亚迪,开盘价,昨收,现价,最高,最低,买一,卖一,成交量(股),成交额(元),b1v,b1p,...,a5v,a5p,日期,时间";
            try:
                left = line.index('=')
                raw = line[left+1:].strip().strip(';')
                if raw.startswith('"') and raw.endswith('"'):
                    raw = raw[1:-1]
                parts = raw.split(',')
                # 从变量名中提取代码
                var_name = line.split('=')[0]
                code_str = var_name.split('hq_str_')[-1]  # e.g., sz002594
                base = code_str[-6:]
                suffix = '.SH' if base.startswith('6') else '.SZ'
                symbol = f"{base}{suffix}"
                if len(parts) < 32 or not parts[0]:
                    continue
                name = parts[0]
                open_p = to_float(parts[1])
                pre_close = to_float(parts[2])
                price = to_float(parts[3])
                high = to_float(parts[4])
                low = to_float(parts[5])
                # 新浪第 9 个字段（索引 8）为成交量(股)，已是“股”为单位，无需再换算
                vol_shares = to_int(parts[8])
                amount_yuan = to_float(parts[9])
                # 计算涨跌额与涨跌幅
                change = None
                pct = None
                if price is not None and pre_close not in (None, 0):
                    change = price - pre_close
                    try:
                        pct = change / pre_close * 100.0
                    except Exception:
                        pct = None
                # 基于五档估算委比（买量索引 11/13/15/17/19；卖量索引 21/23/25/27/29）
                buy_vol = 0.0
                sell_vol = 0.0
                try:
                    # 字段说明：成交额后依次为 b1p(10), b1v(11), b2p(12), b2v(13) ... a1p(20), a1v(21) ...
                    for idx in [11, 13, 15, 17, 19]:
                        buy_vol += float(to_float(parts[idx]) or 0)
                    for idx in [21, 23, 25, 27, 29]:
                        sell_vol += float(to_float(parts[idx]) or 0)
                    denom = buy_vol + sell_vol
                    order_ratio = ((buy_vol - sell_vol) / denom * 100.0) if denom > 0 else None
                except Exception:
                    order_ratio = None
                item = {
                    'name': name,
                    'symbol': symbol,
                    'price': price,
                    'change': change,
                    'pct_change': pct,
                    'volume': vol_shares,
                    'amount': amount_yuan,
                    'high': high,
                    'low': low,
                    'open': open_p,
                    'pre_close': pre_close,
                    'order_ratio': order_ratio,
                    'spot_source': 'sina',
                }
                # 若可能，计算振幅
                if pre_close not in (None, 0) and high is not None and low is not None:
                    try:
                        item['amplitude'] = (high - low) / pre_close * 100.0
                    except Exception:
                        item['amplitude'] = None
                # 通过成交量增量估算“现量”（使用短期缓存保存上次成交量）
                if item.get('volume') is not None:
                    try:
                        v = int(item['volume'])
                        k_prev = f"spot:volume:{symbol}"
                        prev = _cache_get(k_prev)
                        if prev is not None:
                            try:
                                pv = int(float(prev))
                                delta = v - pv
                                if delta >= 0:
                                    item['last_volume'] = int(delta)
                            except Exception:
                                pass
                        _cache_setex(k_prev, 180, str(v))
                    except Exception:
                        pass
                out[symbol] = item
            except Exception:
                continue
        return out

    def _fetch_spot_from_eastmoney(missing_bases: list[str]) -> Dict[str, Dict[str, Any]]:
        """回退方案：从东方财富获取一批基础代码（不带后缀）的实时行情。

        返回：以标准化 symbol 为键的字典；若接口返回更多扩展字段，将一并整理。
        """
        if not missing_bases:
            return {}
        import requests
        # 东方财富 secid 规则：上交所 -> 1.XXXXXX，深交所 -> 0.XXXXXX
        secids = []
        for b in missing_bases:
            pref = '1' if b.startswith('6') else '0'
            secids.append(f"{pref}.{b}")
        fields = (
            "f12,f14,"        # code, name
            "f2,f3,f4,"       # price, pct_change, change
            "f5,f6,"          # volume(手), amount(元)
            "f7,f8,f10,"      # amplitude%, turnover_rate%, volume_ratio
            "f15,f16,f17,f18,"# high, low, open, pre_close
            "f20,f21,"        # total_mv, circ_mv
            "f105,f23,f9,"    # order_ratio, pb, pe(dynamic)
            "f124"            # speed (涨速) - unreliable; sanitized later
        )
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fid=f3"
            f"&secids={','.join(secids)}&fields={fields}"
        )
        try:
            r = requests.get(url, headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"}, timeout=6)
            j = r.json()
        except Exception:
            return {}
        diff = (((j or {}).get('data') or {}).get('diff')) or []
        out: Dict[str, Dict[str, Any]] = {}
        for it in diff:
            try:
                code = str(it.get('f12') or '')
                if not code:
                    continue
                suffix = '.SH' if code.startswith('6') else '.SZ'
                symbol = f"{code}{suffix}"
                def gf(k):
                    v = it.get(k)
                    try:
                        return float(v) if v is not None else None
                    except Exception:
                        return None
                # 成交量单位为“手”，需换算为“股”
                vol = gf('f5')
                if vol is not None:
                    vol = vol * 100.0
                amt = gf('f6')
                item = {
                    'name': it.get('f14'),
                    'symbol': symbol,
                    'price': gf('f2'),
                    'pct_change': gf('f3'),
                    'change': gf('f4'),
                    'volume': int(vol) if vol is not None else None,
                    'amount': amt,
                    'amplitude': gf('f7'),
                    'turnover_rate': gf('f8'),
                    'volume_ratio': gf('f10'),
                    'high': gf('f15'),
                    'low': gf('f16'),
                    'open': gf('f17'),
                    'pre_close': gf('f18'),
                    'total_market_cap': gf('f20'),
                    'order_ratio': gf('f105'),
                    'pb': gf('f23'),
                    'pe_ttm': gf('f9'),
                    # f124 在该接口中并非稳定的“涨速”字段，可能是时间戳，后续会进行清洗
                    'speed': gf('f124'),
                }
                # 基本合理性校验
                try:
                    if item['pe_ttm'] is not None and (item['pe_ttm'] <= 0 or item['pe_ttm'] > 1000):
                        item['pe_ttm'] = None
                except Exception:
                    item['pe_ttm'] = None
                try:
                    if item['pb'] is not None and (item['pb'] <= 0 or item['pb'] > 200):
                        item['pb'] = None
                except Exception:
                    item['pb'] = None
                # 清洗涨速：剔除绝对值过大的异常值
                try:
                    if item['speed'] is not None and abs(float(item['speed'])) > 100:
                        item['speed'] = None
                except Exception:
                    item['speed'] = None
                # 若缺失涨跌额/涨跌幅，则根据 price 与 pre_close 计算
                if item.get('change') is None and item.get('price') is not None and item.get('pre_close') not in (None, 0):
                    item['change'] = item['price'] - item['pre_close']
                if item.get('pct_change') is None and item.get('price') is not None and item.get('pre_close') not in (None, 0):
                    item['pct_change'] = (item['price'] - item['pre_close']) / item['pre_close'] * 100.0
                out[symbol] = item
            except Exception:
                continue
        return out

    def _fetch_last_trade_volume_eastmoney(base_code: str) -> Optional[int]:
        """从东方财富明细接口获取最新一笔成交量（现手/现量）。

        返回以“股”为单位的成交量；短期缓存以避免频繁请求。
        """
        cache_key = f"spot:last_trade_vol:{base_code}"
        cached = _cache_get(cache_key)
        if cached is not None:
            try:
                return int(float(cached))
            except Exception:
                pass
        import requests
        mk = '1' if base_code.startswith('6') else '0'
        url = 'https://push2his.eastmoney.com/api/qt/stock/details/get'
        params = {
            'secid': f'{mk}.{base_code}',
            'fields1': 'f1,f2,f3,f4',
            'fields2': 'f51,f52,f53,f54,f55',
            'pos': '-1',  # 最新一笔
        }
        try:
            r = requests.get(url, params=params, headers={
                'Referer': 'https://quote.eastmoney.com/',
                'User-Agent': 'Mozilla/5.0',
            }, timeout=4)
            j = r.json()
            details = (((j or {}).get('data') or {}).get('details')) or []
            if not isinstance(details, list) or not details:
                return None
            last = details[-1]
            if not isinstance(last, str):
                return None
            # 常见格式："HH:MM:SS,price,vol,bs,amount"
            parts = last.split(',')
            if len(parts) < 3:
                return None
            vol_raw = parts[2]
            try:
                vol = float(vol_raw)
            except Exception:
                return None
            # 经验规则：东方财富明细中的成交量常以“手”为单位；
            # 若数值较小且接近整数，按“手”到“股”换算（×100），否则视为“股”
            vol_shares = int(vol * 100) if vol is not None and vol == float(int(vol)) and vol < 1e5 else int(vol)
            _cache_setex(cache_key, 5, str(vol_shares))
            return vol_shares
        except Exception:
            return None

    def _elapsed_trading_minutes_now() -> float:
        """计算今日至当前时刻的已开盘分钟数（剔除午休）。

        交易时段：09:30-11:30 与 13:00-15:00（以亚洲/台北时区近似处理）。
        若未开盘则返回 0。
        """
        try:
            tz = gettz("Asia/Taipei")
            now = datetime.now(tz)
            if now.weekday() >= 5:
                return 0.0
            d = now.date()
            def _dt(h, m):
                return datetime(d.year, d.month, d.day, h, m, tzinfo=tz)
            s1, e1 = _dt(9, 30), _dt(11, 30)
            s2, e2 = _dt(13, 0), _dt(15, 0)
            total = 0.0
            if now > s1:
                total += max(0.0, (min(now, e1) - s1).total_seconds() / 60.0)
            if now > s2:
                total += max(0.0, (min(now, e2) - s2).total_seconds() / 60.0)
            return max(0.0, total)
        except Exception:
            return 0.0

    def _compute_avg_speed_from_pct(pct: Optional[float]) -> Optional[float]:
        """涨速兜底：基于当前涨跌幅与已开盘分钟数，估算每分钟涨幅。

        - 公式：speed_est = pct_change / 已开盘分钟数
        - 限幅：[-100, 100]
        - 若无有效 pct_change 或尚未开盘，返回 None
        """
        try:
            if pct is None:
                return None
            minutes = _elapsed_trading_minutes_now()
            if minutes <= 0:
                return None
            sp = float(pct) / float(minutes)
            if sp < -100.0:
                return -100.0
            if sp > 100.0:
                return 100.0
            return sp
        except Exception:
            return None
    try:
        # 统一转换为基础代码（不带 .SH/.SZ）
        bases = []
        for s in symbols:
            sym = normalize_symbol(s)
            bases.append(sym.replace('.SH','').replace('.SZ',''))

        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return {}
        code_col = '代码' if '代码' in df.columns else ('symbol' if 'symbol' in df.columns else None)
        if not code_col:
            return {}
        sub = df[df[code_col].isin(bases)].copy()
        # 工具函数/选择器（已在上方定义 to_float/to_int）
        out: Dict[str, Dict[str, Any]] = {}
        # 预定义别名集合，兼容不同 akshare 版本的列名差异
        def pick_from_row(row, candidates, default=None):
            for c in candidates:
                if c in sub.columns and pd.notna(row.get(c, None)):
                    return row[c]
            return default
        def pick_with_colname(row, candidates):
            for c in candidates:
                if c in sub.columns and pd.notna(row.get(c, None)):
                    return row[c], c
            return None, None

        # 常见字段别名（兼容多版本）
        alias = {
            'name': ['名称', 'name'],
            'price': ['最新价', '最新', 'price', '现价'],
            'change': ['涨跌额', '涨跌'],
            'pct_change': ['涨跌幅', '涨跌幅(%)', '涨幅', '涨幅(%)'],
            'volume': ['成交量', '成交量(手)', '成交量(股)'],
            'amount': ['成交额', '成交额(万元)', '成交额(元)'],
            'turnover_rate': ['换手率', '换手率(%)'],
            'volume_ratio': ['量比'],
            'amplitude': ['振幅', '振幅(%)'],
            'pe_ttm': ['市盈率-动态', '市盈率TTM', '市盈率(TTM)', '市盈率'],
            'pb': ['市净率', '市净率(倍)'],
            'total_market_cap': ['总市值', '总市值(亿元)', '总市值(万元)'],
            'high': ['最高'],
            'low': ['最低'],
            'open': ['今开', '开盘价'],
            'pre_close': ['昨收', '昨收盘'],
            'order_ratio': ['委比'],
            'last_volume': ['现量'],
            'speed': ['涨速', '涨速(%)', 'rise_speed']
        }

        for _, row in sub.iterrows():
            base = str(row[code_col])
            # 恢复 normalized symbol
            suffix = '.SH' if base.startswith('6') else '.SZ'
            symbol = f"{base}{suffix}"
            def pick(col, default=None):
                return row[col] if col in sub.columns and pd.notna(row[col]) else default
            # 单位感知：针对成交量/成交额/总市值等识别单位并换算
            # 成交量
            vol_val, vol_col = pick_with_colname(row, alias['volume'])
            vol_num = to_float(vol_val)
            if vol_num is not None:
                if vol_col and ('(手' in vol_col or '手)' in vol_col or vol_col.endswith('手')):
                    vol_num = vol_num * 100.0  # “手” -> “股”
                # 若列名标注“(股)”，则已为“股”
            # 成交额
            amt_val, amt_col = pick_with_colname(row, alias['amount'])
            amt_num = to_float(amt_val)
            if amt_num is not None and isinstance(amt_num, (int, float)) and amt_col:
                if '万元' in amt_col:
                    amt_num = amt_num * 1e4
                elif '亿元' in amt_col:
                    amt_num = amt_num * 1e8
                # 若标注(元) 或无单位，保持原样
            # 总市值
            tmc_val, tmc_col = pick_with_colname(row, alias['total_market_cap'])
            tmc_num = to_float(tmc_val)
            if tmc_num is not None and isinstance(tmc_num, (int, float)) and tmc_col:
                if '亿元' in tmc_col:
                    tmc_num = tmc_num * 1e8
                elif '万元' in tmc_col:
                    tmc_num = tmc_num * 1e4
            item = {
                'name': pick_from_row(row, alias['name']),
                'symbol': symbol,
                'price': to_float(pick_from_row(row, alias['price'])),
                'change': to_float(pick_from_row(row, alias['change'])),
                'pct_change': to_float(pick_from_row(row, alias['pct_change'])),
                'volume': int(vol_num) if vol_num is not None else None,
                'amount': amt_num,
                'turnover_rate': to_float(pick_from_row(row, alias['turnover_rate'])),
                'volume_ratio': to_float(pick('量比')),
                'amplitude': to_float(pick_from_row(row, alias['amplitude'])),
                'pe_ttm': to_float(pick_from_row(row, alias['pe_ttm'])),
                'pb': to_float(pick_from_row(row, alias['pb'])),
                'total_market_cap': tmc_num,
                'high': to_float(pick_from_row(row, alias['high'])),
                'low': to_float(pick_from_row(row, alias['low'])),
                'open': to_float(pick_from_row(row, alias['open'])),
                'pre_close': to_float(pick_from_row(row, alias['pre_close'])),
                'order_ratio': to_float(pick_from_row(row, alias['order_ratio'])) if any(c in sub.columns for c in alias['order_ratio']) else None,
                'last_volume': to_int(pick_from_row(row, alias['last_volume'])) if any(c in sub.columns for c in alias['last_volume']) else None,
                'spot_source': 'akshare',
            }
            # 可选字段：涨速
            item['speed'] = to_float(pick_from_row(row, alias['speed']))
            try:
                if item['speed'] is not None and abs(float(item['speed'])) > 100:
                    item['speed'] = None
            except Exception:
                item['speed'] = None

            # 若关键字段缺失较多，优先尝试用新浪数据回补该标的
            critical = ['change','pct_change','volume','amount','turnover_rate','volume_ratio',
                        'amplitude','high','low','open','pre_close','pe_ttm','pb','total_market_cap']
            missing_count = sum(1 for k in critical if item.get(k) is None)
            if missing_count >= 5:
                try:
                    smap = _fetch_spot_from_sina([base])
                    if symbol in smap:
                        for k, v in smap[symbol].items():
                            if item.get(k) is None and v is not None:
                                item[k] = v
                except Exception:
                    pass
            # 若“委比”仍缺失，短暂拉取盘口估算；失败则尝试仅对该标的使用新浪估算
            if item.get('order_ratio') is None:
                try:
                    computed = _compute_order_ratio_via_bid_ask(base)
                    if computed is not None:
                        item['order_ratio'] = computed
                except Exception:
                    computed = None
                if item.get('order_ratio') is None:
                    try:
                        smap_single = _fetch_spot_from_sina([base])
                        sym_key = symbol
                        if sym_key in smap_single and smap_single[sym_key].get('order_ratio') is not None:
                            item['order_ratio'] = smap_single[sym_key]['order_ratio']
                    except Exception:
                        pass
            # 推导“现量”：以当前成交量与上一快照成交量之差作为现量（短期缓存）
            if item.get('last_volume') is None and item.get('volume') is not None:
                try:
                    v = int(item['volume']) if item['volume'] is not None else None
                    if v is not None:
                        k_prev = f"spot:volume:{symbol}"
                        prev = _cache_get(k_prev)
                        if prev is not None:
                            try:
                                pv = int(float(prev))
                                delta = v - pv
                                # 仅接受正向增量
                                if delta >= 0:
                                    item['last_volume'] = int(delta)
                            except Exception:
                                pass
                        # 无论是否命中均更新缓存
                        _cache_setex(k_prev, 180, str(v))
                except Exception:
                    pass
            # 若现量仍缺失，或数值异常偏大（可能为累计增量），则尝试调用东方财富明细接口以获取“最新一笔成交量”作为兜底
            try:
                lv = item.get('last_volume')
                bad = False
                try:
                    bad = (lv is None) or (isinstance(lv, (int, float)) and lv > 5_000_000)
                except Exception:
                    bad = True
                if bad:
                    em_last = _fetch_last_trade_volume_eastmoney(base)
                    if em_last is not None and em_last > 0:
                        item['last_volume'] = int(em_last)
            except Exception:
                pass
            out[symbol] = item
        # 若部分标的在 akshare 快照中缺失，尝试东方财富与新浪作为补充
        found_bases = set(sub[code_col].astype(str).tolist())
        missing = [b for b in bases if b not in found_bases]
        if missing:
            # 先尝试东方财富
            em_map = _fetch_spot_from_eastmoney(missing)
            # 合并东方财富数据
            for symb, sm in em_map.items():
                if symb not in out:
                    # 标记来源
                    if 'spot_source' not in sm or sm.get('spot_source') is None:
                        sm['spot_source'] = 'eastmoney'
                    out[symb] = sm
                else:
                    for k, v in sm.items():
                        if out[symb].get(k) is None and v is not None:
                            out[symb][k] = v
            # 再尝试新浪
            sina_map = _fetch_spot_from_sina(missing)
            # 合并新浪数据，但不覆盖已有字段
            for symb, sm in sina_map.items():
                if symb not in out:
                    if 'spot_source' not in sm or sm.get('spot_source') is None:
                        sm['spot_source'] = 'sina'
                    out[symb] = sm
                else:
                    # 仅填充缺失值
                    for k, v in sm.items():
                        if out[symb].get(k) is None and v is not None:
                            out[symb][k] = v
        # 对仍缺失委比的标的再尝试一次盘口估算
        for symb, val in list(out.items()):
            try:
                if val.get('order_ratio') is None:
                    base = symb.replace('.SH','').replace('.SZ','')
                    computed = _compute_order_ratio_via_bid_ask(base)
                    if computed is not None:
                        val['order_ratio'] = computed
            except Exception:
                pass
        # 再次检查缺失的标的（第二轮东方财富 + 新浪回补）
        found_bases = set(sub[code_col].astype(str).tolist())
        missing = [b for b in bases if b not in found_bases]
        if missing:
            em_map = _fetch_spot_from_eastmoney(missing)
            for symb, sm in em_map.items():
                if symb not in out:
                    if 'spot_source' not in sm or sm.get('spot_source') is None:
                        sm['spot_source'] = 'eastmoney'
                    out[symb] = sm
                else:
                    for k, v in sm.items():
                        if out[symb].get(k) is None and v is not None:
                            out[symb][k] = v
            sina_map = _fetch_spot_from_sina(missing)
            # 合并新浪数据，但不覆盖已有字段
            for symb, sm in sina_map.items():
                if symb not in out:
                    if 'spot_source' not in sm or sm.get('spot_source') is None:
                        sm['spot_source'] = 'sina'
                    out[symb] = sm
                else:
                    # 仅填充缺失值
                    for k, v in sm.items():
                        if out[symb].get(k) is None and v is not None:
                            out[symb][k] = v
        # 对仍缺失委比的标的再尝试一次盘口估算
        for symb, val in list(out.items()):
            try:
                if val.get('order_ratio') is None:
                    base = symb.replace('.SH','').replace('.SZ','')
                    computed = _compute_order_ratio_via_bid_ask(base)
                    if computed is not None:
                        val['order_ratio'] = computed
            except Exception:
                pass

        # 若缺失涨跌额/涨跌幅，但已有 price 与 pre_close，则补算
        for symb, val in out.items():
            try:
                if val.get('change') is None and val.get('price') is not None and val.get('pre_close') not in (None, 0):
                    val['change'] = float(val['price']) - float(val['pre_close'])
                if val.get('pct_change') is None and val.get('price') is not None and val.get('pre_close') not in (None, 0):
                    pc = (float(val['price']) - float(val['pre_close'])) / float(val['pre_close']) * 100.0
                    val['pct_change'] = pc
                # 若可能，基于 high/low 与 pre_close 计算振幅
                if val.get('amplitude') is None and val.get('high') is not None and val.get('low') is not None and val.get('pre_close') not in (None, 0):
                    try:
                        val['amplitude'] = (float(val['high']) - float(val['low'])) / float(val['pre_close']) * 100.0
                    except Exception:
                        pass
            except Exception:
                pass

        # 预补昨收价：若缺失，从数据库最新日线收盘价回填
        try:
            from ..core.db import engine as _engine
            from sqlalchemy import text as _sa_text
            sym_list = list(out.keys())
            preclose_map: Dict[str, float] = {}
            if sym_list:
                # 优先批量查询；若失败则逐个查询
                try:
                    placeholders = ','.join([f":s{i}" for i in range(len(sym_list))])
                    sql = f"""
                        SELECT DISTINCT ON (symbol) symbol, close
                        FROM prices_daily
                        WHERE symbol IN ({placeholders})
                        ORDER BY symbol, trade_date DESC
                    """
                    params = {f"s{i}": sym for i, sym in enumerate(sym_list)}
                    with _engine.begin() as conn:
                        res = conn.execute(_sa_text(sql), params).fetchall()
                    for r in res:
                        if r.close is not None:
                            preclose_map[r.symbol] = float(r.close)
                except Exception:
                    # 单标的回退查询
                    with _engine.begin() as conn:
                        for sym in sym_list:
                            try:
                                r = conn.execute(_sa_text("SELECT close FROM prices_daily WHERE symbol=:s ORDER BY trade_date DESC LIMIT 1"), {"s": sym}).first()
                                if r and r[0] is not None:
                                    preclose_map[sym] = float(r[0])
                            except Exception:
                                continue
            # 应用回填
            for symb, val in out.items():
                if val.get('pre_close') is None and symb in preclose_map:
                    val['pre_close'] = preclose_map[symb]
                # 若条件满足，重新计算涨跌额/涨跌幅
                try:
                    if val.get('change') is None and val.get('price') is not None and val.get('pre_close') not in (None, 0):
                        val['change'] = float(val['price']) - float(val['pre_close'])
                    if val.get('pct_change') is None and val.get('price') is not None and val.get('pre_close') not in (None, 0):
                        val['pct_change'] = (float(val['price']) - float(val['pre_close'])) / float(val['pre_close']) * 100.0
                except Exception:
                    pass
        except Exception:
            pass

        # 粘性回填：与上一次非空快照合并，避免字段回退为 null/0
        sticky_fields = [
            'change','pct_change','speed','volume','amount','turnover_rate','volume_ratio','amplitude',
            'last_volume','high','low','open','pre_close','order_ratio','pe_ttm','pb','total_market_cap'
        ]
        # 对下列字段，若当前值为 0 也倾向沿用上次值
        prefer_prev_if_zero = {'speed','order_ratio','last_volume'}
        for symb, item in out.items():
            try:
                prev_raw = _cache_get(f"spot:last_item:{symb}")
                if prev_raw:
                    try:
                        prev = json.loads(prev_raw)
                    except Exception:
                        prev = None
                    if isinstance(prev, dict):
                        # 若来源未给出有效“涨速”，尝试用涨跌幅的变化量/时间差 估算每分钟涨幅
                        try:
                            cur_pct = to_float(item.get('pct_change'))
                            prev_pct = to_float(prev.get('pct_change'))
                            prev_ts = float(prev.get('ts')) if prev.get('ts') is not None else None
                            now_ts = time.time()
                            if cur_pct is not None and prev_pct is not None and prev_ts is not None:
                                dt = max(now_ts - prev_ts, 1.0)
                                if 0 < dt < 600:
                                    sp = (cur_pct - prev_pct) / dt * 60.0
                                    if -100.0 <= sp <= 100.0:
                                        # 当当前涨速缺失/为 0/异常时，优先使用估算值
                                        cur_sp = item.get('speed')
                                        if cur_sp is None or (isinstance(cur_sp, (int, float)) and abs(float(cur_sp)) < 1e-9) or (isinstance(cur_sp, (int, float)) and abs(float(cur_sp)) > 100.0):
                                            item['speed'] = sp
                        except Exception:
                            pass
                        for k in sticky_fields:
                            cur_val = item.get(k)
                            prev_val = prev.get(k)
                            if prev_val is None:
                                continue
                            # 对部分字段，将 0 视作“缺失值”，以便使用上一次有效值
                            zero_like = False
                            try:
                                zero_like = (isinstance(cur_val, (int,float)) and abs(float(cur_val)) < 1e-9)
                            except Exception:
                                zero_like = False
                            if cur_val is None or (k in prefer_prev_if_zero and zero_like):
                                if k == 'speed':
                                    try:
                                        if abs(float(prev_val)) > 100:
                                            continue
                                    except Exception:
                                        continue
                                item[k] = prev_val
                else:
                    # 首次调用无历史快照：使用兜底估算，避免涨速卡为 0
                    try:
                        cur_sp = item.get('speed')
                        zero_like = False
                        try:
                            zero_like = (cur_sp is None) or (isinstance(cur_sp, (int, float)) and abs(float(cur_sp)) < 1e-9)
                        except Exception:
                            zero_like = True
                        if zero_like:
                            est = _compute_avg_speed_from_pct(to_float(item.get('pct_change')))
                            if est is not None:
                                item['speed'] = est
                    except Exception:
                        pass
                # 存回缓存（短 TTL 保持新鲜度），并附带时间戳以便下次估算涨速
                item['ts'] = time.time()
                _cache_setex(f"spot:last_item:{symb}", 300, json.dumps(item, ensure_ascii=False))
            except Exception:
                pass

        # 最终标准化：数值字段避免返回 null
        numeric_fields = [
            'change','pct_change','speed','volume','amount','turnover_rate','volume_ratio','amplitude',
            'last_volume','high','low','open','pre_close','order_ratio','pe_ttm','pb','total_market_cap'
        ]
        for symb, item in out.items():
            # 再次过滤明显异常的估值比率
            try:
                if item.get('pe_ttm') is not None and (item['pe_ttm'] <= 0 or item['pe_ttm'] > 1000):
                    item['pe_ttm'] = None
            except Exception:
                item['pe_ttm'] = None
            try:
                if item.get('pb') is not None and (item['pb'] <= 0 or item['pb'] > 200):
                    item['pb'] = None
            except Exception:
                item['pb'] = None
            # 在设置默认值之前，再清洗一次涨速
            try:
                sp = item.get('speed')
                if sp is not None and isinstance(sp, (int, float)) and abs(float(sp)) > 100:
                    item['speed'] = None
            except Exception:
                item['speed'] = None
            for k in numeric_fields:
                if item.get(k) is None:
                    # 统一以 0 作为 UI 兜底；若粘性回填已有值则已在之前使用
                    item[k] = 0

        # 确保所有请求的标的都能返回：优先粘性缓存，最后回退到数据库日线
        try:
            from ..core.db import engine as _engine2
            for s in symbols:
                sym = normalize_symbol(s)
                if sym in out:
                    continue
                # 尝试粘性缓存
                prev_raw = _cache_get(f"spot:last_item:{sym}")
                if prev_raw:
                    try:
                        prev = json.loads(prev_raw)
                        # 应用数值标准化
                        for k in numeric_fields:
                            if prev.get(k) is None:
                                prev[k] = 0
                        # 确保 symbol/name 存在
                        prev['symbol'] = sym
                        out[sym] = prev
                        continue
                    except Exception:
                        pass
                # 尝试以数据库最新收盘价作为 price/pre_close 回退
                try:
                    from sqlalchemy import text as _sa_text2
                    with _engine2.begin() as conn:
                        r = conn.execute(_sa_text2("SELECT close FROM prices_daily WHERE symbol=:s ORDER BY trade_date DESC LIMIT 1"), {"s": sym}).first()
                    last_close = float(r[0]) if r and r[0] is not None else 0.0
                except Exception:
                    last_close = 0.0
                out[sym] = {
                    'name': None,
                    'symbol': sym,
                    'price': last_close,
                    'change': 0,
                    'pct_change': 0,
                    'volume': 0,
                    'amount': 0,
                    'turnover_rate': 0,
                    'volume_ratio': 0,
                    'amplitude': 0,
                    'pe_ttm': 0,
                    'pb': 0,
                    'total_market_cap': 0,
                    'high': 0,
                    'low': 0,
                    'open': 0,
                    'pre_close': last_close,
                    'order_ratio': 0,
                    'last_volume': 0,
                    'speed': 0,
                }
        except Exception:
            pass
        return out
    except Exception as e:
        _log_throttled('akshare_spot_error', logging.WARNING, f"Akshare spot failed: {e} — using fallbacks", 60)
        # 全量回退：对所有标的使用东方财富+新浪组合补齐
        try:
            # 先东方财富，后新浪回补
            out = _fetch_spot_from_eastmoney(bases)
            smap = _fetch_spot_from_sina(bases)
            # 合并新浪数据
            for symb, sm in smap.items():
                if symb not in out:
                    if 'spot_source' not in sm or sm.get('spot_source') is None:
                        sm['spot_source'] = 'sina'
                    out[symb] = sm
                else:
                    for k, v in sm.items():
                        if out[symb].get(k) is None and v is not None:
                            out[symb][k] = v
            # 在全量回退路径同样应用粘性回填
            sticky_fields = [
                'change','pct_change','speed','volume','amount','turnover_rate','volume_ratio','amplitude',
                'last_volume','high','low','open','pre_close','order_ratio','pe_ttm','pb','total_market_cap'
            ]
            prefer_prev_if_zero = {'speed','order_ratio','last_volume'}
            for symb, item in out.items():
                try:
                    prev_raw = _cache_get(f"spot:last_item:{symb}")
                    if prev_raw:
                        try:
                            prev = json.loads(prev_raw)
                        except Exception:
                            prev = None
                        if isinstance(prev, dict):
                            # 基于涨跌幅差/分钟估算涨速
                            try:
                                cur_pct = to_float(item.get('pct_change'))
                                prev_pct = to_float(prev.get('pct_change'))
                                prev_ts = float(prev.get('ts')) if prev.get('ts') is not None else None
                                now_ts = time.time()
                                if cur_pct is not None and prev_pct is not None and prev_ts is not None:
                                    dt = max(now_ts - prev_ts, 1.0)
                                    # 仅在上次时间戳较近（10 分钟内）时计算
                                    if 0 < dt < 600:
                                        sp = (cur_pct - prev_pct) / dt * 60.0
                                        if -100.0 <= sp <= 100.0:
                                            cur_sp = item.get('speed')
                                            if cur_sp is None or (isinstance(cur_sp, (int, float)) and (abs(float(cur_sp)) < 1e-9 or abs(float(cur_sp)) > 100.0)):
                                                item['speed'] = sp
                            except Exception:
                                pass
                            for k in sticky_fields:
                                cur_val = item.get(k)
                                prev_val = prev.get(k)
                                if prev_val is None:
                                    continue
                                zero_like = False
                                try:
                                    zero_like = (isinstance(cur_val, (int,float)) and abs(float(cur_val)) < 1e-9)
                                except Exception:
                                    zero_like = False
                                if cur_val is None or (k in prefer_prev_if_zero and zero_like):
                                    if k == 'speed':
                                        try:
                                            if abs(float(prev_val)) > 100:
                                                continue
                                        except Exception:
                                            continue
                                    item[k] = prev_val
                    item['ts'] = time.time()
                    _cache_setex(f"spot:last_item:{symb}", 300, json.dumps(item, ensure_ascii=False))
                except Exception:
                    pass
            # 回退路径同样进行最终标准化
            numeric_fields = [
                'change','pct_change','speed','volume','amount','turnover_rate','volume_ratio','amplitude',
                'last_volume','high','low','open','pre_close','order_ratio','pe_ttm','pb','total_market_cap'
            ]
            for symb, item in out.items():
                try:
                    sp = item.get('speed')
                    if sp is not None and isinstance(sp, (int, float)) and abs(float(sp)) > 100:
                        item['speed'] = None
                except Exception:
                    item['speed'] = None
                for k in numeric_fields:
                    if item.get(k) is None:
                        item[k] = 0

            # 确保所有请求的标的都能返回：优先粘性缓存，最后回退到数据库日线
            from ..core.db import engine as _engine3
            for s in symbols:
                sym = normalize_symbol(s)
                if sym in out:
                    continue
                # 优先使用粘性缓存
                prev_raw = _cache_get(f"spot:last_item:{sym}")
                if prev_raw:
                    try:
                        prev = json.loads(prev_raw)
                        for k in numeric_fields:
                            if prev.get(k) is None:
                                prev[k] = 0
                        prev['symbol'] = sym
                        out[sym] = prev
                        continue
                    except Exception:
                        pass
                # 兜底：使用数据库最近的收盘价填充
                last_close = 0.0
                try:
                    from sqlalchemy import text as _sa_text3
                    with _engine3.begin() as conn:
                        r = conn.execute(_sa_text3("SELECT close FROM prices_daily WHERE symbol=:s ORDER BY trade_date DESC LIMIT 1"), {"s": sym}).first()
                    if r and r[0] is not None:
                        last_close = float(r[0])
                except Exception:
                    last_close = 0.0
                out[sym] = {
                    'name': None,
                    'symbol': sym,
                    'price': last_close,
                    'change': 0,
                    'pct_change': 0,
                    'volume': 0,
                    'amount': 0,
                    'turnover_rate': 0,
                    'volume_ratio': 0,
                    'amplitude': 0,
                    'pe_ttm': 0,
                    'pb': 0,
                    'total_market_cap': 0,
                    'high': 0,
                    'low': 0,
                    'open': 0,
                    'pre_close': last_close,
                    'order_ratio': 0,
                    'last_volume': 0,
                    'speed': 0,
                }
            return out
        except Exception as fallback_error:
            _log_throttled('spot_snapshot_fallback_error', logging.ERROR, f"Fallback snapshot pipeline failed: {fallback_error}", 60)
            empty = {}
            for s in symbols:
                sym = normalize_symbol(s)
                empty[sym] = {
                    'name': None,
                    'symbol': sym,
                    'price': 0,
                    'change': 0,
                    'pct_change': 0,
                    'volume': 0,
                    'amount': 0,
                    'turnover_rate': 0,
                    'volume_ratio': 0,
                    'amplitude': 0,
                    'pe_ttm': 0,
                    'pb': 0,
                    'total_market_cap': 0,
                    'high': 0,
                    'low': 0,
                    'open': 0,
                    'pre_close': 0,
                    'order_ratio': 0,
                    'last_volume': 0,
                    'speed': 0,
                }
            return empty