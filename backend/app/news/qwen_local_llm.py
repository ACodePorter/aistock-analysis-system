"""
Qwen3-4B 本地 LLM 调用模块

用于调用本地通过 LM Studio 启动的 Qwen3-4B 模型
支持异步 HTTP 请求和重试机制
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全局并发限制 —— 本地 Qwen 模型处理能力有限，需要控制同时发送的请求数量
# 通过 LOCAL_QWEN_MAX_CONCURRENCY 环境变量配置，默认 2
# ---------------------------------------------------------------------------
_qwen_semaphore: Optional[asyncio.Semaphore] = None


def get_qwen_semaphore() -> asyncio.Semaphore:
    """获取全局 Qwen 并发信号量（惰性初始化）"""
    global _qwen_semaphore
    if _qwen_semaphore is None:
        try:
            max_conc = int(os.getenv("LOCAL_QWEN_MAX_CONCURRENCY", "2"))
        except ValueError:
            max_conc = 2
        max_conc = max(1, max_conc)
        _qwen_semaphore = asyncio.Semaphore(max_conc)
        logger.info(f"🔒 Qwen 全局并发信号量已创建，最大并发数: {max_conc}")
    return _qwen_semaphore


class Qwen3LocalLLMClient:
    """
    Qwen3-4B 本地 LLM 客户端
    
    通过 LM Studio 的兼容 OpenAI API 接口调用本地 Qwen3-4B 模型
    
    配置参数（来自 .env）：
    - LOCAL_QWEN_URL: Qwen3 API 端点 (默认: http://localhost:1234/v1)
    - LOCAL_QWEN_MODEL: 模型名称 (默认: local-model)
    - LOCAL_QWEN_TIMEOUT: HTTP 超时时间 (默认: 120 秒)
    - LOCAL_QWEN_MAX_TOKENS: 最大生成 token 数 (默认: 2048)
    - LOCAL_QWEN_TEMPERATURE: 温度参数 (默认: 0.7)
    - LOCAL_QWEN_TOP_P: Top-p 采样参数 (默认: 0.9)
    - LOCAL_QWEN_RETRY_TIMES: 重试次数 (默认: 3)
    - LOCAL_QWEN_RETRY_DELAY: 重试延迟 (默认: 2 秒)
    - LOCAL_QWEN_ENABLED: 是否启用本地 Qwen (默认: false)
    """
    
    def __init__(self):
        """初始化 Qwen3 本地 LLM 客户端"""
        
        # 读取配置
        self.enabled = os.getenv("LOCAL_QWEN_ENABLED", "false").lower() in ("true", "1", "yes")
        self.base_url = os.getenv("LOCAL_QWEN_URL", "http://localhost:1234/v1")
        self.model_name = os.getenv("LOCAL_QWEN_MODEL", "local-model")
        
        # HTTP 配置
        try:
            self.timeout = float(os.getenv("LOCAL_QWEN_TIMEOUT", "120"))
        except ValueError:
            self.timeout = 120.0
        
        # 生成参数
        try:
            self.max_tokens = int(os.getenv("LOCAL_QWEN_MAX_TOKENS", "2048"))
        except ValueError:
            self.max_tokens = 2048
        
        try:
            self.temperature = float(os.getenv("LOCAL_QWEN_TEMPERATURE", "0.7"))
        except ValueError:
            self.temperature = 0.7
        
        try:
            self.top_p = float(os.getenv("LOCAL_QWEN_TOP_P", "0.9"))
        except ValueError:
            self.top_p = 0.9
        
        # 重试配置
        try:
            self.retry_times = int(os.getenv("LOCAL_QWEN_RETRY_TIMES", "3"))
        except ValueError:
            self.retry_times = 3
        
        try:
            self.retry_delay = float(os.getenv("LOCAL_QWEN_RETRY_DELAY", "2"))
        except ValueError:
            self.retry_delay = 2.0
        
        # 初始化 HTTP 客户端
        self.http_client = httpx.AsyncClient(timeout=self.timeout)
        
        # 日志
        logger.info(f"✅ Qwen3-4B 本地 LLM 客户端初始化完成")
        logger.info(f"   启用状态: {'✅ 已启用' if self.enabled else '❌ 已禁用'}")
        logger.info(f"   API 端点: {self.base_url}")
        logger.info(f"   模型名称: {self.model_name}")
        logger.info(f"   生成参数: max_tokens={self.max_tokens}, temperature={self.temperature}, top_p={self.top_p}")
        logger.info(f"   重试配置: 重试次数={self.retry_times}, 延迟={self.retry_delay}s")
    
    async def _check_server_health(self) -> bool:
        """
        检查本地 LLM 服务器是否可用
        
        Returns:
            bool: 服务器是否可用
        """
        try:
            # 检查 /models 端点
            url = f"{self.base_url}/models"
            resp = await asyncio.wait_for(
                self.http_client.get(url),
                timeout=5.0
            )
            
            if resp.status_code == 200:
                logger.debug(f"✅ Qwen3 服务器正常: {url}")
                return True
            else:
                logger.warning(f"⚠️ Qwen3 服务器异常: HTTP {resp.status_code}")
                return False
                
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Qwen3 服务器连接超时 (5s)")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Qwen3 服务器检查失败: {e}")
            return False
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> Optional[str]:
        """
        调用本地 Qwen3 生成文本
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            max_tokens: 最大生成 token 数（可选，默认使用配置值）
            temperature: 温度参数（可选，默认使用配置值）
            top_p: Top-p 采样参数（可选，默认使用配置值）
        
        Returns:
            str: 生成的文本，失败返回 None
        """
        
        if not self.enabled:
            logger.warning("❌ Qwen3-4B 本地 LLM 未启用，请在 .env 中设置 LOCAL_QWEN_ENABLED=true")
            return None
        
        # 使用传入参数或默认配置
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        temperature = temperature if temperature is not None else self.temperature
        top_p = top_p if top_p is not None else self.top_p
        
        # 构建消息列表
        messages = []
        
        # 添加系统提示词
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        # 添加用户提示词
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        # 请求负载
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,  # 不使用流式输出
        }
        
        # 准备 URL
        url = f"{self.base_url}/chat/completions"
        
        logger.debug(f"📝 调用 Qwen3 生成文本")
        logger.debug(f"   URL: {url}")
        logger.debug(f"   Prompt 长度: {len(prompt)} 字符")

        sem = get_qwen_semaphore()

        # 重试机制
        last_error = None
        for attempt in range(1, self.retry_times + 1):
            try:
                logger.debug(f"   尝试 {attempt}/{self.retry_times}...")

                async with sem:
                    logger.info(f"Start URL: {url}, Attempt: {attempt}")

                    # 执行 POST 请求
                    resp = await self.http_client.post(
                        url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                        }
                    )

                    logger.info(f"End URL: {url}, Attempt: {attempt}")
                
                # 检查状态码
                if resp.status_code != 200:
                    error_msg = f"HTTP {resp.status_code}"
                    try:
                        error_data = resp.json()
                        if "error" in error_data:
                            error_msg += f": {error_data['error']}"
                    except Exception:
                        pass
                    
                    last_error = error_msg
                    logger.warning(f"   ⚠️ 请求失败: {error_msg}")
                    
                    # 如果不是最后一次尝试，等待后重试
                    if attempt < self.retry_times:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    else:
                        logger.error(f"❌ Qwen3 生成失败 (已尝试 {self.retry_times} 次): {last_error}")
                        return None
                
                # 解析响应
                try:
                    response_data = resp.json()
                except json.JSONDecodeError as e:
                    last_error = f"JSON 解析错误: {e}"
                    logger.warning(f"   ⚠️ {last_error}")
                    
                    if attempt < self.retry_times:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    else:
                        logger.error(f"❌ Qwen3 响应解析失败: {last_error}")
                        return None
                
                # 提取生成的文本
                if "choices" not in response_data or not response_data["choices"]:
                    last_error = "响应中没有 choices 字段"
                    logger.warning(f"   ⚠️ {last_error}")
                    
                    if attempt < self.retry_times:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    else:
                        logger.error(f"❌ Qwen3 响应格式错误: {last_error}")
                        return None
                
                message = response_data["choices"][0].get("message", {})
                generated_text = message.get("content", "").strip()
                
                if not generated_text:
                    last_error = "生成的文本为空"
                    logger.warning(f"   ⚠️ {last_error}")
                    
                    if attempt < self.retry_times:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    else:
                        logger.error(f"❌ Qwen3 生成文本为空")
                        return None
                
                # 成功
                logger.info(f"✅ Qwen3 生成成功 (尝试 {attempt}/{self.retry_times})")
                logger.debug(f"   生成文本长度: {len(generated_text)} 字符")
                
                return generated_text
                
            except asyncio.TimeoutError:
                last_error = "请求超时"
                logger.warning(f"   ⚠️ {last_error} ({self.timeout}s)")
                
                if attempt < self.retry_times:
                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"❌ Qwen3 请求超时")
                    return None
            
            except Exception as e:
                last_error = str(e)
                logger.warning(f"   ⚠️ 异常: {e}")
                
                if attempt < self.retry_times:
                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"❌ Qwen3 生成失败: {e}")
                    return None
        
        return None
    
    def _extract_final_answer(self, full_text: str) -> str:
        """
        从 Qwen3 推理模型的输出中提取最终答案
        
        Qwen3 是推理模型，会输出：
        <think>推理过程...</think>
        最终答案
        
        Args:
            full_text: 完整输出文本
        
        Returns:
            str: 提取后的最终答案
        """
        # 检查是否包含 think 标签
        if "<think>" in full_text and "</think>" in full_text:
            # 提取 </think> 之后的内容作为最终答案
            think_end_pos = full_text.find("</think>")
            if think_end_pos != -1:
                final_answer = full_text[think_end_pos + len("</think>"):].strip()
                logger.debug(f"   提取推理过程后的最终答案")
                return final_answer
        
        # 如果没有 think 标签，直接返回原文本
        return full_text
    
    async def generate_with_reasoning(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        include_thinking: bool = False,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        调用本地 Qwen3 生成文本，支持获取推理过程或最终答案
        
        Qwen3 是推理模型，会输出推理过程 (<think>...</think>) 和最终答案
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            include_thinking: 是否返回推理过程，默认 False（仅返回最终答案）
            **kwargs: 其他参数传递给 generate 方法
        
        Returns:
            dict: 包含以下字段：
                - final_answer: 最终答案
                - thinking: 推理过程（如果 include_thinking=True）
                - raw_output: 原始输出（仅用于调试）
                失败返回 None
        """
        logger.info(f"📝 调用 Qwen3 生成文本（支持推理）")
        
        # 调用生成方法
        generated_text = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )
        
        if not generated_text:
            logger.warning("❌ 生成文本为空")
            return None
        
        # 解析推理过程和最终答案
        result = {
            "raw_output": generated_text,
            "final_answer": None,
            "thinking": None
        }
        
        # 提取推理过程
        thinking_match = re.search(r'<think>([\s\S]*?)</think>', generated_text)
        if thinking_match:
            thinking_text = thinking_match.group(1).strip()
            result["thinking"] = thinking_text
            logger.debug(f"   推理过程长度: {len(thinking_text)} 字符")
        
        # 提取最终答案
        final_answer = self._extract_final_answer(generated_text)
        result["final_answer"] = final_answer
        logger.info(f"   最终答案长度: {len(final_answer)} 字符")
        
        # 如果不需要推理过程，删除该字段
        if not include_thinking:
            del result["thinking"]
        
        # 删除原始输出（仅用于调试）
        del result["raw_output"]
        
        return result

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        调用本地 Qwen3 生成 JSON 格式的文本
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            **kwargs: 其他参数传递给 generate 方法
        
        Returns:
            dict: 解析后的 JSON 对象，失败返回 None
        """

        logger.info(f"📝 调用 Qwen3 生成 JSON 格式文本")
        
        # 确保提示词要求返回 JSON
        if "json" not in prompt.lower():
            prompt = f"{prompt}\n\n请返回有效的 JSON 格式。"
        
        logger.debug(f"   提示词: {prompt[:100]}...")

        logger.info(f"kwargs: {kwargs}")
        # 调用生成方法
        generated_text = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )

        if not generated_text:
            logger.warning("❌ 生成文本为空，无法解析 JSON")
            return None
        
        # 提取最终答案（去掉推理过程）
        final_answer = self._extract_final_answer(generated_text)
        logger.info(f"   提取后的最终答案: {final_answer}...")
        
        # 尝试提取并解析 JSON
        try:
            # 首先尝试直接解析
            return json.loads(final_answer)
        except json.JSONDecodeError:
            # 尝试从生成的文本中提取 JSON 块
            json_match = re.search(r'\{[\s\S]*\}', final_answer)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ 提取的 JSON 解析失败: {json_match.group(0)[:100]}...")
                    return None
            else:
                logger.warning(f"⚠️ 生成的文本中找不到 JSON 块: {final_answer[:100]}...")
                return None
    
    async def __aenter__(self):
        """异步上下文管理器进入"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()
    
    async def close(self):
        """关闭 HTTP 客户端"""
        await self.http_client.aclose()
        logger.debug("✅ Qwen3 HTTP 客户端已关闭")


# 全局单例实例
_qwen_instance: Optional[Qwen3LocalLLMClient] = None


def get_qwen_client() -> Qwen3LocalLLMClient:
    """
    获取全局 Qwen3 客户端实例
    
    Returns:
        Qwen3LocalLLMClient: 全局客户端实例
    """
    global _qwen_instance
    if _qwen_instance is None:
        _qwen_instance = Qwen3LocalLLMClient()
    return _qwen_instance


async def test_qwen_connection():
    """测试 Qwen3 连接"""
    client = get_qwen_client()
    
    if not client.enabled:
        logger.warning("❌ Qwen3-4B 本地 LLM 未启用")
        return False
    
    # 检查服务器健康
    is_healthy = await client._check_server_health()
    if not is_healthy:
        logger.error("❌ Qwen3 服务器不可用，请确保 LM Studio 正在运行")
        return False
    
    # 测试生成
    logger.info("🧪 测试 Qwen3 生成功能...")
    result = await client.generate(
        prompt="你好，请用一句话介绍自己",
        max_tokens=100
    )
    
    if result:
        logger.info(f"✅ 测试成功: {result}")
        return True
    else:
        logger.error("❌ 测试失败")
        return False


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # 运行测试
    asyncio.run(test_qwen_connection())
