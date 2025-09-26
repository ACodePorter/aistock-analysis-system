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
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB")
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"

engine = create_engine(get_db_url(), pool_pre_ping=True, future=True)
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
    """
    from .models import Base
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
            print(f"Migration note: {mig_err}")
        print("✓ Database tables created/updated successfully")
    except Exception as e:
        print(f"✗ Database initialization error: {e}")
        raise
