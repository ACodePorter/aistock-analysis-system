import requests
import random
import asyncio
import time
import os
import json
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, date
import re
import traceback  # added for error fallback report
from collections import defaultdict
from pathlib import Path as _Path
import hashlib
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import statistics

# 直接API信源模块 - 当SearXNG不可用时的备用信源
try:
    from app.utils.direct_news_api import fetch_news_direct, get_direct_api, DIRECT_API_ENABLED
    DIRECT_API_AVAILABLE = True
except ImportError:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from app.utils.direct_news_api import fetch_news_direct, get_direct_api, DIRECT_API_ENABLED
        DIRECT_API_AVAILABLE = True
    except ImportError:
        DIRECT_API_AVAILABLE = False
        DIRECT_API_ENABLED = False
        fetch_news_direct = None
        get_direct_api = None

# 尝试导入 NewsProcessor 用于正文抽取（无需依赖数据库写入）
try:
    # 当以脚本方式运行时，确保可以定位到 backend/app 包
    from app.news_service import NewsProcessor  # type: ignore
except Exception:
    try:
        sys.path.append(str(Path(__file__).resolve().parents[2]))  # add 'backend' to sys.path
        from app.news_service import NewsProcessor  # type: ignore
    except Exception:
        NewsProcessor = None  # 在不可用时，后续将跳过富化流程

# 预加载项目根目录 .env（不新增依赖，手动解析简单 key=value，忽略注释与空行）
def _load_dotenv():
    root = Path(__file__).resolve().parent.parent.parent.parent  # 回到仓库根目录
    env_file = root / '.env'
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            # 不覆盖已有环境
            if k and k not in os.environ:
                if k == 'AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A':
                    if os.getenv('AGENT_DEBUG_LOG', '0') == '1':
                        print(f"[env-debug] setting AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={v}")
                os.environ[k] = v
    except Exception as e:
        print(f"[env] 加载 .env 警告: {e}")

_load_dotenv()

# 环境变量配置（沿用现有 .env 体系；不强制新增命名）
# 后端端口 8080；SearXNG 若未在 .env 中指定则使用默认 10000；LLM 优先使用 Azure OpenAI 配置。
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:10000")  # 可在 .env 增加 SEARXNG_URL 覆盖
# 可选：提供多个 SearXNG 端点，逗号分隔；请求时自动轮换
_SEARXNG_URLS = [u.strip().rstrip('/') for u in os.getenv("SEARXNG_URLS", "").split(',') if u.strip()]
if not _SEARXNG_URLS:
    _SEARXNG_URLS = [SEARXNG_URL.rstrip('/')]

# 后端 API 基址（用于 DB 回退拉取已存文章）
API_BASE = os.getenv("API_BASE", "http://localhost:8080").rstrip('/')
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", API_BASE)  # 兼容 enhanced_news_fetch 模块
MOVERS_API_URL = os.getenv("MOVERS_API_URL", "http://localhost:8080/api/movers/live_insight?limit=20")

# Azure OpenAI（根据现有 .env）
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")  # 例如 https://xxx.openai.azure.com
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_MODEL")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")

# 兼容：如果用户已经单独提供了一个通用 OpenAI Chat 端点（非 Azure），仍可通过 LLM_API_URL 指定。
LLM_API_URL = os.getenv("LLM_API_URL")  # 可选，不在 .env 中则为 None

HAS_AZURE = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY and AZURE_OPENAI_DEPLOYMENT)
AZURE_USE_RESPONSES = AZURE_OPENAI_API_VERSION.startswith("2025-") and os.getenv("AGENT_DISABLE_RESPONSES","0") != "1"  # 可通过 AGENT_DISABLE_RESPONSES 关闭
_CHAT_EMPTY_COUNT = 0
_FORCE_NO_RESPONSE_FORMAT = False
USE_LLM = HAS_AZURE or bool(LLM_API_URL)  # 若两者都无，则后续退化为无 LLM 评分模式

# Debug logs are OFF by default to keep daily outputs clean.
AGENT_DEBUG_LOG = os.getenv('AGENT_DEBUG_LOG', '0') == '1'
# Storage behavior:
# - By default, write reports to MongoDB (primary) and DO NOT write local report files.
# - Set AGENT_REPORT_WRITE_FILES=1 to also write local JSON/Markdown.
# - Metrics are also file-based by default; set AGENT_METRICS_WRITE_FILES=1 to enable.
AGENT_REPORT_WRITE_FILES = os.getenv('AGENT_REPORT_WRITE_FILES', '0') == '1'
AGENT_METRICS_WRITE_FILES = os.getenv('AGENT_METRICS_WRITE_FILES', '0') == '1'
# Ensure reports are written to the repository root agent_reports directory (same path main.py scans)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUTPUT_DIR = os.getenv("AGENT_REPORT_DIR") or str((_REPO_ROOT / "agent_reports").resolve())
os.makedirs(OUTPUT_DIR, exist_ok=True)
_AZURE_LAST_ERROR: Optional[str] = None
_AZURE_FAIL_COUNT = 0
_FALLBACK_STOCK_COUNT = 0
_FALLBACK_MACRO = False
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 严格 JSON 模式（A+B+E）：
# 通过环境变量 AGENT_STRICT_JSON=1 启用。开启后：
# 1) 在用户 prompt 之前加系统级前缀，明确只允许 JSON。
# 2) 若首次解析失败，进行一次轻量 Retry（同一提示再强调“只输出 JSON”）。
# 3) 记录严格模式重试计数进入 diagnostics。
# 默认开启严格 JSON；可通过 AGENT_STRICT_JSON=0 关闭
AGENT_STRICT_JSON = True  # 强制严格JSON模式，便于调试和修复400错误
_STRICT_JSON_RETRY_STOCK = 0
_STRICT_JSON_RETRY_MACRO = 0

# 系统前缀：对多轮或不同函数共用，避免重复散落。
STRICT_JSON_PREFIX = (
    "你现在处于严格 JSON 输出模式。务必只输出一个 JSON 对象(json)，不要添加任何解释、注释、反引号、语言标记或额外文本。Return json only. Output exactly one json object with no extra text." if AGENT_STRICT_JSON else ""
)

# 解析/验证统计
_PARSE_SUCCESS_STOCK = 0
_PARSE_SUCCESS_STOCK_RETRY = 0
_PARSE_SUCCESS_MACRO = 0
_PARSE_SUCCESS_MACRO_RETRY = 0

# Global metrics for SearXNG filtering diagnostics
_SEARX_FILTER_METRICS: Dict[str, int] = defaultdict(int)

# Dynamic engine cooldown (best-effort):
# Some engines (e.g., sogou / sogou wechat) may redirect to HTTP or be blocked, which can
# spam SearXNG logs and trigger internal "Suspend" backoff. We mitigate by removing
# problematic engines for a short cooldown window based on SearXNG's JSON API error signals.
_SEARX_ENGINE_COOLDOWN_UNTIL: Dict[str, float] = {}

# ------------------------------
# 媒体增量搜索（按域名）辅助
# ------------------------------
_MEDIA_SINCE_FILE = os.getenv("AGENT_MEDIA_SINCE_FILE", str((_Path(__file__).resolve().parents[2] / 'agent_reports' / 'agent_media_since.json')))

def _media_since_load() -> Dict[str, str]:
    try:
        p = _Path(_MEDIA_SINCE_FILE)
        if p.exists():
            return json.loads(p.read_text('utf-8'))
    except Exception:
        pass
    return {}

def _media_since_save(since_map: Dict[str, str]):
    try:
        p = _Path(_MEDIA_SINCE_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(since_map, ensure_ascii=False, indent=2), 'utf-8')
    except Exception as e:
        print(f"[media-since] 保存失败: {e}")

# ------------------------------
# 通用 HTTP 重试/退避
# ------------------------------
_HTTP_MAX_RETRIES = int(os.getenv('AGENT_HTTP_MAX_RETRIES', '2'))
_HTTP_BACKOFF_BASE = float(os.getenv('AGENT_HTTP_BACKOFF_BASE', '1.5'))
_HTTP_JITTER_MS = int(os.getenv('AGENT_HTTP_JITTER_MS', '200'))
_HTTP_TIMEOUT_DB = int(os.getenv('AGENT_HTTP_TIMEOUT_DB', '30'))
_HTTP_TIMEOUT_ENRICHED = int(os.getenv('AGENT_HTTP_TIMEOUT_ENRICHED', '45'))
_HTTP_TIMEOUT_MEDIA = int(os.getenv('AGENT_HTTP_TIMEOUT_MEDIA', '25'))

def _request_with_retry(method: str,
                        url: str,
                        *,
                        timeout: int = 20,
                        params: Optional[Dict[str, Any]] = None,
                        headers: Optional[Dict[str, str]] = None,
                        data: Any = None,
                        json_body: Any = None,
                        max_retries: Optional[int] = None,
                        backoff_base: Optional[float] = None) -> requests.Response:
    """统一带重试的 HTTP 请求。对超时、连接错误、HTTP 429/5xx 进行重试，指数退避+抖动。
    抛出最后一次异常或返回响应（对 4xx 视为最终）。
    """
    if max_retries is None:
        max_retries = _HTTP_MAX_RETRIES
    if backoff_base is None:
        backoff_base = _HTTP_BACKOFF_BASE
    last_exc: Optional[Exception] = None
    for attempt in range(max(0, max_retries) + 1):
        try:
            resp = requests.request(method.upper(), url, timeout=timeout, params=params, headers=headers, data=data, json=json_body)
            # 对 429/5xx 进行重试；其他 4xx 直接返回
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                raise last_exc
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
        except Exception as e:
            last_exc = e
        # 退避等待
        if attempt < max_retries:
            sleep_s = (backoff_base ** attempt) + (random.randint(0, max(0, _HTTP_JITTER_MS)) / 1000.0)
            try:
                time.sleep(sleep_s)
            except Exception:
                pass
        else:
            # 最后一次失败，抛出
            if last_exc:
                raise last_exc
            raise RuntimeError("HTTP request failed without exception")

def _media_incremental_fetch(query: str, domains: List[str], since_map: Dict[str, str], max_results: int) -> List[Dict]:
    """调用后端 /api/news/search_incremental，按域名增量拉取，并更新 since_map。"""
    out: List[Dict] = []
    api = f"{API_BASE}/api/news/search_incremental"
    headers = {"Content-Type": "application/json"}
    for d in domains:
        d = d.strip()
        if not d:
            continue
        payload = {
            "query": query,
            "category": "general",
            "time_range": os.getenv("SEARXNG_TIME_RANGE", "month"),
            "max_results": max_results,
            "language": os.getenv("SEARXNG_LANGUAGE", None),
            "include_domains": [d],
            "since": since_map.get(d) or None,
        }
        try:
            r = _request_with_retry('post', api, headers=headers, data=json.dumps(payload), timeout=_HTTP_TIMEOUT_MEDIA)
            if r.status_code == 200:
                jr = r.json() or {}
                arts = jr.get('articles') or []
                out.extend(arts)
                latest = jr.get('latest_published')
                if isinstance(latest, str) and latest:
                    prev = since_map.get(d)
                    try:
                        import datetime as _dt
                        ld = _dt.datetime.fromisoformat(latest)
                        pd = _dt.datetime.fromisoformat(prev) if prev else None
                        if pd is None or ld > pd:
                            since_map[d] = latest
                    except Exception:
                        since_map[d] = latest
            else:
                print(f"[media-inc] {d} status={r.status_code} body={r.text[:180] if hasattr(r,'text') else ''}")
        except Exception as e:
            print(f"[media-inc] {d} 调用失败: {e}")
    return out

def _clamp(v, lo, hi):
    try:
        return lo if v < lo else hi if v > hi else v
    except Exception:
        return lo

