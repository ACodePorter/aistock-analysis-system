#!/usr/bin/env python3
"""
企业档案定时更新调度器

功能：
1. 每周定时执行企业档案更新任务
2. 区分初始化和增量更新
3. 管理企业状态（正常/退市）
4. 记录企业变更历史
5. 智能判断是否需要更新

作者: AI Assistant
日期: 2025-11-30
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import UpdateOne

from .company_profile_service import CompanyProfileSearchService

logger = logging.getLogger(__name__)


class ProfileStatus(str, Enum):
    """企业档案状态"""
    UNINITIALIZED = "uninitialized"  # 未初始化
    ACTIVE = "active"                # 正常运营
    DELISTED = "delisted"            # 已退市
    SUSPENDED = "suspended"          # 暂停交易
    MERGED = "merged"                # 已合并
    BANKRUPT = "bankrupt"            # 已破产


class ChangeType(str, Enum):
    """变更类型"""
    INITIALIZATION = "initialization"          # 初始化
    LEADERSHIP_CHANGE = "leadership_change"    # 领导层变更
    BUSINESS_CHANGE = "business_change"        # 业务变更
    DELISTING = "delisting"                    # 退市
    FINANCIAL_CHANGE = "financial_change"      # 财务重大变化
    MERGER = "merger"                          # 合并重组
    OTHER = "other"                            # 其他


class CompanyProfileScheduler:
    """
    企业档案定时更新调度器
    
    负责管理企业档案的定期更新、状态追踪和变更历史记录
    """
    
    def __init__(
        self,
        mongodb_client: AsyncIOMotorClient,
        db_name: str = "aistock",
        collection_name: str = "company_profiles_managed"
    ):
        """
        初始化调度器
        
        Args:
            mongodb_client: MongoDB 异步客户端
            db_name: 数据库名称
            collection_name: 集合名称
        """
        self.db: AsyncIOMotorDatabase = mongodb_client[db_name]
        self.collection = self.db[collection_name]
        self.profile_service = CompanyProfileSearchService()
        
        logger.info(f"✅ 企业档案调度器初始化完成")
        logger.info(f"   数据库: {db_name}")
        logger.info(f"   集合: {collection_name}")
    
    async def initialize_indexes(self):
        """创建必要的索引"""
        await self.collection.create_index("stock_code", unique=True)
        await self.collection.create_index("status")
        await self.collection.create_index("last_updated")
        await self.collection.create_index([("company_name", "text")])
        logger.info("✅ 数据库索引创建完成")
    
    async def get_company_profile(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        获取企业档案
        
        Args:
            stock_code: 股票代码
            
        Returns:
            企业档案文档，不存在则返回 None
        """
        return await self.collection.find_one({"stock_code": stock_code})
    
    async def is_company_initialized(self, stock_code: str) -> bool:
        """
        检查企业是否已初始化
        
        Args:
            stock_code: 股票代码
            
        Returns:
            True 表示已初始化，False 表示未初始化
        """
        profile = await self.get_company_profile(stock_code)
        return profile is not None and profile.get("status") != ProfileStatus.UNINITIALIZED
    
    async def should_skip_company(self, stock_code: str) -> bool:
        """
        判断是否应该跳过该企业（退市、破产等）
        
        Args:
            stock_code: 股票代码
            
        Returns:
            True 表示应跳过，False 表示继续处理
        """
        profile = await self.get_company_profile(stock_code)
        if not profile:
            return False
        
        skip_statuses = {
            ProfileStatus.DELISTED,
            ProfileStatus.BANKRUPT,
            ProfileStatus.MERGED
        }
        
        return profile.get("status") in skip_statuses
    
    async def initialize_company_profile(
        self,
        stock_code: str,
        company_name: str
    ) -> Dict[str, Any]:
        """
        初始化企业档案（首次创建完整档案）
        
        Args:
            stock_code: 股票代码
            company_name: 企业名称
            
        Returns:
            创建的档案文档
        """
        logger.info(f"📝 初始化企业档案: {company_name} ({stock_code})")
        
        # 使用 CompanyProfileSearchService 获取完整档案
        search_result = await self.profile_service.search_company_profile(company_name)
        
        if not search_result or not search_result.get("success"):
            logger.warning(f"⚠️ 无法获取 {company_name} 的档案信息")
            profile_data = {}
        else:
            profile_data = search_result.get("profile", {})
        
        # 构建初始档案文档
        now = datetime.utcnow()
        profile_doc = {
            "stock_code": stock_code,
            "company_name": company_name,
            "status": ProfileStatus.ACTIVE,
            "initialized_at": now,
            "last_updated": now,
            "profile": profile_data,
            "change_history": [
                {
                    "timestamp": now,
                    "change_type": ChangeType.INITIALIZATION,
                    "description": "企业档案初始化",
                    "details": {
                        "sources": search_result.get("sources", []) if search_result else [],
                        "confidence": search_result.get("confidence", 0) if search_result else 0
                    }
                }
            ],
            "update_metadata": {
                "update_count": 1,
                "last_significant_change": now,
                "next_scheduled_update": now + timedelta(days=7)
            }
        }
        
        # 保存到数据库
        await self.collection.update_one(
            {"stock_code": stock_code},
            {"$set": profile_doc},
            upsert=True
        )
        
        logger.info(f"✅ {company_name} 档案初始化完成")
        return profile_doc
    
    async def update_company_profile(
        self,
        stock_code: str,
        company_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        更新企业档案（增量更新）
        
        仅在检测到重大变更时才记录历史
        
        Args:
            stock_code: 股票代码
            company_name: 企业名称（可选，如果不提供则从已有档案获取）
            
        Returns:
            更新后的档案文档
        """
        # 获取现有档案
        existing_profile = await self.get_company_profile(stock_code)
        
        if not existing_profile:
            # 如果档案不存在，执行初始化
            if not company_name:
                raise ValueError(f"股票代码 {stock_code} 的档案不存在，且未提供企业名称")
            return await self.initialize_company_profile(stock_code, company_name)
        
        company_name = company_name or existing_profile.get("company_name")
        logger.info(f"🔄 更新企业档案: {company_name} ({stock_code})")
        
        # 获取最新信息
        search_result = await self.profile_service.search_company_profile(company_name)
        
        if not search_result or not search_result.get("success"):
            logger.warning(f"⚠️ 无法获取 {company_name} 的最新信息，跳过本次更新")
            return existing_profile
        
        new_profile_data = search_result.get("profile", {})
        old_profile_data = existing_profile.get("profile", {})
        
        # 检测重大变更
        changes = self._detect_significant_changes(old_profile_data, new_profile_data)
        
        now = datetime.utcnow()
        update_doc = {
            "last_updated": now,
            "profile": new_profile_data,
            "$inc": {"update_metadata.update_count": 1}
        }
        
        if changes:
            # 有重大变更，记录历史
            logger.info(f"📌 检测到 {len(changes)} 项重大变更")
            
            change_records = []
            for change in changes:
                change_record = {
                    "timestamp": now,
                    "change_type": change["type"],
                    "description": change["description"],
                    "details": change.get("details", {})
                }
                change_records.append(change_record)
                logger.info(f"   - {change['description']}")
            
            update_doc["$push"] = {
                "change_history": {"$each": change_records}
            }
            update_doc["update_metadata.last_significant_change"] = now
            
            # 检查是否有退市等特殊状态变更
            for change in changes:
                if change["type"] == ChangeType.DELISTING:
                    update_doc["status"] = ProfileStatus.DELISTED
                    logger.warning(f"⚠️ {company_name} 已退市，更新状态")
        else:
            logger.info(f"✓ 无重大变更，仅更新时间戳")
        
        # 更新下次调度时间
        update_doc["update_metadata.next_scheduled_update"] = now + timedelta(days=7)
        
        # 执行更新
        await self.collection.update_one(
            {"stock_code": stock_code},
            update_doc
        )
        
        # 返回更新后的文档
        updated_profile = await self.get_company_profile(stock_code)
        logger.info(f"✅ {company_name} 档案更新完成")
        
        return updated_profile
    
    def _detect_significant_changes(
        self,
        old_profile: Dict[str, Any],
        new_profile: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        检测重大变更
        
        Args:
            old_profile: 旧档案数据
            new_profile: 新档案数据
            
        Returns:
            变更列表
        """
        changes = []
        
        # 检查关键字段的变更
        key_fields = {
            "industry": "行业分类",
            "sector": "细分行业",
            "headquarters": "总部地址",
            "business_scope": "主营业务",
            "employees": "员工人数",
            "registered_capital": "注册资本"
        }
        
        for field, label in key_fields.items():
            old_value = old_profile.get(field)
            new_value = new_profile.get(field)
            
            if old_value != new_value and new_value is not None:
                # 判断是否为实质性变更（而非仅格式差异）
                if self._is_substantial_change(old_value, new_value, field):
                    changes.append({
                        "type": ChangeType.BUSINESS_CHANGE,
                        "description": f"{label}变更",
                        "details": {
                            "field": field,
                            "old_value": old_value,
                            "new_value": new_value
                        }
                    })
        
        # 检查描述的重大更新（使用语义相似度）
        old_desc = old_profile.get("description", "")
        new_desc = new_profile.get("description", "")
        
        if old_desc and new_desc:
            # 简单检查：长度变化超过20%或包含关键词
            desc_change_ratio = abs(len(new_desc) - len(old_desc)) / max(len(old_desc), 1)
            critical_keywords = ["退市", "破产", "重组", "合并", "收购", "董事长", "CEO"]
            
            has_critical_keyword = any(kw in new_desc for kw in critical_keywords)
            
            if desc_change_ratio > 0.2 or has_critical_keyword:
                change_type = ChangeType.OTHER
                
                if "退市" in new_desc:
                    change_type = ChangeType.DELISTING
                elif any(kw in new_desc for kw in ["董事长", "CEO"]):
                    change_type = ChangeType.LEADERSHIP_CHANGE
                
                changes.append({
                    "type": change_type,
                    "description": "企业描述重大更新",
                    "details": {
                        "field": "description",
                        "change_indicators": [kw for kw in critical_keywords if kw in new_desc]
                    }
                })
        
        return changes
    
    def _is_substantial_change(
        self,
        old_value: Any,
        new_value: Any,
        field: str
    ) -> bool:
        """
        判断是否为实质性变更（排除格式差异）
        
        Args:
            old_value: 旧值
            new_value: 新值
            field: 字段名
            
        Returns:
            True 表示实质性变更
        """
        if old_value is None or new_value is None:
            return True
        
        # 字符串类型：标准化后比较
        if isinstance(old_value, str) and isinstance(new_value, str):
            old_normalized = old_value.strip().replace(" ", "").replace("\n", "")
            new_normalized = new_value.strip().replace(" ", "").replace("\n", "")
            return old_normalized != new_normalized
        
        # 数值类型：检查变化幅度
        if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            # 变化超过10%才算实质性变更
            if old_value == 0:
                return new_value != 0
            change_ratio = abs(new_value - old_value) / abs(old_value)
            return change_ratio > 0.1
        
        return old_value != new_value
    
    async def mark_company_delisted(
        self,
        stock_code: str,
        delisting_reason: str = "退市"
    ):
        """
        标记企业为退市状态
        
        Args:
            stock_code: 股票代码
            delisting_reason: 退市原因
        """
        logger.warning(f"🚫 标记企业退市: {stock_code}")
        
        now = datetime.utcnow()
        await self.collection.update_one(
            {"stock_code": stock_code},
            {
                "$set": {
                    "status": ProfileStatus.DELISTED,
                    "last_updated": now
                },
                "$push": {
                    "change_history": {
                        "timestamp": now,
                        "change_type": ChangeType.DELISTING,
                        "description": delisting_reason,
                        "details": {}
                    }
                }
            }
        )
        
        logger.info(f"✅ {stock_code} 已标记为退市状态")
    
    async def run_weekly_update(
        self,
        stock_codes: Optional[List[str]] = None,
        batch_size: int = 10
    ):
        """
        执行每周定时更新任务
        
        Args:
            stock_codes: 要更新的股票代码列表（None 表示更新所有活跃企业）
            batch_size: 批次大小
        """
        logger.info("🚀 开始执行每周企业档案更新任务")
        start_time = datetime.utcnow()
        
        # 确定要更新的企业列表
        if stock_codes is None:
            # 获取所有需要更新的企业（排除退市等状态）
            cursor = self.collection.find({
                "status": {"$nin": [
                    ProfileStatus.DELISTED,
                    ProfileStatus.BANKRUPT,
                    ProfileStatus.MERGED
                ]}
            })
            
            companies = await cursor.to_list(length=None)
            stock_codes = [c["stock_code"] for c in companies]
        
        total = len(stock_codes)
        logger.info(f"📊 待更新企业数量: {total}")
        
        # 统计信息
        stats = {
            "total": total,
            "initialized": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0
        }
        
        # 分批处理
        for i in range(0, total, batch_size):
            batch = stock_codes[i:i + batch_size]
            logger.info(f"📦 处理批次 {i // batch_size + 1}/{(total + batch_size - 1) // batch_size}")
            
            for stock_code in batch:
                try:
                    # 检查是否应跳过
                    if await self.should_skip_company(stock_code):
                        logger.info(f"⏭️ 跳过 {stock_code}（已退市或其他特殊状态）")
                        stats["skipped"] += 1
                        continue
                    
                    # 检查是否已初始化
                    is_initialized = await self.is_company_initialized(stock_code)
                    
                    if not is_initialized:
                        # 执行初始化
                        profile = await self.get_company_profile(stock_code)
                        company_name = profile.get("company_name") if profile else stock_code
                        await self.initialize_company_profile(stock_code, company_name)
                        stats["initialized"] += 1
                    else:
                        # 执行增量更新
                        await self.update_company_profile(stock_code)
                        stats["updated"] += 1
                    
                    # 避免请求过快
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"❌ 处理 {stock_code} 时发生错误: {e}")
                    stats["failed"] += 1
                    continue
        
        # 输出统计信息
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        logger.info("=" * 60)
        logger.info("✅ 每周更新任务完成")
        logger.info(f"   总计: {stats['total']} 家企业")
        logger.info(f"   初始化: {stats['initialized']} 家")
        logger.info(f"   更新: {stats['updated']} 家")
        logger.info(f"   跳过: {stats['skipped']} 家")
        logger.info(f"   失败: {stats['failed']} 家")
        logger.info(f"   耗时: {elapsed:.1f} 秒")
        logger.info("=" * 60)
        
        return stats


# ==================== 使用示例 ====================

async def example_usage():
    """使用示例"""
    from motor.motor_asyncio import AsyncIOMotorClient
    
    # 连接 MongoDB
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    
    # 创建调度器
    scheduler = CompanyProfileScheduler(client)
    
    # 初始化索引
    await scheduler.initialize_indexes()
    
    # 示例1：初始化单个企业档案
    await scheduler.initialize_company_profile("600519", "贵州茅台")
    
    # 示例2：更新单个企业档案
    await scheduler.update_company_profile("600519")
    
    # 示例3：标记企业退市
    await scheduler.mark_company_delisted("000001", "因业绩不达标被强制退市")
    
    # 示例4：执行每周批量更新
    stock_codes = ["600519", "000858", "600036"]
    await scheduler.run_weekly_update(stock_codes)
    
    # 关闭连接
    client.close()


if __name__ == "__main__":
    asyncio.run(example_usage())
