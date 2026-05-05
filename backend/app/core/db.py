"""
数据库与缓存连接管理模块（后端核心基础设施）

功能概述：
- 构建 PostgreSQL SQLAlchemy Engine 与会话工厂（SessionLocal）
- 提供 FastAPI 依赖（get_session）以便按请求获取/释放会话
- 提供可选的 Redis 客户端（get_redis_client），用于轻量级缓存/节流
- 初始化数据库表结构（init_database），并包含一段幂等的“轻迁移”示例

环境变量（.env 或系统环境）：
- POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_PORT / POSTGRES_DB
- REDIS_HOST / REDIS_PORT / REDIS_DB / REDIS_PASSWORD（可选）

注意事项：
- create_engine 使用 pool_pre_ping=True 以避免连接池中的死连接
- 轻迁移示例（watchlist.added_at）是幂等的 DO $$ 块，仅用于演示安全添加字段
"""

import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Redis 依赖（可选）；若未安装 redis-py，则相关功能将自动降级为 None
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

def get_db_url():
    """拼接 PostgreSQL 连接 URL（psycopg2 驱动）。

    返回格式：postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DB
    """
    user = os.getenv("POSTGRES_USER")
    pwd = os.getenv("POSTGRES_PASSWORD")
    host = os.getenv("POSTGRES_HOST", "db")
    # Allow explicit override via POSTGRES_PORT; otherwise choose sensible default
    # If host is localhost (or loopback), prefer 5433 which matches
    # docker-compose.local.yml mapping "5433:5432" used in local dev.
    env_port = os.getenv("POSTGRES_PORT")
    if env_port:
        port = env_port
    else:
        if host in ("localhost", "127.0.0.1", "::1"):
            port = "5433"
        else:
            port = "5432"
    db   = os.getenv("POSTGRES_DB")
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"

# 配置连接池参数，提高并发容忍度，避免 QueuePool 超时
# 可通过环境变量覆盖：DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT, DB_POOL_RECYCLE
def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

_POOL_SIZE = _int_env("DB_POOL_SIZE", 20)
_MAX_OVERFLOW = _int_env("DB_MAX_OVERFLOW", 40)
_POOL_TIMEOUT = _int_env("DB_POOL_TIMEOUT", 60)  # seconds
_POOL_RECYCLE = _int_env("DB_POOL_RECYCLE", 1800)  # seconds, recycle stale connections

