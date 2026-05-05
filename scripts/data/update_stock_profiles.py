#!/usr/bin/env python3
"""
股票信息批量更新脚本

功能说明：
1. 检查现有股票库中的symbol和company_name一致性
2. 通过三方API（AkShare/TuShare）获取最新股票信息
3. 使用本地 Qwen3-4B 模型进行公司名称校对和验证
4. 通过搜索引擎补充缺失信息
5. 批量更新StockProfile数据库

使用方式：
    python backend/scripts/update_stock_profiles.py [--dry-run] [--limit 100] [--market A股]

参数说明：
    --dry-run       : 演练模式，不实际更新数据库
    --limit N       : 限制处理的股票数量（默认不限制）
    --market TYPE   : 只处理特定市场的股票（A股/港股/美股/全部）
    --force         : 强制更新所有股票（包括已有有效company_name的）

注意：
    - 需要启动本地 LM Studio 服务（http://localhost:1234/v1）
    - 已安装 Qwen2-4B-Instruct 或 Qwen3-4B 模型
"""

import sys
import os
import asyncio
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
import json

# 添加后端路径到 Python 搜索路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

# 确保日志目录存在
log_dir = os.path.join(backend_dir, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'update_stock_profiles.log')

from sqlalchemy import select
from sqlalchemy.orm import Session

# 导入项目模块
from app.core.db import SessionLocal
from app.core.models import StockProfile, Watchlist
from app.data.data_source import get_stock_info, normalize_symbol
from app.utils.stock_profile_validator import StockProfileValidator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


industry_map = {}

