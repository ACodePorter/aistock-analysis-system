"""
数据库迁移脚本：为 StockProfile 添加验证字段
"""

import sys
from sqlalchemy import Column, String, Boolean, Text, TIMESTAMP, DateTime, inspect, text
from sqlalchemy.orm import Session
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_stock_profile_validation_fields():
    """添加 Profile 验证字段到 stock_profiles 表"""
    
    from backend.app.db import engine, SessionLocal
    
    try:
        with SessionLocal() as db:
            # 检查表是否存在
            inspector = inspect(engine)
            
            if "stock_profiles" not in inspector.get_table_names():
                logger.error("❌ stock_profiles 表不存在")
                return False
            
            # 检查字段是否存在
            columns = inspector.get_columns("stock_profiles")
            column_names = [col["name"] for col in columns]
            
            migration_needed = False
            
            # 需要添加的字段
            new_fields = {
                "is_valid": "是否有效",
                "validation_status": "验证状态",
                "validation_reason": "验证原因",
                "last_validated_at": "最后验证时间"
            }
            
            # 检查哪些字段需要添加
            fields_to_add = []
            for field_name, description in new_fields.items():
                if field_name not in column_names:
                    migration_needed = True
                    fields_to_add.append((field_name, description))
            
            if not migration_needed:
                logger.info("✅ 所有验证字段已存在，无需迁移")
                return True
            
            # 执行迁移
            logger.info(f"开始迁移，需添加 {len(fields_to_add)} 个字段")
            
            for field_name, description in fields_to_add:
                try:
                    if field_name == "is_valid":
                        # ALTER TABLE stock_profiles ADD COLUMN is_valid BOOLEAN DEFAULT true
                        db.execute(text("""
                            ALTER TABLE stock_profiles 
                            ADD COLUMN is_valid BOOLEAN DEFAULT true
                        """))
                        logger.info(f"✅ 添加字段: {field_name} ({description})")
                    
                    elif field_name == "validation_status":
                        # ALTER TABLE stock_profiles ADD COLUMN validation_status VARCHAR(50)
                        db.execute(text("""
                            ALTER TABLE stock_profiles 
                            ADD COLUMN validation_status VARCHAR(50) DEFAULT NULL
                        """))
                        logger.info(f"✅ 添加字段: {field_name} ({description})")
                    
                    elif field_name == "validation_reason":
                        # ALTER TABLE stock_profiles ADD COLUMN validation_reason TEXT
                        db.execute(text("""
                            ALTER TABLE stock_profiles 
                            ADD COLUMN validation_reason TEXT DEFAULT NULL
                        """))
                        logger.info(f"✅ 添加字段: {field_name} ({description})")
                    
                    elif field_name == "last_validated_at":
                        # ALTER TABLE stock_profiles ADD COLUMN last_validated_at TIMESTAMP
                        db.execute(text("""
                            ALTER TABLE stock_profiles 
                            ADD COLUMN last_validated_at TIMESTAMP DEFAULT NULL
                        """))
                        logger.info(f"✅ 添加字段: {field_name} ({description})")
                
                except Exception as e:
                    if "already exists" in str(e):
                        logger.info(f"⚠️  字段已存在: {field_name}")
                    else:
                        logger.error(f"❌ 添加字段失败: {field_name} - {str(e)}")
            
            # 添加索引
            try:
                db.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_stock_profile_is_valid 
                    ON stock_profiles(is_valid)
                """))
                logger.info("✅ 添加索引: idx_stock_profile_is_valid")
            except Exception as e:
                if "already exists" in str(e):
                    logger.info("⚠️  索引已存在: idx_stock_profile_is_valid")
                else:
                    logger.error(f"❌ 添加索引失败: {str(e)}")
            
            db.commit()
            logger.info("✅ 迁移完成")
            return True
            
    except Exception as e:
        logger.error(f"❌ 迁移失败: {str(e)}")
        return False


if __name__ == "__main__":
    success = migrate_stock_profile_validation_fields()
    sys.exit(0 if success else 1)
