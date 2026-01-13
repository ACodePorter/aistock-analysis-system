import os
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).resolve().parent))

# Simulate the beginning of top20_llm_agent_full.py
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
if os.getenv('AGENT_DEBUG_LOG', '0') == '1':
    print(f"[var-debug] env_value='{env_value}', AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}")
    with open('debug_env2.txt', 'w') as f:
        f.write(f"AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A env={os.getenv('AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A', 'DEFAULT')}, value={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}\n")
    print(f"Final: AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A={AGENT_GLOBAL_PRE_INGEST_OFFICIAL_A}")