class StockProfileUpdater:
    """股票信息批量更新器"""
    
    def __init__(self, dry_run=False, limit=None, market="全部", force=False):
        """
        初始化更新器
        
        Args:
            dry_run: 演练模式，不实际更新数据库
            limit: 限制处理的股票数量
            market: 处理的市场类型（A股/港股/美股/全部）
            force: 强制更新所有股票
        """
        self.session_factory = SessionLocal
        self.dry_run = dry_run
        self.limit = limit
        self.market = market
        self.force = force
        
        # 初始化新闻搜索服务（用于补充公司信息）
        try:
            from app.news.news_service import NewsSearchService
            self.search_service = NewsSearchService()
            logger.debug("✅ 新闻搜索服务已初始化")
        except Exception as e:
            logger.warning(f"⚠️ 新闻搜索服务初始化失败: {e}，将跳过搜索功能")
            self.search_service = None
        
        # 本地 Qwen3-4B 模型会在需要时动态导入
        # 不在初始化时预加载，以避免不必要的开销
        logger.info("✅ 已配置使用本地 Qwen3-4B 模型进行公司名称校对")
        
        # 初始化验证器（需要传入数据库session）
        try:
            db = self.session_factory()
            self.validator = StockProfileValidator(db)
            self.db_for_validator = db
        except Exception as e:
            logger.warning(f"⚠️ 验证器初始化失败: {e}，将跳过验证")
            self.validator = None
            self.db_for_validator = None
        
        # 统计信息
        self.stats = {
            "total_checked": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "api_errors": 0,
            "llm_validations": 0
        }
    
    def get_stocks_to_update(self) -> List[StockProfile]:
        """获取需要更新的股票列表"""
        session = self.session_factory()
        try:
            query = select(StockProfile)
            
            # 市场过滤
            if self.market != "全部":
                query = query.where(StockProfile.market == self.market)
            
            # 非强制模式：只获取company_name为空或无效的股票
            if not self.force:
                from sqlalchemy import or_
                query = query.where(
                    or_(
                        StockProfile.company_name.is_(None),
                        StockProfile.company_name == '',
                        StockProfile.company_name == StockProfile.symbol,
                        StockProfile.is_valid == False
                    )
                )
            
            # 排序：优先处理最近未更新的
            query = query.order_by(StockProfile.updated_at.asc())
            
            # 应用limit
            if self.limit:
                query = query.limit(self.limit)
            
            stocks = session.execute(query).scalars().all()
            logger.info(f"📊 获取待更新股票数: {len(stocks)}")
            
            return stocks
        finally:
            session.close()
    
    async def fetch_stock_info_from_api(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        从三方API获取股票信息
        
        Args:
            symbol: 股票代码
            
        Returns:
            股票信息字典，包含 name, market, industry, sector 等字段
        """
        try:
            stock_info = get_stock_info(symbol)
            if stock_info:
                logger.debug(f"✅ API获取成功 ({symbol}): {stock_info.get('name')}")
                return stock_info
            else:
                logger.warning(f"⚠️ API未找到股票信息 ({symbol})")
                return None
        except Exception as e:
            logger.error(f"❌ API查询失败 ({symbol}): {e}")
            self.stats["api_errors"] += 1
            return None
    
    async def get_all_stock_industries_from_api(self) -> Dict[str, Dict[str, str]]:
        """
        从MongoDB获取申万2021行业分类数据
        
        数据来源：MongoDB -> industry_metadata_sw2021 集合
        优先级别：三级行业 > 二级行业 > 一级行业
        
        Returns:
            Dict[str, Dict[str, str]]: 行业映射
        """
        industry_map = {}
        
        try:
            # 尝试从MongoDB获取行业数据
            industries_from_mongo = self._get_industries_from_mongodb()
            if industries_from_mongo:
                logger.info(f"✅ 从MongoDB成功获取行业数据: {len(industries_from_mongo)} 条记录")

                return industries_from_mongo
            
            # 如果MongoDB数据不可用，返回空映射（由调用者处理）
            logger.warning("⚠️ MongoDB行业数据不可用，请先运行导入脚本")

            return industry_map
            
        except Exception as e:
            logger.error(f"❌ 获取行业分类失败: {e}")
            return industry_map

    def _get_industries_from_mongodb(self) -> Dict[str, str]:
        """
        从MongoDB的industry_metadata_sw2021集合获取行业数据
        
        Returns:
            Dict[str, str]: 行业映射 {industry_code: industry_name}
        """
        client = None
        try:
            import pymongo
            
            # 获取MongoDB连接参数
            mongo_host = os.getenv("MONGO_HOST", "localhost")
            mongo_port = int(os.getenv("MONGO_PORT", "27017"))
            mongo_user = os.getenv("MONGO_USER", "")
            mongo_password = os.getenv("MONGO_PASSWORD", "")
            mongo_db = os.getenv("MONGO_DB", "aistock_news")
            
            # 构建连接URI
            if mongo_user and mongo_password:
                uri = f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/{mongo_db}"
            else:
                uri = f"mongodb://{mongo_host}:{mongo_port}/{mongo_db}"
            
            # 连接MongoDB
            client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
            db = client[mongo_db]
            collection = db["industry_metadata_sw2021"]
            
            # 验证连接
            collection.database.client.server_info()
            
            # 查询所有行业数据
            industry_records = list(collection.find({}))
            
            if not industry_records:
                logger.warning("⚠️ MongoDB中没有行业数据，请先运行导入脚本")
                return {}
            
            # 构建行业映射: 优先使用三级行业 > 二级行业 > 一级行业
            industry_map = {}
            
            for record in industry_records:
                industry_code = str(record.get("行业代码", ""))
                
                # 优先级：三级 > 二级 > 一级
                industry_name = (
                    record.get("三级行业") or 
                    record.get("二级行业") or 
                    record.get("一级行业") or 
                    "未分类"
                )
                
                # 如果同一个行业代码有多条记录，保留第一条
                if industry_code not in industry_map:
                    industry_map[industry_code] = industry_name
            
            logger.info(f"📊 从MongoDB加载行业数据统计:")
            logger.info(f"   总记录数: {len(industry_records)}")
            logger.info(f"   行业种类: {len(industry_map)}")
            
            return industry_map
            
        except ImportError:
            logger.error("❌ 缺少pymongo库，请安装: pip install pymongo")
            return {}
        except Exception as e:
            logger.error(f"❌ 从MongoDB获取行业数据失败: {e}")
            return {}
        finally:
            # 确保MongoDB连接总是被正确关闭
            if client is not None:
                try:
                    client.close()
                except Exception as e:
                    logger.debug(f"⚠️ 关闭MongoDB连接时出错: {e}")



    async def validate_company_name_with_llm(self, symbol: str, company_name: str, context: str = "") -> Dict[str, Any]:
        """
        使用本地 Qwen3-4B 模型验证和校对公司名称
        
        Args:
            symbol: 股票代码
            company_name: 公司名称
            context: 额外的上下文信息
            
        Returns:
            包含verified(bool), corrected_name(str), confidence(float) 的字典
        """
        try:
            # 导入本地 Qwen3-4B 客户端
            from app.news.qwen_local_llm import get_qwen_client
            
            qwen_client = get_qwen_client()
            if not qwen_client:
                logger.warning(f"⚠️ 本地 Qwen3-4B 模型不可用")
                return {
                    "verified": True,
                    "corrected_name": company_name,
                    "confidence": 0.0,
                    "method": "skipped_no_qwen"
                }
            
            # 构建校对提示词 - 优化长度以适应 4096 token 上下文限制
            # 关键信息：仅包含必要字段，去除冗余说明
            prompt = f"""校对A股公司信息。代码: {symbol}，名称: {company_name}
            
返回JSON格式：{{"is_valid": bool, "corrected_name": "标准名称", "industry": "行业", "sector": "板块", "confidence": 0.0-1.0, "reason": "说明"}}
规则：1) 正确返回true且confidence>=0.8；2) 错误返回corrected_name且confidence>=0.5；3) 无法确认返回原名且confidence<0.5"""
            
            logger.debug(f"📝 使用 Qwen3-4B 校对公司名称 ({symbol}): {company_name}")
            
            # 使用本地 Qwen3-4B 模型调用（优化参数以适应 4096 token 上下文）
            response_text = await qwen_client.generate_json(
                prompt=prompt,
                system_prompt="你是A股公司信息校对专家。快速准确校对公司名称。",
                max_tokens=512,  # 降低至 512 避免 token 溢出，JSON 响应不需要 4096 token
                temperature=0.3
            )
            
            if not response_text:
                logger.warning(f"⚠️ Qwen3-4B 未返回响应 ({symbol})")
                return {
                    "verified": True,
                    "corrected_name": company_name,
                    "industry": "",
                    "sector": "",
                    "confidence": 0.0,
                    "method": "qwen3_no_response"
                }
            
            # 解析 Qwen3-4B 的 JSON 响应
            logger.debug(f"  Qwen3-4B 响应类型: {type(response_text)}")
            print(f"  📌 Qwen3-4B 响应: {response_text}")
            
            # 尝试解析 JSON
            try:
                # generate_json 已经返回解析后的 dict，无需额外处理
                if isinstance(response_text, dict):
                    result_data = response_text
                else:
                    # 如果返回的是字符串，需要手动解析
                    import re
                    json_match = re.search(r'\{.*\}', str(response_text), re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        result_data = json.loads(json_str)
                    else:
                        result_data = json.loads(str(response_text))
                
                # 验证必需字段
                if not all(k in result_data for k in ["is_valid", "corrected_name", "confidence"]):
                    logger.warning(f"⚠️ Qwen3-4B 响应缺少必需字段 ({symbol}): {result_data.keys()}")
                    return {
                        "verified": True,
                        "corrected_name": company_name,
                        "industry": "",
                        "sector": "",
                        "confidence": 0.0,
                        "method": "qwen3_invalid_format"
                    }
                
                result = {
                    "verified": result_data.get("is_valid", True),
                    "corrected_name": result_data.get("corrected_name", company_name),
                    "industry": result_data.get("industry", ""),
                    "sector": result_data.get("sector", ""),
                    "confidence": float(result_data.get("confidence", 0.5)),
                    "reason": result_data.get("reason", ""),
                    "method": "qwen3_validation"
                }
                
                logger.info(f"  ✅ Qwen3-4B 校对完成 ({symbol}): {result['corrected_name']} (置信度: {result['confidence']})")
                self.stats["llm_validations"] += 1
                return result
                
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Qwen3-4B 响应解析失败 ({symbol}): {e}")
                logger.debug(f"  原始响应: {response_text}")
                return {
                    "verified": True,
                    "corrected_name": company_name,
                    "confidence": 0.0,
                    "method": "qwen3_parse_error"
                }
            
        except Exception as e:
            logger.warning(f"⚠️ Qwen3-4B 校对失败 ({symbol}): {e}", exc_info=True)
            return {
                "verified": True,
                "corrected_name": company_name,
                "confidence": 0.0,
                "method": "qwen3_error"
            }
    
    async def search_company_info(self, symbol: str, company_name: str) -> Optional[Dict[str, Any]]:
        """
        通过搜索引擎查找补充信息
        
        使用 SearXNG 搜索公司相关新闻和信息，从结果中提取：
        - 行业分类
        - 所属板块
        
        Args:
            symbol: 股票代码
            company_name: 公司名称
            
        Returns:
            包含 industry/sector 的字典，无结果时返回 None
        """
        # 如果搜索服务未初始化，直接返回
        if not self.search_service:
            return None
        
        if not company_name or not company_name.strip():
            logger.debug(f"🔍 公司名称为空，跳过搜索 ({symbol})")
            return None
        
        try:
            # 构建搜索查询
            query = f"{company_name} A股 公司 行业"
            
            logger.debug(f"🔍 搜索公司补充信息 ({symbol}): {company_name}")
            
            # 使用 SearXNG 搜索
            search_results = await self.search_service.search_news(
                query=query,
                category="general",
                time_range="month",
                max_results=5,
                language="zh-CN"
            )
            
            if not search_results:
                logger.debug(f"🔍 搜索结果为空 ({symbol}): {company_name}")
                return None
            
            logger.debug(f"🔍 搜索到 {len(search_results)} 条结果")
            
            # 从搜索结果中提取信息
            titles = [r.get("title", "") for r in search_results]
            summaries = [r.get("content") or r.get("summary", "") for r in search_results]
            
            company_info = self._extract_company_info_from_search(
                company_name=company_name,
                titles=titles,
                summaries=summaries
            )
            
            if company_info:
                logger.debug(f"  ✅ 搜索补充信息 ({symbol}): 行业={company_info.get('industry')}, 板块={company_info.get('sector')}")
                return company_info
            else:
                logger.debug(f"  ⚠️ 未能从搜索结果中提取信息 ({symbol})")
                return None
        
        except Exception as e:
            logger.debug(f"⚠️ 搜索补充信息失败 ({symbol}): {e}")
            return None
    
    def _extract_company_info_from_search(
        self,
        company_name: str,
        titles: List[str],
        summaries: List[str]
    ) -> Optional[Dict[str, str]]:
        """
        从搜索结果中提取公司相关信息
        
        基于关键词匹配提取行业分类和板块信息
        
        Args:
            company_name: 公司名称
            titles: 搜索结果标题列表
            summaries: 搜索结果摘要列表
            
        Returns:
            包含 industry/sector 的字典，提取失败时返回 None
        """
        if not titles and not summaries:
            return None
        
        # 合并所有文本用于分析
        all_text = " ".join(titles + summaries).lower()
        
        # 行业关键词映射
        industry_keywords = {
            "软件": ["软件", "it", "互联网", "科技", "开发"],
            "汽车": ["汽车", "车企", "新能源", "电动车"],
            "制造": ["制造", "生产", "工业", "加工"],
            "金融": ["银行", "保险", "基金", "证券", "金融"],
            "房产": ["房产", "地产", "房地产", "楼盘"],
            "消费": ["消费", "零售", "商业", "电商", "购物"],
            "医药": ["医药", "制药", "生物", "医疗", "药物"],
            "能源": ["能源", "石油", "天然气", "电力", "水利"],
            "传媒": ["传媒", "广播", "电视", "新闻", "出版"],
            "教育": ["教育", "培训", "学校", "学习"],
            "农业": ["农业", "种植", "养殖", "农产品"],
            "交通": ["交通", "运输", "物流", "航运"],
        }
        
        # 匹配行业
        matched_industries = []
        for industry, keywords in industry_keywords.items():
            if any(kw in all_text for kw in keywords):
                matched_industries.append(industry)
        
        # 获取第一个匹配的行业
        industry = matched_industries[0] if matched_industries else ""
        
        # 板块匹配
        sector = ""
        sector_keywords = {
            "主板": ["主板", "沪深"],
            "创业板": ["创业板"],
            "科创板": ["科创板", "科创"],
            "新三板": ["新三板", "三板"],
        }
        
        for sector_name, keywords in sector_keywords.items():
            if any(kw in all_text for kw in keywords):
                sector = sector_name
                break
        
        if industry or sector:
            return {
                "industry": industry,
                "sector": sector
            }
        
        return None

    async def remove_duplicate_symbols(self, symbols: List[str]) -> None:
        """
        删除数据库中重复的股票记录
        
        Args:
            symbols: 可能重复的股票代码列表
        """
        has_duplicates = False
        session = self.session_factory()
        try:
            for sym in symbols:
                duplicates = session.query(StockProfile).filter(StockProfile.symbol == sym).all()
                if len(duplicates) > 1:
                    has_duplicates = True
                    print(f"  📌 删除重复记录: {sym}，数量: {len(duplicates)}")
                    logger.info(f"🧹 删除重复记录: {sym}，数量: {len(duplicates)}")
                    # 保留第一个，删除其余
                    for dup in duplicates[1:]:
                        session.delete(dup)
                    session.commit()
        except Exception as e:
            logger.error(f"❌ 删除重复记录失败: {e}", exc_info=True)
            session.rollback()
        finally:
            session.close()

        return has_duplicates
    
    async def update_stock_profile(self, profile: StockProfile) -> bool:
        """
        更新单个股票的Profile信息
        
        Args:
            profile: StockProfile对象
            
        Returns:
            是否成功更新
        """
        symbol = profile.symbol
        logger.info(f"📝 处理股票: {symbol}")
        
        try:
            # 第1步：从API获取最新信息
            logger.debug(f"  📌 获取API信息 for {symbol}")
            api_info = await self.fetch_stock_info_from_api(symbol)
            if not api_info:
                logger.warning(f"⚠️ 跳过 {symbol}：无法从API获取信息")
                self.stats["skipped"] += 1
                return False

            logger.debug(f"  📌 完成获取API信息 for {symbol}")
            # 打印API 返回数据的全部信息
            print(f"  📌 API返回数据: {api_info}")
            
            # 第2步：提取关键信息
            api_company_name = api_info.get('name', '')
            api_market = api_info.get('market', profile.market)
            api_industry = api_info.get('industry', '')
            api_sector = api_info.get('sector', '')
            api_symbol = api_info.get('symbol', symbol)  # 从API获取标准化的symbol

            print(f"  📌 API信息 ==> : 名称={api_company_name}, 行业={api_industry}")

            logger.debug(f"  📌 API信息: 名称={api_company_name}, 行业={api_industry}")
            
            # 检查symbol是否需要更新（API可能返回带后缀的标准symbol，如002276.SZ）
            symbol_needs_update = False
            if api_symbol and api_symbol != symbol:
                logger.info(f"  ⚠️ Symbol差异检测: {symbol} → {api_symbol}")
                print(f"  📌 Symbol差异: {symbol} → {api_symbol}")
                symbol_needs_update = True
            
            # 通过搜索引擎补充行业信息
            search_info = await self.search_company_info(symbol, api_company_name)
            if search_info:
                api_industry = search_info.get("industry", api_industry)
                api_sector = search_info.get("sector", api_sector)
                logger.debug(f"  📌 搜索引擎补充信息: 行业={api_industry}, 板块={api_sector}")

            # 第3步：与LLM进行校对
            if not api_industry:
                logger.debug(f"  📌 使用LLM校对公司名称 for {symbol}")

                
                # 使用本地 Qwen3-4B 模型进行校对

                llm_result = await self.validate_company_name_with_llm(
                    symbol, 
                    api_company_name,
                    context=f"行业: {api_industry}, 板块: {api_sector}"
                )
                
                final_company_name = llm_result.get('corrected_name', api_company_name)
                final_industry = llm_result.get('industry', api_industry)
                final_sector = llm_result.get('sector', api_sector)
                confidence = llm_result.get('confidence', 0.8)
            
                logger.debug(f"  ✅ LLM校对结果: {final_company_name} (置信度: {confidence})")
            else:
                final_company_name = api_company_name
                final_industry = api_industry
                final_sector = api_sector
                confidence = 1.0  # 已有行业信息，置信度设为最高
            
            # 第4步：搜索补充信息
            search_info = await self.search_company_info(symbol, final_company_name)
            
            # 第5步：准备更新数据
            old_values = {
                "symbol": profile.symbol,
                "company_name": profile.company_name,
                "industry": profile.industry,
                "market": profile.market,
                "is_valid": profile.is_valid
            }
            
            new_values = {
                "symbol": api_symbol if symbol_needs_update else profile.symbol,  # 使用标准化的symbol
                "company_name": final_company_name,
                "industry": final_industry,
                "sector": final_sector,
                "market": api_market,
                "is_valid": True,  # 标记为有效
                "updated_at": datetime.utcnow()
            }
            
            print(f"  📌 准备更新数据: {new_values}")

            # 生成变更摘要
            changes = []
            if old_values["symbol"] != new_values["symbol"]:
                changes.append(f"symbol: {old_values['symbol']} → {new_values['symbol']}")
            if old_values["company_name"] != new_values["company_name"]:
                changes.append(f"company_name: {old_values['company_name']} → {new_values['company_name']}")
            if old_values["industry"] != new_values["industry"]:
                changes.append(f"industry: {old_values['industry']} → {new_values['industry']}")
            if old_values["market"] != new_values["market"]:
                changes.append(f"market: {old_values['market']} → {new_values['market']}")
            if old_values["is_valid"] != new_values["is_valid"]:
                changes.append(f"is_valid: {old_values['is_valid']} → {new_values['is_valid']}")
            
            if not changes:
                logger.info(f"  ✓ {symbol}: 信息无变化，已是最新")
                self.stats["skipped"] += 1
                return True
            
            # 第6步：如果是演练模式，只显示预期的更改
            if self.dry_run:
                logger.info(f"  [DRY-RUN] {symbol} 将进行以下更改:")
                for change in changes:
                    logger.info(f"    - {change}")
                self.stats["updated"] += 1
                return True
            
            # 第7步：实际更新数据库
            session = self.session_factory()
            try:
                # 重新查询确保获取最新的对象
                db_profile = session.query(StockProfile).filter_by(symbol=symbol).first()
                if not db_profile:
                    logger.error(f"❌ {symbol}: 数据库中找不到Profile")
                    self.stats["failed"] += 1
                    return False
                
                # 如果需要更新symbol，检查新symbol是否已存在
                if symbol_needs_update:
                    existing_with_new_symbol = session.query(StockProfile).filter_by(symbol=api_symbol).first()
                    if existing_with_new_symbol and existing_with_new_symbol.id != db_profile.id:
                        logger.info(f"  🧹 发现冲突记录: {api_symbol} (ID={existing_with_new_symbol.id})，删除旧记录")
                        session.delete(existing_with_new_symbol)
                        session.flush()  # 先提交删除操作
                
                # 应用更新
                for key, value in new_values.items():
                    setattr(db_profile, key, value)
                
                session.commit()
                logger.info(f"  ✅ {symbol} 更新成功:")
                for change in changes:
                    logger.info(f"    ✓ {change}")
                
                self.stats["updated"] += 1
                return True
                
            except Exception as e:
                session.rollback()
                logger.error(f"❌ {symbol} 数据库更新失败: {e}")
                self.stats["failed"] += 1
                return False
            finally:
                session.close()
        
        except Exception as e:
            logger.error(f"❌ {symbol} 处理失败: {e}", exc_info=True)
            self.stats["failed"] += 1
            return False
    
    async def get_stock_profile(self, symbol: str) -> Optional[StockProfile]:
        """
        查询单个股票的Profile信息
        
        Args:
            symbol: 股票代码
            
        Returns:
            StockProfile对象或None
        """
        session = self.session_factory()
        try:
            profile = session.query(StockProfile).filter_by(symbol=symbol).first()

            if not profile:
                # 查询以symbol 开始的记录
                profile = session.query(StockProfile).filter(StockProfile.symbol.like(f"{symbol}%")).first()
                if not profile:
                    logger.warning(f"⚠️ 查询失败: {symbol} 在数据库中不存在")
                    return None


            print(f"  📌 查询到股票信息: {profile.symbol}, {profile.company_name}, {profile.industry}")
            return profile
        finally:
            session.close()

    async def run(self):
        """执行批量更新"""
        logger.info("=" * 80)
        logger.info("🚀 启动股票信息批量更新")
        logger.info("=" * 80)
        logger.info(f"配置: dry_run={self.dry_run}, limit={self.limit}, market={self.market}, force={self.force}")
        
        start_time = datetime.now()

        max_number_of_profile_updates = 1

        update_index = 0

        
        try:
            # 获取待更新股票列表
            stocks = self.get_stocks_to_update()
            if not stocks:
                logger.warning("⚠️ 没有找到需要更新的股票")
                return
            

            # 处理每个股票
            for idx, profile in enumerate(stocks, 1):
                self.stats["total_checked"] += 1
                logger.info(f"\n[{idx}/{len(stocks)}] 处理股票 {profile.symbol}")
                
                try:
                    print(f"  📌 API信息: 名称={profile.company_name}, 行业={profile.industry}")

                    update_index += 1

                    # 判断company_name是否包含数字
                    if any(char.isdigit() for char in profile.company_name):

                        # 检查这个公司的symbol 是否在数据库中有重复记录，查询条件为symbol完全匹配或者symbol+(.SZ/.SH/.US/.HK等等后缀
                        existing_symbols = [
                            f"{profile.symbol}.SZ",
                            f"{profile.symbol}.SH",
                            f"{profile.symbol}.US",
                            f"{profile.symbol}.HK"
                        ]

                        print(f"  📌 检查重复记录: {existing_symbols}")

                        # 如果存在重复记录，则删除这些重复记录
                    has_duplicates = await self.remove_duplicate_symbols(existing_symbols)
                    
                    if not has_duplicates:
                        print(f"  📌 无需检查重复记录: {profile.symbol}")
                        # 则该股票信息， 重新通过API和LLM进行校对和更新
                        update_result = await self.update_stock_profile(profile)

                        if not update_result:
                            logger.warning(f"⚠️ 跳过 {profile.symbol}：更新失败或无变化")
                            # 从数据库中删除这条stock profile记录
                            session = None
                            try:
                                session = self.session_factory()
                                db_profile = session.query(StockProfile).filter_by(symbol=profile.symbol).first()
                                if db_profile:
                                    logger.info(f"  🗑️ 删除记录: {profile.symbol} (ID={db_profile.id})")
                                    session.delete(db_profile)
                                    session.commit()
                                    self.stats["updated"] += 1
                                else:
                                    logger.warning(f"  ⚠️ 删除失败: 未找到 {profile.symbol}")
                            except Exception as e:
                                if session is not None:
                                    try:
                                        session.rollback()
                                    except Exception:
                                        pass
                                logger.error(f"  ❌ 删除记录时出错: {e}", exc_info=True)
                                self.stats["failed"] += 1
                            finally:
                                if session is not None:
                                    try:
                                        session.close()
                                    except Exception:
                                        pass
                            continue

                    
                    # 更新以后，查询更新后的股票信息
                    updated_profile = await self.get_stock_profile(profile.symbol)
                    print(f"  📌 更新后的股票信息: {updated_profile.symbol}, {updated_profile.company_name}, {updated_profile.industry}")

                    if update_index > max_number_of_profile_updates:
                        logger.info(f"⏳ 达到本次运行的最大更新数量限制 ({max_number_of_profile_updates})，跳过后续股票")
                        break
                except Exception as e:
                    logger.error(f"❌ 处理失败: {e}", exc_info=True)
                    self.stats["failed"] += 1
            
            # 生成最终报告
            elapsed_time = datetime.now() - start_time
            self._print_summary(elapsed_time)
            
        except Exception as e:
            logger.error(f"❌ 批量更新失败: {e}", exc_info=True)
    
    def _print_summary(self, elapsed_time):
        """打印执行摘要"""
        logger.info("\n" + "=" * 80)
        logger.info("📊 执行摘要")
        logger.info("=" * 80)
        logger.info(f"✓ 总检查: {self.stats['total_checked']}")
        logger.info(f"✓ 已更新: {self.stats['updated']}")
        logger.info(f"✓ 已跳过: {self.stats['skipped']}")
        logger.info(f"✗ 失败: {self.stats['failed']}")
        logger.info(f"⚠️ API错误: {self.stats['api_errors']}")
        logger.info(f"📝 LLM校对: {self.stats['llm_validations']}")
        logger.info(f"⏱️ 耗时: {elapsed_time}")
        
        # 成功率
        if self.stats['total_checked'] > 0:
            success_rate = ((self.stats['updated'] + self.stats['skipped']) / self.stats['total_checked']) * 100
            logger.info(f"📈 成功率: {success_rate:.1f}%")
        
        logger.info("=" * 80)
        
        if self.dry_run:
            logger.info("⚠️ 这是演练模式，数据库未实际更新")
        else:
            logger.info("✅ 更新完成！")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="股票信息批量更新脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 演练模式：检查会进行哪些更新，但不实际修改数据库
    python backend/scripts/update_stock_profiles.py --dry-run
    
    # 实际更新：只更新company_name为空的前100个A股
    python backend/scripts/update_stock_profiles.py --limit 100 --market A股
    
    # 强制更新：更新所有股票（包括已有company_name的）
    python backend/scripts/update_stock_profiles.py --force
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='演练模式，不实际更新数据库'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='限制处理的股票数量（默认不限制）'
    )
    
    parser.add_argument(
        '--market',
        type=str,
        default='全部',
        choices=['A股', '港股', '美股', '全部'],
        help='处理的市场类型（默认全部）'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        default=False,
        help='强制更新所有股票（包括已有有效company_name的）'
    )
    
    args = parser.parse_args()
    
    # 创建更新器并运行
    updater = StockProfileUpdater(
        dry_run=args.dry_run,
        limit=args.limit,
        market=args.market,
        force=args.force
    )

    global industry_map
    industry_map = await updater.get_all_stock_industries_from_api()

    await updater.run()
    
    # 清理资源：关闭所有MongoDB连接
    try:
        # 关闭 NewsDeduplicator 中的 MongoDB 连接
        import app.news.news_deduplication as dedup_module
        if hasattr(dedup_module, '_DEDUP_MONGO_CLIENT') and dedup_module._DEDUP_MONGO_CLIENT is not None:
            logger.debug("🔌 关闭 MongoDB deduplication 连接...")
            dedup_module._DEDUP_MONGO_CLIENT.close()
            dedup_module._DEDUP_MONGO_CLIENT = None
            dedup_module._DEDUP_MONGO_DB = None
            dedup_module._DEDUP_MONGO_READY = False
    except Exception as e:
        logger.debug(f"⚠️ 关闭 MongoDB 连接时出错: {e}")

if __name__ == '__main__':
    asyncio.run(main())