engine = create_engine(
    get_db_url(),
    pool_pre_ping=True,
    future=True,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
    pool_timeout=_POOL_TIMEOUT,
    pool_recycle=_POOL_RECYCLE,
    pool_use_lifo=True,  # 高并发突发时降低等待尾部延迟
    connect_args={
        # 限制单条 SQL 执行时间，避免慢查询长期占用连接（单位毫秒）
        "options": f"-c statement_timeout={int(os.getenv('DB_STATEMENT_TIMEOUT_MS', '30000'))}"
    },
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

def get_session():
    """FastAPI 依赖：获取一个数据库会话。

    使用方式：在路径函数中注入依赖以便自动关闭连接。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_redis_client():
    """返回 Redis 客户端（如可用），否则返回 None。

    说明：
    - 使用 decode_responses=True，统一字符串读写
    - 将会尝试 PING 以验证连接可用性
    - 失败时打印提示并返回 None（不会抛出异常）
    """
    if not REDIS_AVAILABLE:
        return None
    
    try:
        host = os.getenv("REDIS_HOST", "localhost")  # 默认本机；容器内可按需配置为服务名
        port = int(os.getenv("REDIS_PORT", "6379"))
        db = int(os.getenv("REDIS_DB", "0"))
        password = os.getenv("REDIS_PASSWORD")
        
        client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True
        )
        # 连接探活（避免隐式失败）
        client.ping()
        return client
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return None

def init_database():
    """初始化数据库表结构（幂等）。

    - 使用 Base.metadata.create_all 创建缺失表
    - 示例性地添加 watchlist.added_at 字段（若不存在）：
      该 DO $$ 块是幂等且安全的（不影响已有数据）
    - 添加 stock_profiles.market 字段（若不存在）并自动识别市场
    """
    from ..core.models import Base
    try:
        # 使用 SQLAlchemy 创建所有表
        Base.metadata.create_all(bind=engine)
        # Safe, idempotent migrations
        try:
            # 确保 watchlist 表中存在 added_at 列（若没有则添加）
            with engine.begin() as conn:
                conn.execute(text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='watchlist' AND column_name='added_at'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN added_at TIMESTAMP DEFAULT NOW();
                        END IF;
                    END $$;
                    """
                ))
        except Exception as mig_err:
            print(f"Migration note (watchlist.added_at): {mig_err}")

            # Ensure fundflow_daily unique constraint exists (idempotent)
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        """
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM pg_constraint c
                                JOIN pg_class t ON c.conrelid = t.oid
                                JOIN pg_namespace n ON t.relnamespace = n.oid
                                WHERE c.contype = 'u' AND t.relname = 'fundflow_daily' AND array_to_string(c.conkey, ',') IS NOT NULL
                            ) THEN
                                BEGIN
                                    ALTER TABLE fundflow_daily ADD CONSTRAINT uq_fundflow_symbol_date UNIQUE (symbol, trade_date);
                                EXCEPTION WHEN duplicate_object THEN
                                    -- ignore
                                END;
                            END IF;
                        END $$;
                        """
                    ))
            except Exception:
                # best-effort only; ignore failures here
                pass
        
        # 添加 watchlist.pinned 字段（若不存在）
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='pinned'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN pinned BOOLEAN DEFAULT FALSE;
                            CREATE INDEX IF NOT EXISTS idx_watchlist_pinned ON watchlist(pinned);
                        END IF;
                    END $$;
                    """
                ))
        except Exception as mig_err:
            print(f"Migration note (watchlist.pinned): {mig_err}")

        # 补齐 watchlist 扩展字段（兼容旧库结构）
        # 这些字段已在 ORM 模型中定义；若数据库未迁移，会在 select(Watchlist) 时触发 UndefinedColumn。
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='status'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN status VARCHAR(20) DEFAULT 'active';
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='last_active_at'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN last_active_at TIMESTAMP NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='last_updated_at'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN last_updated_at TIMESTAMP NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='source'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN source VARCHAR(32) DEFAULT 'manual';
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='score'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN score DOUBLE PRECISION NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='investment_potential'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN investment_potential DOUBLE PRECISION NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='remove_suggested'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN remove_suggested BOOLEAN DEFAULT FALSE;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='remove_reason'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN remove_reason TEXT NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='last_analysis_at'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN last_analysis_at TIMESTAMP NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='watchlist' AND column_name='clean_rule_tag'
                        ) THEN
                            ALTER TABLE watchlist ADD COLUMN clean_rule_tag VARCHAR(100) NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM pg_indexes
                            WHERE schemaname = 'public' AND indexname = 'idx_watchlist_status'
                        ) THEN
                            CREATE INDEX idx_watchlist_status ON watchlist(status);
                        END IF;
                    END $$;
                    """
                ))
        except Exception as mig_err:
            print(f"Migration note (watchlist.extended_columns): {mig_err}")

        # 添加 stock_profiles.market 字段（若不存在）并自动填充
        try:
            with engine.begin() as conn:
                # 检查 market 列是否存在
                result = conn.execute(text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='stock_profiles' AND column_name='market'
                    )
                    """
                )).scalar()
                
                if not result:
                    print("Adding market column to stock_profiles...")
                    conn.execute(text(
                        """
                        ALTER TABLE stock_profiles
                        ADD COLUMN market VARCHAR(16) NOT NULL DEFAULT 'A股'
                        """
                    ))
                    conn.commit()
                    print("✓ market column added")
                    
                    # 自动识别并填充市场信息
                    print("Populating market field based on stock codes...")
                    conn.execute(text(
                        """
                        UPDATE stock_profiles
                        SET market = CASE
                            WHEN symbol ILIKE '%.HK' THEN '港股'
                            WHEN symbol ~ '^[A-Z]+$' THEN '美股'
                            ELSE 'A股'
                        END
                        """
                    ))
                    conn.commit()
                    print("✓ market field populated")
        except Exception as mig_err:
            print(f"Migration note (stock_profiles.market): {mig_err}")

        # 添加 stock_pool_members.source 字段（若不存在）
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='stock_pool_members' AND column_name='source'
                        ) THEN
                            ALTER TABLE stock_pool_members ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'top_movers';
                        END IF;
                    END $$;
                    """
                ))
        except Exception as mig_err:
            print(f"Migration note (stock_pool_members.source): {mig_err}")

        # 补齐 qe_signals 扩展字段（兼容旧库结构）
        # 这些字段已在 quant_engine/models 中定义；若旧库未迁移，
        # 会在 /api/quant/signals/ranked 与 /api/report/{sym}/insight 上触发 UndefinedColumn。
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name='qe_signals'
                        ) THEN
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='direction') THEN
                                ALTER TABLE qe_signals ADD COLUMN direction VARCHAR(20) NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='trigger_price') THEN
                                ALTER TABLE qe_signals ADD COLUMN trigger_price DOUBLE PRECISION NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='stop_loss') THEN
                                ALTER TABLE qe_signals ADD COLUMN stop_loss DOUBLE PRECISION NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='take_profit') THEN
                                ALTER TABLE qe_signals ADD COLUMN take_profit DOUBLE PRECISION NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='holding_period') THEN
                                ALTER TABLE qe_signals ADD COLUMN holding_period INTEGER NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='signal_source') THEN
                                ALTER TABLE qe_signals ADD COLUMN signal_source VARCHAR(50) NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='event_id') THEN
                                ALTER TABLE qe_signals ADD COLUMN event_id VARCHAR(64) NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='regime') THEN
                                ALTER TABLE qe_signals ADD COLUMN regime VARCHAR(50) NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='confidence') THEN
                                ALTER TABLE qe_signals ADD COLUMN confidence DOUBLE PRECISION NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='direction_prob_up') THEN
                                ALTER TABLE qe_signals ADD COLUMN direction_prob_up DOUBLE PRECISION NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='predicted_return') THEN
                                ALTER TABLE qe_signals ADD COLUMN predicted_return DOUBLE PRECISION NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='factors_json') THEN
                                ALTER TABLE qe_signals ADD COLUMN factors_json JSONB NULL;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name='qe_signals' AND column_name='model_version_id') THEN
                                ALTER TABLE qe_signals ADD COLUMN model_version_id BIGINT NULL;
                            END IF;
                        END IF;
                    END $$;
                    """
                ))
        except Exception as mig_err:
            print(f"Migration note (qe_signals.extended_columns): {mig_err}")

        print("✓ Database tables created/updated successfully")
    except Exception as e:
        print(f"✗ Database initialization error: {e}")
        raise
