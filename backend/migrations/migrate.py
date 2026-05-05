#!/usr/bin/env python3
"""Versioned SQL migration runner.

Usage:
    cd backend
    python migrations/migrate.py status
    python migrations/migrate.py upgrade
    python migrations/migrate.py downgrade --steps 1
    python migrations/migrate.py downgrade --target 0001_add_last_updated_at_to_watchlist

Migration files follow this naming convention:
    <version>.up.sql
    <version>.down.sql
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.core.db import get_db_url
except Exception:  # pragma: no cover - fallback for standalone envs
    get_db_url = None

DATABASE_URL = os.getenv("DATABASE_URL") or (
    get_db_url() if get_db_url else "postgresql://aistock:aistock@localhost:5432/aistock"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    version: str
    up_path: Path
    down_path: Path | None


def _masked_url(url: str) -> str:
    if "@" not in url:
        return url
    prefix, suffix = url.rsplit("@", 1)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else "postgresql"
    return f"{scheme}://***:***@{suffix}"


def _load_migrations() -> list[Migration]:
    migrations: list[Migration] = []
    for up_path in sorted(MIGRATIONS_DIR.glob("*.up.sql")):
        version = up_path.name[: -len(".up.sql")]
        down_path = MIGRATIONS_DIR / f"{version}.down.sql"
        migrations.append(Migration(version=version, up_path=up_path, down_path=down_path if down_path.exists() else None))
    return migrations


def _ensure_schema_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(160) PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))


def _applied_versions(conn) -> list[str]:
    rows = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version ASC")).fetchall()
    return [row[0] for row in rows]


def _execute_sql_file(conn, path: Path) -> None:
    sql = path.read_text(encoding="utf-8").strip()
    if sql:
        conn.execute(text(sql))


def status(database_url: str = DATABASE_URL) -> bool:
    engine = create_engine(database_url, future=True)
    migrations = _load_migrations()
    with engine.begin() as conn:
        _ensure_schema_table(conn)
        applied = set(_applied_versions(conn))
    logger.info("数据库: %s", _masked_url(database_url))
    if not migrations:
        logger.info("未发现 *.up.sql 迁移文件")
        return True
    for migration in migrations:
        mark = "applied" if migration.version in applied else "pending"
        logger.info("%-48s %s", migration.version, mark)
    return True


def upgrade(database_url: str = DATABASE_URL, target: str | None = None) -> bool:
    engine = create_engine(database_url, future=True)
    migrations = _load_migrations()
    if target:
        migrations = [migration for migration in migrations if migration.version <= target]
    try:
        with engine.begin() as conn:
            _ensure_schema_table(conn)
            applied = set(_applied_versions(conn))
            pending = [migration for migration in migrations if migration.version not in applied]
            if not pending:
                logger.info("没有待执行迁移")
                return True
            for migration in pending:
                logger.info("执行升级迁移: %s", migration.version)
                _execute_sql_file(conn, migration.up_path)
                conn.execute(
                    text("INSERT INTO schema_migrations(version) VALUES (:version) ON CONFLICT (version) DO NOTHING"),
                    {"version": migration.version},
                )
        logger.info("升级完成，共执行 %d 个迁移", len(pending))
        return True
    except Exception as exc:
        logger.error("升级失败: %s", exc, exc_info=True)
        return False


def downgrade(database_url: str = DATABASE_URL, target: str | None = None, steps: int = 1) -> bool:
    engine = create_engine(database_url, future=True)
    migrations_by_version = {migration.version: migration for migration in _load_migrations()}
    try:
        with engine.begin() as conn:
            _ensure_schema_table(conn)
            applied = _applied_versions(conn)
            if target:
                rollback_versions = [version for version in reversed(applied) if version > target]
            else:
                rollback_versions = list(reversed(applied))[: max(steps, 1)]
            if not rollback_versions:
                logger.info("没有待回滚迁移")
                return True
            for version in rollback_versions:
                migration = migrations_by_version.get(version)
                if migration is None or migration.down_path is None:
                    raise RuntimeError(f"缺少回滚脚本: {version}.down.sql")
                logger.info("执行回滚迁移: %s", version)
                _execute_sql_file(conn, migration.down_path)
                conn.execute(text("DELETE FROM schema_migrations WHERE version = :version"), {"version": version})
        logger.info("回滚完成，共执行 %d 个迁移", len(rollback_versions))
        return True
    except Exception as exc:
        logger.error("回滚失败: %s", exc, exc_info=True)
        return False


def migrate(database_url: str = DATABASE_URL) -> bool:
    return upgrade(database_url)


def main() -> int:
    parser = argparse.ArgumentParser(description="AIStock versioned SQL migration runner")
    parser.add_argument("command", nargs="?", choices=["status", "upgrade", "downgrade"], default="upgrade")
    parser.add_argument("--target", help="目标迁移版本；upgrade 执行到该版本，downgrade 回滚到该版本")
    parser.add_argument("--steps", type=int, default=1, help="downgrade 未指定 target 时回滚步数")
    args = parser.parse_args()

    logger.info("数据库: %s", _masked_url(DATABASE_URL))
    if args.command == "status":
        ok = status(DATABASE_URL)
    elif args.command == "downgrade":
        ok = downgrade(DATABASE_URL, target=args.target, steps=args.steps)
    else:
        ok = upgrade(DATABASE_URL, target=args.target)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