def validate_stock_json(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure required fields & basic types/ranges for stock analysis JSON."""
    if not isinstance(data, dict):
        return {}
    res = {}
    res['sentiment_score'] = float(_clamp(float(data.get('sentiment_score', 0.0)), -1, 1))
    # Normalize sentiment label: accept either English enum or Chinese label.
    lab_en = (data.get('sentiment_label_en') or '').strip().lower()
    lab_raw = (data.get('sentiment_label') or '').strip()
    if lab_en not in ('positive', 'neutral', 'negative'):
        zh_to_en = {'正面': 'positive', '中性': 'neutral', '负面': 'negative'}
        lab_en = zh_to_en.get(lab_raw, '')
    if lab_en not in ('positive', 'neutral', 'negative'):
        lab_en = 'neutral'

    # Public-facing outputs must be simplified Chinese; keep English label in a separate field.
    res['sentiment_label_en'] = lab_en
    res['sentiment_label'] = '正面' if lab_en == 'positive' else ('负面' if lab_en == 'negative' else '中性')
    # factors
    factors = []
    for f in data.get('factors') or []:
        if not isinstance(f, dict):
            continue
        name = str(f.get('name') or '').strip() or '未命名因子'
        direction = f.get('direction') if f.get('direction') in ('正面','负面','不确定') else '不确定'
        try:
            weight = float(f.get('weight', 0))
        except Exception:
            weight = 0.0
        evidence_raw = str(f.get('evidence') or '')
        # 屏蔽内部实现细节/占位措辞
        ev = evidence_raw
        for ban in ('localhost', '占位', 'about:placeholder', '后端接口超时', '暂缺新闻'):
            ev = ev.replace(ban, '')
        evidence = ev.strip()[:400]
        factors.append({'name': name, 'direction': direction, 'weight': weight, 'evidence': evidence})
    if not factors:
        factors = [{'name':'信息不足','direction':'不确定','weight':1.0,'evidence':'LLM 空'}]
    # re-normalize weights if positive sum
    s = sum(max(f['weight'],0) for f in factors)
    if s > 0:
        for f in factors:
            f['weight'] = round(max(f['weight'],0)/s,4)
    # 约束“信息不足”类因子的权重占比，避免其主导
    insuff_idx = [i for i,f in enumerate(factors) if '信息不足' in (f.get('name') or '')]
    if insuff_idx and len(factors) > 1:
        # 将其上限设为 0.3，再按比例把多余的分配给其他因子
        for idx in insuff_idx:
            if factors[idx]['weight'] > 0.3:
                excess = factors[idx]['weight'] - 0.3
                factors[idx]['weight'] = 0.3
                # 分配给非不足因子
                others = [j for j in range(len(factors)) if j not in insuff_idx]
                if others:
                    add = excess / len(others)
                    for j in others:
                        factors[j]['weight'] = round(factors[j]['weight'] + add, 4)
    res['factors'] = factors[:12]
    res['score'] = int(_clamp(int(data.get('score', 50)), 0, 100))
    res['need_macro'] = bool(data.get('need_macro', False))
    # macro keywords
    mk = []
    for k in (data.get('macro_keywords') or [])[:5]:
        if k:
            mk.append(str(k)[:40])
    res['macro_keywords'] = mk
    rk = []
    for k in (data.get('risk_flags') or [])[:8]:
        if k:
            rk.append(str(k)[:60])
    res['risk_flags'] = rk
    cw_out = []
    for c in (data.get('correlation_watch') or [])[:6]:
        if isinstance(c, dict):
            cw_out.append({
                'metric': str(c.get('metric') or '')[:40],
                'reason': str(c.get('reason') or '')[:120],
                'suggest_window': str(c.get('suggest_window') or '')[:30]
            })
    res['correlation_watch'] = cw_out
    try:
        conf = float(data.get('confidence', 0.5))
    except Exception:
        conf = 0.5
    res['confidence'] = round(_clamp(conf,0,1),3)
    res['summary'] = str(data.get('summary') or '')[:1200]
    return res

def validate_macro_json(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    r = {}
    r['market_sentiment_index'] = int(_clamp(int(data.get('market_sentiment_index',50)),0,100))
    r['risk_index'] = int(_clamp(int(data.get('risk_index',50)),0,100))
    ih_out = []
    for it in (data.get('industry_heat') or [])[:10]:
        if isinstance(it, dict):
            ih_out.append({
                'industry': str(it.get('industry') or '')[:40],
                'heat': int(_clamp(int(it.get('heat',0)),0,100)),
                'drivers': [str(d)[:24] for d in (it.get('drivers') or [])[:4]]
            })
    r['industry_heat'] = ih_out
    pt = data.get('policy_tone') or {}
    bias = pt.get('bias') if pt.get('bias') in ('supportive','neutral','restrictive') else 'neutral'
    r['policy_tone'] = {'summary': str(pt.get('summary') or '')[:400], 'bias': bias}
    r['capital_flow_focus'] = [str(x)[:40] for x in (data.get('capital_flow_focus') or [])[:10]]
    mf_out = []
    for m in (data.get('macro_factors') or [])[:12]:
        if isinstance(m, dict):
            impact = m.get('impact') if m.get('impact') in ('正面','负面','中性') else '中性'
            try:
                conf = float(m.get('confidence',0.5))
            except Exception:
                conf = 0.5
            mf_out.append({'name': str(m.get('name') or '')[:60], 'impact': impact, 'confidence': round(_clamp(conf,0,1),3)})
    r['macro_factors'] = mf_out
    ai_out = []
    for a in (data.get('actionable_insights') or [])[:8]:
        if isinstance(a, dict):
            ai_out.append({
                'theme': str(a.get('theme') or '')[:60],
                'rationale': str(a.get('rationale') or '')[:240],
                'watch_metrics': [str(x)[:40] for x in (a.get('watch_metrics') or [])[:6]]
            })
    r['actionable_insights'] = ai_out
    r['suggest_global_watch'] = [str(x)[:50] for x in (data.get('suggest_global_watch') or [])[:10]]
    r['extra_keywords'] = [str(x)[:40] for x in (data.get('extra_keywords') or [])[:8]]
    r['summary'] = str(data.get('summary') or '')[:1500]
    return r

# 配置（可通过环境覆盖）
MAX_STOCK_NEWS = int(os.getenv("AGENT_STOCK_NEWS_LIMIT", "10"))  # 需求 5=10 可配置
MAX_MACRO_KEYWORDS = int(os.getenv("AGENT_MAX_MACRO_KEYWORDS", "15"))
PARALLEL_WORKERS = int(os.getenv("AGENT_PARALLEL_WORKERS", "8"))

# ------------------------------
# 多信源采集 + 入库前 LLM Gate（脚本侧闭环）
# ------------------------------
AGENT_MULTI_SOURCE = os.getenv('AGENT_MULTI_SOURCE', '1') in ('1', 'true', 'yes')
AGENT_NEWS_GATE = os.getenv('AGENT_NEWS_GATE', '1') in ('1', 'true', 'yes')
AGENT_NEWS_PIPELINE_WRITE_DB = os.getenv('AGENT_NEWS_PIPELINE_WRITE_DB', '1') in ('1', 'true', 'yes')

AGENT_NEWS_DB_FIRST_MIN = int(os.getenv('AGENT_NEWS_DB_FIRST_MIN', str(min(5, MAX_STOCK_NEWS))))
AGENT_NEWS_GATE_MAX_CANDIDATES = int(os.getenv('AGENT_NEWS_GATE_MAX_CANDIDATES', '12'))
AGENT_NEWS_GATE_RELEVANCE_THRESHOLD = float(os.getenv('AGENT_NEWS_GATE_RELEVANCE_THRESHOLD', '0.35'))
AGENT_NEWS_GATE_TITLE_ONLY_KEYWORDS = [
    k.strip() for k in os.getenv('AGENT_NEWS_GATE_TITLE_ONLY_KEYWORDS', '公告,年度报告,业绩预告,业绩快报,停牌,复牌,回购,减持,增持,股权激励,重大合同,中标,签约,投资,收购,重组,诉讼,立案,监管,问询,处罚').split(',')
    if k.strip()
]

AGENT_BACKEND_TIMEOUT = float(os.getenv('AGENT_BACKEND_TIMEOUT', '25'))
AGENT_BACKEND_STOCK_DAYS = int(os.getenv('AGENT_BACKEND_STOCK_DAYS', '7'))
AGENT_BACKEND_STOCK_FALLBACK_DAYS = int(os.getenv('AGENT_BACKEND_STOCK_FALLBACK_DAYS', '60'))
AGENT_BACKEND_STOCK_ENSURE_MIN = int(os.getenv('AGENT_BACKEND_STOCK_ENSURE_MIN', str(min(5, MAX_STOCK_NEWS))))
AGENT_BACKEND_TRIGGER_TOPUP = os.getenv('AGENT_BACKEND_TRIGGER_TOPUP', '1') in ('1', 'true', 'yes')
AGENT_BACKEND_TOPUP_WAIT_SECONDS = int(os.getenv('AGENT_BACKEND_TOPUP_WAIT_SECONDS', '1'))

# Global pre-ingest (build a larger DB pool before daily analysis)
AGENT_GLOBAL_PRE_INGEST = os.getenv('AGENT_GLOBAL_PRE_INGEST', '1') in ('1', 'true', 'yes')
env_value = os.getenv('AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A', '1')
AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A = env_value in ('1', 'true', 'yes')
AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A_MAX_FEEDS = int(os.getenv('AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A_MAX_FEEDS', '3'))
AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A_MAX_ITEMS = int(os.getenv('AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A_MAX_ITEMS', '12'))
AGENT_GLOBAL_PRE_INGEST_MEDIA_BASE_URLS = [
    x.strip().rstrip('/') for x in os.getenv('AGENT_GLOBAL_PRE_INGEST_MEDIA_BASE_URLS', '').split(',') if x.strip()
]
AGENT_GLOBAL_PRE_INGEST_MEDIA_FEED_URLS = [
    x.strip() for x in os.getenv('AGENT_GLOBAL_PRE_INGEST_MEDIA_FEED_URLS', '').split(',') if x.strip()
]
AGENT_GLOBAL_PRE_INGEST_OPML_URLS = [
    x.strip() for x in os.getenv('AGENT_GLOBAL_PRE_INGEST_OPML_URLS', '').split(',') if x.strip()
]
AGENT_GLOBAL_PRE_INGEST_OPML_MAX_FEEDS = int(os.getenv('AGENT_GLOBAL_PRE_INGEST_OPML_MAX_FEEDS', '80'))
AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT = float(os.getenv('AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT', '20'))

# RSSHub rewrite (recommended: self-host; keep downstream ingest unchanged)
AGENT_RSSHUB_REWRITE_ENABLE = os.getenv('AGENT_RSSHUB_REWRITE_ENABLE', '0') in ('1', 'true', 'yes')
AGENT_RSSHUB_BASE = (os.getenv('AGENT_RSSHUB_BASE', '') or '').strip().rstrip('/')
AGENT_GLOBAL_PRE_INGEST_MEDIA_MAX_FEEDS_PER_SITE = int(os.getenv('AGENT_GLOBAL_PRE_INGEST_MEDIA_MAX_FEEDS_PER_SITE', '2'))
AGENT_GLOBAL_PRE_INGEST_RSS_MAX_ITEMS = int(os.getenv('AGENT_GLOBAL_PRE_INGEST_RSS_MAX_ITEMS', '25'))

# Feed quality heuristics (to avoid polluting DB with stale/garbled feeds)
AGENT_FEED_MIN_RECENCY_DAYS = int(os.getenv('AGENT_FEED_MIN_RECENCY_DAYS', '180'))
AGENT_FEED_MIN_MEDIAN_TITLE_LEN = int(os.getenv('AGENT_FEED_MIN_MEDIAN_TITLE_LEN', '6'))
AGENT_FEED_QUALITY_CHECK_ENABLE = os.getenv('AGENT_FEED_QUALITY_CHECK_ENABLE', '1') in ('1', 'true', 'yes')

# Built-in seed feeds (best-effort). These are only used when the user did not configure
# AGENT_GLOBAL_PRE_INGEST_MEDIA_FEED_URLS.
_AGENT_BUILTIN_SEED_FEEDS: List[str] = [
    # Investing.com (international)
    'https://www.investing.com/rss/news.rss',
    # GFM Review
    'https://www.gfmreview.com/rss/all-stories',
    'https://www.gfmreview.com/rss/banking',
]
if not AGENT_GLOBAL_PRE_INGEST_MEDIA_FEED_URLS:
    AGENT_GLOBAL_PRE_INGEST_MEDIA_FEED_URLS = list(_AGENT_BUILTIN_SEED_FEEDS)

_GLOBAL_PRE_INGEST_DONE = False

AGENT_GATE_AUDIT_MONGO_ENABLE = os.getenv('AGENT_GATE_AUDIT_MONGO_ENABLE', '1') in ('1', 'true', 'yes')
AGENT_GATE_AUDIT_TTL_DAYS = int(os.getenv('AGENT_GATE_AUDIT_TTL_DAYS', '14'))


def _backend_url(path: str) -> str:
    p = (path or '').strip()
    if not p.startswith('/'):
        p = '/' + p
    return API_BASE.rstrip('/') + p


def _safe_get(d: Any, key: str, default=None):
    try:
        if isinstance(d, dict):
            return d.get(key, default)
    except Exception:
        pass
    return default


def _backend_get_json(path: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
    url = _backend_url(path)
    try:
        r = requests.get(url, params=params or {}, timeout=timeout or AGENT_BACKEND_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        return j if isinstance(j, dict) else None
    except Exception as e:
        if AGENT_DEBUG_LOG:
            print(f"[multi-source] backend GET failed: {url} err={e}")
        return None


def _backend_post_json(path: str, payload: Dict[str, Any], timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
    url = _backend_url(path)
    try:
        r = requests.post(url, json=payload, timeout=timeout or AGENT_BACKEND_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        return j if isinstance(j, dict) else None
    except Exception as e:
        if AGENT_DEBUG_LOG:
            body = ''
            try:
                body = getattr(e, 'response', None).text[:200]  # type: ignore
            except Exception:
                body = ''
            print(f"[multi-source] backend POST failed: {url} err={e} body={body}")
        return None


def _md5_hex(s: str) -> str:
    return hashlib.md5((s or '').encode('utf-8')).hexdigest()


def _maybe_rewrite_rsshub(url: str) -> str:
    """Optionally rewrite rsshub.app URLs to self-hosted RSSHub base."""
    u = (url or '').strip()
    if not u:
        return u
    if not AGENT_RSSHUB_REWRITE_ENABLE:
        return u
    if not AGENT_RSSHUB_BASE:
        return u
    try:
        if u.startswith('https://rsshub.app/'):
            return AGENT_RSSHUB_BASE + u[len('https://rsshub.app'):]
        if u.startswith('http://rsshub.app/'):
            return AGENT_RSSHUB_BASE + u[len('http://rsshub.app'):]
    except Exception:
        return u
    return u


def _parse_opml_xmlurls(xml_text: str, *, limit: int) -> List[str]:
    """Extract feed urls from OPML. Returns list of xmlUrl values."""
    out: List[str] = []
    if not xml_text:
        return out
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    # OPML typically: <opml><body><outline xmlUrl="..." />...</body></opml>
    for node in root.findall('.//outline'):
        if len(out) >= int(limit):
            break
        u = (node.attrib.get('xmlUrl') or '').strip()
        if not u:
            continue
        if not (u.startswith('http://') or u.startswith('https://')):
            continue
        out.append(u)
    # Dedup keep order
    seen = set()
    res: List[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        res.append(u)
    return res


def _gate_audit_mongo(*, kind: str, url: str, symbol: Optional[str], company_name: Optional[str], source: Optional[str], decision: Dict[str, Any]) -> bool:
    """将 gate 结果写入 Mongo news_error_logs（幂等 upsert）。"""
    if not AGENT_GATE_AUDIT_MONGO_ENABLE:
        return False
    u = (url or '').strip()
    if not u:
        return False
    try:
        from pymongo import MongoClient  # type: ignore
    except Exception:
        return False

    try:
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        db_name = os.getenv("MONGO_DB_NAME", os.getenv("MONGO_DB", "aistock_news"))
        coll_name = os.getenv("AGENT_GATE_AUDIT_COLLECTION", "news_error_logs")

        parsed = urlparse(u)
        domain = parsed.netloc
        now = datetime.utcnow()
        url_hash = _md5_hex(u)

        doc_set = {
            'kind': (kind or '').lower(),
            'url': u,
            'url_hash': url_hash,
            'domain': domain,
            'symbol': (symbol or '').upper() if symbol else None,
            'company_name': company_name,
            'source': source,
            'message': decision.get('reason') if isinstance(decision, dict) else None,
            'detail': decision if isinstance(decision, dict) else {},
            'updated_at': now,
        }
        doc_on_insert = {
            'created_at': now,
            'status': 'gate',
            'ttl_days': int(AGENT_GATE_AUDIT_TTL_DAYS),
        }

        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000)
        db = client[db_name]
        coll = db[coll_name]
        coll.update_one(
            {'kind': (kind or '').lower(), 'url_hash': url_hash, 'symbol': (symbol or '').upper() if symbol else None},
            {'$set': doc_set, '$setOnInsert': doc_on_insert},
            upsert=True,
        )
        return True
    except Exception:
        return False


def _llm_gate_item(*, company_name: str, symbol: Optional[str], title: str, content: str, source: str, url: str) -> Dict[str, Any]:
    """LLM 价值门卫：判断是否值得入库。严格输出 JSON；失败则启发式降级。"""
    title_s = (title or '').strip()
    content_s = (content or '').strip()

    # Title-only fast keep for announcements when content is empty
    if not content_s and title_s:
        for kw in AGENT_NEWS_GATE_TITLE_ONLY_KEYWORDS:
            if kw and kw in title_s:
                return {
                    'keep': True,
                    'relevance': 0.7,
                    'value_level': 'medium',
                    'category': '公告',
                    'reason': f'标题包含关键信披词：{kw}',
                    'source': source,
                }

    # If LLM disabled, heuristic fallback
    if not USE_LLM or not AGENT_NEWS_GATE:
        low = (title_s + ' ' + content_s).lower()
        bad = any(k in low for k in ('百科', '维基', 'wiki', '问答', '贴吧', '论坛', '商品', '购物', '价格', '行情', '股吧'))
        keep = (not bad) and (len(content_s) >= 60 or len(title_s) >= 10)
        return {
            'keep': bool(keep),
            'relevance': 0.5 if keep else 0.1,
            'value_level': 'low' if keep else 'none',
            'category': '其他',
            'reason': '启发式判定（LLM 未启用）',
            'source': source,
        }

    excerpt = content_s
    if len(excerpt) > 900:
        excerpt = excerpt[:900]

    sym = (symbol or '').strip().upper()
    prompt = (
        f"{STRICT_JSON_PREFIX}\n"
        "你是A股投研资讯的‘入库门卫’。任务：判断这条候选内容是否值得进入数据库用于‘每日分析’。\n"
        "要求：\n"
        "- 只输出一个 JSON 对象；不要输出任何额外文字。\n"
        "- 必须用简体中文。\n"
        "- 必须剔除低信息/非文章：字典/百科/论坛/电商/行情报价页/纯转载无增量/广告。\n"
        "- 关注可影响公司基本面/风险/股价驱动的增量信息（公告、订单、业绩、监管、诉讼、重大交易、产品、产能、资本运作等）。\n"
        "\n"
        "请输出 JSON，字段：\n"
        "{\n"
        "  \"keep\": true/false,\n"
        "  \"relevance\": 0.0-1.0,\n"
        "  \"value_level\": \"high\"|\"medium\"|\"low\"|\"none\",\n"
        "  \"category\": \"公告\"|\"经营\"|\"财务\"|\"监管\"|\"交易\"|\"诉讼\"|\"舆情\"|\"其他\",\n"
        "  \"reason\": \"不超过60字\",\n"
        "  \"key_points\": [\"要点1\", \"要点2\"]\n"
        "}\n"
        "\n"
        f"公司：{company_name}\n"
        f"股票：{sym}\n"
        f"来源：{source}\n"
        f"URL：{url}\n"
        f"标题：{title_s}\n"
        f"内容摘录：{excerpt}\n"
    )
    raw = _invoke_llm(prompt, temperature=0.2)
    js = _extract_first_json(_strip_code_fences(raw or '')) if raw else None
    try:
        data = json.loads(js) if js else {}
    except Exception:
        data = {}

    keep = bool(data.get('keep'))
    try:
        rel = float(data.get('relevance', 0.0))
    except Exception:
        rel = 0.0
    vl = str(data.get('value_level') or '').lower()
    if vl not in ('high', 'medium', 'low', 'none'):
        vl = 'none'
    cat = str(data.get('category') or '')
    reason = str(data.get('reason') or '')[:80]
    kps = data.get('key_points')
    if not isinstance(kps, list):
        kps = []
    kps_out = [str(x)[:60] for x in kps[:4] if x]

    # Enforce threshold
    final_keep = bool(keep and rel >= float(AGENT_NEWS_GATE_RELEVANCE_THRESHOLD) and vl != 'none')
    return {
        'keep': final_keep,
        'relevance': round(max(0.0, min(1.0, rel)), 3),
        'value_level': vl,
        'category': cat if cat else '其他',
        'reason': reason or ('通过' if final_keep else '不相关/低信息'),
        'key_points': kps_out,
        'source': source,
    }


def _fetch_stock_news_db_first(symbol: str) -> List[Dict[str, Any]]:
    """优先从后端 DB 取已入库高价值新闻，减少对搜索引擎依赖。"""
    sym = (symbol or '').strip().upper()
    if not sym:
        return []
    params = {
        'limit': int(MAX_STOCK_NEWS),
        'days': int(AGENT_BACKEND_STOCK_DAYS),
        'ensure_min': int(AGENT_BACKEND_STOCK_ENSURE_MIN),
        'fallback_days': int(AGENT_BACKEND_STOCK_FALLBACK_DAYS),
        'include_content': True,
        'min_content': 0,
        'trigger_topup': bool(AGENT_BACKEND_TRIGGER_TOPUP),
        'wait_seconds': int(AGENT_BACKEND_TOPUP_WAIT_SECONDS) if AGENT_BACKEND_TRIGGER_TOPUP else 0,
        'allow_placeholder': False,
    }
    j = _backend_get_json(f"/api/news/stock/{sym}", params=params)
    arts = _safe_get(j, 'articles', []) if isinstance(j, dict) else []
    out: List[Dict[str, Any]] = []
    if isinstance(arts, list):
        for a in arts:
            if not isinstance(a, dict):
                continue
            url = (a.get('url') or '').strip()
            title = (a.get('title') or '').strip() or url
            if not url:
                continue
            content = (a.get('content') or a.get('summary') or '').strip()
            out.append({
                'title': title,
                'url': url,
                'content': content,
                'published_at': a.get('published_at'),
                'source': a.get('source') or 'db',
                'from_db': True,
            })
    return out[: int(MAX_STOCK_NEWS)]


def _topup_official_for_symbol(symbol: str) -> int:
    """针对单只股票，触发官方披露补池（SSE/SZSE/CNINFO/CSRC），返回新增条目数。
    
    直接实现RSS发现和抓取，避免调用后端API导致timeout。
    """
    if AGENT_DEBUG_LOG:
        print(f"[topup-debug] BEFORE CHECK: symbol={symbol}, AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}, type={type(AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A)}")
        print(f"[topup-debug] checking: symbol={symbol}, AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}, type={type(AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A)}")
    if not symbol or not AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A:
        if AGENT_DEBUG_LOG:
            print(f"[topup-debug] skipped: symbol={symbol}, enabled={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}")
        return 0
    
    # 官方披露预设配置
    OFFICIAL_A_PRESETS = {
        'sse': {'name': '上交所（SSE）公告/披露', 'base_url': 'https://www.sse.com.cn'},
        'szse': {'name': '深交所（SZSE）公告/披露', 'base_url': 'https://www.szse.cn'},
        'cninfo': {'name': '巨潮资讯（CNINFO）公告', 'base_url': 'https://www.cninfo.com.cn'},
        'csrc': {'name': '证监会/监管披露', 'base_url': 'http://www.csrc.gov.cn'},
    }
    
    added_total = 0
    
    # 根据股票代码确定交易所
    symbol_upper = symbol.upper()
    if symbol_upper.startswith('6') or symbol_upper.startswith('9'):
        presets = ['sse', 'cninfo', 'csrc']  # 上海交易所
    elif symbol_upper.startswith('0') or symbol_upper.startswith('3'):
        presets = ['szse', 'cninfo', 'csrc']  # 深圳交易所
    else:
        presets = ['cninfo', 'csrc']  # 默认
    
    if AGENT_DEBUG_LOG:
        print(f"[topup-debug] symbol={symbol}, presets={presets}")
    
    for p in presets:
        meta = OFFICIAL_A_PRESETS.get(p)
        if not meta:
            continue
        
        base_url = meta['base_url']
        feeds_found = []
        
        # 快速探测几个常见RSS路径
        common_feed_paths = [
            '/rss.xml', '/feed.xml', '/atom.xml', '/rss', '/feed',
            '/disclosure/rss.xml', '/announcement/rss.xml',
            '/news/rss.xml', '/rss/news.xml'
        ]
        
        if AGENT_DEBUG_LOG:
            print(f"[topup-debug] checking {p} base_url={base_url}")
        
        for path in common_feed_paths[:3]:  # 只试前3个避免过多请求
            feed_url = f"{base_url.rstrip('/')}{path}"
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                    'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
                }
                r = _request_with_retry('get', feed_url, timeout=10, headers=headers)
                if r.status_code == 200:
                    body = _response_text_best_effort(r)
                    if body and ('<rss' in body.lower() or '<feed' in body.lower() or '<channel' in body.lower()):
                        feeds_found.append(feed_url)
                        if AGENT_DEBUG_LOG:
                            print(f"[topup-debug] found feed: {feed_url}")
                        break  # 找到一个就够了
            except Exception as e:
                if AGENT_DEBUG_LOG:
                    print(f"[topup-debug] failed to check {feed_url}: {e}")
                continue
        
        if AGENT_DEBUG_LOG:
            print(f"[topup-debug] {p} feeds_found={len(feeds_found)}")
        
        # 对找到的feed进行抓取
        for feed_url in feeds_found[:1]:  # 只抓一个feed
            try:
                # 直接本地解析和写入数据库
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                    'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
                }
                r = _request_with_retry('get', feed_url, timeout=int(AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT) if AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT else 20, headers=headers)
                body_text = _response_text_best_effort(r)
                if getattr(r, 'status_code', 0) != 200 or not (body_text or '').strip():
                    if AGENT_DEBUG_LOG:
                        print(f"[topup-debug] feed fetch failed: status={getattr(r, 'status_code', 0)}, body_len={len(body_text or '')}")
                    continue
                if _feed_looks_like_html_error(r):
                    if AGENT_DEBUG_LOG:
                        print(f"[topup-debug] feed looks like HTML error page")
                    continue
                rows = _parse_feed_items_local(body_text, limit=int(AGENT_GLOBAL_PRE_INGEST_RSS_MAX_ITEMS))
                if AGENT_DEBUG_LOG:
                    print(f"[topup-debug] parsed {len(rows)} items from feed")
                if not rows:
                    continue
                ok, qm = _feed_quality_check(rows)
                if AGENT_DEBUG_LOG:
                    print(f"[topup-debug] quality check: ok={ok}, metrics={qm}")
                if not ok:
                    continue
                _ingest_items_to_sql(rows)
                added_total += len(rows)
                if AGENT_DEBUG_LOG:
                    print(f"[topup-debug] ingested {len(rows)} items, total_added={added_total}")
                    print(f"[topup] rss ok items={len(rows)} feed={feed_url[:120]}")
            except Exception as e:
                if AGENT_DEBUG_LOG:
                    print(f"[topup-debug] feed processing failed: {e}")
                    print(f"[topup] rss failed feed={feed_url[:120]} err={e}")
                continue
    
    return added_total


def _enrich_short_content_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """对内容过短的条目（<40 字），尝试用 NewsProcessor 抽取正文，避免 LLM 看到空内容。"""
    if not items or NewsProcessor is None:
        return items
    min_len = int(os.getenv('NEWS_ENRICH_EXISTING_MIN', '40'))
    to_enrich = [it for it in items if len((it.get('content') or '').strip()) < min_len and (it.get('url') or '').strip()]
    if not to_enrich:
        return items
    try:
        np = NewsProcessor()
        async def _runner():
            sem = asyncio.Semaphore(int(os.getenv('NEWS_ENRICH_CONCURRENCY', '4')))
            async def _one(it: Dict[str, Any]):
                url = (it.get('url') or '').strip()
                if not url:
                    return it
                async with sem:
                    try:
                        soup = await np._fetch_soup(url)
                        full = await np._extract_content(url, soup)
                        if full and len(full) >= min_len:
                            it2 = dict(it)
                            it2['content'] = full
                            return it2
                    except Exception:
                        pass
                return it
            tasks = [_one(it) for it in to_enrich]
            res = await asyncio.gather(*tasks, return_exceptions=True)
            return [x for x in res if isinstance(x, dict)]
        enriched = asyncio.run(_runner())
        # 合并回原列表
        enriched_map = {it['url']: it for it in enriched if it.get('url')}
        out = []
        for it in items:
            url = it.get('url')
            if url in enriched_map:
                out.append(enriched_map[url])
            else:
                out.append(it)
        return out
    except Exception:
        return items


def _discover_feeds_for_base_url(base_url: str) -> List[str]:
    payload = {
        'base_url': (base_url or '').strip(),
        'timeout_seconds': 12.0,
        'max_candidates': 30,
    }
    j = _backend_post_json('/api/news/discover/rss', payload, timeout=max(AGENT_BACKEND_TIMEOUT, 20.0))
    cands = _safe_get(j, 'candidates', []) if isinstance(j, dict) else []
    out: List[str] = []
    if isinstance(cands, list):
        for u in cands:
            s = (str(u) or '').strip()
            if s and (s.startswith('http://') or s.startswith('https://')):
                out.append(s)
    return out


def _discover_site_hints(base_url: str) -> Dict[str, Any]:
    payload = {
        'base_url': (base_url or '').strip(),
        'timeout_seconds': 12.0,
        'max_candidates': 30,
    }
    j = _backend_post_json('/api/news/discover/rss', payload, timeout=max(AGENT_BACKEND_TIMEOUT, 20.0))
    return j if isinstance(j, dict) else {}


def _sitemap_extract_urls(xml_text: str, *, limit: int) -> List[str]:
    out: List[str] = []
    if not xml_text:
        return out
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out

    # urlset: <url><loc>...</loc></url>
    locs = root.findall('.//{*}url/{*}loc')
    for loc in locs:
        if len(out) >= int(limit):
            break
        u = (loc.text or '').strip()
        if u.startswith('http://') or u.startswith('https://'):
            out.append(u)

    # sitemapindex: <sitemap><loc>...</loc></sitemap>
    if not out:
        idx_locs = root.findall('.//{*}sitemap/{*}loc')
        for loc in idx_locs:
            if len(out) >= int(limit):
                break
            u = (loc.text or '').strip()
            if u.startswith('http://') or u.startswith('https://'):
                out.append(u)
    return out


def _looks_like_feed_url(url: str) -> bool:
    u = (url or '').strip().lower()
    if not (u.startswith('http://') or u.startswith('https://')):
        return False
    if 'sitemap' in u or u.endswith('map.xml'):
        return False
    # Avoid common false positives like "feedback" paths
    if 'feedback' in u:
        return False
    # Prefer explicit rss/atom markers; "feed" alone is too noisy.
    if 'rss' in u or 'atom' in u:
        return True
    # Allow "feed" only when the URL clearly points to an XML feed endpoint.
    if 'feed' in u and (u.endswith('.xml') or u.endswith('.rss') or u.endswith('.atom')):
        return True
    return False


def _parse_feed_items_local(xml_text: str, *, limit: int) -> List[Dict[str, Any]]:
    """Parse RSS 2.0 / Atom feed to a normalized list of {url,title,published_at}.

    NOTE: This intentionally mirrors backend parsing logic to avoid relying on /api/news/ingest/rss,
    which may fail in some deployments.
    """
    out: List[Dict[str, Any]] = []
    if not xml_text:
        return out
    root = None
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        # Some feeds may contain control characters; retry with a cleaned payload.
        try:
            cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', xml_text)
            root = ET.fromstring(cleaned)
        except Exception:
            return out

    tag = (root.tag or '').lower()
    is_atom = tag.endswith('feed')

    if is_atom:
        entries = root.findall('.//{*}entry')
        for e in entries:
            if len(out) >= int(limit):
                break
            title = ''.join(e.findtext('{*}title', default='') or '').strip()
            pub = (e.findtext('{*}published', default='') or '').strip() or (e.findtext('{*}updated', default='') or '').strip()
            url = ''
            links = e.findall('{*}link')
            if links:
                pick = None
                for lk in links:
                    if (lk.get('rel') or '').lower() == 'alternate' and lk.get('href'):
                        pick = lk
                        break
                if pick is None:
                    pick = links[0]
                url = (pick.get('href') or '').strip()
            if url:
                out.append({'url': url, 'title': title or url, 'published_at': pub or None})
    else:
        items = root.findall('.//item')
        for it in items:
            if len(out) >= int(limit):
                break
            title = ''.join((it.findtext('title', default='') or '')).strip()
            url = ''.join((it.findtext('link', default='') or '')).strip()
            pub = ''.join((it.findtext('pubDate', default='') or '')).strip() or ''.join((it.findtext('date', default='') or '')).strip()
            if url:
                out.append({'url': url, 'title': title or url, 'published_at': pub or None})

    # Normalize published_at to ISO string if possible
    normed: List[Dict[str, Any]] = []
    for x in out:
        pub = x.get('published_at')
        if isinstance(pub, str) and pub.strip():
            s = pub.strip()
            iso = None
            try:
                dt = parsedate_to_datetime(s)
                iso = dt.isoformat()
            except Exception:
                try:
                    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
                    iso = dt.isoformat()
                except Exception:
                    iso = s
            x['published_at'] = iso
        normed.append(x)
    return normed


def _extract_xml_declared_encoding(raw: bytes) -> Optional[str]:
    """Extract encoding from XML declaration like <?xml version="1.0" encoding="gb2312"?>."""
    if not raw:
        return None
    try:
        head = raw[:400].decode('ascii', errors='ignore')
    except Exception:
        return None
    m = re.search(r'encoding\s*=\s*["\"]([^"\"]+)["\"]', head, flags=re.IGNORECASE)
    if not m:
        return None
    enc = (m.group(1) or '').strip()
    return enc or None


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove port if present
        if ':' in domain:
            domain = domain.split(':')[0]
        return domain
    except Exception:
        return 'unknown'


def _response_text_best_effort(resp: requests.Response) -> str:
    """Decode response body reliably for RSS/Atom feeds.

    Many Chinese RSS endpoints either:
    - omit charset in Content-Type, causing requests to default to ISO-8859-1, or
    - declare GB2312/GBK in XML header.

    We prefer XML-declared encoding, then requests' apparent encoding, then common fallbacks.
    """
    try:
        raw = getattr(resp, 'content', b'') or b''
    except Exception:
        raw = b''
    if not raw:
        try:
            return (getattr(resp, 'text', '') or '')
        except Exception:
            return ''

    declared = _extract_xml_declared_encoding(raw)
    candidates: List[str] = []
    for enc in [declared, getattr(resp, 'encoding', None), getattr(resp, 'apparent_encoding', None)]:
        if isinstance(enc, str) and enc.strip():
            candidates.append(enc.strip())
    # Common practical fallbacks for feeds
    candidates.extend(['utf-8', 'utf-8-sig', 'gb18030', 'gbk'])
    seen = set()
    for enc in candidates:
        key = enc.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode('utf-8', errors='replace')


def _try_parse_datetime_any(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    ss = (str(s) or '').strip()
    if not ss:
        return None
    # Prefer RFC822 and ISO8601
    try:
        dt = parsedate_to_datetime(ss)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(ss.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _feed_quality_check(rows: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any]]:
    """Return (ok, metrics). When ok is False, metrics includes 'reject_reason'."""
    metrics: Dict[str, Any] = {
        'items': len(rows or []),
        'latest_published_at': None,
        'recency_days': None,
        'median_title_len': None,
    }
    if not AGENT_FEED_QUALITY_CHECK_ENABLE:
        return True, metrics
    if not rows:
        metrics['reject_reason'] = 'no_items'
        return False, metrics

    # Title length median
    title_lens: List[int] = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        t = (x.get('title') or '').strip()
        if t:
            title_lens.append(len(t))
    if title_lens:
        try:
            metrics['median_title_len'] = int(statistics.median(title_lens))
        except Exception:
            metrics['median_title_len'] = None

    if isinstance(metrics.get('median_title_len'), int) and metrics['median_title_len'] < int(AGENT_FEED_MIN_MEDIAN_TITLE_LEN):
        metrics['reject_reason'] = f"median_title_len<{int(AGENT_FEED_MIN_MEDIAN_TITLE_LEN)}"
        return False, metrics

    # Recency
    dts: List[datetime] = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        dt = _try_parse_datetime_any(x.get('published_at'))
        if dt:
            dts.append(dt)
    if dts:
        latest = max(dts)
        metrics['latest_published_at'] = latest.isoformat()
        now = datetime.now(timezone.utc)
        try:
            metrics['recency_days'] = int((now - latest).total_seconds() // 86400)
        except Exception:
            metrics['recency_days'] = None
        if isinstance(metrics.get('recency_days'), int) and metrics['recency_days'] > int(AGENT_FEED_MIN_RECENCY_DAYS):
            metrics['reject_reason'] = f"latest_pubDate_older_than_{int(AGENT_FEED_MIN_RECENCY_DAYS)}d"
            return False, metrics

    return True, metrics


def _feed_looks_like_html_error(resp: requests.Response) -> bool:
    """Detect common cases where a feed URL returns an HTML error page (often 404) instead of RSS/Atom."""
    try:
        ct = (resp.headers.get('Content-Type') or '').lower()
    except Exception:
        ct = ''
    # Many sites return a themed HTML 404 page even for *.xml URLs.
    if 'text/html' in ct:
        return True
    # If the payload looks like HTML and mentions 404/Not Found, treat it as invalid feed.
    try:
        head = (_response_text_best_effort(resp) or '')[:800].lower()
    except Exception:
        head = ''
    if '<html' in head or '<!doctype html' in head:
        if '404' in head or 'not found' in head or '页面不存在' in head or 'page not found' in head:
            return True
        # HTML without those tokens is still not a feed.
        return True
    return False


def _probe_rss_feeds(feed_urls: List[str]) -> None:
    """Probe RSS/Atom feeds: fetch, validate content-type/body, parse items count, print a compact report."""
    urls = [(_maybe_rewrite_rsshub(u) or '').strip() for u in (feed_urls or []) if (u or '').strip()]
    if not urls:
        print('[probe-feeds] no feed urls configured')
        return
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
    }
    max_items = int(AGENT_GLOBAL_PRE_INGEST_RSS_MAX_ITEMS)
    print(f"[probe-feeds] probing feeds={len(urls)} max_items={max_items}")
    for u in urls:
        try:
            r = _request_with_retry('get', u, timeout=int(AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT) if AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT else 20, headers=headers)
            ct = (getattr(r, 'headers', {}) or {}).get('Content-Type') if hasattr(r, 'headers') else None
            ct_s = (ct or '')
            body_text = _response_text_best_effort(r)
            if getattr(r, 'status_code', 0) != 200 or not (body_text or '').strip():
                print(f"[probe-feeds] FAIL status={getattr(r,'status_code',None)} ct={ct_s[:40]} url={u}")
                continue
            if _feed_looks_like_html_error(r):
                print(f"[probe-feeds] FAIL html ct={ct_s[:40]} url={u}")
                continue
            rows = _parse_feed_items_local(body_text, limit=max_items)
            if not rows:
                print(f"[probe-feeds] FAIL parsed=0 ct={ct_s[:40]} url={u}")
                continue
            ok, qm = _feed_quality_check(rows)
            if not ok:
                reason = str(qm.get('reject_reason') or 'reject')
                lp = str(qm.get('latest_published_at') or '')
                md = qm.get('median_title_len')
                print(f"[probe-feeds] REJECT reason={reason} latest={lp[:19]} median_title_len={md} url={u}")
                continue
            # Print a couple of titles to confirm semantic correctness.
            t1 = (rows[0].get('title') or '') if rows else ''
            t2 = (rows[1].get('title') or '') if len(rows) > 1 else ''
            print(f"[probe-feeds] OK parsed={len(rows)} ct={ct_s[:40]} url={u}")
            if t1:
                print(f"  - {str(t1)[:120]}")
            if t2:
                print(f"  - {str(t2)[:120]}")
        except Exception as e:
            print(f"[probe-feeds] ERROR err={e} url={u}")


def _ingest_items_to_sql(items: List[Dict[str, Any]]) -> None:
    """Directly ingest news items to SQL database, avoiding backend API calls."""
    if not items:
        return
    
    try:
        from app.core.db import SessionLocal  # type: ignore
        from app.core.models import NewsArticle, NewsSource  # type: ignore
        from sqlalchemy import select
        import datetime
        
        with SessionLocal() as session:
            for item in items:
                url = (item.get('url') or '').strip()
                title = (item.get('title') or '').strip() or url
                if not url:
                    continue
                
                # Check if article already exists
                existing = session.execute(
                    select(NewsArticle).where(NewsArticle.url == url)
                ).scalar_one_or_none()
                
                if existing:
                    continue  # Skip duplicates
                
                # Get or create news source
                domain = _extract_domain(url)
                source = session.execute(
                    select(NewsSource).where(NewsSource.domain == domain)
                ).scalar_one_or_none()
                
                if not source:
                    source = NewsSource(
                        name=domain,
                        domain=domain,
                        category='general',
                        reliability_score=0.5,
                        language='zh-CN',
                        enabled=True
                    )
                    session.add(source)
                    session.flush()  # Get the ID
                
                # Create news article
                article = NewsArticle(
                    title=title[:500],  # Truncate if too long
                    url=url,
                    content=item.get('content'),
                    summary=item.get('summary')[:1000] if item.get('summary') else None,
                    summary_from_llm=False,
                    author=item.get('author')[:100] if item.get('author') else None,
                    published_at=item.get('published_at'),
                    crawled_at=datetime.datetime.utcnow(),
                    source_id=source.id,
                    category='general',
                    keywords=None,
                    entities=None,
                    sentiment_type=None,
                    sentiment_score=None,
                    sentiment_confidence=None,
                    related_stocks=None,  # Will be populated later if needed
                    relevance_score=None,
                    content_quality=0.5,
                    is_duplicate=False,
                    duplicate_of=None,
                    is_bookmarked=False,
                    is_read=False
                )
                session.add(article)
            
            session.commit()
            
    except Exception as e:
        if AGENT_DEBUG_LOG:
            print(f"[ingest] Failed to ingest items to SQL: {e}")
        # Don't raise exception to avoid breaking the flow


def _ingest_rss_feed(feed_url: str) -> None:
    """Pre-ingest a feed by fetching+parsing locally, then ingesting via /api/news/ingest.

    This avoids relying on backend /api/news/ingest/rss which may fail (500) in some deployments.
    """
    feed = ( _maybe_rewrite_rsshub(feed_url) or '' ).strip()
    if not feed:
        return
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
        }
        r = _request_with_retry('get', feed, timeout=int(AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT) if AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT else 20, headers=headers)
        body_text = _response_text_best_effort(r)
        if getattr(r, 'status_code', 0) != 200 or not (body_text or '').strip():
            return
        if _feed_looks_like_html_error(r):
            if AGENT_DEBUG_LOG:
                try:
                    ct = (r.headers.get('Content-Type') or '')
                except Exception:
                    ct = ''
                print(f"[pre-ingest] rss invalid (html) ct={ct[:60]} feed={feed[:120]}")
            return
        rows = _parse_feed_items_local(body_text, limit=int(AGENT_GLOBAL_PRE_INGEST_RSS_MAX_ITEMS))
        if not rows:
            return
        ok, qm = _feed_quality_check(rows)
        if not ok:
            if AGENT_DEBUG_LOG:
                reason = str(qm.get('reject_reason') or 'reject')
                lp = str(qm.get('latest_published_at') or '')
                md = qm.get('median_title_len')
                print(f"[pre-ingest] rss rejected reason={reason} latest={lp[:19]} median_title_len={md} feed={feed[:120]}")
            return
        _ingest_items_to_sql(rows)
        if AGENT_DEBUG_LOG:
            print(f"[pre-ingest] rss ok items={len(rows)} feed={feed[:120]}")
    except Exception as e:
        if AGENT_DEBUG_LOG:
            print(f"[pre-ingest] rss failed feed={feed[:120]} err={e}")
        return


def _global_pre_ingest_sources() -> None:
    """在日报生成前先扩充 DB 内容池，避免单一依赖搜索引擎即时抓取。"""
    global _GLOBAL_PRE_INGEST_DONE
    if _GLOBAL_PRE_INGEST_DONE or not AGENT_GLOBAL_PRE_INGEST:
        return

    try:
        print('[phase] 预采集：扩充 DB 内容池（官方披露 + RSS）...')
    except Exception:
        pass

    # 1) 官方披露（内置 preset）
    try:
        _global_ingest_official_a_presets()
    except Exception:
        pass

    # 2) 显式 feed URLs（如果用户配置了）
    for feed in (AGENT_GLOBAL_PRE_INGEST_MEDIA_FEED_URLS or [])[:50]:
        try:
            _ingest_rss_feed(feed)
        except Exception:
            continue

    # 2b) OPML 批量导入（例如新浪财经 OPML）
    for opml_url in (AGENT_GLOBAL_PRE_INGEST_OPML_URLS or [])[:10]:
        try:
            ou = (opml_url or '').strip()
            if not ou:
                continue
            r = requests.get(ou, timeout=float(AGENT_GLOBAL_PRE_INGEST_OPML_TIMEOUT))
            if r.status_code != 200 or not (r.text or '').strip():
                continue
            feeds = _parse_opml_xmlurls(r.text, limit=int(AGENT_GLOBAL_PRE_INGEST_OPML_MAX_FEEDS))
            for f in feeds[: int(AGENT_GLOBAL_PRE_INGEST_OPML_MAX_FEEDS)]:
                try:
                    _ingest_rss_feed(f)
                except Exception:
                    continue
        except Exception:
            continue

    # 3) 站点 base_url -> discover/rss -> ingest/rss
    for base in (AGENT_GLOBAL_PRE_INGEST_MEDIA_BASE_URLS or [])[:30]:
        try:
            # First try RSS/Atom candidates
            hints = _discover_site_hints(base)
            candidates = hints.get('candidates') or []
            feeds = [str(u).strip() for u in candidates if isinstance(u, (str,)) and _looks_like_feed_url(str(u))]
            for f in feeds[: int(AGENT_GLOBAL_PRE_INGEST_MEDIA_MAX_FEEDS_PER_SITE)]:
                try:
                    _ingest_rss_feed(f)
                except Exception:
                    continue

            # If still nothing, fall back to sitemap URL extraction (best-effort)
            if not feeds:
                sitemaps = hints.get('sitemap_urls') or []
                # Also treat xml candidates that look like sitemaps
                for u in candidates:
                    su = (str(u) or '').strip()
                    if su and (su.lower().endswith('.xml') or 'sitemap' in su.lower() or su.lower().endswith('map.xml')):
                        if su not in sitemaps:
                            sitemaps.append(su)
                max_urls = int(os.getenv('AGENT_GLOBAL_PRE_INGEST_SITEMAP_MAX_URLS', '25'))
                url_items: List[Dict[str, Any]] = []
                for sm in sitemaps[:2]:
                    try:
                        rr = _request_with_retry('get', sm, timeout=max(30, int(_HTTP_TIMEOUT_DB)), headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
                        })
                        if getattr(rr, 'status_code', 0) != 200 or not (getattr(rr, 'text', '') or '').strip():
                            continue
                        locs = _sitemap_extract_urls(rr.text, limit=max_urls)
                        # If sitemapindex, follow the first child sitemap only
                        if locs and all(x.lower().endswith('.xml') or 'sitemap' in x.lower() for x in locs[:3]):
                            child = locs[0]
                            rr2 = _request_with_retry('get', child, timeout=max(30, int(_HTTP_TIMEOUT_DB)), headers={
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
                            })
                            if getattr(rr2, 'status_code', 0) == 200 and (getattr(rr2, 'text', '') or '').strip():
                                locs = _sitemap_extract_urls(rr2.text, limit=max_urls)
                        for u in locs[:max_urls]:
                            if len(url_items) >= max_urls:
                                break
                            if u.startswith('http://') or u.startswith('https://'):
                                url_items.append({'url': u, 'title': u, 'published_at': None})
                        if len(url_items) >= max_urls:
                            break
                    except Exception:
                        continue
                if url_items:
                    try:
                        _ingest_items_to_sql(url_items)
                        if AGENT_DEBUG_LOG:
                            print(f"[pre-ingest] sitemap ok urls={len(url_items)} base={base[:80]}")
                    except Exception as e:
                        if AGENT_DEBUG_LOG:
                            print(f"[pre-ingest] sitemap ingest failed base={base[:80]} err={e}")
        except Exception:
            continue

    _GLOBAL_PRE_INGEST_DONE = True


def _collect_cninfo_candidates(company_name: str, symbol: Optional[str]) -> List[Dict[str, Any]]:
    """通过后端 /api/news/ingest/cninfo (dry_run) 拉公告附件 URL 作为候选。"""
    name = (company_name or '').strip()
    if not name:
        return []
    payload = {
        'searchkey': name,
        'symbol': (symbol or None),
        'page_num': 1,
        'page_size': min(20, max(5, int(os.getenv('AGENT_CNINFO_PAGE_SIZE', '12')))),
        'dry_run': True,
    }
    j = _backend_post_json('/api/news/ingest/cninfo', payload)
    res = _safe_get(j, 'results', []) if isinstance(j, dict) else []
    out: List[Dict[str, Any]] = []
    if isinstance(res, list):
        for it in res:
            if not isinstance(it, dict):
                continue
            url = (it.get('url') or '').strip()
            title_used = (it.get('title_used') or '').strip() or url
            status = (it.get('status') or '').strip()
            if not url:
                continue
            # dry_run 中 status=created/duplicate/skipped/error 都可能出现；我们把 URL 都作为候选
            out.append({'title': title_used, 'url': url, 'content': '', 'source': 'cninfo', 'status': status})
    return out


def _collect_searx_candidates(company_name: str, symbol: Optional[str]) -> List[Dict[str, Any]]:
    res = search_news_searxng(company_name, max_results=max(5, int(MAX_STOCK_NEWS)), symbol=symbol)
    out: List[Dict[str, Any]] = []
    for r in res or []:
        if not isinstance(r, dict):
            continue
        url = (r.get('url') or '').strip()
        title = (r.get('title') or '').strip() or url
        if not url:
            continue
        out.append({'title': title, 'url': url, 'content': (r.get('content') or '').strip(), 'source': 'searx'})
    return out


def _ingest_kept_to_sql(items: List[Dict[str, Any]], *, symbol: Optional[str], company_name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not items or not AGENT_NEWS_PIPELINE_WRITE_DB:
        return None
    ingest_items = []
    for it in items:
        if not isinstance(it, dict):
            continue
        url = (it.get('url') or '').strip()
        title = (it.get('title') or '').strip() or url
        if not url:
            continue
        ingest_items.append({
            'url': url,
            'title': title,
            'symbol': (symbol or None),
            'company_name': (company_name or None),
            'published_at': it.get('published_at'),
        })
    if not ingest_items:
        return None
    payload = {'items': ingest_items, 'dry_run': False, 'max_items': len(ingest_items)}
    return _backend_post_json('/api/news/ingest', payload, timeout=max(AGENT_BACKEND_TIMEOUT, 35.0))


def _merge_dedup_by_url(primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for lst in (primary, secondary):
        for it in lst or []:
            if len(out) >= int(limit):
                break
            if not isinstance(it, dict):
                continue
            url = (it.get('url') or '').strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(it)
    return out


def _fetch_news_multi_source(stock: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """单股票：DB-first + CNINFO + SearXNG -> gate -> ingest kept -> return for analysis."""
    name = (stock.get('name') or '').strip()
    symbol = (stock.get('symbol') or '').strip().upper() if stock.get('symbol') else None

    diagnostics = {
        'db_first_count': 0,
        'cninfo_candidates': 0,
        'searx_raw': 0,
        'searx_filtered': 0,
        'kept_after_gate': 0,
        'official_topup_triggered': False,
        'official_topup_added': 0,
        'enrich_attempts': 0,
        'enrich_success': 0,
    }

    # 1) DB-first
    db_items: List[Dict[str, Any]] = []
    if symbol:
        db_items = _fetch_stock_news_db_first(symbol)
        diagnostics['db_first_count'] = len(db_items)
        if len(db_items) >= int(AGENT_NEWS_DB_FIRST_MIN):
            db_items = _enrich_short_content_items(db_items)
            diagnostics['enrich_attempts'] = len([it for it in db_items if len((it.get('content') or '').strip()) < 40])
            diagnostics['enrich_success'] = len([it for it in db_items if len((it.get('content') or '').strip()) >= 40])
            return db_items[: int(MAX_STOCK_NEWS)], diagnostics

    # 2) Multi-source candidates
    candidates: List[Dict[str, Any]] = []
    if name:
        try:
            cninfo_cands = _collect_cninfo_candidates(name, symbol)
            candidates.extend(cninfo_cands)
            diagnostics['cninfo_candidates'] = len(cninfo_cands)
        except Exception:
            pass
        try:
            searx_cands = _collect_searx_candidates(name, symbol)
            diagnostics['searx_raw'] = len(searx_cands)
            candidates.extend(searx_cands)
        except Exception:
            pass

    # de-dup candidates and cap
    uniq: List[Dict[str, Any]] = []
    seen_url = set()
    for it in candidates:
        url = (it.get('url') or '').strip()
        if not url or url in seen_url:
            continue
        seen_url.add(url)
        uniq.append(it)
        if len(uniq) >= int(AGENT_NEWS_GATE_MAX_CANDIDATES):
            break

    # 3) Enrich content best-effort (reuse existing searx enrich logic if possible)
    if NewsProcessor is not None and uniq:
        try:
            np = NewsProcessor()
            async def _runner():
                sem = asyncio.Semaphore(int(os.getenv('NEWS_ENRICH_CONCURRENCY', '4')))
                async def _one(r: Dict[str, Any]):
                    url = (r.get('url') or '').strip()
                    if not url:
                        return r
                    content = (r.get('content') or '').strip()
                    if content and len(content) >= int(os.getenv('NEWS_ENRICH_EXISTING_MIN', '40')):
                        return r
                    # Skip non-article-like URLs (best-effort)
                    try:
                        if hasattr(np, '_is_article_like_url') and not np._is_article_like_url(url):
                            return r
                    except Exception:
                        pass
                    async with sem:
                        try:
                            soup = await np._fetch_soup(url)
                            full = await np._extract_content(url, soup)
                            if full and len(full) >= int(os.getenv('NEWS_ENRICH_MIN_LEN', '60')):
                                r2 = dict(r)
                                r2['content'] = full
                                return r2
                        except Exception:
                            return r
                    return r
                tasks = [_one(dict(x)) for x in uniq]
                res = await asyncio.gather(*tasks, return_exceptions=True)
                out2: List[Dict[str, Any]] = []
                for x in res:
                    if isinstance(x, dict):
                        out2.append(x)
                return out2
            uniq = asyncio.run(_runner())
        except Exception:
            pass

    # 4) Gate
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for it in uniq:
        title = (it.get('title') or '').strip()
        url = (it.get('url') or '').strip()
        content = (it.get('content') or '').strip()
        source = (it.get('source') or 'unknown')
        if not url:
            continue
        decision = _llm_gate_item(company_name=name or (symbol or ''), symbol=symbol, title=title, content=content, source=source, url=url)
        if decision.get('keep'):
            it2 = dict(it)
            it2['gate'] = decision
            kept.append(it2)
        else:
            it2 = dict(it)
            it2['gate'] = decision
            rejected.append(it2)
            _gate_audit_mongo(kind='gate', url=url, symbol=symbol, company_name=name, source=source, decision=decision)
        if len(kept) >= int(MAX_STOCK_NEWS):
            break

    diagnostics['searx_filtered'] = len(uniq) - diagnostics['cninfo_candidates']
    diagnostics['kept_after_gate'] = len(kept)

    # 5) Persist kept to SQL
    if kept and AGENT_NEWS_PIPELINE_WRITE_DB:
        try:
            _ingest_kept_to_sql(kept, symbol=symbol, company_name=name)
        except Exception:
            pass

    # 6) Merge DB + kept
    merged = _merge_dedup_by_url(db_items, kept, int(MAX_STOCK_NEWS))

    # 7) 如果仍不足，触发官方披露补池 + 重新 DB-first
    min_news_for_topup = int(os.getenv('AGENT_OFFICIAL_TOPUP_MIN_NEWS', '2'))
    if len(merged) < min_news_for_topup and symbol:
        diagnostics['official_topup_triggered'] = True
        added = _topup_official_for_symbol(symbol)
        diagnostics['official_topup_added'] = added
        if added > 0:
            # 重新拉 DB-first
            fresh_db_items = _fetch_stock_news_db_first(symbol)
            merged = _merge_dedup_by_url(fresh_db_items, kept, int(MAX_STOCK_NEWS))

    # 8) 最后 enrich 短内容
    merged = _enrich_short_content_items(merged)
    diagnostics['enrich_attempts'] = len([it for it in merged if len((it.get('content') or '').strip()) < 40])
    diagnostics['enrich_success'] = len([it for it in merged if len((it.get('content') or '').strip()) >= 40])

    return merged, diagnostics

# SearXNG 降频与查询缓存
# 在高并发/多标的场景下降低对 SearXNG 的瞬时压力，并复用短期内的相同查询结果
_SEARX_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
SEARX_CACHE_TTL = int(os.getenv("SEARXNG_CACHE_TTL_SEC", "300"))  # 默认缓存 5 分钟
SEARX_REQ_DELAY_MS = int(os.getenv("AGENT_SEARX_DELAY_MS", "150"))  # 每次请求间隔（毫秒）

# 1. 获取Top20榜单
def fetch_top20():
    try:
        resp = requests.get(MOVERS_API_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected response format for movers API")
        top20 = (data.get('gainers') or []) + (data.get('losers') or [])
        return top20[:20]
    except Exception as e:
        print(f"[fetch_top20] API unavailable: {e}, using mock data")
        # Return mock data for testing
        return [
            {"symbol": "000001", "name": "平安银行", "pct_chg": 5.0},
            {"symbol": "000002", "name": "万科A", "pct_chg": -3.0},
            {"symbol": "600000", "name": "浦发银行", "pct_chg": 2.5},
            {"symbol": "600036", "name": "招商银行", "pct_chg": -1.8},
            {"symbol": "000858", "name": "五粮液", "pct_chg": 4.2},
        ]

def discover_movers_url(candidates: Optional[List[str]] = None) -> str:
    if candidates is None:
        candidates = [
            MOVERS_API_URL,
            "http://localhost:8080/api/movers/live_insight?limit=20",
            "http://127.0.0.1:8080/api/movers/live_insight?limit=20",
            "http://localhost:8000/api/movers/live_insight?limit=20",
        ]
    for url in candidates:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200 and 'gainers' in r.text:
                print(f"[preflight] 发现可用 MOVERS_API_URL: {url}")
                return url
        except Exception:
            continue
    raise RuntimeError("无法发现可用的 movers API，请确认后端服务已在 8080 或指定端口运行。")

# 2. 用searxng搜索新闻
def search_news_searxng(query: str, max_results: int = MAX_STOCK_NEWS, symbol: Optional[str] = None) -> List[Dict]:
    """Search news via SearXNG with strict filtering, then staged relax and query augmentation.
    1) Strict: zh-CN, news category, env time_range; domain/tld filtering; CJK density; recency.
    2) Relax time_range to month, allow short content.
    3) Switch to general category with broader zh language.
    4) Augment query with finance terms (公告/研报/财报/互动易/投资者关系/涨停/异动).
    """
    # 构造 SearXNG 端点列表（支持轮换）
    endpoints = [b.rstrip('/') + "/search" for b in _SEARXNG_URLS if b]

    def _has_cjk(s: str) -> bool:
        return any('\u4e00' <= ch <= '\u9fff' for ch in (s or ''))

    def _is_a_share_symbol(s: Optional[str]) -> bool:
        ss = (s or '').strip().upper()
        if not ss:
            return False
        if re.fullmatch(r"\d{6}(?:\.(SZ|SH))?", ss):
            return True
        return False

    cn_context = _has_cjk(query) or _is_a_share_symbol(symbol) or _is_a_share_symbol(query)

    def _phrase_cn_name(s: str) -> str:
        ss = (s or '').strip()
        if not ss:
            return ''
        # For Chinese company names, use phrase query to avoid token-splitting
        # (e.g., “飞/科技” leading to Zhihu-dominated generic results).
        if _has_cjk(ss) and '"' not in ss and "'" not in ss and len(ss) <= 16:
            return f'"{ss}"'
        return ss

    # Compose query
    force_cn_suffix = os.getenv("SEARXNG_FORCE_CN_SUFFIX", "0") == "1"
    if cn_context or force_cn_suffix:
        # NOTE: Some engines (notably Bing) can return highly irrelevant results when the
        # company name is quoted and placed first (e.g., lots of Zhihu/Q&A). When a 6-digit
        # A-share code is available, lead with the code and use a disclosure-focused suffix.
        m_code0 = re.search(r"\b(\d{6})\b", str(symbol or '')) if symbol else None
        code6_0 = m_code0.group(1) if m_code0 else None
        if code6_0:
            q_terms = [code6_0, str(query).strip(), "公告", "披露"]
        else:
            q_terms = [_phrase_cn_name(query), "新闻", "财经"]
    else:
        # Non-CJK query: use English suffix terms for better recall on global sources.
        en_suffix = os.getenv("SEARXNG_QUERY_SUFFIX_EN", "news finance").strip()
        q_terms = [query] + [t for t in en_suffix.split() if t]

    if symbol:
        q_terms.insert(1, symbol)
        # Also add 6-digit raw code (many CN sources index by numeric code only).
        m_code = re.search(r"\b(\d{6})\b", str(symbol))
        if m_code:
            q_terms.insert(1, m_code.group(1))
    extra_q = os.getenv("SEARXNG_QUERY_APPEND", "").strip()
    if extra_q:
        q_terms.append(extra_q)
    q = " ".join([t for t in q_terms if t])

    # Must-match terms: for CN/A-share context, always require explicit company signal.
    cn_must_match_terms: List[str] = []
    if cn_context:
        if query and str(query).strip():
            cn_must_match_terms.append(str(query).strip())
        if symbol and str(symbol).strip():
            cn_must_match_terms.append(str(symbol).strip())
        m_code = re.search(r"\b(\d{6})\b", str(symbol or ''))
        if m_code:
            cn_must_match_terms.append(m_code.group(1))

    def _searx_request(p: Dict[str, Any]) -> List[Dict[str, Any]]:
        """尝试轮换多个 SearXNG 端点，返回第一份成功的 results。"""
        last_err_snippet = None
        req_timeout = float(os.getenv('SEARXNG_REQUEST_TIMEOUT', '30'))
        timeout_retries = int(os.getenv('SEARXNG_TIMEOUT_RETRIES', '1'))
        timeout_backoff_base_ms = int(os.getenv('SEARXNG_TIMEOUT_BACKOFF_BASE_MS', '250'))
        timeout_jitter_ms = int(os.getenv('SEARXNG_TIMEOUT_JITTER_MS', '150'))
        # 轻量抖动节流，降低被风控概率（与 SEARX_REQ_DELAY_MS 叠加）
        req_jitter_ms = int(os.getenv('AGENT_SEARX_JITTER_MS', os.getenv('SEARXNG_REQ_JITTER_MS', '120')))

        def _split_engines(s: str) -> List[str]:
            return [x.strip() for x in (s or '').split(',') if x and x.strip()]

        def _current_engines(p0: Dict[str, Any]) -> List[Optional[str]]:
            engs = _split_engines(str((p0 or {}).get('engines') or ''))
            # IMPORTANT: Never send multi-engine in one request; we will try them sequentially.
            if not engs:
                return [None]
            return engs

        def _extract_engine_errors(data: Any) -> List[Tuple[str, str]]:
            out: List[Tuple[str, str]] = []
            if not isinstance(data, dict):
                return out
            errs = data.get('errors')
            if isinstance(errs, dict):
                for eng, msg in errs.items():
                    if isinstance(msg, list):
                        for it in msg:
                            out.append((str(eng), str(it)))
                    elif msg is not None:
                        out.append((str(eng), str(msg)))
            elif isinstance(errs, list):
                for it in errs:
                    s_it = str(it)
                    m = re.match(r"^([^:]{2,40}):\s*(.+)$", s_it)
                    if m:
                        out.append((m.group(1).strip(), m.group(2).strip()))
                    else:
                        out.append(('', s_it))

            # SearXNG JSON: unresponsive_engines can be a list of strings
            # OR list of [engine, reason] pairs.
            unresp = data.get('unresponsive_engines')
            if isinstance(unresp, list):
                for it in unresp:
                    if isinstance(it, (list, tuple)) and len(it) >= 1:
                        eng = str(it[0]) if it[0] is not None else ''
                        reason = str(it[1]) if len(it) >= 2 and it[1] is not None else 'unresponsive'
                        if eng.strip():
                            out.append((eng.strip(), reason))
                    elif it:
                        out.append((str(it), 'unresponsive'))
            return out

        def _apply_engine_cooldown(engine_errors: List[Tuple[str, str]]):
            if not engine_errors:
                return
            base_sec = int(os.getenv('SEARXNG_ENGINE_COOLDOWN_SEC', '1800'))
            http_disabled_sec = int(os.getenv('SEARXNG_ENGINE_HTTP_DISABLED_COOLDOWN_SEC', '7200'))
            captcha_sec = int(os.getenv('SEARXNG_ENGINE_CAPTCHA_COOLDOWN_SEC', '3600'))
            access_denied_sec = int(os.getenv('SEARXNG_ENGINE_ACCESS_DENIED_COOLDOWN_SEC', '21600'))
            timeout_sec = int(os.getenv('SEARXNG_ENGINE_TIMEOUT_COOLDOWN_SEC', str(base_sec)))
            now = time.time()
            for eng, msg in engine_errors:
                eng = (eng or '').strip()
                if not eng:
                    continue
                msg_l = (msg or '').lower()
                sec = base_sec
                if 'http protocol is disabled' in msg_l or 'unsupportedprotocol' in msg_l:
                    sec = max(sec, http_disabled_sec)
                    _SEARX_FILTER_METRICS['engine_http_disabled'] += 1
                elif 'captcha' in msg_l:
                    sec = max(sec, captcha_sec)
                    _SEARX_FILTER_METRICS['engine_captcha'] = _SEARX_FILTER_METRICS.get('engine_captcha', 0) + 1
                elif 'access denied' in msg_l or 'http error 403' in msg_l or '403' in msg_l:
                    sec = max(sec, access_denied_sec)
                    _SEARX_FILTER_METRICS['engine_access_denied'] = _SEARX_FILTER_METRICS.get('engine_access_denied', 0) + 1
                elif 'forbidden' in msg_l or 'blocked' in msg_l:
                    _SEARX_FILTER_METRICS['engine_blocked'] += 1
                elif 'timeout' in msg_l:
                    sec = max(sec, timeout_sec)
                    _SEARX_FILTER_METRICS['engine_timeout'] = _SEARX_FILTER_METRICS.get('engine_timeout', 0) + 1

                _SEARX_ENGINE_COOLDOWN_UNTIL[eng] = max(_SEARX_ENGINE_COOLDOWN_UNTIL.get(eng, 0.0), now + sec)
                if AGENT_DEBUG_LOG:
                    print(f"[searx-engine] cooldown engine='{eng}' sec={sec} reason='{(msg or '')[:80]}'")
        # IMPORTANT: Do NOT send multi-engine requests (e.g., engines=baidu,quark).
        # Some engines getting CAPTCHA can poison the whole response and lead to 0 results.
        engine_candidates = _current_engines(p or {})

        def _sleep_throttle():
            base = max(0, int(SEARX_REQ_DELAY_MS))
            jit = max(0, int(req_jitter_ms))
            if base <= 0 and jit <= 0:
                return
            time.sleep((base + (random.randint(0, jit) if jit > 0 else 0)) / 1000.0)

        for idx, ep in enumerate(endpoints):
            for eng in engine_candidates:
                for attempt in range(timeout_retries + 1):
                    try:
                        # Engine compatibility: in this environment Baidu returns 0 whenever
                        # the time_range parameter is present (even for valid queries).
                        p_send = dict(p or {})
                        if eng:
                            p_send['engines'] = eng
                        else:
                            p_send.pop('engines', None)

                        eng_l = str(p_send.get('engines') or '').lower()
                        if eng_l == 'baidu' and 'time_range' in p_send:
                            p_send.pop('time_range', None)
                            _SEARX_FILTER_METRICS['compat_drop_time_range_baidu'] = _SEARX_FILTER_METRICS.get('compat_drop_time_range_baidu', 0) + 1

                        _sleep_throttle()
                        resp = requests.get(ep, params=p_send, timeout=req_timeout)
                        if resp.status_code >= 400:
                            _SEARX_FILTER_METRICS['http_error'] += 1
                            body = ''
                            try:
                                body = resp.text[:300]
                            except Exception:
                                body = ''
                            print(f"[searxng:{idx}] HTTP {resp.status_code} engine='{eng_l or 'default'}' params: {{ { {k:v for k,v in p_send.items() if k!='q'} } }} body: {body}")
                            last_err_snippet = body
                            break

                        data = resp.json()
                        # Best-effort: observe engine errors and temporarily remove problematic engines.
                        try:
                            _apply_engine_cooldown(_extract_engine_errors(data))
                        except Exception:
                            pass
                        results = (data.get("results") or [])
                        if results:
                            if idx > 0:
                                _SEARX_FILTER_METRICS['endpoint_rotated_success'] += 1
                            if attempt > 0:
                                _SEARX_FILTER_METRICS['http_timeout_recovered'] = _SEARX_FILTER_METRICS.get('http_timeout_recovered', 0) + 1
                            if eng_l:
                                _SEARX_FILTER_METRICS['engine_success'] = _SEARX_FILTER_METRICS.get('engine_success', 0) + 1
                            return results

                        _SEARX_FILTER_METRICS['empty_results'] += 1
                        break
                    except requests.exceptions.Timeout as te:
                        _SEARX_FILTER_METRICS['http_timeout'] += 1
                        if attempt < timeout_retries:
                            _SEARX_FILTER_METRICS['http_timeout_retry'] = _SEARX_FILTER_METRICS.get('http_timeout_retry', 0) + 1
                            backoff_ms = max(0, timeout_backoff_base_ms) * (attempt + 1)
                            jitter = random.randint(0, max(timeout_jitter_ms, 0))
                            sleep_s = (backoff_ms + jitter) / 1000.0
                            print(f"[searxng:{idx}] 请求超时(将重试 {attempt+1}/{timeout_retries}) engine='{eng or 'default'}': {te}; sleep={sleep_s:.2f}s")
                            time.sleep(sleep_s)
                            continue
                        print(f"[searxng:{idx}] 请求超时 engine='{eng or 'default'}': {te}")
                        break
                    except requests.exceptions.RequestException as re_err:
                        _SEARX_FILTER_METRICS['request_exc'] += 1
                        print(f"[searxng:{idx}] 请求异常 engine='{eng or 'default'}': {re_err}")
                        break
                    except Exception as e:
                        _SEARX_FILTER_METRICS['unknown_exc'] += 1
                        print(f"[searxng:{idx}] 未知异常 engine='{eng or 'default'}': {e}")
                        break
        if last_err_snippet:
            print(f"[searxng] 所有端点失败，最后错误片段: {last_err_snippet}")
        return []

    # Prefer a finance/news focused default engine set; can be overridden via env.
    # Include general web engines to avoid 0-results when news-specific engines are sparse.
    se_eng = os.getenv(
        "SEARXNG_ENGINES",
        # Default to CN-friendly engines (configured in local SearXNG settings.yml).
        # Keep this list minimal to avoid hitting disabled engines / foreign-language noise.
        "baidu",
    ).strip()
    se_eng_base = se_eng
    # For CJK queries, prefer a China-focused engine list to reduce irrelevant English pages.
    se_eng_cjk = os.getenv(
        "SEARXNG_ENGINES_CJK",
        "baidu",
    ).strip()
    if _has_cjk(q) and se_eng_cjk:
        se_eng = se_eng_cjk
    # For non-CJK rewritten queries (e.g., CATL/EN alias), allow a separate engine set.
    se_eng_en = os.getenv('SEARXNG_ENGINES_EN', se_eng_base).strip()
    # Separate minimal general engine set for fallback (avoid using all default engines which may trigger bans/timeouts).
    general_eng = os.getenv(
        "SEARXNG_GENERAL_ENGINES",
        "baidu",
    ).strip()

    # Apply cooldown filter to engine lists (avoid engines that are known-bad recently)
    def _cooldown_filter(s: str) -> str:
        now = time.time()
        kept: List[str] = []
        for e in [x.strip() for x in (s or '').split(',') if x and x.strip()]:
            until = _SEARX_ENGINE_COOLDOWN_UNTIL.get(e)
            if until and until > now:
                continue
            kept.append(e)
        return ','.join(kept)

    se_eng = _cooldown_filter(se_eng)
    se_eng_en = _cooldown_filter(se_eng_en)
    general_eng = _cooldown_filter(general_eng)

    # When results are scarce, continue staged relax even if not exactly zero.
    relax_min_results = int(os.getenv("SEARXNG_RELAX_MIN_RESULTS", "3"))
    params = {
        "q": q,
        "categories": os.getenv("SEARXNG_CATEGORIES", "news,general"),
        "format": "json",
        # 扩大基础时间窗，避免 0 结果
        "time_range": os.getenv("SEARXNG_TIME_RANGE", "month"),
    }
    if se_eng:
        params["engines"] = se_eng
    _lang = os.getenv("SEARXNG_LANGUAGE", "").strip()
    if not _lang and (cn_context or _has_cjk(q)):
        _lang = os.getenv('SEARXNG_LANGUAGE_CJK_DEFAULT', 'zh-CN').strip()
    if _lang:
        params["language"] = _lang

    # Domain filtering
    # 默认不过滤头部财经媒体域（sina/163/ifeng 等），避免 0 新闻；仍拦截低质量或封闭平台
    # Allow WeChat official-accounts as an optional high-signal source via sogou_wechat.
    # We still suppress obvious community/Q&A and low-quality platforms elsewhere.
    blacklist_env = os.getenv("SEARXNG_DOMAIN_BLACKLIST", "sohu.com,360doc.com,baidu.com,docschina.org,zhihu.com,toutiao.com,toutiaoapi.com,tw.yahoo.com,hk.yahoo.com")
    whitelist_env = os.getenv("SEARXNG_DOMAIN_WHITELIST", "")
    blacklist = {d.strip().lower() for d in blacklist_env.split(',') if d.strip()}
    whitelist = {d.strip().lower() for d in whitelist_env.split(',') if d.strip()}
    block_tlds = {t.strip().lower() for t in os.getenv("SEARXNG_BLOCK_TLDS", "hk,tw,mo").split(',') if t.strip()}

    def domain_of(url: str) -> str:
        try:
            from urllib.parse import urlparse
            netloc = urlparse(url).netloc.lower()
            host = netloc.split(':')[0].strip('.')
            if not host:
                return ''
            # IP or localhost
            if host == 'localhost' or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
                return host
            parts = [p for p in host.split('.') if p]
            if len(parts) < 2:
                return host
            # Handle common multi-part public suffixes like com.cn so that
            # finance.sina.com.cn -> sina.com.cn (not com.cn)
            two_level_suffixes = {
                ('com', 'cn'), ('net', 'cn'), ('org', 'cn'), ('gov', 'cn'), ('edu', 'cn'), ('ac', 'cn'),
                ('com', 'hk'), ('net', 'hk'), ('org', 'hk'),
                ('com', 'tw'), ('net', 'tw'), ('org', 'tw'),
            }
            if len(parts) >= 3 and (parts[-2], parts[-1]) in two_level_suffixes:
                return '.'.join(parts[-3:])
            return '.'.join(parts[-2:])
        except Exception:
            return ""

    def is_allowed(url: str) -> bool:
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            host = (p.netloc or '').lower().split(':')[0].strip('.')
            path = (p.path or '')
        except Exception:
            host, path = '', ''

        d = domain_of(url)
        if whitelist and any(d.endswith(w) for w in whitelist):
            return True

        tld = d.split('.')[-1] if d else ''
        if tld in block_tlds:
            return False

        # Special-case: Baidu engine often returns redirect wrapper URLs like
        # https://www.baidu.com/link?url=... which can point to external news.
        # We still block Baidu-owned content surfaces (zhidao/baike/wenku/etc.).
        if d.endswith('baidu.com'):
            baidu_block_hosts = (
                'zhidao.baidu.com',
                'baike.baidu.com',
                'wenku.baidu.com',
                'jingyan.baidu.com',
                'tieba.baidu.com',
                'bk.baidu.com',
            )
            if any(host.endswith(h) for h in baidu_block_hosts):
                return False
            if host.endswith('baidu.com') and path.startswith('/link'):
                return True

        if blacklist and any(d.endswith(b) for b in blacklist):
            return False
        return True

    def norm_title(t: str) -> str:
        t = (t or "").strip()
        t = re.sub(r"[\s\-_|·【】\[\]（）()]+", " ", t)
        t = re.sub(r"^【.*?】", "", t)
        return t.lower()

    def _is_etf_or_sector_title(t: str) -> bool:
        nt = (t or '').strip().lower()
        # Broad/sector/ETF-market headlines tend to be less actionable for single-stock factors
        pats = [
            'etf', '指数', '板块', '概念', '盘中', '午评', '收盘', '大盘', '市场', '资金面', '北向', '南向',
            '港股', '美股', 'a股', '行业', '主题', '轮动', '普涨', '普跌', '领涨', '领跌'
        ]
        return any(p in nt for p in pats)

    def _is_company_event_title(t: str) -> bool:
        s = (t or '').strip()
        if not s:
            return False
        # Signal words for company-level events / disclosures
        pats = [
            '公告', '业绩', '预告', '快报', '年报', '季报', '财报', '分红', '回购', '回購', '增持', '减持',
            '中标', '订单', '訂單', '签约', '簽約', '项目', '項目', '合作', '訴訟', '诉讼', '仲裁', '问询', '問詢',
            '回复', '回覆', '停牌', '复牌', '重大', '重组', '并购', '定增', '募资', '转债', '监管', '交易所'
        ]
        return any(p in s for p in pats)

    def _low_quality_metrics(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(items or [])
        if n <= 0:
            return {
                'n': 0,
                'dup_ratio': 1.0,
                'etf_ratio': 1.0,
                'company_ratio': 0.0,
                'event_ratio': 0.0,
                'data_ratio': 1.0,
                'community_ratio': 1.0,
                'short_ratio': 1.0,
            }
        titles = [(it.get('title') or '').strip() for it in items]
        normed = [norm_title(t) for t in titles if t]
        uniq = len(set(normed)) if normed else 0
        dup_ratio = 1.0 - (uniq / max(1, n))

        etf_cnt = sum(1 for t in titles if _is_etf_or_sector_title(t))
        etf_ratio = etf_cnt / max(1, n)

        company_cnt = 0
        if symbol:
            company_cnt += sum(1 for t in titles if symbol in t)
        if query and len(query) >= 2:
            company_cnt = max(company_cnt, sum(1 for t in titles if query in t))
        company_ratio = company_cnt / max(1, n)

        event_cnt = sum(1 for t in titles if _is_company_event_title(t))
        event_ratio = event_cnt / max(1, n)

        short_min = int(os.getenv('SEARXNG_REQUERY_SHORT_CONTENT_MIN', '35'))
        short_cnt = 0
        for it in items:
            c = (it.get('content') or '').strip()
            if len(c) < short_min:
                short_cnt += 1
        short_ratio = short_cnt / max(1, n)

        data_cnt = 0
        for it in items:
            data_cnt += 1 if _is_quote_or_data_page(it.get('title') or '', it.get('url') or '') else 0
        data_ratio = data_cnt / max(1, n)

        community_cnt = 0
        for it in items:
            community_cnt += 1 if _is_community_or_qa_page(it.get('title') or '', it.get('url') or '') else 0
        community_ratio = community_cnt / max(1, n)

        return {
            'n': n,
            'dup_ratio': dup_ratio,
            'etf_ratio': etf_ratio,
            'company_ratio': company_ratio,
            'event_ratio': event_ratio,
            'data_ratio': data_ratio,
            'community_ratio': community_ratio,
            'short_ratio': short_ratio,
        }

    def _should_llm_requery(items: List[Dict[str, Any]]) -> bool:
        if os.getenv('SEARXNG_ENABLE_LLM_REQUERY', '1') != '1':
            return False
        m = _low_quality_metrics(items)
        # Simple, robust heuristic: scarce OR mostly ETF/sector OR too repetitive OR lacks company events
        min_n = int(os.getenv('SEARXNG_REQUERY_MIN_N', '4'))
        etf_hi = float(os.getenv('SEARXNG_REQUERY_ETF_RATIO', '0.65'))
        dup_hi = float(os.getenv('SEARXNG_REQUERY_DUP_RATIO', '0.45'))
        event_lo = float(os.getenv('SEARXNG_REQUERY_EVENT_RATIO', '0.20'))
        company_lo = float(os.getenv('SEARXNG_REQUERY_COMPANY_RATIO', '0.25'))
        data_hi = float(os.getenv('SEARXNG_REQUERY_DATA_RATIO', '0.55'))
        community_hi = float(os.getenv('SEARXNG_REQUERY_COMMUNITY_RATIO', '0.45'))
        if m['n'] < min_n:
            return True
        if m['dup_ratio'] >= dup_hi:
            return True
        # Many quote/data hub pages: rewrite query towards announcements/news
        if m.get('data_ratio', 0.0) >= data_hi and m.get('event_ratio', 0.0) <= (event_lo + 0.10):
            return True
        # Community/Q&A dominated results (e.g., 知乎/贴吧/知道): force rewrite to news/disclosures
        if m.get('community_ratio', 0.0) >= community_hi and m.get('event_ratio', 0.0) <= (event_lo + 0.15):
            return True
        if m['etf_ratio'] >= etf_hi and m['company_ratio'] <= company_lo:
            return True
        if m['event_ratio'] <= event_lo and m['company_ratio'] <= company_lo:
            return True
        return False

    def _rule_rewrite_query() -> str:
        base = query or ''
        sym = symbol or ''
        if _has_cjk(base) or _has_cjk(sym) or force_cn_suffix:
            # Use OR terms to widen recall for company disclosures/events
            return f"{base} {sym} (公告 OR 业绩 OR 财报 OR 年报 OR 季报 OR 预告 OR 快报 OR 回购 OR 增持 OR 减持 OR 中标 OR 订单 OR 签约 OR 互动易 OR 投资者关系 OR 问询 OR 回复 OR 停牌 OR 复牌 OR 重组)"
        return f"{base} {sym} (announcement OR earnings OR guidance OR buyback OR contract OR tender OR order OR investor relations)"

    def _llm_rewrite_query() -> Optional[str]:
        # Only attempt when LLM is configured; otherwise None
        if not USE_LLM:
            return None
        try:
            prompt = (
                "You are optimizing a web/news search query for Chinese A-share stock news. "
                "Given company name and stock code, produce ONE improved query string focusing on company-specific disclosures/events. "
                "Avoid generic market/ETF/sector words. Prefer terms like 公告/业绩/财报/回购/中标/订单/签约/互动易/投资者关系/问询/回复/停复牌/重组.\n\n"
                f"Company name: {query}\n"
                f"Stock code: {symbol or ''}\n"
                f"Original query: {q}\n\n"
                "Return JSON only: {\"query\": \"...\"}"
            )
            raw = _invoke_llm(prompt, temperature=0.2)
            if not raw:
                return None
            raw_s = raw.strip()
            # Try parse as json object
            try:
                obj = json.loads(raw_s)
                if isinstance(obj, dict):
                    qq = (obj.get('query') or '').strip()
                    return qq or None
            except Exception:
                # Attempt substring json
                try:
                    m = re.search(r"\{[\s\S]*\}", raw_s)
                    if m:
                        obj = json.loads(m.group(0))
                        if isinstance(obj, dict):
                            qq = (obj.get('query') or '').strip()
                            return qq or None
                except Exception:
                    pass
            # Fallback: treat raw as query text
            # (may happen if strict-json is disabled)
            if len(raw_s) >= 3:
                return raw_s[:300]
        except Exception as e_rew:
            print(f"[searx-rewrite] llm rewrite failed: {e_rew}")
        return None

    def _llm_rewrite_queries() -> List[str]:
        # Return multiple candidate queries (CN + optional EN alias) to improve recall.
        if not USE_LLM:
            return []
        try:
            prompt = (
                "You are optimizing web/news search queries for Chinese A-share stock news. "
                "Given company name and stock code, produce 2-3 alternative query strings that will find company-specific disclosures/news. "
                "One should be Chinese-focused (公告/业绩/财报/回购/中标/订单/签约/互动易/投资者关系/问询/回复/停复牌/重组). "
                "If you know an English company name or common abbreviation, include one English query variant (e.g., using the abbreviation + stock code).\n\n"
                "Avoid generic market/ETF/sector words and avoid Q&A/community terms like 知乎/股吧.\n\n"
                f"Company name: {query}\n"
                f"Stock code: {symbol or ''}\n"
                f"Original query: {q}\n\n"
                "Return JSON only: {\"queries\": [\"...\", \"...\"]}"
            )
            raw = _invoke_llm(prompt, temperature=0.2)
            if not raw:
                return []
            raw_s = raw.strip()
            obj = None
            try:
                obj = json.loads(raw_s)
            except Exception:
                try:
                    m = re.search(r"\{[\s\S]*\}", raw_s)
                    if m:
                        obj = json.loads(m.group(0))
                except Exception:
                    obj = None
            if not isinstance(obj, dict):
                return []
            qs = obj.get('queries')
            if not isinstance(qs, list):
                return []
            out: List[str] = []
            seen: set = set()
            for x in qs:
                if not isinstance(x, str):
                    continue
                s = x.strip()
                if len(s) < 3:
                    continue
                k = s.lower()
                if k in seen:
                    continue
                seen.add(k)
                out.append(s[:300])
                if len(out) >= 3:
                    break
            return out
        except Exception as _e:
            print(f"[searx-rewrite] llm rewrite queries failed: {_e}")
        return []

    def cjk_count(s: str) -> int:
        return sum(1 for ch in (s or '') if '\u4e00' <= ch <= '\u9fff')

    def _has_japanese_kana(s: str) -> bool:
        # Hiragana / Katakana / halfwidth katakana
        return any(
            ('\u3040' <= ch <= '\u30ff') or ('\uff66' <= ch <= '\uff9d')
            for ch in (s or '')
        )

    from datetime import datetime
    # 放宽默认时间窗口，降低“0 结果”概率（可通过环境变量覆盖）
    max_age_days = int(os.getenv("SEARXNG_MAX_AGE_DAYS", "45"))
    title_date_max_days = int(os.getenv("SEARXNG_TITLE_DATE_MAX_DAYS", "180"))
    now_dt = datetime.now(timezone.utc)

    def parse_published(r: Dict[str, Any]) -> Optional[datetime]:
        v = r.get('published') or r.get('publishedDate') or r.get('published_time') or r.get('date')
        if v is None:
            return None
        try:
            if isinstance(v, (int, float)):
                return datetime.fromtimestamp(float(v), tz=timezone.utc)
            s = str(v).strip()
            s2 = s.replace('Z', '+00:00')
            try:
                dt = datetime.fromisoformat(s2)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
            m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
            if m:
                y, mo, d = map(int, m.groups())
                return datetime(y, mo, d, tzinfo=timezone.utc)
        except Exception:
            return None
        return None

    def title_has_old_date(title: str) -> bool:
        t = title or ''
        m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", t)
        if not m:
            return False
        try:
            y, mo, d = map(int, m.groups())
            dt = datetime(y, mo, d, tzinfo=timezone.utc)
            return (now_dt - dt).days > title_date_max_days
        except Exception:
            return False

    seen_titles: set = set()
    seen_urls: set = set()
    results: List[Dict] = []
    min_title_len = int(os.getenv("SEARXNG_MIN_TITLE_LEN", "4"))
    min_content_len = int(os.getenv("SEARXNG_MIN_CONTENT_LEN", "5"))
    min_cjk_title = int(os.getenv("SEARXNG_MIN_CJK_TITLE", "2"))
    min_cjk_any = int(os.getenv("SEARXNG_MIN_CJK_ANY", "4"))
    blocked_title_patterns = [
        "中文報紙頭條","中文报纸头条","報紙頭條","报纸头条","報章摘要","报章摘要","頭條新聞","头条新闻","今日快訊","今日快讯",
        # Dictionary / encyclopedia / generic term pages (common noise for short company names)
        "汉语字典","漢語字典","新华字典","新華字典","拼音","部首","笔顺","筆順","字典","百科","搜狗百科","维基百科","維基百科"
    ]

    # For CJK queries, always enforce CJK density even in permissive stages.
    enforce_cjk = cn_context

    # Collect more candidates than max_results so we can rerank and keep
    # quote/data pages only as a last resort.
    collect_cap = int(os.getenv('SEARXNG_COLLECT_CAP', str(max(max_results * 3, max_results))))

    def _norm_domain(s: str) -> str:
        ss = (s or '').strip().lower()
        if not ss:
            return ''
        ss = ss.replace('https://', '').replace('http://', '')
        ss = ss.split('/')[0].split(':')[0]
        parts = ss.split('.')
        if len(parts) >= 2:
            two_level_suffixes = {
                ('com', 'cn'), ('net', 'cn'), ('org', 'cn'), ('gov', 'cn'), ('edu', 'cn'), ('ac', 'cn'),
                ('com', 'hk'), ('net', 'hk'), ('org', 'hk'),
                ('com', 'tw'), ('net', 'tw'), ('org', 'tw'),
            }
            if len(parts) >= 3 and (parts[-2], parts[-1]) in two_level_suffixes:
                return '.'.join(parts[-3:])
            return '.'.join(parts[-2:])
        return ss

    relevant_domains_env = os.getenv(
        'SEARXNG_RELEVANT_DOMAINS',
        os.getenv('SEARXNG_CN_SITES', 'cninfo.com.cn,sse.com.cn,szse.cn,eastmoney.com,10jqka.com.cn,sina.com.cn,qq.com,sohu.com,ifeng.com')
    )
    relevant_domains = { _norm_domain(x) for x in relevant_domains_env.split(',') if _norm_domain(x) }

    def _is_quote_or_data_page(title: str, url: str) -> bool:
        t = (title or '').strip().lower()
        u = (url or '').strip().lower()
        if not t and not u:
            return False

        # Expanded URL patterns to catch more quote/data/F10 pages across major portals
        url_pats = [
            'quote.eastmoney.com',
            'f10.eastmoney.com',
            'data.eastmoney.com',
            'stockpage.10jqka.com.cn',
            'basic.10jqka.com.cn',
            'data.10jqka.com.cn',
            'finance.sina.com.cn/realstock',
            'gu.qq.com',
            'q.stock.sohu.com',
            'quote.cfi.cn',
            'stock.quote.stockstar.com',
            'gushitong.baidu.com/stock',
            'xueqiu.com/S/',
            'cn.investing.com/equities',
            'stock.9fzt.com',
            'quote.stockstar.com',
            'hq.gucheng.com',
        ]
        if any(p in u for p in url_pats):
            return True

        # Expanded title patterns to detect quote/F10 pages even without explicit URL signals
        title_pats = [
            '实时行情', '行情', '分时', 'k线', 'k线图', '走势图', '股价', '股價',
            '数据中心', '數據中心', '财务指标', '財務指標', 'f10', '公司资料', '公司資料', '公司概况', '公司概況',
            '资金流向', '資金流向', '龙虎榜', '龍虎榜', '大宗交易',
            '股吧', '讨论区', '討論區',
            '股票股价', '股票价格', '股票行情', '个股资金流向', '最新价格行情',
        ]
        return any(p in t for p in title_pats)

    def _is_community_or_qa_page(title: str, url: str) -> bool:
        t = (title or '').strip().lower()
        u = (url or '').strip().lower()
        if not t and not u:
            return False

        # Domain / path level signals
        if 'zhihu.com' in u:
            return True
        if 'zhidao.baidu.com' in u:
            return True
        if 'tieba.baidu.com' in u:
            return True
        if 'guba.' in u:
            return True
        if 'bbs.' in u or '/bbs' in u:
            return True
        if any(x in u for x in ['/question/', '/answers/', '/answer/']):
            return True

        # Title signals
        if any(x in t for x in ['知乎', '知道', '贴吧', '股吧', '论坛', '討論', '讨论', '问答', '提问', '回答']):
            return True

        return False

    def _filter_and_append(
        rlist: List[Dict],
        allow_short: bool = False,
        permissive: bool = False,
        must_match_terms: Optional[List[str]] = None,
    ):
        nonlocal results, seen_titles, seen_urls
        nq = norm_title(query) if enforce_cjk else ''
        nq_compact = re.sub(r"\s+", "", nq) if nq else ''
        mm = [str(x).strip().lower() for x in (must_match_terms or []) if str(x).strip()]
        for r in rlist:
            title = (r.get("title") or "").strip()
            url = r.get("url") or ""
            content = (r.get("content") or "").strip()
            if not title or len(title) < min_title_len:
                _SEARX_FILTER_METRICS['skip_short_title'] += 1
                continue
            if not url:
                _SEARX_FILTER_METRICS['skip_no_url'] += 1
                continue
            if not is_allowed(url):
                _SEARX_FILTER_METRICS['skip_domain'] += 1
                continue
            if any(pat in title for pat in blocked_title_patterns):
                _SEARX_FILTER_METRICS['skip_blocked_title'] += 1
                continue
            nt = norm_title(title)
            if nt in seen_titles or url in seen_urls:
                _SEARX_FILTER_METRICS['skip_duplicate'] += 1
                continue
            if any(x in nt for x in ["报纸头条", "頭條", "头条", "每日要闻", "今日快讯", "今日快訊"]):
                _SEARX_FILTER_METRICS['skip_generic'] += 1
                continue
            if not permissive and not allow_short and len(content) < min_content_len and not os.getenv("SEARXNG_ALLOW_SHORT", "0") == "1":
                _SEARX_FILTER_METRICS['skip_short_content'] += 1
                continue
            if (not permissive or enforce_cjk) and cjk_count(title) < min_cjk_title and (cjk_count(title) + cjk_count(content)) < min_cjk_any:
                _SEARX_FILTER_METRICS['skip_low_cjk'] += 1
                continue

            # Block Japanese pages that can pass the CJK filter due to shared Han characters.
            # This prevents cases like イオン... from leaking into A-share daily analysis.
            if enforce_cjk and (_has_japanese_kana(title) or _has_japanese_kana(content)):
                _SEARX_FILTER_METRICS['skip_japanese_kana'] = _SEARX_FILTER_METRICS.get('skip_japanese_kana', 0) + 1
                continue

            # In CN/A-share context, never accept results without explicit company signal.
            # This prevents unrelated pages under broad finance portals (sina/qq/etc) from leaking in.
            if enforce_cjk:
                blob_l = f"{title} {url} {content}".lower()
                # Try to match company name and/or 6-digit code.
                code6 = None
                try:
                    m = re.search(r"\b(\d{6})\b", (symbol or ''))
                    code6 = m.group(1) if m else None
                except Exception:
                    code6 = None
                must_hit = False
                hit_name = False
                hit_symbol = False
                hit_code = False
                if nq_compact:
                    nt_compact = re.sub(r"\s+", "", nt)
                    if nq_compact in nt_compact:
                        hit_name = True
                        must_hit = True
                if symbol and str(symbol).lower() in blob_l:
                    hit_symbol = True
                    must_hit = True
                if code6 and code6 in blob_l:
                    hit_code = True
                    must_hit = True

                # Avoid random foreign pages matching only by a 6-digit number.
                # Allow code-only matches only on trusted/known CN finance domains.
                if must_hit and (hit_code and not hit_name and not hit_symbol):
                    d0 = domain_of(url)
                    if d0 and not any(d0.endswith(rd) for rd in relevant_domains):
                        _SEARX_FILTER_METRICS['skip_code_only_untrusted'] = _SEARX_FILTER_METRICS.get('skip_code_only_untrusted', 0) + 1
                        continue
                if not must_hit:
                    _SEARX_FILTER_METRICS['skip_not_match_terms'] = _SEARX_FILTER_METRICS.get('skip_not_match_terms', 0) + 1
                    continue

                # Suppress community/Q&A pages unless we're already in a permissive rescue stage.
                if not permissive and _is_community_or_qa_page(title, url):
                    _SEARX_FILTER_METRICS['skip_community'] = _SEARX_FILTER_METRICS.get('skip_community', 0) + 1
                    continue

            if mm:
                blob = f"{title} {url} {content}".lower()
                if not any(t in blob for t in mm):
                    _SEARX_FILTER_METRICS['skip_not_match_terms'] = _SEARX_FILTER_METRICS.get('skip_not_match_terms', 0) + 1
                    continue
            pub = parse_published(r)
            if pub is not None:
                try:
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=timezone.utc)
                    age_days = (now_dt - pub).days
                except Exception:
                    age_days = max_age_days + 1
                if age_days > max_age_days:
                    _SEARX_FILTER_METRICS['skip_old_published'] += 1
                    continue
            else:
                if title_has_old_date(title):
                    _SEARX_FILTER_METRICS['skip_old_title_date'] += 1
                    continue
            results.append({"title": title, "url": url, "content": content})
            seen_titles.add(nt)
            seen_urls.add(url)
            if len(results) >= collect_cap:
                break

    def _news_score(it: Dict[str, Any]) -> float:
        title = (it.get('title') or '').strip()
        url = (it.get('url') or '').strip()
        content = (it.get('content') or '').strip()
        if it.get('is_placeholder'):
            return -100.0

        score = 0.0
        u = url.lower()
        t = title.lower()
        # Official disclosure sites get highest priority
        if any(x in u for x in ['cninfo.com.cn', 'sse.com.cn', 'szse.cn']):
            score += 10.0
        # Trusted CN finance media portals (prefer as high-signal sources)
        trusted_media = (
            'cs.com.cn', 'cnstock.com', 'stcn.com', 'yicai.com', 'cls.cn', 'caixin.com', 'nbd.com.cn',
            'wallstreetcn.com', 'jiemian.com', '21jingji.com', 'chinastarmarket.cn', 'p5w.net',
            'money.163.com', 'finance.qq.com', 'finance.sina.com.cn', 'finance.sohu.com', 'finance.ifeng.com'
        )
        if any(x in u for x in trusted_media):
            score += 2.5
        # Policy / regulator sources can help macro context
        if any(x in u for x in ['csrc.gov.cn', 'pbc.gov.cn', 'mof.gov.cn', 'ndrc.gov.cn', 'stats.gov.cn']):
            score += 2.0
        # PDF announcements are highly valuable
        if u.endswith('.pdf') or '/finalpage/' in u:
            score += 8.0
        # News article paths (common on major portals) are preferred over quote pages
        if any(x in u for x in ['/article/', '/news/', '/finance/', '/stock/', '/company/']):
            score += 2.0
        # Announcement/disclosure keywords in title boost priority
        if any(x in t for x in ['公告', '披露', '业绩', '财报', '年报', '季报', '问询', '回复', '重大事项', '澄清']):
            score += 4.0
        if _is_company_event_title(title):
            score += 3.0
        if _is_etf_or_sector_title(title):
            score -= 2.0
        # Quote/data pages: strongly downrank but still allow as fallback
        if _is_quote_or_data_page(title, url):
            score -= 8.0
        # Community/Q&A pages: only as last resort
        if _is_community_or_qa_page(title, url):
            score -= 10.0
        if len(content) >= 80:
            score += 0.6
        elif len(content) <= 15:
            score -= 0.4
        return score

    def _build_must_match_terms(rq: str) -> List[str]:
        terms: List[str] = []
        try:
            base = (rq or '')
            # Keep symbol/code as strong match term
            if symbol and symbol.strip():
                terms.append(symbol.strip())
            # Extract ASCII tokens like CATL
            for m in re.findall(r"[A-Za-z]{2,}", base):
                terms.append(m)
            # Extract longer digit tokens
            for m in re.findall(r"\d{4,}", base):
                terms.append(m)
            # Extract CJK runs
            for m in re.findall(r"[\u4e00-\u9fff]{2,}", base):
                terms.append(m)
        except Exception:
            pass
        # Deduplicate while keeping order
        seen: set = set()
        out: List[str] = []
        for t in terms:
            tl = (t or '').strip().lower()
            if not tl or tl in seen:
                continue
            seen.add(tl)
            out.append(t)
        return out

    def _is_company_related(it: Dict[str, Any]) -> bool:
        title = (it.get('title') or '').strip()
        url = (it.get('url') or '').strip()
        content = (it.get('content') or '').strip()
        if not title and not url and not content:
            return False
        d = domain_of(url) if url else ''
        code6 = None
        try:
            m = re.search(r"\b(\d{6})\b", (symbol or ''))
            code6 = m.group(1) if m else None
        except Exception:
            code6 = None
        code_prefixed: List[str] = []
        if code6:
            code_prefixed = [f"sz{code6}", f"sh{code6}"]
        # Strong signals: symbol/name appears
        if symbol and symbol in title:
            return True
        if symbol and symbol in url:
            return True
        if symbol and symbol in content:
            return True
        if code6 and (code6 in title or code6 in url or code6 in content):
            return True
        if code_prefixed and any(x in (title.lower()) for x in code_prefixed):
            return True
        if code_prefixed and any(x in (url.lower()) for x in code_prefixed):
            return True
        if code_prefixed and any(x in (content.lower()) for x in code_prefixed):
            return True
        if query and len(query) >= 2 and query in title:
            return True
        if query and len(query) >= 2 and query in content:
            return True
        if query and len(query) >= 2 and query in url:
            return True
        # Event keywords often indicate company-level news even if name is omitted
        if _is_company_event_title(title) and d and any(d.endswith(rd) for rd in relevant_domains):
            return True
        return False

    def _finalize_results() -> List[Dict[str, Any]]:
        base_list = results
        # Prefer company-related items when available to avoid irrelevant pages
        rel = [it for it in results if _is_company_related(it)]
        if rel:
            base_list = rel
        else:
            # If nothing looks company-related, do a stricter fallback based on explicit name/symbol match.
            hard: List[Dict[str, Any]] = []
            code6 = None
            try:
                m = re.search(r"\b(\d{6})\b", (symbol or ''))
                code6 = m.group(1) if m else None
            except Exception:
                code6 = None
            code_prefixed: List[str] = []
            if code6:
                code_prefixed = [f"sz{code6}", f"sh{code6}"]
            if query and len(query) >= 2:
                hard = [it for it in results if query in (it.get('title') or '') or query in (it.get('content') or '') or query in (it.get('url') or '')]
            if not hard and symbol:
                hard = [it for it in results if symbol in (it.get('title') or '') or symbol in (it.get('content') or '') or symbol in (it.get('url') or '')]
            if not hard and code6:
                hard = [it for it in results if code6 in (it.get('title') or '') or code6 in (it.get('content') or '') or code6 in (it.get('url') or '')]
            if not hard and code_prefixed:
                hard = [it for it in results if any(x in (it.get('title') or '').lower() for x in code_prefixed) or any(x in (it.get('content') or '').lower() for x in code_prefixed) or any(x in (it.get('url') or '').lower() for x in code_prefixed)]
            if hard:
                base_list = hard
            else:
                # Do not leak obviously unrelated pages into downstream analysis.
                return []

        # Stable sort by score (tie -> earlier first)
        scored: List[Any] = []
        for idx, it in enumerate(base_list):
            scored.append((float(_news_score(it)), idx, it))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [x[2] for x in scored[:max_results]]

    # DB-first 预填充：优先从近 N 天的入库新闻中抓取，减少 0 新闻概率
    try_db_first = (os.getenv('AGENT_DB_FIRST', '1') == '1')
    if try_db_first:
        try:
            prefill_limit = int(os.getenv('AGENT_DB_FIRST_LIMIT', '6'))
            if prefill_limit > 0 and len(results) < max_results:
                queries: List[str] = []
                # 先用公司名，再用交易代码（可能不在标题，但作为次选）
                if query:
                    queries.append(query)
                if symbol and symbol not in queries:
                    queries.append(symbol)
                days = int(os.getenv('AGENT_DB_FIRST_DAYS', '30'))
                min_len = int(os.getenv('AGENT_DB_FIRST_MIN_CONTENT', '40'))
                added_total = 0
                for qdb in queries:
                    if len(results) >= max_results or added_total >= prefill_limit:
                        break
                    try:
                        url_api = f"{API_BASE}/api/news/search_db"
                        params_db = {
                            'query': qdb,
                            'limit': str(max(0, prefill_limit - added_total)),
                            'days': str(days),
                            'include_content': 'true'
                        }
                        rdb = _request_with_retry('get', url_api, params=params_db, timeout=_HTTP_TIMEOUT_DB)
                        if rdb.status_code == 200:
                            jdb = rdb.json() or {}
                            arts = jdb.get('articles') or []
                            added = 0
                            for a in arts:
                                if len(results) >= max_results or added_total >= prefill_limit:
                                    break
                                t = (a.get('title') or '').strip()
                                u = (a.get('url') or '').strip()
                                if not t or not u:
                                    continue
                                nt = (re.sub(r"[\s\-_|·【】\[\]（）()]+", " ", t).lower()).strip()
                                if nt in seen_titles or u in seen_urls:
                                    continue
                                content = (a.get('content') or a.get('summary') or '').strip()
                                if len(content) < min_len:
                                    continue
                                results.append({'title': t, 'url': u, 'content': content})
                                seen_titles.add(nt)
                                seen_urls.add(u)
                                added += 1
                                added_total += 1
                            if added > 0:
                                _SEARX_FILTER_METRICS['db_first_added'] = _SEARX_FILTER_METRICS.get('db_first_added', 0) + added
                                print(f"[db-first] 预填充 {added} 条 (query='{qdb}')")
                        else:
                            print(f"[db-first] API {url_api} status={rdb.status_code} body={rdb.text[:180] if hasattr(rdb,'text') else ''}")
                    except Exception as _dbf_err:
                        print(f"[db-first] 查询失败: {_dbf_err}")
        except Exception as e_dbfirst:
            print(f"[db-first] 预填充流程异常: {e_dbfirst}")
    if len(results) >= max_results and not _should_llm_requery(results):
        return _finalize_results()

    # 媒体增量搜索（可配置域名），在早期阶段融入，提升稳定度
    try_media_inc = (os.getenv('AGENT_USE_MEDIA_INCREMENTAL', '1') == '1')
    if try_media_inc:
        try:
            domains_env = os.getenv('AGENT_MEDIA_INCREMENTAL_DOMAINS', os.getenv('SEARXNG_CN_SITES', 'cninfo.com.cn,sse.com.cn,szse.cn,eastmoney.com,cnstock.com,stcn.com,yicai.com,cs.com.cn,10jqka.com.cn,jrj.com.cn,nbd.com.cn,cfi.cn,stockstar.com,hexun.com,money.163.com,finance.qq.com,finance.sina.com.cn,finance.sohu.com,stock.qq.com,finance.ifeng.com,caixin.com,chinastarmarket.cn,21jingji.com,wallstreetcn.com,jiemian.com,cls.cn,p5w.net,csrc.gov.cn,pbc.gov.cn,mof.gov.cn,ndrc.gov.cn,stats.gov.cn,qq.com,sina.com.cn,sohu.com,ifeng.com'))
            domains = [s.strip() for s in domains_env.split(',') if s.strip()]
            if domains:
                since_map = _media_since_load()
                inc_max = int(os.getenv('AGENT_MEDIA_INCREMENTAL_MAX', str(max(3, max_results // 2))))
                site_cap = int(os.getenv('AGENT_MEDIA_INCREMENTAL_MAX_SITES','8'))
                inc_news = _media_incremental_fetch(q, domains[:site_cap], since_map, inc_max)
                added = 0
                for r in inc_news:
                    if len(results) >= max_results:
                        break
                    t = (r.get('title') or '').strip()
                    u = (r.get('url') or '').strip()
                    if not t or not u:
                        continue
                    nt = norm_title(t)
                    if nt in seen_titles or u in seen_urls:
                        continue
                    content = (r.get('content') or r.get('summary') or '').strip()
                    results.append({'title': t, 'url': u, 'content': content})
                    seen_titles.add(nt)
                    seen_urls.add(u)
                    added += 1
                if added > 0:
                    print(f"[media-inc] 融合增量 {added} 条")
                _media_since_save(since_map)
        except Exception as e_media:
            print(f"[media-inc] 异常: {e_media}")

    # 直接API信源 - 当SearXNG不可用或引擎被封时的关键备用信源
    # 在所有SearXNG pass之前尝试直接API，因为日志显示SearXNG引擎全部被封
    if DIRECT_API_AVAILABLE and DIRECT_API_ENABLED and len(results) < max_results:
        try:
            _SEARX_FILTER_METRICS['direct_api_try'] = _SEARX_FILTER_METRICS.get('direct_api_try', 0) + 1
            print(f"[direct-api] 尝试直接API信源 (symbol={symbol}, query={query[:50] if query else 'N/A'})")
            
            # 提取股票代码和名称
            stock_code = symbol.replace('.SH', '').replace('.SZ', '').replace('.BJ', '') if symbol else None
            stock_name = query.split()[0] if query and ' ' in query else query
            
            # 调用直接API
            direct_news = fetch_news_direct(
                stock_code=stock_code,
                stock_name=stock_name,
                industry=None,
                limit=max(max_results - len(results), 10)
            )
            
            added = 0
            for r in direct_news:
                if len(results) >= max_results:
                    break
                t = (r.get('title') or '').strip()
                u = (r.get('url') or '').strip()
                if not t or not u:
                    continue
                nt = norm_title(t)
                if nt in seen_titles or u in seen_urls:
                    continue
                content = (r.get('content') or r.get('summary') or '').strip()
                cand = {'title': t, 'url': u, 'content': content}
                # 可选：检查是否公司相关
                if cn_context and not _is_company_related(cand):
                    continue
                results.append(cand)
                seen_titles.add(nt)
                seen_urls.add(u)
                added += 1
            
            if added > 0:
                _SEARX_FILTER_METRICS['direct_api_added'] = _SEARX_FILTER_METRICS.get('direct_api_added', 0) + added
                print(f"[direct-api] 成功添加 {added} 条新闻")
            else:
                print(f"[direct-api] 无新增（返回 {len(direct_news)} 条，均已去重或不相关）")
        except Exception as e_direct:
            print(f"[direct-api] 异常: {e_direct}")

    # 如果直接API已获得足够结果，可跳过SearXNG（节省时间）
    if len(results) >= max_results and not _should_llm_requery(results):
        print(f"[direct-api] 已获得足够结果 ({len(results)})，跳过SearXNG")
        return _finalize_results()

    # Pass 1（带查询级缓存）
    cache_key = f"{params.get('q','')}|{params.get('categories','')}|{params.get('time_range','')}|{max_results}|{se_eng}"
    if SEARX_CACHE_TTL > 0:
        ts_res = _SEARX_CACHE.get(cache_key)
        if ts_res and (time.time() - ts_res[0] < SEARX_CACHE_TTL):
            print(f"[searx-cache] hit key='{cache_key}' size={len(ts_res[1])}")
            return ts_res[1][:max_results]
    raw1 = _searx_request(params)
    print(f"[searx-pass1] raw={len(raw1)} q='{q}' params={{k: params[k] for k in params if k!='q'}}")
    _filter_and_append(raw1, allow_short=True)
    if len(results) >= max_results and not _should_llm_requery(results):
        return _finalize_results()

    # Pass 2
    if len(results) < relax_min_results:
        _SEARX_FILTER_METRICS['requery_relax_time'] += 1
        p2 = dict(params)
        p2['time_range'] = os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month')
        if se_eng:
            p2['engines'] = se_eng
        raw2 = _searx_request(p2)
        print(f"[searx-pass2] raw={len(raw2)} params={{k: p2[k] for k in p2 if k!='q'}}")
        _filter_and_append(raw2, allow_short=True)
        if len(results) >= max_results and not _should_llm_requery(results):
            return _finalize_results()

    # Pass 3: broaden category and relax language
    if len(results) == 0:
        _SEARX_FILTER_METRICS['requery_general'] += 1
    p3 = dict(params)
    p3['categories'] = os.getenv('SEARXNG_CATEGORIES_RELAX', 'news,general,science,blogs')
    # 进一步放宽语言以获取可用结果
    p3_lang = os.getenv('SEARXNG_LANGUAGE_RELAX', '')
    if p3_lang:
        p3['language'] = p3_lang
    else:
        # Keep language for CJK queries; omit only for non-CJK to avoid 400 in some setups
        if 'language' in p3 and not (cn_context or _has_cjk(q)):
            del p3['language']
    p3['time_range'] = os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month')
    if se_eng:
        p3['engines'] = se_eng
    raw3 = _searx_request(p3)
    print(f"[searx-pass3] raw={len(raw3)} params={{k: p3[k] for k in p3 if k!='q'}}")
    _filter_and_append(raw3, allow_short=True)
    if len(results) >= max_results and not _should_llm_requery(results):
        return _finalize_results()

    # Pass 3b: remove categories & language fully (use SearX defaults)
    # NOTE: For CN/A-share context we keep language/categories to prevent foreign/noise.
    if (not cn_context) and len(results) < relax_min_results:
        _SEARX_FILTER_METRICS['requery_general'] += 1
        p3b = dict(params)
        if 'categories' in p3b:
            del p3b['categories']
        if 'language' in p3b:
            del p3b['language']
        p3b['time_range'] = os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month')
        if se_eng:
            p3b['engines'] = se_eng
        raw3b = _searx_request(p3b)
        print(f"[searx-pass3b] raw={len(raw3b)} params={{k: p3b[k] for k in p3b if k!='q'}}")
        _filter_and_append(raw3b, allow_short=True)
        if len(results) >= max_results and not _should_llm_requery(results):
            return _finalize_results()

    # Pass 3c: simplest query without symbol, permissive filtering
    if len(results) < relax_min_results:
        simple_q = f"{query} 新闻" if cn_context else f"{query} news"
        p3c = {
            'q': simple_q,
            'format': 'json',
            'time_range': os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month')
        }
        if se_eng:
            p3c['engines'] = se_eng
        if cn_context:
            p3c['language'] = os.getenv('SEARXNG_LANGUAGE_CJK_DEFAULT', 'zh-CN').strip()
        raw3c = _searx_request(p3c)
        print(f"[searx-pass3c] raw={len(raw3c)} params={{k: p3c[k] for k in p3c if k!='q'}}")
        _filter_and_append(raw3c, allow_short=True, permissive=True, must_match_terms=(cn_must_match_terms or None))
        if len(results) >= max_results and not _should_llm_requery(results):
            return _finalize_results()

    # Pass 4
    if len(results) < max_results:
        aug_terms = os.getenv('SEARXNG_QUERY_AUG_TERMS', '公告,研报,财报,互动易,投资者关系,涨停,异动').split(',')
        aug_terms = [t.strip() for t in aug_terms if t.strip()]
        max_aug = int(os.getenv('SEARXNG_MAX_AUG_PASSES', '5'))
        for term in aug_terms[:max_aug]:
            _SEARX_FILTER_METRICS['requery_aug'] += 1
            # augment on the most permissive base
            p4 = {
                'q': q + f" {term}",
                'format': 'json',
                'time_range': os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month')
            }
            if se_eng:
                p4['engines'] = se_eng
            p4['q'] = q + f" {term}"
            raw4 = _searx_request(p4)
            print(f"[searx-pass4] raw={len(raw4)} term='{term}'")
            _filter_and_append(raw4, allow_short=True, permissive=True, must_match_terms=(cn_must_match_terms or None))
            if len(results) >= max_results:
                break
    # Pass 5: Targeted CN finance domains (site: filters)
    if len(results) < max_results:
        cn_sites_env = os.getenv('SEARXNG_CN_SITES', 'cninfo.com.cn,sse.com.cn,szse.cn,eastmoney.com,cnstock.com,stcn.com,yicai.com,cs.com.cn,10jqka.com.cn,jrj.com.cn,nbd.com.cn,cfi.cn,stockstar.com,hexun.com,money.163.com,finance.qq.com,finance.sina.com.cn,finance.sohu.com,stock.qq.com,finance.ifeng.com,caixin.com,chinastarmarket.cn,21jingji.com,wallstreetcn.com,jiemian.com,cls.cn,p5w.net,csrc.gov.cn,pbc.gov.cn,mof.gov.cn,ndrc.gov.cn,stats.gov.cn,qq.com,sina.com.cn,sohu.com,ifeng.com')
        cn_sites = [s.strip() for s in cn_sites_env.split(',') if s.strip()]
        # 增加默认站点覆盖与单站点抓取量，以提高命中率
        max_sites = int(os.getenv('SEARXNG_MAX_CN_SITES', '10'))
        per_site = int(os.getenv('SEARXNG_PER_SITE_RESULTS', '3'))
        code6_site: Optional[str] = None
        try:
            m_code_site = re.search(r"\b(\d{6})\b", str(symbol or ''))
            code6_site = m_code_site.group(1) if m_code_site else None
        except Exception:
            code6_site = None

        def _build_site_query(site: str) -> str:
            # NOTE: Reusing the full generic query string (with suffix like “新闻 财经”) often
            # yields 0 results on site: scoped searches. Use a minimal, disclosure-focused query.
            terms: List[str] = []
            if code6_site:
                terms.append(code6_site)
            if query and str(query).strip():
                # IMPORTANT: Baidu's site: queries often return 0 when the company name is quoted.
                terms.append(str(query).strip())

            s = (site or '').strip().lower()
            # Official disclosure / exchanges: bias toward announcements/disclosures.
            if any(s.endswith(x) for x in ['cninfo.com.cn', 'sse.com.cn', 'szse.cn', 'szse.cn.cn']):
                terms.extend(['公告', '披露'])
            else:
                # For general finance portals, keep it lightweight.
                terms.append('公告')

            base = ' '.join([t for t in terms if t])
            return f"{base} site:{site}".strip()

        used = 0
        for site in cn_sites:
            if len(results) >= max_results or used >= max_sites:
                break
            _SEARX_FILTER_METRICS['requery_cn_sites'] += 1
            site_l = (site or '').strip().lower()
            official_sites = {'cninfo.com.cn', 'sse.com.cn', 'szse.cn'}
            force_official_engine = os.getenv('SEARXNG_OFFICIAL_SITE_ENGINE', 'baidu').strip()
            p5 = {
                'q': _build_site_query(site),
                'format': 'json',
            }
            # NOTE: For official disclosure sites, using Baidu without time_range has proven
            # much more reliable in this environment.
            if site_l in official_sites and force_official_engine:
                p5['engines'] = force_official_engine
            else:
                p5['time_range'] = os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month')
                if se_eng:
                    p5['engines'] = se_eng
            raw5 = _searx_request(p5)
            print(f"[searx-pass5] raw={len(raw5)} site='{site}'")
            # Temporarily cap per-site additions by slicing before filter to reduce overhead
            if isinstance(raw5, list) and per_site > 0:
                raw5 = raw5[:max(per_site, 0)]
            _filter_and_append(raw5, allow_short=True, permissive=True, must_match_terms=(cn_must_match_terms or None))
            used += 1

    rawf_relax_domain: List[Dict] = []
    # Final fallback: unfiltered top N results (only dedup + allowed domain)
    if len(results) == 0:
        if AGENT_DEBUG_LOG:
            print("[searx-fallback] no results after all passes; returning top unfiltered hits")
        pf = { 'q': q, 'format': 'json' }
        if se_eng:
            pf['engines'] = se_eng
        rawf = _searx_request(pf)
        rawf_relax_domain = rawf or []
        for r in rawf:
            if len(results) >= collect_cap:
                break
            title = (r.get('title') or '').strip()
            url = r.get('url') or ''
            if not title or not url:
                continue
            if not is_allowed(url):
                continue
            nt = norm_title(title)
            if nt in seen_titles or url in seen_urls:
                continue
            cand = {'title': title, 'url': url, 'content': (r.get('content') or '').strip()}
            if not _is_company_related(cand):
                continue
            results.append(cand)
            seen_titles.add(nt)
            seen_urls.add(url)

    # Extra fallback: when still 0, try minimal general engines explicitly.
    # NOTE: For CN/A-share context this tends to introduce foreign/noise, so we skip it.
    if (not cn_context) and len(results) == 0 and general_eng:
        try:
            _SEARX_FILTER_METRICS['requery_general_engines'] = _SEARX_FILTER_METRICS.get('requery_general_engines', 0) + 1
            pg = {
                'q': q,
                'format': 'json',
                'categories': 'general',
                'time_range': os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month'),
                'engines': general_eng
            }
            rawg = _searx_request(pg)
            if AGENT_DEBUG_LOG:
                print(f"[searx-fallback-general] raw={len(rawg)} engines='{general_eng}'")
            _filter_and_append(rawg, allow_short=True, permissive=True, must_match_terms=(cn_must_match_terms or None))
        except Exception as _ge:
            if AGENT_DEBUG_LOG:
                print(f"[searx-fallback-general] failed: {_ge}")

    # Pass 6: Low-quality results -> rewrite query (LLM if available) and requery once
    # Inserted before DB blend/fallback to improve web recall/quality first.
    try:
        if _should_llm_requery(results):
            _SEARX_FILTER_METRICS['requery_low_quality'] = _SEARX_FILTER_METRICS.get('requery_low_quality', 0) + 1
            m0 = _low_quality_metrics(results)
            print(f"[searx-quality] low quality detected metrics={m0}")

            rq_candidates: List[str] = []
            try:
                rq_candidates = _llm_rewrite_queries()
            except Exception:
                rq_candidates = []
            if not rq_candidates:
                rq_single = _llm_rewrite_query() or _rule_rewrite_query()
                if rq_single:
                    rq_candidates = [rq_single]
            else:
                # Ensure a deterministic rule-based candidate exists as fallback
                rb = _rule_rewrite_query()
                if rb and all((rb.lower() != x.lower()) for x in rq_candidates):
                    rq_candidates.append(rb)

            tried = 0
            for rq in rq_candidates[:3]:
                if not rq:
                    continue
                tried += 1
                _SEARX_FILTER_METRICS['requery_llm_rewrite'] = _SEARX_FILTER_METRICS.get('requery_llm_rewrite', 0) + 1
                p6 = {
                    'q': rq,
                    'format': 'json',
                    'time_range': os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month')
                }
                # Use CJK engines for CN context even if rq is non-CJK; for EN alias queries allow a separate engine set.
                _p6_eng = se_eng if _has_cjk(rq) else (se_eng_cjk if cn_context else se_eng_en)
                if _p6_eng:
                    p6['engines'] = _p6_eng
                if cn_context:
                    p6['language'] = os.getenv('SEARXNG_LANGUAGE_CJK_DEFAULT', 'zh-CN').strip()
                raw6 = _searx_request(p6)
                print(f"[searx-pass6] raw={len(raw6)} rq='{rq[:120]}'")
                mm_terms = (cn_must_match_terms or None)
                if mm_terms is None and not _has_cjk(rq):
                    mm_terms = _build_must_match_terms(rq)
                _filter_and_append(raw6, allow_short=True, permissive=True, must_match_terms=mm_terms)

                # Optional small boost for official disclosure sites
                if len(results) < max_results and os.getenv('SEARXNG_REWRITE_SITE_BOOST', '1') == '1':
                    boost_sites = [s.strip() for s in os.getenv('SEARXNG_REWRITE_BOOST_SITES', 'cninfo.com.cn,sse.com.cn,szse.cn').split(',') if s.strip()]
                    for site in boost_sites[:3]:
                        if len(results) >= max_results:
                            break
                        _SEARX_FILTER_METRICS['requery_rewrite_sites'] = _SEARX_FILTER_METRICS.get('requery_rewrite_sites', 0) + 1
                        p6s = {
                            'q': f"{rq} site:{site}",
                            'format': 'json',
                            'time_range': os.getenv('SEARXNG_TIME_RANGE_RELAX', 'month')
                        }
                        _p6s_eng = se_eng if _has_cjk(rq) else (se_eng_cjk if cn_context else se_eng_en)
                        if _p6s_eng:
                            p6s['engines'] = _p6s_eng
                        if cn_context:
                            p6s['language'] = os.getenv('SEARXNG_LANGUAGE_CJK_DEFAULT', 'zh-CN').strip()
                        raw6s = _searx_request(p6s)
                        print(f"[searx-pass6b] raw={len(raw6s)} site='{site}'")
                        mm_terms_s = (cn_must_match_terms or None)
                        if mm_terms_s is None and not _has_cjk(rq):
                            mm_terms_s = _build_must_match_terms(rq)
                        _filter_and_append(raw6s, allow_short=True, permissive=True, must_match_terms=mm_terms_s)

                if len(results) >= max_results:
                    break
    except Exception as _rq_err:
        print(f"[searx-quality] requery path error: {_rq_err}")

    # Absolute last resort: if still empty after Pass6, relax domain blacklist.
    # This prevents 0 results but keeps community/Q&A pages from blocking rewrite attempts.
    if len(results) == 0 and rawf_relax_domain:
        _SEARX_FILTER_METRICS['fallback_relaxed_domain'] = _SEARX_FILTER_METRICS.get('fallback_relaxed_domain', 0) + 1
        for r in rawf_relax_domain:
            if len(results) >= collect_cap:
                break
            title = (r.get('title') or '').strip()
            url = (r.get('url') or '').strip()
            if not title or not url:
                continue
            # Keep TLD block to avoid cross-region noise
            d = domain_of(url)
            tld = d.split('.')[-1] if d else ''
            if tld in block_tlds:
                continue
            nt = norm_title(title)
            if nt in seen_titles or url in seen_urls:
                continue
            cand = {'title': title, 'url': url, 'content': (r.get('content') or '').strip()}
            if not _is_company_related(cand):
                continue
            results.append(cand)
            seen_titles.add(nt)
            seen_urls.add(url)

    # 可选：将 DB 中的最近入库文章与 SearXNG 结果进行“融合”，用于更稳定的新闻输入
    # 启用方式：AGENT_DB_BLEND=1；控制融合最多条数：AGENT_DB_BLEND_MAX（默认 5）
    try_db_blend = (os.getenv('AGENT_DB_BLEND', '0') == '1')
    if try_db_blend and symbol:
        try:
            url_api = f"{API_BASE}/api/news/articles"
            # 获取最近文章，优先含正文，按 published_at desc
            blend_max = int(os.getenv('AGENT_DB_BLEND_MAX', '5'))
            params_db = {
                'symbol': symbol,
                'limit': str(max(blend_max, 1)),
                'include_content': 'true'
            }
            rdb = _request_with_retry('get', url_api, params=params_db, timeout=_HTTP_TIMEOUT_DB)
            if rdb.status_code == 200:
                jdb = rdb.json() or {}
                arts = jdb.get('articles') or []
                blended = 0
                for a in arts:
                    if len(results) >= max_results:
                        break
                    t = (a.get('title') or '').strip()
                    u = (a.get('url') or '').strip()
                    if not t or not u:
                        continue
                    nt = norm_title(t)
                    if nt in seen_titles or u in seen_urls:
                        continue
                    content = (a.get('content') or a.get('summary') or '').strip()
                    if len(content) < int(os.getenv('DB_FALLBACK_MIN_CONTENT', '20')):
                        continue
                    results.append({'title': t, 'url': u, 'content': content})
                    seen_titles.add(nt)
                    seen_urls.add(u)
                    blended += 1
                if blended > 0:
                    print(f"[db-blend] 融合了 {blended} 条 DB 文章")
            else:
                print(f"[db-blend] API {url_api} status={rdb.status_code} body={rdb.text[:200] if hasattr(rdb,'text') else ''}")
        except Exception as e_db:
            print(f"[db-blend] 融合失败: {e_db}")

    # 回退：若 SearXNG 仍然很少或 0，则尝试从后端 API 拉取最近入库文章
    try_db_fallback = (os.getenv('AGENT_DB_FALLBACK', '1') == '1')
    min_before_db = int(os.getenv('AGENT_DB_FALLBACK_TRIGGER', '3'))
    if try_db_fallback and symbol and len(results) < min_before_db:
        try:
            _SEARX_FILTER_METRICS['db_fallback_try'] += 1
            url_api = f"{API_BASE}/api/news/articles"
            params_db = {
                'symbol': symbol,
                'limit': str(max_results),
                'include_content': 'true'
            }
            rdb = _request_with_retry('get', url_api, params=params_db, timeout=_HTTP_TIMEOUT_DB)
            if rdb.status_code == 200:
                jdb = rdb.json() or {}
                arts = jdb.get('articles') or []
                added = 0
                for a in arts:
                    if len(results) >= max_results:
                        break
                    t = (a.get('title') or '').strip()
                    u = (a.get('url') or '').strip()
                    if not t or not u:
                        continue
                    nt = norm_title(t)
                    if nt in seen_titles or u in seen_urls:
                        continue
                    content = (a.get('content') or a.get('summary') or '').strip()
                    # 仅在内容最少有一些文本时纳入，避免再次触发空信息
                    if len(content) < int(os.getenv('DB_FALLBACK_MIN_CONTENT', '20')):
                        continue
                    results.append({'title': t, 'url': u, 'content': content})
                    seen_titles.add(nt)
                    seen_urls.add(u)
                    added += 1
                if added > 0:
                    _SEARX_FILTER_METRICS['db_fallback_added'] = _SEARX_FILTER_METRICS.get('db_fallback_added', 0) + added
                    if AGENT_DEBUG_LOG:
                        print(f"[db-fallback] 从 DB 加载了 {added} 条文章作为回退")
            else:
                if AGENT_DEBUG_LOG:
                    print(f"[db-fallback] API {url_api} status={rdb.status_code} body={rdb.text[:200] if hasattr(rdb,'text') else ''}")
        except Exception as e_db:
            if AGENT_DEBUG_LOG:
                print(f"[db-fallback] 失败: {e_db}")

    # 直接API最终兜底 - 当SearXNG和DB都失败后的最后尝试
    if DIRECT_API_AVAILABLE and DIRECT_API_ENABLED and len(results) < int(os.getenv('AGENT_ENSURE_MIN_NEWS', '5')):
        try:
            _SEARX_FILTER_METRICS['direct_api_fallback_try'] = _SEARX_FILTER_METRICS.get('direct_api_fallback_try', 0) + 1
            print(f"[direct-api-fallback] SearXNG和DB结果不足({len(results)}条)，尝试直接API兜底")
            
            stock_code = symbol.replace('.SH', '').replace('.SZ', '').replace('.BJ', '') if symbol else None
            stock_name = query.split()[0] if query and ' ' in query else query
            
            # 获取行业新闻作为补充
            api = get_direct_api()
            industry_news = []
            try:
                industry_news = api.fetch_eastmoney_industry_news(limit=5)
            except Exception:
                pass
            
            # 合并直接新闻
            direct_news = fetch_news_direct(
                stock_code=stock_code,
                stock_name=stock_name,
                industry=None,
                limit=10
            )
            all_direct = direct_news + industry_news
            
            added = 0
            for r in all_direct:
                if len(results) >= max_results:
                    break
                t = (r.get('title') or '').strip()
                u = (r.get('url') or '').strip()
                if not t or not u:
                    continue
                nt = norm_title(t)
                if nt in seen_titles or u in seen_urls:
                    continue
                content = (r.get('content') or r.get('summary') or '').strip()
                results.append({'title': t, 'url': u, 'content': content})
                seen_titles.add(nt)
                seen_urls.add(u)
                added += 1
            
            if added > 0:
                _SEARX_FILTER_METRICS['direct_api_fallback_added'] = _SEARX_FILTER_METRICS.get('direct_api_fallback_added', 0) + added
                print(f"[direct-api-fallback] 兜底添加 {added} 条新闻")
        except Exception as e_direct_fb:
            print(f"[direct-api-fallback] 异常: {e_direct_fb}")

    # Extreme fallback: if still below minimum, try DB search again (ensure) before ignoring filters
    ensure_min = int(os.getenv('AGENT_ENSURE_MIN_NEWS', '5'))
    if ensure_min > 0 and len(results) < ensure_min:
        print(f"[ensure] current={len(results)} < ensure_min={ensure_min}; trying DB ensure...")
        # DB ensure with both query and symbol as keywords
        try:
            ensure_added = 0
            min_len_ensure = int(os.getenv('AGENT_DB_ENSURE_MIN_CONTENT', '40'))
            for qkw in [query, symbol]:
                if not qkw:
                    continue
                if len(results) >= ensure_min:
                    break
                try:
                    url_api = f"{API_BASE}/api/news/search_db"
                    params_db = {
                        'query': qkw,
                        'limit': str(max(0, ensure_min - len(results))),
                        'days': os.getenv('AGENT_DB_ENSURE_DAYS', '60'),
                        'include_content': 'true'
                    }
                    rdb = _request_with_retry('get', url_api, params=params_db, timeout=_HTTP_TIMEOUT_DB)
                    if rdb.status_code == 200:
                        jdb = rdb.json() or {}
                        arts = jdb.get('articles') or []
                        for a in arts:
                            if len(results) >= ensure_min:
                                break
                            t = (a.get('title') or '').strip()
                            u = (a.get('url') or '').strip()
                            if not t or not u:
                                continue
                            nt = (re.sub(r"[\s\-_|·【】\[\]（）()]+", " ", t).lower()).strip()
                            if nt in seen_titles or u in seen_urls:
                                continue
                            content = (a.get('content') or a.get('summary') or '').strip()
                            if len(content) < min_len_ensure:
                                continue
                            results.append({'title': t, 'url': u, 'content': content})
                            seen_titles.add(nt)
                            seen_urls.add(u)
                            ensure_added += 1
                    else:
                        print(f"[ensure] DB API {url_api} status={rdb.status_code}")
                except Exception as _db_ens_err:
                    print(f"[ensure] DB ensure failed: {_db_ens_err}")
            if ensure_added > 0:
                _SEARX_FILTER_METRICS['db_ensure_added'] = _SEARX_FILTER_METRICS.get('db_ensure_added', 0) + ensure_added
                print(f"[ensure] added {ensure_added} from DB ensure")
        except Exception as _ens_e:
            print(f"[ensure] ensure path error: {_ens_e}")
    # Extreme fallback: if still below minimum, ignore domain/CJK filters to guarantee data
    if ensure_min > 0 and len(results) < ensure_min:
        _SEARX_FILTER_METRICS['extreme_fallback'] += 1
        print(f"[searx-extreme] ensuring at least {ensure_min} items (current={len(results)})")
        tried_queries = []
        def _ascii_letter_ratio_local(t: str) -> float:
            try:
                tt = re.sub(r"\s+", "", (t or ""))
                if not tt:
                    return 0.0
                letters = sum(1 for ch in tt if ('A' <= ch <= 'Z') or ('a' <= ch <= 'z'))
                return letters / max(1, len(tt))
            except Exception:
                return 0.0

        max_ascii_ratio_extreme = float(os.getenv('AGENT_EXTREME_MAX_ASCII_RATIO', '0.35'))
        # Try with the most informative first, then simpler variants
        for qx in [q, query, (symbol or '')]:
            if not qx or qx in tried_queries:
                continue
            tried_queries.append(qx)
            pxf = { 'q': qx, 'format': 'json' }
            if se_eng:
                pxf['engines'] = se_eng
            rawx = _searx_request(pxf)
            for r in rawx:
                if len(results) >= ensure_min:
                    break
                title = (r.get('title') or '').strip()
                url = (r.get('url') or '').strip()
                if not title or not url:
                    continue
                # Even in extreme fallback, keep minimal quality & CN-only constraints.
                if not is_allowed(url):
                    continue
                if any(pat in title for pat in blocked_title_patterns):
                    continue
                content = (r.get('content') or '').strip()
                if _has_japanese_kana(title) or _has_japanese_kana(content):
                    continue
                # Avoid foreign / pure-English fragments
                if _ascii_letter_ratio_local(title) >= max_ascii_ratio_extreme or _ascii_letter_ratio_local(content) >= max_ascii_ratio_extreme:
                    continue
                # Enforce basic CJK density for CN/A-share context (avoid unrelated foreign pages)
                if cn_context:
                    if cjk_count(title) < min_cjk_title and cjk_count(content) < min_cjk_any:
                        continue
                nt = norm_title(title)
                if nt in seen_titles or url in seen_urls:
                    continue
                cand = {'title': title, 'url': url, 'content': content}
                # If symbol is known, enforce company-relatedness even in fallback.
                if symbol and not _is_company_related(cand):
                    continue
                results.append(cand)
                seen_titles.add(nt)
                seen_urls.add(url)
            if len(results) >= ensure_min:
                break
        # As a last resort, synthesize a placeholder item if still below minimum（默认禁用）
        allow_synth = os.getenv('AGENT_ALLOW_SYNTHETIC_NEWS', '0') == '1'
        if allow_synth and len(results) < ensure_min:
            try:
                from urllib.parse import quote_plus as _qp
            except Exception:
                _qp = None
            placeholder_q = query or (symbol or 'A股')
            # 使用 about:placeholder 方案，避免暴露本地/内部链接
            placeholder_url = f"about:placeholder:{placeholder_q}"
            ph_title = f"{placeholder_q} 信息有限（临时占位）"
            ph_content = "系统暂未检索到可用新闻，将在后台继续补充数据。"
            print("[searx-placeholder] injecting synthetic news item to guarantee data")
            results.append({
                'title': ph_title,
                'url': placeholder_url,
                'content': ph_content,
                'is_placeholder': True,
                'source': 'placeholder'
            })
    # 富化：使用 NewsProcessor 抓取正文，减少 content 为空的情况
    enrich_on = os.getenv('AGENT_NEWS_ENRICH', '1') == '1'
    # 在富化前，若仍未达到 ensure_min，尝试使用后端富集接口进行最后兜底（可合成占位）
    try_backend_fallback = (os.getenv('AGENT_USE_BACKEND_ENRICHED_FALLBACK', '1') == '1')
    if try_backend_fallback and ensure_min > 0 and len(results) < ensure_min and symbol:
        try:
            need = max(0, ensure_min - len(results))
            if need > 0:
                params = {
                    'limit': str(need),
                    'days': os.getenv('AGENT_ENRICHED_DAYS', '7'),
                    'ensure_min': str(need),
                    'fallback_days': os.getenv('AGENT_ENRICHED_FALLBACK_DAYS', '120'),
                    'include_content': 'true',
                    'min_content': os.getenv('AGENT_ENRICHED_MIN_CONTENT', '0'),
                    'trigger_topup': 'true',
                    'wait_seconds': os.getenv('AGENT_BACKEND_FALLBACK_WAIT_SECONDS', '3'),
                    'allow_placeholder': 'false'
                }
                url_be = f"{API_BASE}/api/news/company_enriched/{symbol}"
                rbe = _request_with_retry('get', url_be, params=params, timeout=_HTTP_TIMEOUT_ENRICHED)
                if rbe.status_code == 200:
                    jbe = rbe.json() or {}
                    arts = (jbe.get('articles') or [])
                    added = 0
                    for a in arts:
                        if len(results) >= ensure_min:
                            break
                        t = (a.get('title') or '').strip()
                        u = (a.get('url') or '').strip()
                        if not t or not u:
                            continue
                        nt = (re.sub(r"[\s\-_|·【】\[\]（）()]+", " ", t).lower()).strip()
                        if nt in seen_titles or u in seen_urls:
                            continue
                        content = (a.get('content') or a.get('summary') or '').strip()
                        results.append({'title': t, 'url': u, 'content': content})
                        seen_titles.add(nt)
                        seen_urls.add(u)
                        added += 1
                    if added > 0:
                        _SEARX_FILTER_METRICS['backend_enriched_fallback_added'] = _SEARX_FILTER_METRICS.get('backend_enriched_fallback_added', 0) + added
                        if AGENT_DEBUG_LOG:
                            print(f"[backend-fallback] enriched 补齐 {added} 条 (need={need})")
                else:
                    if AGENT_DEBUG_LOG:
                        print(f"[backend-fallback] {url_be} status={rbe.status_code} body={rbe.text[:180] if hasattr(rbe,'text') else ''}")
        except Exception as _be_err:
            if AGENT_DEBUG_LOG:
                print(f"[backend-fallback] 异常: {_be_err}")

    # 兜底：默认不合成占位条目。占位条目会在 LLM 分析前被过滤，容易导致
    # news_count>0 但 item_count==0，进而触发“信息不足/no-news”。
    if ensure_min > 0 and len(results) < ensure_min and os.getenv('AGENT_FINAL_PLACEHOLDER', '0') == '1':
        missing = ensure_min - len(results)
        try:
            from urllib.parse import quote_plus as _qp
        except Exception:
            _qp = None
        base_q = query or (symbol or 'A股')
        for i in range(missing):
            ph_title = f"{base_q} 信息有限（临时占位 {i+1}/{missing}）"
            # 改为 about:placeholder，避免出现 localhost 链接
            ph_url = f"about:placeholder:{base_q}:{i}"
            ph_content = "系统将继续补充信息；建议关注公司公告、财报与交易数据。"
            results.append({'title': ph_title, 'url': ph_url, 'content': ph_content, 'is_placeholder': True, 'source': 'placeholder'})

    # Final rerank: prioritize announcements/news; keep quote/data pages as last resort
    if results:
        try:
            results = _finalize_results()
        except Exception as _rk_err:
            print(f"[searx-rerank] failed: {_rk_err}")

    if enrich_on and results and NewsProcessor is not None:
        try:
            def _enrich_sync(raw_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                async def _runner() -> List[Dict[str, Any]]:
                    np = NewsProcessor()  # NewsProcessor 在 __init__ 中对 DB 失败有降级保护
                    out: List[Dict[str, Any]] = []
                    sem = asyncio.Semaphore(int(os.getenv('NEWS_ENRICH_CONCURRENCY', '4')))

                    async def _one(r: Dict[str, Any]):
                        title = (r.get('title') or '').strip()
                        url = (r.get('url') or '').strip()
                        content = (r.get('content') or '').strip()
                        if not url or not title:
                            return None
                        # 若已有较长内容则跳过抓取
                        if content and len(content) >= int(os.getenv('NEWS_ENRICH_EXISTING_MIN', '40')):
                            return {'title': title, 'url': url, 'content': content}
                        # 过滤非文章型 URL，避免抓取列表/JS 门户
                        try:
                            if hasattr(np, '_is_article_like_url') and not np._is_article_like_url(url):
                                return None
                        except Exception:
                            pass
                        async with sem:
                            try:
                                soup = await np._fetch_soup(url)
                                full = await np._extract_content(url, soup)
                                if full and len(full) >= int(os.getenv('NEWS_ENRICH_MIN_LEN', '60')):
                                    return {'title': title, 'url': url, 'content': full}
                            except Exception:
                                return None
                        # 抓取失败则保留原内容
                        return {'title': title, 'url': url, 'content': content}

                    tasks = [_one(r) for r in raw_list[:max_results]]
                    res = await asyncio.gather(*tasks, return_exceptions=True)
                    for x in res:
                        if isinstance(x, dict):
                            out.append(x)
                    return out

                return asyncio.run(_runner())

            enriched = _enrich_sync(results)
            # 保持返回数量与顺序（若富化过程中某些被判定为非文章而丢弃，则保留原条目兜底）
            if enriched:
                # 构建 URL 映射，尽量用富化后的正文替换
                m = {e['url']: e for e in enriched if isinstance(e, dict) and e.get('url')}
                merged: List[Dict[str, Any]] = []
                for r in results[:max_results]:
                    u = r.get('url')
                    if u in m:
                        merged.append(m[u])
                    else:
                        merged.append(r)
                results = merged
        except Exception as _enrich_err:
            print(f"[news-enrich] 富化流程失败: {_enrich_err}")
    # 写入缓存
    if SEARX_CACHE_TTL > 0:
        _SEARX_CACHE[cache_key] = (time.time(), results[:max_results])
    return results[:max_results]
def _invoke_llm(prompt: str, temperature: float = 0.7) -> str:
    """调用 LLM 进行文本生成或补全。
    优先使用 Azure OpenAI，若失败则尝试通用 OpenAI 接口（如果配置了 LLM_API_URL）。
    """
    global HAS_AZURE, AZURE_USE_RESPONSES, _AZURE_LAST_ERROR, _AZURE_FAIL_COUNT, _CHAT_EMPTY_COUNT, _FORCE_NO_RESPONSE_FORMAT, USE_LLM
    # Azure OpenAI 处理
    if HAS_AZURE and os.getenv("AGENT_DISABLE_AZURE") != '1':
        try:
            # 新版 Responses API 优先（修正为 /openai/responses 且按新参数命名）
            if AZURE_USE_RESPONSES:
                url = AZURE_OPENAI_ENDPOINT.rstrip('/') + "/openai/responses"
                params = {"api-version": AZURE_OPENAI_API_VERSION}
                # 官方推荐使用 Authorization: Bearer；与 chat 接口区分
                headers = {"Authorization": f"Bearer {AZURE_OPENAI_KEY}", "Content-Type": "application/json"}
                # payload 使用 input + max_output_tokens + model（传入部署名）
                try:
                    max_comp = int(os.getenv("AZURE_OPENAI_MAX_COMPLETION_TOKENS", "1024"))
                except Exception:
                    max_comp = 1024
                # 限制单次输出上限，避免过大
                max_out = max(256, min(max_comp, 4096))
                payload = {
                    "model": AZURE_OPENAI_DEPLOYMENT,
                    "input": prompt,
                    "max_output_tokens": max_out
                }
                # 当严格 JSON 开启时，提示使用 JSON 输出格式（Responses 支持 text.format）
                if AGENT_STRICT_JSON and not _FORCE_NO_RESPONSE_FORMAT:
                    payload["text"] = {"format": {"type": "json_object"}}
                resp = requests.post(url, params=params, headers=headers, json=payload, timeout=180)
                if resp.status_code in (400,404):
                    try:
                        print(f"[llm] Responses {resp.status_code}: {resp.text[:300]}")
                        _AZURE_LAST_ERROR = resp.text[:2000]
                        _AZURE_FAIL_COUNT += 1
                    except Exception:
                        pass
                    if resp.status_code == 404:
                        # 环境不支持 /responses，永久关闭本次进程的 Responses 尝试
                        AZURE_USE_RESPONSES = False
                resp.raise_for_status()
                data = resp.json()
                if AGENT_DEBUG_LOG:
                    print(f"[llm-debug] responses json keys={list(data.keys())} fail_count={_AZURE_FAIL_COUNT}")
                if isinstance(data, dict):
                    # 官方示例常见结构： data['output'][0]['content'][*]{type, text}
                    out_list = data.get('output') or data.get('responses') or []
                    if isinstance(out_list, list):
                        for seg in out_list:
                            if not isinstance(seg, dict):
                                continue
                            content_blocks = seg.get('content')
                            # content 可能是 list / dict / str，统一归一化
                            if isinstance(content_blocks, dict):
                                content_blocks = [content_blocks]
                            elif isinstance(content_blocks, str):
                                if content_blocks.strip():
                                    return content_blocks
                                content_blocks = []
                            elif content_blocks is None:
                                content_blocks = []

                            if isinstance(content_blocks, list):
                                for block in content_blocks:
                                    if isinstance(block, str) and block.strip():
                                        return block
                                    if isinstance(block, dict):
                                        # 常见：{type:'output_text', text:'...'} 或 {type:'text', text:'...'}
                                        if block.get('type') in ('output_text', 'text', 'message'):
                                            t = block.get('text') or block.get('output_text')
                                            if isinstance(t, str) and t.strip():
                                                return t
                                        # 兜底：若直接包含 text 字段
                                        t2 = block.get('text')
                                        if isinstance(t2, str) and t2.strip():
                                            return t2
                    # 兼容 output_text 聚合字段
                    ot = data.get('output_text')
                    if isinstance(ot, str) and ot.strip():
                        return ot
                    if isinstance(ot, list) and ot:
                        first = ot[0]
                        if isinstance(first, str):
                            return first
                        if isinstance(first, dict):
                            t3 = first.get('text') or first.get('output_text')
                            if isinstance(t3, str) and t3.strip():
                                return t3
        except Exception as e:
            _AZURE_LAST_ERROR = str(e)
            _AZURE_FAIL_COUNT += 1
            if AGENT_DEBUG_LOG:
                print(f"[llm] Responses 调用失败: {e}")
        # Chat fallback
        if _AZURE_FAIL_COUNT < 3 and os.getenv("AGENT_DISABLE_AZURE") != '1':  # 只在失败不多时尝试 Chat
            try:
                url = AZURE_OPENAI_ENDPOINT.rstrip('/') + f"/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions"
                params = {"api-version": AZURE_OPENAI_API_VERSION}
                headers = {"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"}
                # 构造消息，并在严格 JSON 模式下明确加入包含 'json' 的 system 指令以满足 Azure 要求
                messages = [{"role": "user", "content": prompt}]
                if AGENT_STRICT_JSON:
                    messages = [
                        {"role": "system", "content": "你现在处于严格 JSON 输出模式。务必只输出一个 JSON 对象(json)，不要添加任何解释、注释、反引号、语言标记或额外文本。Return json only. Output exactly one json object with no extra text."},
                        {"role": "user", "content": prompt}
                    ]
                payload = {
                    "messages": messages,
                    # tokens 参数：对 gpt-5/gpt-o 等新模型统一使用 max_completion_tokens，
                    # 以避免 "Unsupported parameter: 'max_tokens'" 错误。
                }
                max_tok = int(os.getenv("AZURE_OPENAI_MAX_COMPLETION_TOKENS", "2048"))
                # 始终优先使用 max_completion_tokens；部分旧模型若不支持，将由下方错误处理分支兜底。
                payload["max_completion_tokens"] = max_tok
                if AGENT_STRICT_JSON and not _FORCE_NO_RESPONSE_FORMAT:
                    # new API supports explicit JSON mode
                    payload["response_format"] = {"type": "json_object"}
                resp = requests.post(url, params=params, headers=headers, json=payload, timeout=60)
                if resp.status_code == 400:
                    body = resp.text[:500]
                    print(f"[llm] Chat 400: {body}")
                    _AZURE_LAST_ERROR = body
                    _AZURE_FAIL_COUNT += 1
                resp.raise_for_status()
                data = resp.json()
                print(f"[llm-debug] chat json keys={list(data.keys())} fail_count={_AZURE_FAIL_COUNT}")
                if isinstance(data, dict) and data.get("choices"):
                    first_choice = (data.get("choices") or [{}])[0]
                    msg = first_choice.get("message", {})
                    txt = msg.get("content") or ""
                    finish_reason = first_choice.get("finish_reason") or ""
                    if not txt:
                        try:
                            _CHAT_EMPTY_COUNT += 1
                        except Exception:
                            pass
                        # 打印更多调试信息便于定位空内容的原因
                        try:
                            print("[llm-debug] empty content; first choice snippet:", json.dumps(first_choice, ensure_ascii=False)[:400])
                        except Exception:
                            pass
                        # 若因为内容过滤导致 finish_reason=content_filter，优先关闭 response_format 再试
                        if str(finish_reason).lower() == 'content_filter':
                            try:
                                if 'response_format' in payload:
                                    payload.pop('response_format', None)
                                print("[llm-debug] finish_reason=content_filter -> retry without response_format")
                                payload_cf = dict(payload)
                                resp_cf = requests.post(url, params=params, headers=headers, json=payload_cf, timeout=60)
                                resp_cf.raise_for_status()
                                data_cf = resp_cf.json()
                                msg_cf = (data_cf.get('choices') or [{}])[0].get('message', {})
                                txt = msg_cf.get('content') or ''
                            except Exception as e_cf:
                                print(f"[llm-debug] content_filter retry failed: {e_cf}")
                    # If content unexpectedly empty, try a second call without response_format JSON to bypass filters
                    if not txt and payload.get("response_format") is not None:
                        try:
                            pf = payload.pop("response_format", None)
                            print("[llm-debug] chat empty content, retrying without response_format ...")
                            resp2 = requests.post(url, params=params, headers=headers, json=payload, timeout=60)
                            resp2.raise_for_status()
                            data2 = resp2.json()
                            msg2 = (data2.get("choices") or [{}])[0].get("message", {})
                            txt = msg2.get("content") or ""
                        except Exception as _e_no_rf:
                            print(f"[llm-debug] retry without response_format failed: {_e_no_rf}")
                        finally:
                            if pf is not None:
                                payload["response_format"] = pf
                    # 进一步降级：移除严格 system 指令，仅用用户提示词再试一次（无 response_format）
                    if not txt and AGENT_STRICT_JSON:
                        try:
                            print("[llm-debug] empty again -> retry with user-only message, no system, no response_format")
                            messages_min = [{"role":"user","content": prompt}]
                            payload_min = {
                                "messages": messages_min
                            }
                            # 统一使用 max_completion_tokens，避免新模型对 max_tokens 的限制
                            payload_min["max_completion_tokens"] = max_tok
                            resp_min = requests.post(url, params=params, headers=headers, json=payload_min, timeout=60)
                            resp_min.raise_for_status()
                            data_min = resp_min.json()
                            msg_min = (data_min.get('choices') or [{}])[0].get('message', {})
                            txt = msg_min.get('content') or ''
                        except Exception as e_min:
                            # Try print body if available
                            try:
                                if hasattr(e_min, 'response') and getattr(e_min, 'response') is not None:
                                    print(f"[llm-debug] user-only retry 400 body: {getattr(e_min,'response').text[:400]}")
                            except Exception:
                                pass
                            print(f"[llm-debug] user-only retry failed: {e_min}")
                    # After repeated empties, stop sending response_format for the rest of process
                    if not txt and _CHAT_EMPTY_COUNT >= 2:
                        try:
                            print("[llm-debug] consecutive empty contents, disabling response_format for this process")
                            _FORCE_NO_RESPONSE_FORMAT = True
                        except Exception:
                            pass
                    # 兼容降级：若仍为空且为 2025- 预览版，尝试使用较旧 API 版本一次
                    if not txt and AZURE_OPENAI_API_VERSION.startswith("2025-"):
                        try:
                            alt_api_ver = os.getenv("AZURE_CHAT_FALLBACK_VERSION", "2024-02-15-preview")
                            alt_params = {"api-version": alt_api_ver}
                            alt_payload = {
                                "messages": messages,
                                # 统一使用 max_completion_tokens，避免新模型报错
                                "max_completion_tokens": max_tok
                            }
                            if AGENT_DEBUG_LOG:
                                print(f"[llm-debug] fallback chat using api-version={alt_api_ver} ...")
                            resp3 = requests.post(url, params=alt_params, headers=headers, json=alt_payload, timeout=60)
                            resp3.raise_for_status()
                            data3 = resp3.json()
                            msg3 = (data3.get("choices") or [{}])[0].get("message", {})
                            txt = msg3.get("content") or ""
                            if not txt:
                                try:
                                    print("[llm-debug] alt-version still empty; snippet:", json.dumps((data3.get('choices') or [{}])[0], ensure_ascii=False)[:400])
                                except Exception:
                                    pass
                        except Exception as alt_e:
                            try:
                                if hasattr(alt_e, 'response') and getattr(alt_e, 'response') is not None:
                                    print(f"[llm-debug] alt-version 400 body: {getattr(alt_e,'response').text[:400]}")
                            except Exception:
                                pass
                            print(f"[llm-debug] alt api-version chat failed: {alt_e}")
                    return txt
            except Exception as e:
                _AZURE_LAST_ERROR = str(e)
                _AZURE_FAIL_COUNT += 1
                print(f"[llm] Azure Chat 调用失败: {e}")
        if _AZURE_FAIL_COUNT >= 3:
            # 过多失败，禁用 Azure，后续直接走 fallback
            HAS_AZURE = False
            if not LLM_API_URL:
                USE_LLM = False
            return ""
    # 其次通用 OpenAI 兼容接口（如果提供）
    if LLM_API_URL:
        try:
            payload = {
                "model": os.getenv("LLM_MODEL", "gpt-3.5-turbo"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature
            }
            if AGENT_STRICT_JSON:
                payload["response_format"] = {"type": "json_object"}
            resp = requests.post(LLM_API_URL, json=payload, timeout=120)
            resp.raise_for_status()
            result = resp.json()
            if "choices" in result and result["choices"]:
                return result["choices"][0]["message"]["content"]
            return result.get("text", "")
        except Exception as e:
            print(f"[llm] 通用 LLM_API_URL 调用失败: {e}")
    return ""  # 全部失败 -> 空字符串，后续解析将产生 fallback JSON

def _extract_first_json(text: str) -> Optional[str]:
    """从任意混杂文本中提取第一个顶层 JSON 对象字符串。"""
    if not text:
        return None
    # 快速直接匹配纯 JSON
    text = text.strip()
    if text.startswith('{') and text.endswith('}'):
        return text
    # 逐字符扫描
    stack = []
    start_idx = None
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if ch == '"' and not escape:
            in_str = not in_str
        if in_str and ch == '\\' and not escape:
            escape = True
            continue
        else:
            escape = False
        if in_str:
            continue
        if ch == '{':
            stack.append('{')
            if start_idx is None:
                start_idx = i
        elif ch == '}' and stack:
            stack.pop()
            if not stack and start_idx is not None:
                candidate = text[start_idx:i+1]
                return candidate
    return None

def _extract_all_json(text: str, limit: int = 5) -> List[str]:
    """提取文本中多个顶层 JSON 对象（最多 limit 个）。用于处理模型输出多个/截断片段的情况。"""
    res: List[str] = []
    if not text:
        return res
    text = text.strip()
    # 如果本身就是 JSON 直接返回
    if text.startswith('{') and text.endswith('}'):
        return [text]
    stack = []
    start_idx = None
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if ch == '"' and not escape:
            in_str = not in_str
        if ch == '\\' and not escape:
            escape = True
        else:
            escape = False
        if in_str:
            continue
        if ch == '{':
            if not stack:
                start_idx = i
            stack.append('{')
        elif ch == '}' and stack:
            stack.pop()
            if not stack and start_idx is not None:
                cand = text[start_idx:i+1]
                res.append(cand)
                if len(res) >= limit:
                    break
    return res

def _strip_code_fences(text: str) -> str:
    if not text:
        return text
    # Remove markdown code fences like ```json ... ``` or ``` ... ```
    # Keep only the content; if multiple fences exist, prefer the first block
    try:
        if '```' in text:
            parts = text.split('```')
            # heuristic: if there are 3 parts, middle is content
            if len(parts) >= 3:
                # if first fence specifies language (e.g., ```json), skip it
                inner = parts[1]
                if inner.strip().lower().startswith('json'):
                    inner = inner.split('\n',1)[1] if '\n' in inner else ''
                return inner.strip()
            # otherwise drop all backticks
            return text.replace('```','').strip()
        return text
    except Exception:
        return text

def _remove_trailing_commas(s: str) -> str:
    try:
        import re as _re
        # remove trailing commas before } or ]
        return _re.sub(r",\s*([}\]])", r"\1", s)
    except Exception:
        return s

def _json_loads_lenient(s: str) -> Optional[dict]:
    # Try strict json
    try:
        return json.loads(s)
    except Exception:
        pass
    # try after removing code fences and trailing commas
    try:
        s2 = _strip_code_fences(s)
        s2 = _remove_trailing_commas(s2)
        return json.loads(s2)
    except Exception:
        pass
    # try literal_eval for python-like dicts
    try:
        import ast as _ast
        obj = _ast.literal_eval(s)
        if isinstance(obj, dict):
            # convert any non-JSON types recursively if necessary
            return obj
    except Exception:
        pass
    return None

def _summarize_news_item(item: Dict[str, Any], max_len: int = 260) -> Tuple[str, int, int]:
    """对单条新闻进行简单摘要: 标题 + 内容前 max_len 字符。
    返回: (摘要文本, 原始内容长度, 摘要内容长度) 不包含标题长度在统计中的拆分复杂化处理，统计使用内容部分。
    """
    title = (item.get('title') or '').strip()
    content = (item.get('content') or '').strip().replace('\r',' ')[:4000]  # 先粗裁防极端长
    original_len = len(content)
    if len(content) > max_len:
        content_summary = content[:max_len]
    else:
        content_summary = content
    summary_len = len(content_summary)
    summary_text = f"标题: {title}\n内容: {content_summary}"
    return summary_text, original_len, summary_len


_BASIC_PROFILE_CACHE: Dict[str, Dict[str, Any]] = {}

def _try_fetch_basic_profile(symbol: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fetch basic company profile clues from backend when news is missing.

    This intentionally uses existing backend API (/api/news/basic_profile/{symbol}) to avoid introducing new
    external dependencies or scraping logic inside the agent.
    """
    if not symbol:
        return None
    if os.getenv('AGENT_BASIC_PROFILE_FALLBACK', '1') != '1':
        return None
    sym = (symbol or '').upper().strip()
    if sym and sym in _BASIC_PROFILE_CACHE:
        cached = _BASIC_PROFILE_CACHE.get(sym)
        return cached if isinstance(cached, dict) else None
    try:
        url = f"{API_BASE}/api/news/basic_profile/{symbol}"
        params = {
            'max_results': str(int(os.getenv('AGENT_BASIC_PROFILE_MAX_RESULTS', '6'))),
            'include_crawl': 'true' if os.getenv('AGENT_BASIC_PROFILE_INCLUDE_CRAWL', '0') == '1' else 'false',
        }
        # Default timeout should be conservative: this endpoint may call search engines and can be slow/unreliable.
        r = _request_with_retry('get', url, params=params, timeout=int(os.getenv('AGENT_BASIC_PROFILE_TIMEOUT', '10')))
        if r.status_code == 200:
            j = r.json() or {}
            if isinstance(j, dict) and sym:
                _BASIC_PROFILE_CACHE[sym] = j
            return j if isinstance(j, dict) else None
    except Exception:
        return None
    return None

