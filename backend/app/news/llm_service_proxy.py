"""
LLM 服务代理 - 支持多个 LLM 后端

这个模块提供一个统一的接口来调用不同的 LLM 服务：
1. Azure OpenAI (云端)
2. 本地 Qwen3-4B (通过 LM Studio)

根据 .env 中的配置自动选择合适的后端
"""

import os
import logging
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """支持的 LLM 提供商"""
    AZURE = "azure"
    LOCAL_QWEN = "local_qwen"
    NONE = "none"


class LLMServiceProxy:
    """
    LLM 服务代理 - 自动选择和切换 LLM 后端
    
    优先级：
    1. 本地 Qwen3-4B (如果启用)
    2. Azure OpenAI (如果配置有效)
    3. None (都不可用)
    """
    
    def __init__(self):
        """初始化 LLM 服务代理"""
        self.provider = self._determine_provider()
        self.qwen_client = None
        self.azure_processor = None
        
        logger.info(f"✅ LLM 服务代理初始化完成，当前提供商: {self.provider.value}")
    
    def _determine_provider(self) -> LLMProvider:
        """
        根据配置确定使用的 LLM 提供商
        
        Returns:
            LLMProvider: 确定的 LLM 提供商
        """
        
        # 检查本地 Qwen3-4B 是否启用
        qwen_enabled = os.getenv("LOCAL_QWEN_ENABLED", "false").lower() in ("true", "1", "yes")
        if qwen_enabled:
            logger.info("📍 检测到本地 Qwen3-4B 启用")
            return LLMProvider.LOCAL_QWEN
        
        # 检查 Azure OpenAI 是否配置
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        azure_key = os.getenv("AZURE_OPENAI_KEY")
        if azure_endpoint and azure_key:
            logger.info("📍 检测到 Azure OpenAI 配置")
            return LLMProvider.AZURE
        
        logger.warning("⚠️ 未检测到可用的 LLM 配置")
        return LLMProvider.NONE
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """
        生成文本 - 使用当前配置的 LLM 提供商
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            **kwargs: 其他参数
        
        Returns:
            str: 生成的文本，失败返回 None
        """
        
        if self.provider == LLMProvider.LOCAL_QWEN:
            return await self._generate_with_qwen(prompt, system_prompt, **kwargs)
        elif self.provider == LLMProvider.AZURE:
            return await self._generate_with_azure(prompt, system_prompt, **kwargs)
        else:
            logger.error("❌ 没有可用的 LLM 提供商")
            return None
    
    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Optional[dict]:
        """
        生成 JSON 格式的文本 - 使用当前配置的 LLM 提供商
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            **kwargs: 其他参数
        
        Returns:
            dict: 解析后的 JSON 对象，失败返回 None
        """
        
        if self.provider == LLMProvider.LOCAL_QWEN:
            return await self._generate_json_with_qwen(prompt, system_prompt, **kwargs)
        elif self.provider == LLMProvider.AZURE:
            return await self._generate_json_with_azure(prompt, system_prompt, **kwargs)
        else:
            logger.error("❌ 没有可用的 LLM 提供商")
            return None
    
    async def _generate_with_qwen(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """使用本地 Qwen3-4B 生成文本"""
        try:
            from .qwen_local_llm import get_qwen_client
            
            if self.qwen_client is None:
                self.qwen_client = get_qwen_client()
            
            return await self.qwen_client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                **kwargs
            )
        except Exception as e:
            logger.error(f"❌ Qwen3 生成失败: {e}")
            return None
    
    async def _generate_json_with_qwen(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Optional[dict]:
        """使用本地 Qwen3-4B 生成 JSON"""
        try:
            from .qwen_local_llm import get_qwen_client
            
            if self.qwen_client is None:
                self.qwen_client = get_qwen_client()
            
            return await self.qwen_client.generate_json(
                prompt=prompt,
                system_prompt=system_prompt,
                **kwargs
            )
        except Exception as e:
            logger.error(f"❌ Qwen3 JSON 生成失败: {e}")
            return None
    
    async def _generate_with_azure(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """使用 Azure OpenAI 生成文本"""
        try:
            # 这里需要调用 LLMNewsProcessor 的相应方法
            # 由于 LLMNewsProcessor 已经是异步的，我们直接使用其方法
            logger.warning("⚠️ Azure OpenAI 后端暂未在此模块实现，请使用 LLMNewsProcessor 直接调用")
            return None
        except Exception as e:
            logger.error(f"❌ Azure OpenAI 生成失败: {e}")
            return None
    
    async def _generate_json_with_azure(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Optional[dict]:
        """使用 Azure OpenAI 生成 JSON"""
        try:
            logger.warning("⚠️ Azure OpenAI 后端暂未在此模块实现，请使用 LLMNewsProcessor 直接调用")
            return None
        except Exception as e:
            logger.error(f"❌ Azure OpenAI JSON 生成失败: {e}")
            return None
    
    def get_provider_name(self) -> str:
        """获取当前 LLM 提供商的名称"""
        if self.provider == LLMProvider.LOCAL_QWEN:
            return "本地 Qwen3-4B"
        elif self.provider == LLMProvider.AZURE:
            return "Azure OpenAI"
        else:
            return "无"
    
    def is_available(self) -> bool:
        """检查是否有可用的 LLM 提供商"""
        return self.provider != LLMProvider.NONE


# 全局单例
_proxy_instance: Optional[LLMServiceProxy] = None


def get_llm_service_proxy() -> LLMServiceProxy:
    """
    获取全局 LLM 服务代理实例
    
    Returns:
        LLMServiceProxy: 全局代理实例
    """
    global _proxy_instance
    if _proxy_instance is None:
        _proxy_instance = LLMServiceProxy()
    return _proxy_instance


# 快速接口函数
async def generate_text(
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    """
    快速生成文本接口
    
    Args:
        prompt: 用户提示词
        system_prompt: 系统提示词（可选）
        **kwargs: 其他参数
    
    Returns:
        str: 生成的文本，失败返回 None
    """
    proxy = get_llm_service_proxy()
    return await proxy.generate(prompt, system_prompt, **kwargs)


async def generate_json(
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs
) -> Optional[dict]:
    """
    快速生成 JSON 接口
    
    Args:
        prompt: 用户提示词
        system_prompt: 系统提示词（可选）
        **kwargs: 其他参数
    
    Returns:
        dict: 解析后的 JSON 对象，失败返回 None
    """
    proxy = get_llm_service_proxy()
    return await proxy.generate_json(prompt, system_prompt, **kwargs)
