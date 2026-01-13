"""
Stock Profile 验证服务
用于检查公司是否仍然存在、运营正常、无重大风险
"""

import json
import logging
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, select

from app.core.models import StockProfile

# LLM 配置
HAS_OPENAI = False
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if OPENAI_API_KEY:
    try:
        from openai import AsyncOpenAI
        HAS_OPENAI = True
    except ImportError:
        pass

HAS_CLAUDE = False
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
if ANTHROPIC_API_KEY:
    try:
        import anthropic
        HAS_CLAUDE = True
    except ImportError:
        pass

logger = logging.getLogger(__name__)


async def call_openai_llm(prompt: str, temperature: float = 0.7) -> Optional[str]:
    """
    调用OpenAI API进行分析
    """
    if not HAS_OPENAI or not OPENAI_API_KEY:
        logger.warning('OpenAI not available')
        return None
    
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model='gpt-3.5-turbo',
            messages=[
                {'role': 'system', 'content': '你是一个专业的金融分析师。请用中文回答。'},
                {'role': 'user', 'content': prompt}
            ],
            temperature=temperature,
            max_tokens=2000,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f'OpenAI API error: {e}')
        return None


async def call_claude_llm(prompt: str, temperature: float = 0.7) -> Optional[str]:
    """
    调用Claude API进行分析
    """
    if not HAS_CLAUDE or not ANTHROPIC_API_KEY:
        logger.warning('Claude not available')
        return None
    
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model='claude-3-haiku-20240307',
            max_tokens=2000,
            messages=[
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            temperature=temperature,
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f'Claude API error: {e}')
        return None


async def call_llm(prompt: str, temperature: float = 0.7) -> Optional[str]:
    """
    调用LLM进行分析（自动选择可用的提供商）
    """
    if HAS_CLAUDE:
        result = await call_claude_llm(prompt, temperature)
        if result:
            return result
        logger.info('Claude failed, falling back to OpenAI')
    
    result = await call_openai_llm(prompt, temperature)
    if result:
        return result
    
    logger.warning('No LLM provider available')
    return None


class ProfileValidationStatus:
    """Profile 验证状态常量"""
    VALID = "valid"  # 有效，公司正常运营
    INVALID = "invalid"  # 作废，公司不再运营
    SUSPENDED = "suspended"  # 暂停，公司暂停运营
    DELISTED = "delisted"  # 已退市
    RISK_ALERT = "risk_alert"  # 风险警示
    UNKNOWN = "unknown"  # 未知状态


