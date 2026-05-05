#!/usr/bin/env python3
"""
Qwen3-4B 本地 LLM 诊断脚本

用于诊断本地 Qwen3 模型的连接和配置问题
"""

import asyncio
import json
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

# 从项目根目录加载 .env 文件
project_root = Path(__file__).parent.parent.parent
env_file = project_root / ".env"
load_dotenv(dotenv_path=str(env_file), override=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Qwen3Diagnostics:
    """Qwen3 诊断工具"""
    
    def __init__(self):
        """初始化诊断工具"""
        self.results = []
        self.errors = []
    
    def _log_result(self, title: str, status: bool, message: str = ""):
        """记录诊断结果"""
        symbol = "✅" if status else "❌"
        full_msg = f"{symbol} {title}"
        if message:
            full_msg += f": {message}"
        
        logger.info(full_msg)
        self.results.append({
            "title": title,
            "status": status,
            "message": message
        })
        
        if not status:
            self.errors.append(title)
    
    def check_env_config(self) -> bool:
        """检查 .env 配置"""
        logger.info("\n" + "=" * 80)
        logger.info("🔍 检查 .env 配置")
        logger.info("=" * 80)
        
        enabled = os.getenv("LOCAL_QWEN_ENABLED", "false").lower() in ("true", "1", "yes")
        self._log_result(
            "LOCAL_QWEN_ENABLED",
            enabled,
            "已启用" if enabled else "未启用（需要设置为 true）"
        )
        
        if not enabled:
            logger.warning("⚠️ Qwen3 未启用，需要在 .env 中设置 LOCAL_QWEN_ENABLED=true")
            return False
        
        # 检查其他配置
        url = os.getenv("LOCAL_QWEN_URL", "http://localhost:1234/v1")
        self._log_result("LOCAL_QWEN_URL", bool(url), url)
        
        model = os.getenv("LOCAL_QWEN_MODEL", "local-model")
        self._log_result("LOCAL_QWEN_MODEL", bool(model), model)
        
        try:
            timeout = float(os.getenv("LOCAL_QWEN_TIMEOUT", "120"))
            self._log_result("LOCAL_QWEN_TIMEOUT", True, f"{timeout} 秒")
        except ValueError:
            self._log_result("LOCAL_QWEN_TIMEOUT", False, "配置值无效")
        
        return True
    
    async def check_network_connectivity(self) -> bool:
        """检查网络连接"""
        logger.info("\n" + "=" * 80)
        logger.info("🌐 检查网络连接")
        logger.info("=" * 80)
        
        # 解析 URL
        url = os.getenv("LOCAL_QWEN_URL", "http://localhost:1234/v1")
        
        # 提取主机和端口
        try:
            if url.startswith("http://"):
                url_part = url[7:]  # 移除 http://
            elif url.startswith("https://"):
                url_part = url[8:]  # 移除 https://
            else:
                url_part = url
            
            if "/" in url_part:
                host_port = url_part.split("/")[0]
            else:
                host_port = url_part
            
            if ":" in host_port:
                host, port_str = host_port.rsplit(":", 1)
                port = int(port_str)
            else:
                host = host_port
                port = 80 if url.startswith("http://") else 443
            
            logger.info(f"   主机: {host}")
            logger.info(f"   端口: {port}")
            
            # 尝试 TCP 连接
            logger.info(f"   尝试连接 {host}:{port}...")
            
            try:
                # 创建套接字
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                
                # 连接
                result = sock.connect_ex((host, port))
                sock.close()
                
                if result == 0:
                    self._log_result(
                        f"TCP 连接到 {host}:{port}",
                        True,
                        "连接成功"
                    )
                    return True
                else:
                    self._log_result(
                        f"TCP 连接到 {host}:{port}",
                        False,
                        f"连接失败（错误码: {result}）"
                    )
                    return False
            
            except socket.gaierror as e:
                self._log_result(
                    f"主机解析 {host}",
                    False,
                    f"DNS 解析失败: {e}"
                )
                return False
            except Exception as e:
                self._log_result(
                    f"TCP 连接",
                    False,
                    f"连接异常: {e}"
                )
                return False
        
        except Exception as e:
            self._log_result("URL 解析", False, str(e))
            return False
    
    async def check_lm_studio_api(self) -> bool:
        """检查 LM Studio API"""
        logger.info("\n" + "=" * 80)
        logger.info("🤖 检查 LM Studio API")
        logger.info("=" * 80)
        
        url = os.getenv("LOCAL_QWEN_URL", "http://localhost:1234/v1")
        timeout = float(os.getenv("LOCAL_QWEN_TIMEOUT", "120"))
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 检查 /models 端点
                models_url = f"{url}/models"
                logger.info(f"   检查 {models_url}...")
                
                try:
                    resp = await asyncio.wait_for(
                        client.get(models_url),
                        timeout=10
                    )
                    
                    if resp.status_code == 200:
                        try:
                            models_data = resp.json()
                            models = models_data.get("data", [])
                            
                            self._log_result(
                                "GET /models",
                                True,
                                f"获取成功，共 {len(models)} 个模型"
                            )
                            
                            # 显示可用的模型
                            if models:
                                logger.info("   可用的模型:")
                                for model in models:
                                    model_id = model.get("id", "unknown")
                                    logger.info(f"     - {model_id}")
                            
                            return True
                        except json.JSONDecodeError as e:
                            self._log_result(
                                "GET /models",
                                False,
                                f"响应 JSON 解析失败: {e}"
                            )
                            return False
                    else:
                        self._log_result(
                            "GET /models",
                            False,
                            f"HTTP {resp.status_code}"
                        )
                        return False
                
                except asyncio.TimeoutError:
                    self._log_result(
                        "GET /models",
                        False,
                        "请求超时（10秒）"
                    )
                    return False
                except Exception as e:
                    self._log_result(
                        "GET /models",
                        False,
                        f"请求失败: {e}"
                    )
                    return False
        
        except Exception as e:
            self._log_result("LM Studio API", False, str(e))
            return False
    
    async def check_qwen_model_loading(self) -> bool:
        """检查 Qwen 模型是否已加载"""
        logger.info("\n" + "=" * 80)
        logger.info("📦 检查 Qwen 模型加载状态")
        logger.info("=" * 80)
        
        url = os.getenv("LOCAL_QWEN_URL", "http://localhost:1234/v1")
        model_name = os.getenv("LOCAL_QWEN_MODEL", "local-model")
        timeout = float(os.getenv("LOCAL_QWEN_TIMEOUT", "120"))
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                models_url = f"{url}/models"
                
                try:
                    resp = await asyncio.wait_for(
                        client.get(models_url),
                        timeout=10
                    )
                    
                    if resp.status_code == 200:
                        models_data = resp.json()
                        models = models_data.get("data", [])
                        model_ids = [m.get("id", "") for m in models]
                        
                        # 检查配置的模型是否在列表中
                        if model_name in model_ids:
                            self._log_result(
                                f"模型 '{model_name}' 已加载",
                                True,
                                "模型可用"
                            )
                            return True
                        else:
                            # 检查是否有任何模型
                            if model_ids:
                                available = ", ".join(model_ids)
                                self._log_result(
                                    f"模型 '{model_name}' 已加载",
                                    False,
                                    f"模型不在已加载列表中。已加载的模型: {available}"
                                )
                            else:
                                self._log_result(
                                    f"模型 '{model_name}' 已加载",
                                    False,
                                    "没有模型被加载，请在 LM Studio 中加载 Qwen3-4B"
                                )
                            return False
                    else:
                        self._log_result(
                            "模型检查",
                            False,
                            f"HTTP {resp.status_code}"
                        )
                        return False
                
                except asyncio.TimeoutError:
                    self._log_result(
                        "模型检查",
                        False,
                        "请求超时"
                    )
                    return False
                except Exception as e:
                    self._log_result(
                        "模型检查",
                        False,
                        f"异常: {e}"
                    )
                    return False
        
        except Exception as e:
            self._log_result("模型检查", False, str(e))
            return False
    
    async def test_qwen_generation(self) -> bool:
        """测试 Qwen 文本生成"""
        logger.info("\n" + "=" * 80)
        logger.info("✍️ 测试文本生成")
        logger.info("=" * 80)
        
        url = os.getenv("LOCAL_QWEN_URL", "http://localhost:1234/v1")
        model_name = os.getenv("LOCAL_QWEN_MODEL", "local-model")
        timeout = float(os.getenv("LOCAL_QWEN_TIMEOUT", "120"))
        
        # 简单的测试提示词
        test_prompt = "你好"
        
        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": test_prompt}
            ],
            "max_tokens": 100,
            "temperature": 0.7,
            "top_p": 0.9,
            "stream": False,
        }
        
        chat_url = f"{url}/chat/completions"
        logger.info(f"   调用 {chat_url}")
        logger.info(f"   测试提示词: '{test_prompt}'")
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                try:
                    resp = await asyncio.wait_for(
                        client.post(
                            chat_url,
                            json=payload,
                            headers={"Content-Type": "application/json"}
                        ),
                        timeout=timeout + 5
                    )
                    
                    if resp.status_code == 200:
                        response_data = resp.json()
                        
                        # 提取生成的文本
                        if "choices" in response_data and response_data["choices"]:
                            message = response_data["choices"][0].get("message", {})
                            generated_text = message.get("content", "").strip()
                            
                            if generated_text:
                                self._log_result(
                                    "文本生成",
                                    True,
                                    f"成功生成 {len(generated_text)} 字符"
                                )
                                logger.info(f"   生成的文本: {generated_text[:100]}...")
                                return True
                            else:
                                self._log_result(
                                    "文本生成",
                                    False,
                                    "生成的文本为空"
                                )
                                return False
                        else:
                            self._log_result(
                                "文本生成",
                                False,
                                "响应中没有 choices 字段"
                            )
                            logger.info(f"   响应: {response_data}")
                            return False
                    else:
                        try:
                            error_data = resp.json()
                            error_msg = error_data.get("error", {}).get("message", str(resp.status_code))
                        except:
                            error_msg = f"HTTP {resp.status_code}"
                        
                        self._log_result(
                            "文本生成",
                            False,
                            error_msg
                        )
                        return False
                
                except asyncio.TimeoutError:
                    self._log_result(
                        "文本生成",
                        False,
                        f"生成超时（{timeout}秒），模型可能在处理中"
                    )
                    return False
                except Exception as e:
                    self._log_result(
                        "文本生成",
                        False,
                        f"异常: {e}"
                    )
                    return False
        
        except Exception as e:
            self._log_result("文本生成", False, str(e))
            return False
    
    async def run_all_diagnostics(self):
        """运行所有诊断"""
        logger.info("\n")
        logger.info("████████████████████████████████████████████████████████████████████████████████")
        logger.info("█ Qwen3-4B 本地 LLM 诊断工具")
        logger.info("████████████████████████████████████████████████████████████████████████████████")
        
        # 1. 检查环境配置
        config_ok = self.check_env_config()
        
        if not config_ok:
            logger.error("\n❌ 环境配置不正确，请先修改 .env 文件")
            logger.error("   需要设置: LOCAL_QWEN_ENABLED=true")
            return False
        
        # 2. 检查网络连接
        network_ok = await self.check_network_connectivity()
        
        if not network_ok:
            logger.error("\n❌ 无法连接到 LM Studio")
            logger.error("   请检查:")
            logger.error("   1. LM Studio 是否正在运行")
            logger.error("   2. 本地 Qwen3-4B 模型是否已启动")
            logger.error("   3. LM Studio 监听地址是否正确 (默认: http://localhost:1234)")
            return False
        
        # 3. 检查 LM Studio API
        api_ok = await self.check_lm_studio_api()
        
        if not api_ok:
            logger.error("\n❌ LM Studio API 不可用")
            logger.error("   请检查 LM Studio 是否正在运行")
            return False
        
        # 4. 检查模型加载
        model_ok = await self.check_qwen_model_loading()
        
        if not model_ok:
            logger.error("\n❌ Qwen3 模型未加载")
            logger.error("   请在 LM Studio 中加载 Qwen3-4B 模型")
            return False
        
        # 5. 测试文本生成
        gen_ok = await self.test_qwen_generation()
        
        if not gen_ok:
            logger.error("\n❌ 文本生成失败")
            logger.error("   请检查模型和 LM Studio 的状态")
            return False
        
        # 所有诊断通过
        logger.info("\n" + "=" * 80)
        logger.info("✅ 所有诊断通过！Qwen3-4B 本地 LLM 可以正常使用")
        logger.info("=" * 80)
        return True


async def main():
    """主函数"""
    diag = Qwen3Diagnostics()
    success = await diag.run_all_diagnostics()
    
    # 返回退出码
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