def _format_basic_profile_hint(bp: Dict[str, Any], max_links: int = 2) -> str:
    try:
        company_name = (bp.get('company_name') or '').strip()
        prof = bp.get('profile_db') or {}
        industry = (prof.get('industry') or '').strip() if isinstance(prof, dict) else ''
        sub_industry = (prof.get('sub_industry') or '').strip() if isinstance(prof, dict) else ''
        biz = (prof.get('business_summary') or '').strip() if isinstance(prof, dict) else ''
        if biz:
            biz = biz[:160] + ('…' if len(biz) > 160 else '')

        links = []
        for r in (bp.get('search_results') or [])[:max(0, max_links)]:
            if not isinstance(r, dict):
                continue
            t = (r.get('title') or '').strip()
            u = (r.get('url') or '').strip()
            if t and u:
                links.append(f"{t} ({u})")
        parts = []
        if company_name:
            parts.append(f"公司: {company_name}")
        if industry:
            parts.append(f"行业: {industry}" + (f" / {sub_industry}" if sub_industry else ''))
        if biz:
            parts.append(f"简介: {biz}")
        if links:
            parts.append("参考链接: " + "；".join(links))
        return " | ".join(parts)
    except Exception:
        return ""

def llm_analyze_news(stock_name: str, news_list: List[Dict], symbol: Optional[str] = None, basic_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # 先过滤明显的占位或无效项，避免影响专业性
    def _is_placeholder(n: Dict[str, Any]) -> bool:
        if n.get('is_placeholder') is True:
            return True
        url = (n.get('url') or '').strip().lower()
        title = (n.get('title') or '').strip()
        content = (n.get('content') or '').strip()
        if url.startswith('about:placeholder'):
            return True
        if '占位' in title or '信息不足' in title or '信息有限' in title:
            return True
        if '占位' in content:
            return True
        # 避免把 localhost/内网链接带入 LLM
        if url.startswith('http://localhost') or url.startswith('https://localhost'):
            return True
        return False
    news_list = [n for n in (news_list or []) if not _is_placeholder(n)]
    # 若无新闻或新闻极少且内容非常短，则直接返回信息不足的结构，避免 LLM 解析回退。
    # 默认阈值偏低，减少因“短但有效”的新闻触发信息不足。
    min_total = int(os.getenv("AGENT_MIN_TOTAL_CONTENT", "30"))
    if not news_list:
        bp = basic_profile if isinstance(basic_profile, dict) else _try_fetch_basic_profile(symbol)
        hint = _format_basic_profile_hint(bp, max_links=0) if isinstance(bp, dict) else ''
        snippet = ''
        if isinstance(bp, dict):
            try:
                crawled = bp.get('crawled_snippets') or []
                if isinstance(crawled, list) and crawled:
                    first = crawled[0] if isinstance(crawled[0], dict) else None
                    snippet = (first.get('snippet') or '').strip() if first else ''
            except Exception:
                snippet = ''
        if snippet:
            snippet = snippet.replace('\r', ' ').replace('\n', ' ').strip()[:220]

        factors: List[Dict[str, Any]] = []
        if hint:
            factors.append({'name': '公司概况', 'direction': '不确定', 'weight': 1.1, 'evidence': hint})
        if snippet:
            factors.append({'name': '资料摘要', 'direction': '不确定', 'weight': 1.0, 'evidence': snippet})
        factors.append({'name': '当日新闻缺失', 'direction': '不确定', 'weight': 0.8, 'evidence': '当日未命中公司相关新闻，已用公司画像/资料线索补充背景信息。'})
        # 保留“信息不足”但不让其主导（validate_stock_json 会限制权重占比）
        factors.append({'name': '信息不足', 'direction': '不确定', 'weight': 0.6, 'evidence': '公开新闻检索未命中，后续可关注公告披露、互动易、业绩预告等官方渠道。'})

        summary_parts = [f"当日未检索到与{stock_name}直接相关的公开新闻，以下为基础资料线索（非新闻）。"]
        if hint:
            summary_parts.append(hint)
        if snippet:
            summary_parts.append(f"摘要: {snippet}")

        return {
            'sentiment_score': 0.0,
            'sentiment_label_en': 'neutral',
            'sentiment_label': '中性',
            'factors': factors,
            'score': 50,
            'need_macro': False,
            'macro_keywords': [],
            'risk_flags': [],
            'correlation_watch': [],
            'confidence': 0.35 if (hint or snippet) else 0.2,
            'summary': '；'.join([p for p in summary_parts if p])[:1200],
            'news_truncation_stats': {'item_count': 0, 'original_chars': 0, 'truncated_chars': 0, 'avg_original_per_item': 0, 'avg_truncated_per_item': 0, 'ratio_truncated': 0, 'max_len_per_item': 260},
            'prompt_token_est': 0
        }
    total_len = sum(len((n.get('content') or '').strip()) + len((n.get('title') or '').strip()) for n in news_list)
    # 当 LLM 不可用时，不走 low-news 的快速返回，让后续启发式继续工作
    allow_low_news_shortcut = True
    try:
        if not USE_LLM:
            allow_low_news_shortcut = False
    except Exception:
        pass
    if allow_low_news_shortcut and total_len < min_total and len(news_list) <= 1:
        return {
            'sentiment_score': 0.0,
            'sentiment_label_en': 'neutral',
            'sentiment_label': '中性',
            'factors': [
                {'name': '信息不足', 'direction': '中性', 'weight': 1.0, 'evidence': '新闻信息量有限，缺乏公司层面事实'}
            ],
            'score': 50,
            'need_macro': False,
            'macro_keywords': [],
            'risk_flags': [],
            'correlation_watch': [],
            'confidence': 0.2,
            'summary': '仅有极少量简讯且缺乏公司层面依据，暂不形成判断。',
            'news_truncation_stats': {'item_count': len(news_list), 'original_chars': total_len, 'truncated_chars': total_len, 'avg_original_per_item': total_len/len(news_list), 'avg_truncated_per_item': total_len/len(news_list), 'ratio_truncated': 0, 'max_len_per_item': 260},
            'prompt_token_est': 0
        }
    # 预摘要新闻，控制长度
    summaries: List[str] = []
    orig_total = 0
    trunc_total = 0
    for n in news_list:
        s, o_len, t_len = _summarize_news_item(n, max_len=180)
        orig_total += o_len
        trunc_total += t_len
        # 不向 LLM 暴露 about:placeholder/localhost 链接
        link = (n.get('url','') or '')
        if link.startswith('about:placeholder') or 'localhost' in link:
            link = ''
        summaries.append(s + (f"\n链接: {link}" if link else ''))
    summarized_text = "\n".join(summaries)
    news_text = summarized_text  # 代替原始长文本
    trunc_stats = {
        'item_count': len(news_list),
        'original_chars': orig_total,
        'truncated_chars': trunc_total,
        'avg_original_per_item': round(orig_total/len(news_list),2) if news_list else 0,
        'avg_truncated_per_item': round(trunc_total/len(news_list),2) if news_list else 0,
        'ratio_truncated': round(trunc_total/max(orig_total,1),4),
    'max_len_per_item': 180
    }
    base_prompt = (
                "你是 A 股量化与基本面混合型研究 Agent。基于以下 {} 的最新新闻，进行结构化分析。\n"
                "输出严格 json（仅一个对象，不要解释），键与类型如下：\n"
                "{{\n"
                "  \"sentiment_score\": float (-1~1),\n"
                "  \"sentiment_label\": \"positive|neutral|negative\",\n"
                "  \"factors\": [{{\"name\": str, \"direction\": \"正面|负面|不确定\", \"weight\": 0~1, \"evidence\": str}}],\n"
                "  \"score\": int (0~100),\n"
                "  \"need_macro\": bool,\n"
                "  \"macro_keywords\": [str],\n"
                "  \"risk_flags\": [str],\n"
                "  \"correlation_watch\": [{{\"metric\": str, \"reason\": str, \"suggest_window\": str}}],\n"
                "  \"confidence\": 0~1,\n"
                "  \"summary\": str\n"
                "}}\n"
                "规则：\n"
                "- factors 数量 3~8，weight 需归一化之和≈1。\n"
                "- need_macro 为 True 条件：出现政策、行业周期、全球因素、汇率、利率、能源、地缘等宏观触发词。\n"
                "- macro_keywords 限 1~5 个，高概括名词（行业/政策/主题）。\n"
                "- correlation_watch 关注短期可验证数据（如 成交量, 北向资金净流入, 订单, ASP, 库存, 产销率, 设备稼动率）。\n"
                "- 如新闻不足，请保持专业中性表达，不涉及系统/占位/内部实现；可用一个简短的‘信息不足’因子，但权重不应主导结论。\n"
                "仅输出 json；若信息不足，也必须输出合法 json（不要写解释性文字）。\n"
                "新闻：\n"
                "{}".format(stock_name, news_text)
        )
    if STRICT_JSON_PREFIX:
        prompt = STRICT_JSON_PREFIX + "\n" + base_prompt
    else:
        prompt = base_prompt
    prompt_char_count = len(prompt)
    prompt_token_est = round(prompt_char_count / 1.5)
    raw = _invoke_llm(prompt)
    parse_mode = None  # 'direct' | 'substring' | 'retry' | 'heuristic'
    parse_error: Optional[str] = None
    if raw:
        if AGENT_DEBUG_LOG:
            print(f"[llm-raw-stock] {stock_name} snippet: {raw[:220].replace('\n',' ')} ...")
    if raw:
        # 统一控制流：direct -> substring -> (strict retry direct -> substring)
        last_error: Optional[Exception] = None
        parsing_attempts = 0
        # 1) direct parse
        try:
            data = _json_loads_lenient(raw)
            if not isinstance(data, dict):
                raise ValueError("not dict")
            factors_ok = isinstance(data.get('factors'), list) and len(data.get('factors')) > 0
            score_ok = data.get('score') is not None
            if factors_ok and score_ok:
                vd = validate_stock_json(data)
                global _PARSE_SUCCESS_STOCK
                _PARSE_SUCCESS_STOCK += 1
                parse_mode = 'direct'
                vd['parsing_attempts'] = 1
                vd['news_truncation_stats'] = trunc_stats
                vd['prompt_token_est'] = prompt_token_est
                # keep internal parse mode for diagnostics only; do not expose in user-facing report
                vd['_parse_mode'] = parse_mode
                return vd
            else:
                if AGENT_DEBUG_LOG:
                    print(f"[fallback-guard] 缺少核心字段 factors_ok={factors_ok} score_ok={score_ok} -> 尝试子串解析")
        except Exception as e:
            last_error = e
        parsing_attempts += 1
        # 2) substring attempt if not already returned
        jfrag = _extract_first_json(raw)
        if jfrag:
            try:
                data2 = _json_loads_lenient(jfrag)
                factors_ok = isinstance(data2.get('factors'), list) and len(data2.get('factors')) > 0
                score_ok = data2.get('score') is not None
                if factors_ok and score_ok:
                    if AGENT_DEBUG_LOG:
                        print("[json-extract] 通过子串提取成功解析 JSON")
                    vd2 = validate_stock_json(data2)
                    _PARSE_SUCCESS_STOCK += 1
                    parse_mode = 'substring'
                    vd2['parsing_attempts'] = parsing_attempts + 1
                    vd2['news_truncation_stats'] = trunc_stats
                    vd2['prompt_token_est'] = prompt_token_est
                    vd2['_parse_mode'] = parse_mode
                    return vd2
            except Exception as e2:
                if AGENT_DEBUG_LOG:
                    print(f"[json-extract] 子串解析仍失败: {e2}")
                last_error = last_error or e2
        parsing_attempts += 1
        # 2b) multi fragments attempt
        multi_frags = _extract_all_json(raw, limit=5)
        if multi_frags and len(multi_frags) > 1:
            for idx, frag in enumerate(multi_frags):
                if jfrag and frag == jfrag:
                    continue  # 已尝试
                try:
                    data_m = _json_loads_lenient(frag)
                    if isinstance(data_m, dict) and isinstance(data_m.get('factors'), list) and data_m.get('score') is not None:
                        if AGENT_DEBUG_LOG:
                            print(f"[json-extract-multi] 第{idx+1}个片段解析成功")
                        vd_m = validate_stock_json(data_m)
                        _PARSE_SUCCESS_STOCK += 1
                        parse_mode = 'multi-substring'
                        vd_m['parsing_attempts'] = parsing_attempts + idx
                        vd_m['news_truncation_stats'] = trunc_stats
                        vd_m['prompt_token_est'] = prompt_token_est
                        vd_m['_parse_mode'] = parse_mode
                        return vd_m
                except Exception as em:
                    last_error = last_error or em
            parsing_attempts += len(multi_frags)-1
        # 3) auto-repair truncated JSON (attempt basic bracket closure)
        if raw.strip().startswith('{') and 'factors' in raw and 'sentiment_label' in raw:
            braces_open = raw.count('{')
            braces_close = raw.count('}')
            repaired = raw
            if braces_open > braces_close:
                repaired += '}' * (braces_open - braces_close)
            if repaired.count('[') > repaired.count(']'):
                repaired += ']' * (repaired.count('[') - repaired.count(']'))
            if repaired != raw:
                try:
                    data_rep = _json_loads_lenient(repaired)
                    if isinstance(data_rep, dict) and isinstance(data_rep.get('factors'), list) and data_rep.get('score') is not None:
                        if AGENT_DEBUG_LOG:
                            print("[auto-repair] 通过括号补全成功解析 JSON")
                        vd_rep = validate_stock_json(data_rep)
                        _PARSE_SUCCESS_STOCK += 1
                        parse_mode = 'auto-repair'
                        vd_rep['parsing_attempts'] = parsing_attempts + 1
                        vd_rep['news_truncation_stats'] = trunc_stats
                        vd_rep['prompt_token_est'] = prompt_token_est
                        vd_rep['_parse_mode'] = parse_mode
                        return vd_rep
                except Exception as e_rep:
                    last_error = last_error or e_rep
        # 4) strict retry (only if enabled and still not parsed)
        if AGENT_STRICT_JSON:
            global _STRICT_JSON_RETRY_STOCK
            if AGENT_DEBUG_LOG:
                print("[strict-json] stock retry once ...")
            _STRICT_JSON_RETRY_STOCK += 1
            retry_prompt = (STRICT_JSON_PREFIX + "\n" + base_prompt + "\n请牢记：输出中不能出现除 JSON 以外的任何字符。") if STRICT_JSON_PREFIX else base_prompt
            raw_retry = _invoke_llm(retry_prompt)
            if raw_retry:
                _snippet = raw_retry[:200].replace('\n', ' ')
                if AGENT_DEBUG_LOG:
                    print(f"[llm-raw-stock-retry] {stock_name} snippet: {_snippet} ...")
                # retry direct
                try:
                    data_r = _json_loads_lenient(raw_retry)
                    if isinstance(data_r, dict) and isinstance(data_r.get('factors'), list) and data_r.get('score') is not None:
                        vdr = validate_stock_json(data_r)
                        global _PARSE_SUCCESS_STOCK_RETRY
                        _PARSE_SUCCESS_STOCK_RETRY += 1
                        parse_mode = 'retry'
                        vdr['parsing_attempts'] = parsing_attempts + 1
                        vdr['news_truncation_stats'] = trunc_stats
                        vdr['prompt_token_est'] = prompt_token_est
                        vdr['_parse_mode'] = parse_mode
                        return vdr
                except Exception as e_r:
                    last_error = last_error or e_r
                # retry substring
                jfrag2 = _extract_first_json(raw_retry)
                if jfrag2:
                    try:
                        data_r2 = _json_loads_lenient(jfrag2)
                        if isinstance(data_r2, dict) and isinstance(data_r2.get('factors'), list) and data_r2.get('score') is not None:
                            if AGENT_DEBUG_LOG:
                                print("[strict-json] retry JSON substring success")
                            vdr2 = validate_stock_json(data_r2)
                            _PARSE_SUCCESS_STOCK_RETRY += 1
                            parse_mode = 'retry-substring'
                            vdr2['parsing_attempts'] = parsing_attempts + 2
                            vdr2['news_truncation_stats'] = trunc_stats
                            vdr2['prompt_token_est'] = prompt_token_est
                            vdr2['_parse_mode'] = parse_mode
                            return vdr2
                    except Exception as e_r2:
                        last_error = last_error or e_r2
        # record parse error for fallback
        if last_error:
            if AGENT_DEBUG_LOG:
                print(f"[fallback-parse] 解析失败: {last_error} -> 启动启发式")
            parse_error = str(last_error)
    else:
        if AGENT_DEBUG_LOG:
            print("[fallback-guard] raw 为空 -> 启动启发式")
        parse_error = 'raw_empty'
    # fallback 词典打分（启用）
    pos_words = ["增持","超预期","扩产","订单","涨价","提效","回购","高景气","放量","突破","增长","盈利","新签"]
    neg_words = ["减持","预亏","下滑","亏损","处罚","调查","下行","萎缩","放缓","限产","下跌","亏损扩大","裁员"]
    text_all = news_text
    pos = sum(w in text_all for w in pos_words)
    neg = sum(w in text_all for w in neg_words)
    sentiment_score = 0.0
    if pos+neg > 0:
        sentiment_score = (pos - neg) / (pos + neg)
    label = 'positive' if sentiment_score > 0.2 else ('negative' if sentiment_score < -0.2 else 'neutral')
    label_zh = '正面' if label == 'positive' else ('负面' if label == 'negative' else '中性')
    # 动态评分区间：基础 50，情绪正偏上调，负偏下调；无新闻给 45
    # 启发式补救：当 LLM 空响应/解析失败时，至少基于标题/摘要抽取“事件型”因子，避免只输出“信息不足”。
    # 这里特别兼容常见繁体/简体写法（如 回购/回購），并把证据落到“匹配到的标题片段”，提升可读性。
    extracted: List[Dict[str, Any]] = []

    # 公司直接事件优先级：同样命中关键词时，优先使用包含公司名/代码的标题作为证据，
    # 并避免 ETF/板块/指数类标题盖过公司公告/经营事件。
    symbol_core = (symbol or '').split('.')[0]

    def _title_direct_score(title: str) -> int:
        t = (title or '').strip()
        if not t:
            return -10
        score = 0
        if stock_name and stock_name in t:
            score += 3
        if symbol_core and symbol_core in t:
            score += 3
        # ETF/板块/指数类：通常是“成分股/板块热度”，不是公司自身事件
        sectorish = [
            'ETF', 'etf', '指数', '成分股', '板块', '概念', '主题', '行业', '产业ETF', '行业ETF', '指数基金'
        ]
        if any(k in t for k in sectorish):
            score -= 2
        # 盘口描述/泛市场语气（弱提示）
        marketish = ['早盘', '午盘', '盘中', '收涨', '收跌', '冲高', '跳水', '领涨', '领跌']
        if any(k in t for k in marketish):
            score -= 1
        return score

    def _collect_title_evidence(keywords: List[str], max_titles: int = 2) -> tuple[str, int]:
        titles_full = [((n.get('title') or '').strip()) for n in news_list]
        scored_hits: List[tuple[int, str]] = []
        for t in titles_full:
            if not t:
                continue
            if any(k in t for k in keywords):
                scored_hits.append((_title_direct_score(t), t[:90]))
        if scored_hits:
            scored_hits.sort(key=lambda x: x[0], reverse=True)
            best_score = scored_hits[0][0]
            picked = [t for _, t in scored_hits[:max_titles]]
            joined = ' | '.join(picked)
            tag = '公司直接' if best_score >= 3 else ('板块/ETF' if best_score <= 0 else '相关')
            return (f"标题命中({tag}): {joined}"[:220], best_score)
        # fallback：至少说明命中关键词
        return (f"关键词命中: {', '.join(keywords[:3])}"[:220], 0)

    # 规则：name, direction, weight, keywords(含繁体/简体/同义)
    factor_rules: List[Dict[str, Any]] = [
        {
            'name': '股份回购进展', 'direction': '正面', 'weight': 1.2,
            'keywords': ['回购', '回購', '回购股份', '回購股份', '购回', '購回', '累计回购', '累計回購']
        },
        {
            'name': '股东增持', 'direction': '正面', 'weight': 1.0,
            'keywords': ['增持', '增持计划', '增持計劃', '拟增持', '擬增持']
        },
        {
            'name': '减持风险', 'direction': '负面', 'weight': 1.1,
            'keywords': ['减持', '減持', '拟减持', '擬減持', '清仓', '套现', '套現']
        },
        {
            'name': '资金面改善', 'direction': '正面', 'weight': 0.9,
            'keywords': ['资金流入', '資金流入', '主力', '淨流入', '净流入', '大幅流入', '大幅流入', '资金净流入', '資金淨流入']
        },
        {
            'name': '订单动能', 'direction': '正面', 'weight': 1.0,
            'keywords': ['订单', '訂單', '中标', '中標', '新签', '新簽', '签约', '簽約', '合同', '合約']
        },
        {
            'name': '产品推进与验证', 'direction': '正面', 'weight': 1.0,
            'keywords': ['送样', '送樣', '验证', '驗證', '试产', '試產', '量产', '量產', '交付', '交付']
        },
        {
            'name': '技术与应用进展', 'direction': '正面', 'weight': 0.95,
            'keywords': ['砷化镓', '砷化鎵', '卫星', '衛星', '在轨', '在軌', '适合长期', '適合長期', '技术突破', '技術突破']
        },
        {
            'name': '业绩压力', 'direction': '负面', 'weight': 1.1,
            'keywords': ['预亏', '預虧', '下滑', '下滑', '亏损', '虧損', '不及预期', '不及預期']
        },
        {
            'name': '合规风险', 'direction': '负面', 'weight': 1.0,
            'keywords': ['处罚', '處罰', '调查', '調查', '立案', '立案', '监管', '監管']
        },
        {
            'name': '诉讼与纠纷', 'direction': '负面', 'weight': 0.95,
            'keywords': ['诉讼', '訴訟', '仲裁', '仲裁', '纠纷', '糾紛']
        },
    ]

    seen_names = set()
    for rule in factor_rules:
        kws = rule.get('keywords') or []
        if not kws:
            continue
        if any(k in text_all for k in kws) and rule['name'] not in seen_names:
            evidence, best_score = _collect_title_evidence(kws)
            # 公司直接事件优先级：公司名/代码命中则适度加权；仅板块/ETF/泛市场标题命中则降权
            base_w = float(rule.get('weight', 1.0))
            if best_score >= 3:
                base_w *= 1.15
            elif best_score <= 0:
                base_w *= 0.75
            extracted.append({
                'name': rule['name'],
                'direction': rule['direction'],
                'weight': round(base_w, 4),
                'evidence': evidence
            })
            seen_names.add(rule['name'])
        if len(extracted) >= 5:
            break

    # 如果确实没有命中任何结构化关键词，但仍有新闻标题，则给出“事件概览”而非“信息不足”。
    news_titles = [ (n.get('title') or '')[:80] for n in news_list ]
    if not extracted:
        if news_titles:
            extracted.append({
                'name': '新闻事件概览',
                'direction': '中性',
                'weight': 1.0,
                # Do not leak raw titles (may be non-Chinese / low-quality). Keep evidence in simplified Chinese.
                'evidence': '近24小时存在相关新闻，但标题信息密度不足以稳定提炼结构化因子（报告已统一输出为简体中文摘要）。'[:220]
            })
        else:
            extracted.append({'name': '信息不足', 'direction': '中性', 'weight': 1.0, 'evidence': '近24小时未检索到公司相关新闻或标题关键词命中不足'})

    # 记录关键词命中次数（按规则中出现过的关键词）
    all_keywords = []
    for r in factor_rules:
        all_keywords.extend(r.get('keywords') or [])
    keyword_hits = {k: (k in text_all) for k in all_keywords}
    # 归一化
    wsum = sum(f['weight'] for f in extracted)
    if wsum > 0:
        for f in extracted:
            f['weight'] = round(f['weight']/wsum,4)
    base_score = 50 + (10 if sentiment_score > 0.3 else (-10 if sentiment_score < -0.3 else 0))
    final_score = int(max(0,min(100, base_score)))
    # 统计 fallback 次数
    global _FALLBACK_STOCK_COUNT
    _FALLBACK_STOCK_COUNT += 1
    parse_mode = parse_mode or 'heuristic'
    
    # 动态生成摘要：基于实际新闻标题拼接，而非固定模板
    def _build_dynamic_summary(titles: List[str], factors: List[Dict], stock_name: str) -> str:
        parts = []
        # 提取有效标题（去重、去空、截断）
        valid_titles = []
        seen = set()
        for t in titles:
            t_clean = (t or '').strip()
            if not t_clean or len(t_clean) < 6:
                continue
            # 简单去重
            t_key = t_clean[:30]
            if t_key in seen:
                continue
            seen.add(t_key)
            valid_titles.append(t_clean[:60])
            if len(valid_titles) >= 4:
                break
        
        # 构建摘要
        if valid_titles:
            parts.append(f"近期新闻：{'；'.join(valid_titles)}")
        
        # 添加因子关注点
        if factors:
            factor_names = [f['name'] for f in factors[:3] if f.get('name') and f['name'] not in ('新闻事件概览', '信息不足')]
            if factor_names:
                parts.append(f"关注点：{', '.join(factor_names)}")
        
        # 添加情绪判断
        if sentiment_score > 0.3:
            parts.append("整体偏正面")
        elif sentiment_score < -0.3:
            parts.append("存在负面信号")
        
        if parts:
            return '。'.join(parts) + '。'
        return f"当日{stock_name}相关新闻信息有限，建议关注后续公告披露。"
    
    dynamic_summary = _build_dynamic_summary(news_titles, extracted, stock_name)
    
    return {
        'sentiment_score': sentiment_score,
        'sentiment_label_en': label,
        'sentiment_label': label_zh,
        'factors': extracted,
        'score': final_score,
        'need_macro': False,
        'macro_keywords': [],
        'risk_flags': [],
        'correlation_watch': [],
        'confidence': round(0.3 + 0.4 * min(1, (pos+neg)/8),3) if news_list else 0.1,
        'summary': dynamic_summary,
        # Keep internal diagnostics under underscore-prefixed keys; strip before writing reports.
        '_llm_fallback': True,
        '_parse_mode': parse_mode,
        '_parse_error': parse_error,
        '_keyword_hits': keyword_hits,
        '_news_titles': news_titles,
        'news_truncation_stats': trunc_stats,
        'prompt_token_est': prompt_token_est,
    }

# 4. 大势分析（行业/宏观政策）
def llm_macro_analysis(all_news: List[Dict]) -> Dict[str, Any]:
    # 预摘要 & 截断统计
    summaries = []
    orig_total = 0
    trunc_total = 0
    # 降低单条摘要长度与总条目数量，缓解 LLM 截断
    max_macro_items = int(os.getenv("MACRO_MAX_ITEMS", "40"))
    for n in all_news[:max_macro_items]:
        s, o_len, t_len = _summarize_news_item(n, max_len=160)
        orig_total += o_len
        trunc_total += t_len
        summaries.append(s)
    summarized_text = "\n".join(summaries)
    trunc_stats = {
        'item_count': len(all_news),
        'original_chars': orig_total,
        'truncated_chars': trunc_total,
        'avg_original_per_item': round(orig_total/len(all_news),2) if all_news else 0,
        'avg_truncated_per_item': round(trunc_total/len(all_news),2) if all_news else 0,
        'ratio_truncated': round(trunc_total/max(orig_total,1),4),
    'max_len_per_item': 160
    }
    base_prompt = (
        "你是宏观与行业结构分析 Agent。基于以下新闻摘要，简洁作答并输出严格 json（禁止附加解释文字）：\n"
        "{\n"
        "  \"market_sentiment_index\": 0-100,\n"
        "  \"risk_index\": 0-100,\n"
        "  \"industry_heat\": [{\"industry\": str, \"heat\": 0-100, \"drivers\": [str]}],\n"
        "  \"policy_tone\": {\"summary\": str, \"bias\": \"supportive|neutral|restrictive\"},\n"
        "  \"capital_flow_focus\": [str],\n"
        "  \"macro_factors\": [{\"name\": str, \"impact\": \"正面|负面|中性\", \"confidence\": 0-1}],\n"
        "  \"actionable_insights\": [{\"theme\": str, \"rationale\": str, \"watch_metrics\": [str]}],\n"
        "  \"suggest_global_watch\": [str],\n"
        "  \"extra_keywords\": [str],\n"
        "  \"summary\": str\n"
        "}\n"
        "新闻摘要:\n" + summarized_text
    )
    prompt = (STRICT_JSON_PREFIX + "\n" + base_prompt) if STRICT_JSON_PREFIX else base_prompt
    prompt_char_count = len(prompt)
    prompt_token_est = round(prompt_char_count / 1.5)
    raw = _invoke_llm(prompt)
    if raw and AGENT_DEBUG_LOG:
        print(f"[llm-raw-macro] snippet: {raw[:220].replace('\n',' ')} ...")
    if raw:
        last_error = None
        # direct
        try:
            data = _json_loads_lenient(raw)
            if isinstance(data, dict) and data.get('industry_heat'):
                data['macro_truncation_stats'] = trunc_stats
                data['macro_prompt_token_est'] = prompt_token_est
                data['parse_mode'] = 'direct'
                return data
            else:
                if AGENT_DEBUG_LOG:
                    print("[macro-fallback-guard] direct 缺少 industry_heat -> substring")
        except Exception as e:
            last_error = e
        # substring first
        jfrag = _extract_first_json(raw)
        if jfrag:
            try:
                d2 = _json_loads_lenient(jfrag)
                if isinstance(d2, dict) and d2.get('industry_heat'):
                    if AGENT_DEBUG_LOG:
                        print("[json-extract-macro] 子串成功")
                    d2['macro_truncation_stats'] = trunc_stats
                    d2['macro_prompt_token_est'] = prompt_token_est
                    d2['parse_mode'] = 'substring'
                    return d2
            except Exception as e2:
                last_error = last_error or e2
        # multi fragments
        frags = _extract_all_json(raw, limit=5)
        if frags and len(frags) > 1:
            for idx, f in enumerate(frags):
                if jfrag and f == jfrag:
                    continue
                try:
                    d_m = _json_loads_lenient(f)
                    if isinstance(d_m, dict) and d_m.get('industry_heat'):
                        if AGENT_DEBUG_LOG:
                            print(f"[json-extract-macro-multi] 第{idx+1}个片段成功")
                        d_m['macro_truncation_stats'] = trunc_stats
                        d_m['macro_prompt_token_est'] = prompt_token_est
                        d_m['parse_mode'] = 'multi-substring'
                        return d_m
                except Exception as em:
                    last_error = last_error or em
        # auto-repair
        if raw.strip().startswith('{') and 'industry_heat' in raw:
            bo = raw.count('{'); bc = raw.count('}')
            repaired = raw + ('}' * (bo-bc) if bo>bc else '')
            if repaired != raw:
                try:
                    dr = _json_loads_lenient(repaired)
                    if isinstance(dr, dict) and dr.get('industry_heat'):
                        if AGENT_DEBUG_LOG:
                            print("[auto-repair-macro] 括号补全成功")
                        dr['macro_truncation_stats'] = trunc_stats
                        dr['macro_prompt_token_est'] = prompt_token_est
                        dr['parse_mode'] = 'auto-repair'
                        return dr
                except Exception as er:
                    last_error = last_error or er
        if last_error:
            if AGENT_DEBUG_LOG:
                print(f"[macro-fallback-parse] 解析失败: {last_error} -> 启动启发式")
    else:
        if AGENT_DEBUG_LOG:
            print("[macro-fallback-guard] raw 为空 -> 启发式")
    # 启发式宏观：统计出现频次高的行业/主题词
    text_all = "\n".join([ (n.get('title') or '') + ' ' + (n.get('content') or '') for n in all_news ])
    themes = {
        "半导体": ["芯片","半导体","晶圆"],
        "新能源": ["光伏","锂","电池","储能"],
        "人工智能": ["AI","人工智能","算力"],
        "消费复苏": ["消费","出行","旅游","复苏"],
        "基建": ["基建","铁路","公路","建设"],
        "出海": ["出口","外需","跨境"],
        "地产链": ["地产","物业","房地产"],
    }
    heat = []
    for name, kws in themes.items():
        cnt = sum(k in text_all for k in kws)
        if cnt:
            heat.append({"industry": name, "heat": min(100, cnt*15), "drivers": kws[:2]})
    # 记录每个主题的命中次数用于诊断
    theme_hits = {name: sum(k in text_all for k in kws) for name, kws in themes.items()}
    heat = sorted(heat, key=lambda x: x['heat'], reverse=True)[:8]
    macro_factors = []
    if heat:
        for h in heat[:5]:
            macro_factors.append({"name": h['industry'], "impact": "中性", "confidence": 0.4})
    summary_frag = [f"主题 {h['industry']} 相关信息增量" for h in heat[:3]] or ["新闻密度不足，宏观信号弱"]
    global _FALLBACK_MACRO
    _FALLBACK_MACRO = True
    return {
        "market_sentiment_index": 50 + (5 if any(h['industry']=="消费复苏" for h in heat) else 0),
        "risk_index": 40 + (10 if any(h['industry']=="地产链" for h in heat) else 0),
        "industry_heat": heat,
        "policy_tone": {"summary": "政策信号暂不明确", "bias": "neutral"},
        "capital_flow_focus": [h['industry'] for h in heat[:3]],
        "macro_factors": macro_factors,
        "actionable_insights": [],
        "suggest_global_watch": [],
        "extra_keywords": [],
        "summary": "；".join(summary_frag),
        "llm_fallback": True,
        "raw": raw,
        "error": "macro_llm_empty",
        "theme_hits": theme_hits,
        "macro_truncation_stats": trunc_stats,
        "macro_prompt_token_est": prompt_token_est,
        "parse_mode": "heuristic"
    }

# 5. agent主流程
def preflight():
    print("[preflight] 开始服务可用性检测...")
    # 1. movers API 自动发现
    try:
        global MOVERS_API_URL
        MOVERS_API_URL = discover_movers_url([MOVERS_API_URL])  # 先试现有配置，再 fallback
    except Exception as e:
        print(f"[preflight] 指定 MOVERS_API_URL 无法访问: {e}")
        MOVERS_API_URL = discover_movers_url()
    # 2. SearXNG
    try:
        base = SEARXNG_URL.rstrip('/')
        # 使用更短的超时以避免在 preflight 阶段长时间阻塞
        r = requests.get(f"{base}/search", params={"q":"测试","format":"json"}, timeout=3)
        if r.status_code not in (200, 403):
            print(f"[preflight] 警告: SearXNG 状态码 {r.status_code}")
        else:
            print(f"[preflight] SearXNG 可访问 status={r.status_code}")
    except Exception as e:
        print(f"[preflight] 警告: SearXNG 不可访问（已短超时）: {e}")
    # 3. LLM (Azure 或 通用)
    global USE_LLM
    if not USE_LLM:
        print("[preflight] 未配置 LLM（将以无评分模式运行）")
    else:
        test_ok = False
        try:
            reply = _invoke_llm("ping json only")
            if reply:
                print("[preflight] LLM 可用")
                test_ok = True
        except Exception as e:
            print(f"[preflight] LLM 连接异常: {e}")
        if not test_ok:
            print("[preflight] LLM 不可用，降级为无评分模式")
            USE_LLM = False
    print("[preflight] 基础服务检测完成\n")

def _parallel_fetch_news(stocks: List[Dict]) -> List[Tuple[Dict, List[Dict], Dict[str, Any]]]:
    # parallel debug prints removed
    # 并行抓取每只股票新闻，返回 (stock, news_list, diagnostics) 列表
    
    # 尝试导入增强搜索模块
    enhanced_search_available = False
    enhance_func = None
    try:
        from app.utils.enhanced_news_fetch import enhance_stock_news_for_analysis
        enhanced_search_available = os.getenv('ENHANCED_SEARCH_ENABLE', '1') in ('1', 'true', 'yes')
        enhance_func = enhance_stock_news_for_analysis
        if AGENT_DEBUG_LOG:
            print(f"[parallel] 增强搜索模块已加载, enabled={enhanced_search_available}")
    except ImportError as e:
        if AGENT_DEBUG_LOG:
            print(f"[parallel] 增强搜索模块不可用: {e}")
    
    results: List[Tuple[Dict, List[Dict], Dict[str, Any]]] = []
    def task(stock: Dict):
        name = stock.get("name")
        symbol = stock.get("symbol")
        # 多信源：DB-first + CNINFO + SearXNG，并在入库前做 LLM gate
        if AGENT_MULTI_SOURCE:
            try:
                news, diag = _fetch_news_multi_source(stock)
            except Exception as e:
                if AGENT_DEBUG_LOG:
                    print(f"[multi-source] failed for {name}({symbol}): {e}")
                news = search_news_searxng(name, max_results=MAX_STOCK_NEWS, symbol=symbol)
                diag = {'error': str(e)}
        else:
            news = search_news_searxng(name, max_results=MAX_STOCK_NEWS, symbol=symbol)
            diag = {}
        
        # 如果新闻数不足，尝试官方披露补池
        min_news_for_topup = int(os.getenv('AGENT_OFFICIAL_TOPUP_MIN_NEWS', '2'))
        if len(news) < min_news_for_topup and symbol:
            added = _topup_official_for_symbol(symbol)
            if added > 0:
                # 重新从DB获取最新新闻
                try:
                    fresh_db_items = _fetch_stock_news_db_first(symbol)
                    if fresh_db_items:
                        # 合并新旧新闻
                        existing_urls = {n.get('url') for n in news if n.get('url')}
                        for item in fresh_db_items:
                            if item.get('url') and item.get('url') not in existing_urls:
                                news.append(item)
                                if len(news) >= int(MAX_STOCK_NEWS):
                                    break
                except Exception as e:
                    if AGENT_DEBUG_LOG:
                        print(f"[parallel-topup] failed to refresh DB news for {symbol}: {e}")
        
        # 增强搜索：当新闻仍不足时，使用行业/关键词扩展
        if enhanced_search_available and enhance_func and len(news) < min_news_for_topup:
            try:
                enhanced_news, enhance_diag = enhance_func(
                    stock, news,
                    backend_url=BACKEND_BASE_URL,
                    searxng_url=SEARXNG_URL,
                )
                if enhanced_news and len(enhanced_news) > len(news):
                    if AGENT_DEBUG_LOG:
                        print(f"[enhanced] {name}({symbol}): {len(news)} -> {len(enhanced_news)} 条新闻")
                    news = enhanced_news
                    diag['enhanced'] = True
                    diag['enhance_strategies'] = enhance_diag.get('strategies', [])
                    diag['enhance_industry'] = enhance_diag.get('industry', '')
                    diag['industry_news_count'] = enhance_diag.get('industry_count', 0)
            except Exception as e:
                if AGENT_DEBUG_LOG:
                    print(f"[enhanced] failed for {name}({symbol}): {e}")
                diag['enhance_error'] = str(e)
        
        return stock, news, diag
    with ThreadPoolExecutor(max_workers=min(PARALLEL_WORKERS, len(stocks))) as ex:
        future_map = {ex.submit(task, s): s for s in stocks}
        for fut in as_completed(future_map):
            try:
                stock, news, diag = fut.result()
                results.append((stock, news, diag))
            except Exception as e:
                s = future_map[fut]
                print("[parallel] 抓取 {} 失败: {}".format(s.get('name'), e))
                results.append((s, [], {'error': str(e)}))
    return results


def _parse_report_date_yyyymmdd(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    ss = str(s).strip()
    if not re.fullmatch(r"\d{8}", ss):
        raise ValueError("--date 必须是 YYYYMMDD（8位数字）")
    return datetime.strptime(ss, "%Y%m%d").date()


def _maybe_upsert_daily_report_mongo(report_date: date, payload: Dict[str, Any], markdown_text: Optional[str]) -> Optional[Tuple[str, str]]:
    """将日报（按 report_date）写入 MongoDB（最佳努力）。

    读取环境变量：
    - AGENT_MONGO_ENABLE: 1/true/yes 启用（默认启用）
    - MONGO_URI: Mongo 连接串（默认 mongodb://localhost:27017）
    - MONGO_DB_NAME / MONGO_DB: 数据库名（默认 aistock_news）
    - AGENT_MONGO_COLLECTION: 集合名（默认 agent_daily_reports）
    """
    if os.getenv("AGENT_MONGO_ENABLE", "1").lower() not in ("1", "true", "yes"):
        return None
    try:
        from pymongo import MongoClient  # type: ignore
    except Exception:
        return None


def _maybe_upsert_daily_report_sql(report_date: date, payload: Dict[str, Any], markdown_text: Optional[str]) -> bool:
    """将日报（按 report_date）写入后端 SQL 表 agent_daily_reports（最佳努力）。

    说明：
    - 前端默认读取 /api/agent/daily/latest，该接口优先读 SQL。
    - 若仅写 Mongo 而 SQL 未写入，页面可能回退读取旧的 agent_reports 文件，导致历史噪声再次出现。

    环境变量：
    - AGENT_SQL_ENABLE: 1/true/yes 启用（默认启用）
    """
    if os.getenv("AGENT_SQL_ENABLE", "1").lower() not in ("1", "true", "yes"):
        return False

    try:
        from app.core.db import SessionLocal  # type: ignore
        from app.core.models import AgentDailyReport  # type: ignore
    except Exception:
        try:
            # 当以脚本方式运行时，确保可以定位到 backend/app 包
            sys.path.append(str(Path(__file__).resolve().parents[2]))  # add 'backend' to sys.path
            from app.core.db import SessionLocal  # type: ignore
            from app.core.models import AgentDailyReport  # type: ignore
        except Exception:
            return False

    stock_reports = payload.get("stock_reports")
    macro = payload.get("macro")
    analytics = payload.get("analytics")
    diagnostics = payload.get("diagnostics")
    top20_count = payload.get("top20_count")
    version = payload.get("version") or 1

    try:
        try:
            from sqlalchemy import select as _select  # type: ignore
        except Exception:
            _select = None  # type: ignore

        with SessionLocal() as session:
            existing = None
            if _select is not None:
                existing = session.execute(
                    _select(AgentDailyReport).where(AgentDailyReport.report_date == report_date)
                ).scalar_one_or_none()
            else:
                # fallback for older SQLAlchemy APIs
                existing = session.query(AgentDailyReport).filter(AgentDailyReport.report_date == report_date).one_or_none()  # type: ignore

            if existing:
                existing.generated_at = datetime.utcnow()
                existing.top20_count = top20_count if isinstance(top20_count, int) else existing.top20_count
                try:
                    existing.version = int(version)
                except Exception:
                    pass
                existing.stock_reports_json = json.dumps(stock_reports, ensure_ascii=False) if stock_reports is not None else None
                existing.macro_json = json.dumps(macro, ensure_ascii=False) if macro is not None else None
                existing.analytics_json = json.dumps(analytics, ensure_ascii=False) if analytics is not None else None
                existing.diagnostics_json = json.dumps(diagnostics, ensure_ascii=False) if diagnostics is not None else None
                if markdown_text is not None:
                    existing.markdown = markdown_text
                session.commit()
                return True

            row = AgentDailyReport(
                report_date=report_date,
                generated_at=datetime.utcnow(),
                job_id=payload.get("job_id"),
                version=int(version) if str(version).isdigit() else 1,
                top20_count=top20_count if isinstance(top20_count, int) else None,
                stock_reports_json=json.dumps(stock_reports, ensure_ascii=False) if stock_reports is not None else None,
                macro_json=json.dumps(macro, ensure_ascii=False) if macro is not None else None,
                analytics_json=json.dumps(analytics, ensure_ascii=False) if analytics is not None else None,
                diagnostics_json=json.dumps(diagnostics, ensure_ascii=False) if diagnostics is not None else None,
                markdown=markdown_text,
            )
            session.add(row)
            session.commit()
            return True
    except Exception as e:
        if AGENT_DEBUG_LOG:
            print(f"[sql] upsert failed: {e}")
        return False

    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME", os.getenv("MONGO_DB", "aistock_news"))
    coll_name = os.getenv("AGENT_MONGO_COLLECTION", "agent_daily_reports")

    doc = {
        "report_date": report_date.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "version": payload.get("version"),
        "top20_count": payload.get("top20_count"),
        "stock_reports": payload.get("stock_reports"),
        "macro": payload.get("macro"),
        "macro_extra": payload.get("macro_extra"),
        "macro_keywords_used": payload.get("macro_keywords_used"),
        "analytics": payload.get("analytics"),
        "diagnostics": payload.get("diagnostics"),
        "markdown": markdown_text,
        "source": "agent_script",
    }
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000)
        db = client[db_name]
        coll = db[coll_name]
        coll.update_one(
            {"report_date": doc["report_date"]},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
        return (db_name, coll_name)
    except Exception:
        return None


def agent_main(*, report_date: Optional[date] = None):
    try:
        preflight()  # 不再因 LLM 失败而退出
    except Exception as e:
        if AGENT_DEBUG_LOG:
            print(f"[agent-main] preflight failed: {e}, continuing anyway...")
    started = datetime.now(timezone.utc).isoformat()
    started = datetime.now(timezone.utc).isoformat()
    if report_date is None:
        report_date = datetime.now(timezone.utc).date()
    report_day = report_date.strftime('%Y%m%d')
    top20 = fetch_top20()
    # debug prints removed
    # 预采集：先扩充 DB 内容池，再做 Top20 个股抓取
    try:
        _global_pre_ingest_sources()
    except Exception:
        pass
    print("[phase] 并行抓取新闻 (limit={}) ...".format(MAX_STOCK_NEWS))
    parallel_results = _parallel_fetch_news(top20)
    all_news: List[Dict] = []
    stock_reports: List[Dict[str, Any]] = []
    
    # 统计增强搜索效果
    enhance_stats = {'enhanced_count': 0, 'industry_news_added': 0}
    
    for stock, news_list, diag in parallel_results:
        name = stock.get("name")
        symbol = stock.get("symbol")
        pct_chg = stock.get("pct_chg")
        all_news.extend(news_list)
        bp = None
        effective_news_count = len(news_list)
        
        # 记录增强搜索统计
        if diag.get('enhanced'):
            enhance_stats['enhanced_count'] += 1
            enhance_stats['industry_news_added'] += diag.get('industry_news_count', 0)
        
        # When public news hits are zero, try a lightweight company-profile fallback to avoid empty reports.
        if effective_news_count == 0:
            bp = _try_fetch_basic_profile(symbol)
            if isinstance(bp, dict) and (bp.get('profile_db') or bp.get('crawled_snippets') or bp.get('search_results')):
                effective_news_count = 1
        
        # 分离直接新闻和行业背景新闻
        direct_news = [n for n in news_list if not n.get('_is_industry_context')]
        industry_context_news = [n for n in news_list if n.get('_is_industry_context')]
        
        # 显示增强信息
        enhance_info = ""
        if diag.get('enhanced'):
            industry = diag.get('enhance_industry', '')
            strategies = diag.get('enhance_strategies', [])
            if industry or strategies:
                enhance_info = f" [增强: 行业={industry}, 策略={strategies}]"
        
        print("\n分析: {} ({}) 涨跌幅: {} | 直接新闻: {} | 行业背景: {}{}".format(
            name, symbol, pct_chg, len(direct_news), len(industry_context_news), enhance_info))
        report = validate_stock_json(llm_analyze_news(name, news_list, symbol=symbol, basic_profile=bp))
        
        # 在报告中添加增强搜索信息
        report_entry = {
            "name": name,
            "symbol": symbol,
            "pct_chg": pct_chg,
            "news_count": effective_news_count,
            "direct_news_count": len(direct_news),
            "industry_context_count": len(industry_context_news),
            "report": report,
            "fetch_diagnostics": diag,
        }
        
        # 如果有行业信息，添加到报告
        if diag.get('enhance_industry'):
            report_entry['industry'] = diag.get('enhance_industry')
        
        stock_reports.append(report_entry)
    # 输出评分与因子数量（防止 f-string 嵌套花括号问题引发解析错误）
    _score = report.get('score')
    _factors_len = len(report.get('factors', [])) if isinstance(report.get('factors'), list) else 0
    print("量化评分: {} | 因子数: {}".format(_score, _factors_len))
    # 聚合宏观关键词（来自个股结果）
    macro_candidate_keywords: List[str] = []
    for sr in stock_reports:
        rep = sr.get("report", {})
        if rep and rep.get("need_macro"):
            for kw in rep.get("macro_keywords", []) or []:
                if kw:
                    macro_candidate_keywords.append(kw.strip())
    # 去重与截断
    seen = set()
    macro_keywords_unique = []
    for kw in macro_candidate_keywords:
        if kw not in seen:
            seen.add(kw)
            macro_keywords_unique.append(kw)
        if len(macro_keywords_unique) >= MAX_MACRO_KEYWORDS:
            break
    # 追加关键词新闻到 all_news （用于更丰富宏观输入）
    if macro_keywords_unique:
        print(f"[macro] 触发宏观深度分析，关键词: {macro_keywords_unique}")
        for kw in macro_keywords_unique:
            extra_news = search_news_searxng(kw, max_results=3, symbol=None)
            all_news.extend(extra_news)
    macro = llm_macro_analysis(all_news)
    # 补充检索
    extra_sections = []
    for kw in macro.get('extra_keywords', [])[:int(os.getenv("MACRO_MAX_EXTRA", "3"))]:
        print(f"补充检索关键词: {kw}")
        extra_news = search_news_searxng(kw, max_results=int(os.getenv("SEARXNG_MACRO_RESULTS", "5")), symbol=None)
        extra_macro = llm_macro_analysis(extra_news)
        extra_sections.append({"keyword": kw, "analysis": extra_macro})
        time.sleep(float(os.getenv("AGENT_MACRO_DELAY", "2")))
    # 统计分析（面向报告：使用中文标签）
    sentiment_dist = {"正面": 0, "中性": 0, "负面": 0}
    factor_freq: Dict[str, int] = {}
    for sr in stock_reports:
        rep = sr.get("report", {}) or {}
        lbl = rep.get("sentiment_label")
        if lbl in sentiment_dist:
            sentiment_dist[lbl] += 1
        for fct in rep.get("factors", []) or []:
            if isinstance(fct, dict):
                nm = fct.get("name")
            else:
                nm = None
            if nm:
                factor_freq[nm] = factor_freq.get(nm, 0) + 1
    top_factor_frequency = sorted(factor_freq.items(), key=lambda x: x[1], reverse=True)[:15]
    # 方向统计
    direction_counts = {"正面":0, "负面":0, "不确定":0}
    for sr in stock_reports:
        for f in (sr.get('report', {}).get('factors') or []):
            if isinstance(f, dict):
                d = f.get('direction')
                if d in direction_counts:
                    direction_counts[d]+=1

    finished = datetime.now(timezone.utc).isoformat()

    # ---- diagnostics (metrics-only; do NOT include in report JSON/Markdown) ----
    _fallback_ratio = _FALLBACK_STOCK_COUNT / max(1, len(stock_reports))
    warnings: List[dict] = []
    def _add(level: str, msg: str):
        warnings.append({"level": level, "message": msg})
    if _fallback_ratio > 0.5:
        _add("warning", f"高回退比例: {(_fallback_ratio*100):.1f}%")
    if AGENT_STRICT_JSON and (_STRICT_JSON_RETRY_STOCK > 0 or _STRICT_JSON_RETRY_MACRO > 0):
        _add("info", "严格 JSON 模式触发了重试")
    if _AZURE_LAST_ERROR:
        _add("error", f"Azure 最近错误: {_AZURE_LAST_ERROR[:120]}")
    if _PARSE_SUCCESS_STOCK == 0 and len(stock_reports) > 0:
        _add("warning", "所有个股首次解析 JSON 失败")
    if macro and _PARSE_SUCCESS_MACRO == 0:
        _add("warning", "宏观分析首次解析 JSON 失败")

    diagnostics: Dict[str, Any] = {
        'fallback_stock_count': _FALLBACK_STOCK_COUNT,
        'fallback_macro_used': _FALLBACK_MACRO,
        'strict_json_enabled': AGENT_STRICT_JSON,
        'strict_retry_stock': _STRICT_JSON_RETRY_STOCK,
        'strict_retry_macro': _STRICT_JSON_RETRY_MACRO,
        'parse_success_stock_first': _PARSE_SUCCESS_STOCK,
        'parse_success_stock_retry': _PARSE_SUCCESS_STOCK_RETRY,
        'parse_success_macro_first': _PARSE_SUCCESS_MACRO,
        'parse_success_macro_retry': _PARSE_SUCCESS_MACRO_RETRY,
        'fallback_ratio': round(_fallback_ratio, 3),
        'warnings': warnings,
        'chat_empty_count': _CHAT_EMPTY_COUNT,
        'force_no_response_format': _FORCE_NO_RESPONSE_FORMAT,
        'azure_fail_count': _AZURE_FAIL_COUNT,
        'searx_filter_metrics': dict(_SEARX_FILTER_METRICS),
        # 增强搜索统计
        'enhanced_search': {
            'stocks_enhanced': enhance_stats.get('enhanced_count', 0),
            'industry_news_added': enhance_stats.get('industry_news_added', 0),
        },
    }

    token_list: List[int] = []
    trunc_original_sum = 0
    trunc_truncated_sum = 0
    trunc_items_sum = 0
    for sr in stock_reports:
        rep = (sr.get('report') or {})
        t_est = rep.get('prompt_token_est')
        if isinstance(t_est, (int, float)):
            token_list.append(int(t_est))
        ts = rep.get('news_truncation_stats') or {}
        trunc_original_sum += ts.get('original_chars', 0) or 0
        trunc_truncated_sum += ts.get('truncated_chars', 0) or 0
        trunc_items_sum += ts.get('item_count', 0) or 0
    if token_list:
        diagnostics['stock_prompt_token_summary'] = {
            'min': min(token_list),
            'max': max(token_list),
            'avg': round(sum(token_list) / len(token_list), 2),
            'total': sum(token_list),
            'count': len(token_list)
        }
    diagnostics['stock_truncation_summary'] = {
        'total_items': trunc_items_sum,
        'sum_original_chars': trunc_original_sum,
        'sum_truncated_chars': trunc_truncated_sum,
        'avg_original_per_item': round(trunc_original_sum / max(1, trunc_items_sum), 2) if trunc_items_sum else 0,
        'avg_truncated_per_item': round(trunc_truncated_sum / max(1, trunc_items_sum), 2) if trunc_items_sum else 0,
        'overall_ratio_truncated': round(trunc_truncated_sum / max(1, trunc_original_sum), 4) if trunc_original_sum else 0
    }
    if isinstance(macro, dict):
        if macro.get('macro_prompt_token_est') is not None:
            diagnostics['macro_prompt_token_est'] = macro.get('macro_prompt_token_est')
        if macro.get('macro_truncation_stats') is not None:
            diagnostics['macro_truncation_stats'] = macro.get('macro_truncation_stats')

    def _ensure_report_zh(text: Any, *, max_len: int = 140) -> str:
        """Ensure report-visible snippets are simplified Chinese.

        - Never expose raw titles / foreign-language fragments.
        - Prefer LLM translation/rewriting when available.
        - If LLM is unavailable, suppress non-CJK snippets.
        """
        s = (str(text or '')).strip()
        if not s:
            return ''
        # Strip URLs and obvious noise to avoid leaking raw references.
        try:
            s = re.sub(r'https?://\S+', '', s)
            s = re.sub(r'\s+', ' ', s).strip()
        except Exception:
            pass
        if not s:
            return ''
        def _cjk_count_local(t: str) -> int:
            return sum(1 for ch in (t or '') if '\u4e00' <= ch <= '\u9fff')

        def _has_japanese_kana_local(t: str) -> bool:
            # Hiragana / Katakana / halfwidth katakana
            return any(
                ('\u3040' <= ch <= '\u30ff') or ('\uff66' <= ch <= '\uff9d')
                for ch in (t or '')
            )

        def _ascii_letter_ratio(t: str) -> float:
            tt = re.sub(r"\s+", "", (t or ""))
            if not tt:
                return 0.0
            letters = sum(1 for ch in tt if ('A' <= ch <= 'Z') or ('a' <= ch <= 'z'))
            return letters / max(1, len(tt))

        min_cjk_report = int(os.getenv('AGENT_REPORT_MIN_CJK', '4'))

        # Hard block Japanese pages that may contain shared Han characters.
        # Example: "イオン…" should never appear in CN-only reports.
        if _has_japanese_kana_local(s):
            force_llm_zh = os.getenv('AGENT_REPORT_FORCE_LLM_ZH', '1') == '1'
            if USE_LLM and force_llm_zh:
                prompt = (
                    "请将以下内容翻译并改写为【简体中文】，保留原意与专业性，删除网址与外语碎片，只输出最终中文文本，不要加前缀：\n"
                    + s[:600]
                )
                tr = _invoke_llm(prompt)
                if tr:
                    tr = str(tr).strip()
                    if _cjk_count_local(tr) >= min_cjk_report:
                        return tr[:max_len]
            return '（已省略非中文引用）'

        # If it's already Chinese enough and not Japanese kana, pass through.
        if _cjk_count_local(s) >= min_cjk_report:
            return s[:max_len]

        # Suppress pure-English / high-English-ratio fragments in CN-only reports.
        max_ascii_ratio = float(os.getenv('AGENT_REPORT_MAX_ASCII_RATIO', '0.35'))
        if _ascii_letter_ratio(s) >= max_ascii_ratio:
            force_llm_zh = os.getenv('AGENT_REPORT_FORCE_LLM_ZH', '1') == '1'
            if USE_LLM and force_llm_zh:
                prompt = (
                    "请将以下内容翻译并改写为【简体中文】，保留原意与专业性，只输出最终中文文本，不要加前缀：\n"
                    + s[:600]
                )
                tr = _invoke_llm(prompt)
                if tr:
                    tr = str(tr).strip()
                    if _cjk_count_local(tr) >= min_cjk_report:
                        return tr[:max_len]
            return '（已省略非中文引用）'
        force_llm_zh = os.getenv('AGENT_REPORT_FORCE_LLM_ZH', '1') == '1'
        if USE_LLM and force_llm_zh:
            prompt = (
                "请将以下内容翻译并改写为【简体中文】，保留原意与专业性，删除网址与外语碎片，只输出最终中文文本，不要加前缀：\n"
                + s[:600]
            )
            tr = _invoke_llm(prompt)
            if tr:
                tr = str(tr).strip()
                # Final safety: if translation still has no CJK, suppress it.
                if _cjk_count_local(tr) >= min_cjk_report:
                    return tr[:max_len]
        return '（已省略非中文引用）'

    # ---- public-facing sanitization (CN only; strip parse/raw/error fields) ----
    def _public_stock_report(rep: Any) -> Dict[str, Any]:
        if not isinstance(rep, dict):
            return {}

        cleaned_factors: List[Dict[str, Any]] = []
        for f in (rep.get('factors') or [])[:10]:
            if not isinstance(f, dict):
                continue
            direction = (f.get('direction') or '').strip()
            low = direction.lower()
            if direction in ('不确定', 'uncertain', 'unknown', ''):
                direction = '中性'
            else:
                direction = {'positive': '正面', 'negative': '负面', 'neutral': '中性'}.get(low, direction)
            cleaned_factors.append({
                'name': _ensure_report_zh((f.get('name') or '').strip(), max_len=40),
                'direction': direction,
                'weight': f.get('weight'),
                'evidence': _ensure_report_zh((f.get('evidence') or '').strip(), max_len=120),
            })

        cleaned_watch: List[Dict[str, Any]] = []
        for cw in (rep.get('correlation_watch') or [])[:8]:
            if not isinstance(cw, dict):
                continue
            cleaned_watch.append({
                'metric': _ensure_report_zh((cw.get('metric') or '').strip(), max_len=24),
                'reason': _ensure_report_zh((cw.get('reason') or '').strip(), max_len=120),
                'suggest_window': _ensure_report_zh((cw.get('suggest_window') or '').strip(), max_len=24),
            })

        return {
            'sentiment_score': rep.get('sentiment_score'),
            'sentiment_label': rep.get('sentiment_label'),
            'factors': cleaned_factors,
            'score': rep.get('score'),
            'need_macro': rep.get('need_macro'),
            'macro_keywords': [_ensure_report_zh(x, max_len=24) for x in (rep.get('macro_keywords') or [])[:8] if x],
            'risk_flags': [_ensure_report_zh(x, max_len=24) for x in (rep.get('risk_flags') or [])[:10] if x],
            'correlation_watch': cleaned_watch,
            'confidence': rep.get('confidence'),
            'summary': _ensure_report_zh(rep.get('summary'), max_len=260),
        }

    def _public_macro(m: Any) -> Dict[str, Any]:
        if not isinstance(m, dict):
            return {}
        pt = m.get('policy_tone') if isinstance(m.get('policy_tone'), dict) else {}
        bias = (pt or {}).get('bias')
        bias_zh = {'supportive': '偏宽松', 'neutral': '中性', 'restrictive': '偏收紧'}.get(str(bias or '').strip().lower(), '中性')

        def _clean_list(xs: Any, max_items: int = 12) -> List[str]:
            out: List[str] = []
            for it in (xs or [])[:max_items]:
                s = _ensure_report_zh(str(it), max_len=40)
                if s and s != '（已省略非中文引用）':
                    out.append(s)
            return out

        ih = []
        for item in (m.get('industry_heat') or [])[:10]:
            if not isinstance(item, dict):
                continue
            industry = _ensure_report_zh(item.get('industry'), max_len=30)
            drivers = _clean_list(item.get('drivers') or [], max_items=6)
            ih.append({'industry': industry, 'heat': item.get('heat'), 'drivers': drivers})

        mf = []
        for f in (m.get('macro_factors') or [])[:12]:
            if isinstance(f, dict):
                mf.append({
                    'name': _ensure_report_zh(f.get('name'), max_len=30),
                    'impact': _ensure_report_zh(f.get('impact'), max_len=10),
                    'confidence': f.get('confidence'),
                })

        ai = []
        for it in (m.get('actionable_insights') or [])[:10]:
            if isinstance(it, dict):
                ai.append({
                    'theme': _ensure_report_zh(it.get('theme'), max_len=40),
                    'rationale': _ensure_report_zh(it.get('rationale'), max_len=120),
                    'watch_metrics': _clean_list(it.get('watch_metrics') or [], max_items=8),
                })

        return {
            'market_sentiment_index': m.get('market_sentiment_index'),
            'risk_index': m.get('risk_index'),
            'industry_heat': ih,
            'policy_tone': {
                'summary': _ensure_report_zh((pt or {}).get('summary'), max_len=120),
                'bias': bias_zh,
            },
            'capital_flow_focus': _clean_list(m.get('capital_flow_focus') or [], max_items=10),
            'macro_factors': mf,
            'actionable_insights': ai,
            'suggest_global_watch': _clean_list(m.get('suggest_global_watch') or [], max_items=10),
            'extra_keywords': _clean_list(m.get('extra_keywords') or [], max_items=20),
            'summary': _ensure_report_zh(m.get('summary'), max_len=260),
        }

    stock_reports = [
        {**sr, 'report': _public_stock_report(sr.get('report'))}
        for sr in stock_reports
    ]
    macro = _public_macro(macro)

    macro_keywords_public: List[str] = []
    for kw in macro_keywords_unique:
        s_kw = _ensure_report_zh(kw, max_len=40)
        if s_kw and s_kw != '（已省略非中文引用）':
            macro_keywords_public.append(s_kw)
    extra_sections = [
        {
            'keyword': _ensure_report_zh(sec.get('keyword'), max_len=40),
            'analysis': _public_macro(sec.get('analysis') or {}),
        }
        for sec in (extra_sections or [])
        if isinstance(sec, dict)
    ]

    output = {
        "report_date": report_date.isoformat(),
        "started_at": started,
        "finished_at": finished,
        "top20_count": len(top20),
        "stock_reports": stock_reports,
        "macro": macro,
        "macro_extra": extra_sections,
        "macro_keywords_used": macro_keywords_public,
        "analytics": {
            "sentiment_distribution": sentiment_dist,
            "top_factor_frequency": top_factor_frequency,
            "factor_direction_counts": direction_counts
        },
        "config": {
            "SEARXNG_URL": SEARXNG_URL,
            "LLM": "azure" if HAS_AZURE else ("generic" if LLM_API_URL else "disabled"),
            "MOVERS_API_URL": MOVERS_API_URL,
            "AZURE_USE_RESPONSES": AZURE_USE_RESPONSES,
        }
    }
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    # 每日唯一文件：按日期覆盖（可通过 --date 刷新指定日期）
    json_path = os.path.join(OUTPUT_DIR, f"agent_report_{report_day}.json")
    md_path = os.path.join(OUTPUT_DIR, f"agent_report_{report_day}.md")
    if AGENT_REPORT_WRITE_FILES:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

    # Write separate metrics files (diagnostics only plus timestamp)
    if AGENT_METRICS_WRITE_FILES:
        try:
            metrics = {
                'timestamp': ts,
                'generated_at_utc': datetime.now(timezone.utc).isoformat(),
                'diagnostics': diagnostics,
                'version': 1
            }
            metrics_path = os.path.join(OUTPUT_DIR, f"agent_metrics_{ts}.json")
            with open(metrics_path, 'w', encoding='utf-8') as mf:
                json.dump(metrics, mf, ensure_ascii=False, indent=2)
            latest_metrics_path = os.path.join(OUTPUT_DIR, 'agent_metrics_latest.json')
            # atomic replace
            tmp_latest = latest_metrics_path + '.tmp'
            with open(tmp_latest, 'w', encoding='utf-8') as lm:
                json.dump(metrics, lm, ensure_ascii=False, indent=2)
            os.replace(tmp_latest, latest_metrics_path)
        except Exception as e:
            print(f"[metrics] 写入指标文件失败: {e}")

    # Markdown 生成
    def _zh_sentiment_label(s: Any) -> str:
        v = (str(s or '')).strip()
        if not v:
            return ''
        low = v.lower()
        mp = {
            'neutral': '中性',
            'positive': '正面',
            'negative': '负面',
            'bullish': '正面',
            'bearish': '负面',
        }
        return mp.get(low, v)

    def _zh_parse_mode(s: Any) -> str:
        v = (str(s or '')).strip()
        if not v:
            return ''
        low = v.lower()
        mp = {
            'direct': '直接',
            'heuristic': '启发式',
            'retry': '重试',
            'substring': '截取',
            'multi': '多段',
            'auto-repair': '修复',
            'retry-substring': '重试-截取',
            'no-news': '无新闻',
            'low-news': '低信息量',
        }
        return mp.get(low, v)

    def _fmt_factor_line(fct: Any) -> str:
        if isinstance(fct, dict):
            name = _ensure_report_zh((fct.get('name') or '').strip(), max_len=40)
            direction = (fct.get('direction') or '').strip()
            if direction in ('不确定', 'uncertain', 'unknown', ''):
                direction = '中性'
            else:
                low = direction.lower()
                direction = {'positive': '正面', 'negative': '负面', 'neutral': '中性'}.get(low, direction)
            evidence = _ensure_report_zh((fct.get('evidence') or '').strip(), max_len=80)
            return f"- {name} | {direction} | 权重={fct.get('weight')} | {evidence}"
        return f"- {fct}"

    lines: List[str] = []
    lines.append(f"# 涨跌Top20智能分析报告 {report_day}")
    lines.append("")
    lines.append("## 市场大势")
    if macro:
        lines.append(f"- 市场情绪指数: {macro.get('market_sentiment_index')}")
        lines.append(f"- 风险指数: {macro.get('risk_index')}")
    lines.append("")
    # 行业热度
    ih = macro.get('industry_heat', []) if isinstance(macro, dict) else []
    if ih:
        lines.append("### 行业热度 (前) ")
        for item in ih:
            if isinstance(item, dict):
                lines.append(f"- {item.get('industry')}: {item.get('heat')} 驱动: {', '.join(item.get('drivers') or [])}")
    # 宏观因子
    mf_list = macro.get('macro_factors', []) if isinstance(macro, dict) else []
    if mf_list:
        lines.append("\n### 宏观因子")
        for mf in mf_list:
            if isinstance(mf, dict):
                lines.append(f"- {mf.get('name')} ({mf.get('impact')}) 置信度={mf.get('confidence')}")
            else:
                lines.append(f"- {mf}")
    # 摘要
    lines.append("\n### 摘要")
    lines.append(_ensure_report_zh(macro.get('summary'), max_len=220))
    # 宏观主题命中次数
    if isinstance(macro, dict) and macro.get('theme_hits'):
        lines.append("\n### 宏观主题命中统计")
        for th, ct in sorted(macro.get('theme_hits').items(), key=lambda x: x[1], reverse=True):
            if ct:
                lines.append(f"- {th}: {ct}")

    # 额外补充
    if extra_sections:
        lines.append("\n### 额外补充分析")
        for sec in extra_sections:
            lines.append(f"#### 关键词: {sec.get('keyword')}")
            a = sec.get('analysis') or {}
            lines.append(f"- 情绪: {a.get('market_sentiment_index')} 风险: {a.get('risk_index')}")
            lines.append(f"- 摘要: {_ensure_report_zh(a.get('summary'), max_len=180)}")

    # 统计
    lines.append("\n## 分析统计")
    lines.append("### 情绪分布")
    total_sd = sum(sentiment_dist.values()) or 1
    for k,v in sentiment_dist.items():
        pct = round(v*100/total_sd,2)
        lines.append(f"- {_zh_sentiment_label(k)}: {v} ({pct}%)")
    if top_factor_frequency:
        lines.append("\n### 因子频次 (Top15)")
        for name, cnt in top_factor_frequency:
            lines.append(f"- {name}: {cnt}")
    # 因子方向统计
    lines.append("\n### 因子方向统计")
    merged_dir: Dict[str, int] = {}
    for k, v in direction_counts.items():
        kk = (k or '').strip()
        if kk in ('不确定', 'uncertain', 'unknown', ''):
            kk = '中性'
        merged_dir[kk] = merged_dir.get(kk, 0) + int(v or 0)
    for kk, v in merged_dir.items():
        lines.append(f"- {kk}: {v}")
    # 宏观关键词列出
    if macro_keywords_public:
        lines.append("\n### 触发宏观关键词")
        lines.append(", ".join(macro_keywords_public))
    # 诊断信息/解析模式/回退信息一律不写入报告正文，避免技术噪声与外语泄漏。

    # 个股
    lines.append("\n## 个股分析")
    for sr in stock_reports:
        lines.append(f"### {sr['name']} ({sr['symbol']}) 涨跌幅: {sr['pct_chg']} 新闻数: {sr['news_count']}")
        rep = sr.get('report') or {}
        lines.append(f"- 情绪: {_zh_sentiment_label(rep.get('sentiment_label'))} 分值: {rep.get('sentiment_score')}")
        lines.append(f"- 评分: {rep.get('score')}")
        factors = rep.get('factors') or []
        if factors:
            lines.append("- 因子:")
            for fct in factors:
                lines.append(_fmt_factor_line(fct))
        lines.append("- 摘要:")
        lines.append(_ensure_report_zh(rep.get('summary'), max_len=260))
        lines.append("")

    markdown_text = "\n".join(lines)
    if AGENT_REPORT_WRITE_FILES:
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown_text)

    # MongoDB 持久化：当不写本地文件时，默认要求写入成功（避免无落地）
    mongo_target: Optional[Tuple[str, str]] = None
    try:
        mongo_target = _maybe_upsert_daily_report_mongo(report_date, output, markdown_text)
    except Exception:
        mongo_target = None
    mongo_ok = mongo_target is not None
    if mongo_ok:
        try:
            db_name, coll_name = mongo_target
            print(f"[mongo] upsert ok db={db_name} coll={coll_name} report_date={report_date.isoformat()}")
        except Exception:
            pass

    # SQL 持久化（用于 /api/agent/daily/latest 默认读取）
    sql_ok = False
    try:
        sql_ok = _maybe_upsert_daily_report_sql(report_date, output, markdown_text)
    except Exception:
        sql_ok = False
    if sql_ok:
        try:
            print(f"[sql] upsert ok table=agent_daily_reports report_date={report_date.isoformat()}")
        except Exception:
            pass

    if not AGENT_REPORT_WRITE_FILES and not (mongo_ok or sql_ok):
        raise RuntimeError("MongoDB/SQL 写入均失败（且已关闭本地落盘）。请检查数据库连接与服务可用性，或临时设置 AGENT_REPORT_WRITE_FILES=1 以便落盘兜底。")

    if AGENT_REPORT_WRITE_FILES:
        print(f"\n报告已生成:\nJSON: {json_path}\nMarkdown: {md_path}")
        return {"json": json_path, "markdown": md_path, "mongo": mongo_ok}
    if mongo_ok and sql_ok:
        print("\n报告已写入 MongoDB + SQL（本地落盘已关闭）")
    elif sql_ok:
        print("\n报告已写入 SQL（本地落盘已关闭；Mongo 可能未启用或写入失败）")
    else:
        print("\n报告已写入 MongoDB（本地落盘已关闭；SQL 可能未启用或写入失败）")
    return {"json": None, "markdown": None, "mongo": mongo_ok, "sql": sql_ok}

if __name__ == "__main__":
    # Wrap execution to always emit SOME agent_report_*.json file even on fatal errors
    try:
        parser = argparse.ArgumentParser(description="Top20 日报生成（按日期唯一，支持写入 MongoDB）")
        parser.add_argument(
            "--probe-feeds",
            action="store_true",
            help="探测 RSS/Atom 可用性（抓取+解析条目数），不入库、不生成日报",
        )
        parser.add_argument(
            "--probe-feed-urls",
            type=str,
            default=None,
            help="逗号分隔的 feed URL 列表（覆盖环境变量 AGENT_GLOBAL_PRE_INGEST_MEDIA_FEED_URLS）",
        )
        parser.add_argument(
            "--pre-ingest-only",
            action="store_true",
            help="只运行全局预采集（官方披露 + RSS/OPML/站点发现）并退出，不生成日报",
        )
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="报告日期 YYYYMMDD（不传则默认今天；同一天会覆盖同一份文件，可用于刷新指定日期）",
        )
        args = parser.parse_args()

        if getattr(args, "probe_feeds", False):
            raw = (getattr(args, "probe_feed_urls", None) or '').strip()
            urls = [x.strip() for x in raw.split(',') if x.strip()] if raw else (AGENT_GLOBAL_PRE_INGEST_MEDIA_FEED_URLS or [])
            _probe_rss_feeds(urls)
            sys.exit(0)

        if getattr(args, "pre_ingest_only", False):
            _global_pre_ingest_sources()
            print("[pre-ingest-only] done")
            sys.exit(0)

        report_date = _parse_report_date_yyyymmdd(getattr(args, "date", None))
        agent_main(report_date=report_date)
    except SystemExit as se:
        # Allow explicit exits. Only emit fallback JSON for non-zero exits.
        # (e.g., argparse --help exits with code=0 and should not generate an error report)
        try:
            code = getattr(se, 'code', 0)
        except Exception:
            code = 0
        if code in (0, None):
            raise
        try:
            ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            json_path = os.path.join(OUTPUT_DIR, f"agent_report_{ts}_systemexit.json")
            err = {
                'error': f'SystemExit: {se}',
                'type': 'system_exit',
                'finished_at': datetime.now(timezone.utc).isoformat(),
                'fallback': 'error'
            }
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(err, f, ensure_ascii=False, indent=2)
            print(f"[agent-error] system exit fallback JSON: {json_path}")
        finally:
            raise
    except Exception as e:
        ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        tb = traceback.format_exc()
        # ensure a path for error fallback
        json_path = os.path.join(OUTPUT_DIR, f"agent_report_{ts}_error.json")
        err = {
            'error': str(e),
            'traceback': tb[-8000:],  # cap length
            'finished_at': datetime.now(timezone.utc).isoformat(),
            'fallback': 'error'
        }
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(err, f, ensure_ascii=False, indent=2)
            print(f"[agent-error] wrote error fallback JSON: {json_path}")
            # Emit a line that matches watcher pattern in main.py (contains 'agent_report_' & '.json')
            print(f"agent_report_error_json: {json_path}")
        except Exception as werr:
            print(f"[agent-error] failed to write fallback JSON: {werr}")
        # Non-zero exit to signal failure upstream (job will be marked failed but file still present)
        sys.exit(1)
