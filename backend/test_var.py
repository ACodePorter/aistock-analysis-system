import os
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).resolve().parent))

# Test variable definition
AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A = os.getenv('AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A', '1') in ('1', 'true', 'yes')
print(f"Initial: AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}")

# Test function
def test_topup(symbol: str) -> int:
    print(f"test_topup: symbol={symbol}, AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}")
    if not symbol or not AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A:
        print(f"skipped: symbol={symbol}, enabled={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}")
        return 0
    return 1

# Test
result = test_topup("000001.SZ")
print(f"Result: {result}")