class StockProfileValidator:
    """Stock Profile 验证器"""

    VALIDATION_PROMPT_TEMPLATE = """
你是一个股票市场专家。请根据以下公司信息，判断这家公司是否仍然存在、是否正常运营、是否存在重大风险。

【公司信息】
- 股票代码: {symbol}
- 公司名称: {company_name}
- 行业: {industry}
- 主营业务: {business_summary}
- 核心产品: {core_products}
- 竞争地位: {competitive_position}
- 风险因素: {risk_factors}
- 历史亮点: {history_highlights}

请从以下几个方面进行判断:
1. 公司是否仍然存在（是否已破产、清算、注销）
2. 公司是否仍在正常运营（是否停运、暂停）
3. 是否存在重大风险（财务风险、合规风险、技术风险等）
4. 是否已经退市或面临退市风险
5. 整体评估：是否值得继续跟踪

请以 JSON 格式返回你的判断结果，包含以下字段：
{{
    "validation_status": "valid|invalid|suspended|delisted|risk_alert",
    "is_operating": true/false,  // 是否正在运营
    "has_major_risk": true/false,  // 是否有重大风险
    "delisting_risk": true/false,  // 是否有退市风险
    "recommendation": "valid|monitor|remove",  // 建议：有效/监控/移除
    "reasons": ["原因1", "原因2", ...],  // 详细原因列表
    "summary": "一句话总结"
}}
"""

    def __init__(self, db: Session):
        """初始化验证器"""
        self.db = db

    def validate_profile(self, profile: StockProfile) -> Tuple[str, Optional[str]]:
        """
        验证单个 Profile

        Returns:
            Tuple[validation_status, validation_reason]
        """
        try:
            # 首先尝试基于规则的快速验证
            is_valid, quick_reason = self.validate_by_criteria(profile)
            
            if not is_valid and quick_reason:
                # 如果规则验证发现问题，直接返回
                logger.info(
                    f"✅ 快速验证完成 [{profile.symbol}]: invalid - {quick_reason}"
                )
                return ProfileValidationStatus.INVALID, quick_reason
            
            # 如果规则验证通过，则返回有效
            # 注：可以在这里添加 LLM 验证，但需要异步处理
            logger.info(
                f"✅ 验证完成 [{profile.symbol}]: valid (规则验证通过)"
            )
            return ProfileValidationStatus.VALID, "规则验证通过，公司信息完整有效"

        except Exception as e:
            logger.error(f"❌ 验证失败 [{profile.symbol}]: {str(e)}")
            return ProfileValidationStatus.UNKNOWN, f"验证过程异常: {str(e)}"

    def batch_validate_profiles(
        self,
        profiles: List[StockProfile],
        update_db: bool = True
    ) -> dict:
        """
        批量验证 Profiles

        Args:
            profiles: 要验证的 Profile 列表
            update_db: 是否更新数据库

        Returns:
            验证结果统计
        """
        results = {
            "total": len(profiles),
            "valid": 0,
            "invalid": 0,
            "risk_alert": 0,
            "suspended": 0,
            "delisted": 0,
            "unknown": 0,
            "errors": []
        }

        for idx, profile in enumerate(profiles, 1):
            try:
                status, reason = self.validate_profile(profile)

                # 更新统计
                if status == ProfileValidationStatus.VALID:
                    results["valid"] += 1
                elif status == ProfileValidationStatus.INVALID:
                    results["invalid"] += 1
                elif status == ProfileValidationStatus.RISK_ALERT:
                    results["risk_alert"] += 1
                elif status == ProfileValidationStatus.SUSPENDED:
                    results["suspended"] += 1
                elif status == ProfileValidationStatus.DELISTED:
                    results["delisted"] += 1
                else:
                    results["unknown"] += 1

                # 更新数据库
                if update_db:
                    profile.validation_status = status
                    profile.validation_reason = reason
                    profile.last_validated_at = datetime.utcnow()
                    
                    # 根据状态设置 is_valid
                    profile.is_valid = (status == ProfileValidationStatus.VALID)
                    
                self.db.add(profile)

                if idx % 10 == 0:
                    logger.info(f"进度: {idx}/{len(profiles)}")

            except Exception as e:
                results["errors"].append({
                    "symbol": profile.symbol,
                    "error": str(e)
                })
                logger.error(f"❌ 验证失败 [{profile.symbol}]: {str(e)}")

        # 批量提交
        if update_db:
            try:
                self.db.commit()
                logger.info("✅ 所有验证结果已保存到数据库")
            except Exception as e:
                self.db.rollback()
                logger.error(f"❌ 保存验证结果失败: {str(e)}")

        return results

    def validate_by_criteria(self, profile: StockProfile) -> Tuple[bool, Optional[str]]:
        """
        基于简单规则的快速验证（不调用 LLM）
        用于快速标记明显的作废数据

        Returns:
            Tuple[is_valid, reason]
        """
        reasons = []

        # 检查关键字段是否为空（可能表示数据不完整/公司不存在）
        if not profile.company_name or "已停止" in (profile.company_name or ""):
            reasons.append("公司名称为空或标记为停止")

        # 检查风险因素中的风险词
        if profile.risk_factors:
            risk_keywords = ["退市", "风险警示", "停止运营", "清算", "破产", "已注销"]
            for keyword in risk_keywords:
                if keyword in profile.risk_factors:
                    reasons.append(f"风险因素中包含关键词: {keyword}")

        # 检查业务摘要中的风险词
        if profile.business_summary:
            risk_keywords = ["已停止", "已终止", "清算中", "停止运营"]
            for keyword in risk_keywords:
                if keyword in profile.business_summary:
                    reasons.append(f"业务摘要中包含关键词: {keyword}")

        is_valid = len(reasons) == 0
        reason = "; ".join(reasons) if reasons else None

        return is_valid, reason

    def get_invalid_profiles(self) -> List[StockProfile]:
        """获取所有被标记为无效的 Profiles"""
        query = select(StockProfile).where(StockProfile.is_valid == False)
        return self.db.execute(query).scalars().all()

    def get_profiles_needing_validation(self, days_since_validation: int = 30) -> List[StockProfile]:
        """
        获取需要重新验证的 Profiles
        （超过指定天数未验证或从未验证的）
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_since_validation)
        
        query = select(StockProfile).where(
            (StockProfile.last_validated_at == None) |
            (StockProfile.last_validated_at < cutoff_date)
        )
        return self.db.execute(query).scalars().all()

    def mark_invalid(
        self,
        symbol: str,
        reason: str,
        status: str = ProfileValidationStatus.INVALID
    ) -> bool:
        """
        手动标记 Profile 为无效

        Args:
            symbol: 股票代码
            reason: 标记原因
            status: 验证状态

        Returns:
            是否成功
        """
        try:
            query = select(StockProfile).where(StockProfile.symbol == symbol)
            profile = self.db.execute(query).scalar_one_or_none()

            if not profile:
                logger.warning(f"⚠️  未找到 Profile: {symbol}")
                return False

            profile.is_valid = False
            profile.validation_status = status
            profile.validation_reason = reason
            profile.last_validated_at = datetime.utcnow()

            self.db.add(profile)
            self.db.commit()

            logger.info(f"✅ 已标记为无效: {symbol} - {reason}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ 标记失败: {str(e)}")
            return False

    def restore_profile(self, symbol: str) -> bool:
        """
        恢复被标记为无效的 Profile

        Args:
            symbol: 股票代码

        Returns:
            是否成功
        """
        try:
            query = select(StockProfile).where(StockProfile.symbol == symbol)
            profile = self.db.execute(query).scalar_one_or_none()

            if not profile:
                logger.warning(f"⚠️  未找到 Profile: {symbol}")
                return False

            profile.is_valid = True
            profile.validation_status = ProfileValidationStatus.VALID
            profile.validation_reason = None
            profile.last_validated_at = datetime.utcnow()

            self.db.add(profile)
            self.db.commit()

            logger.info(f"✅ 已恢复: {symbol}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ 恢复失败: {str(e)}")
            return False
