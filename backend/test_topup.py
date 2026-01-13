import os
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).resolve().parent))

# Simulate the variable definition
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
                    print(f"[env-debug] setting AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={v}")
                os.environ[k] = v
    except Exception as e:
        print(f"[env] 加载 .env 警告: {e}")

_load_dotenv()

# Global pre-ingest (build a larger DB pool before daily analysis)
AGENT_GLOBAL_PRE_INGEST = os.getenv('AGENT_GLOBAL_PRE_INGEST', '1') in ('1', 'true', 'yes')
env_value = os.getenv('AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A', '1')
AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A = env_value in ('1', 'true', 'yes')
print(f"[var-debug] env_value='{env_value}', AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}")

# Mock the function
def _topup_official_for_symbol(symbol: str) -> int:
    """针对单只股票，触发官方披露补池（SSE/SZSE/CNINFO/CSRC），返回新增条目数。

    直接实现RSS发现和抓取，避免调用后端API导致timeout。
    """
    print(f"[topup-debug] BEFORE CHECK: symbol={symbol}, AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}, type={type(AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A)}")
    print(f"[topup-debug] checking: symbol={symbol}, AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}, type={type(AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A)}")
    if not symbol or not AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A:
        print(f"[topup-debug] skipped: symbol={symbol}, enabled={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}")
        return 0
    return 1

# Test
result = _topup_official_for_symbol("000001.SZ")
print(f"Result: {result}")