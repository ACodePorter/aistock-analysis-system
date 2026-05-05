"""刷新股票池 (最小实现)。

调用 `app.services.stock_pool_service.daily_top20_to_pool`，该函数会：
    - 读取 A 股实时快照 / EOD 数据
    - 选出 Top20 活跃标的
    - UPSERT 到 `stock_pool_members`，触发画像异步补全

由 main.py 在 Agent 日报成功后 best-effort 触发；失败不影响主流程。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s update_stock_pool %(message)s",
)
logger = logging.getLogger("update_stock_pool")


def main() -> int:
    try:
        from app.services.stock_pool_service import daily_top20_to_pool  # type: ignore
    except Exception as exc:
        logger.error("import stock_pool_service failed: %s", exc, exc_info=True)
        return 1
    try:
        result = daily_top20_to_pool()
        logger.info("daily_top20_to_pool result: %s", result)
        return 0
    except Exception as exc:
        logger.error("daily_top20_to_pool failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
