#!/usr/bin/env python3
"""
Qwen3-4B 本地 LLM 测试脚本

测试包括：
1. Qwen3 服务器连接
2. 基本文本生成
3. JSON 格式生成
4. 与 Azure OpenAI 的切换
"""

import sys
import os
import asyncio
import logging

# 添加后端路径到 Python 搜索路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from app.news.qwen_local_llm import Qwen3LocalLLMClient, get_qwen_client, test_qwen_connection
from app.news.llm_service_proxy import get_llm_service_proxy, LLMProvider

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_qwen_basic():
    """测试基本的 Qwen3 功能"""
    logger.info("\n" + "="*80)
    logger.info("🧪 测试 1: 基本 Qwen3 功能")
    logger.info("="*80)
    
    client = get_qwen_client()
    
    if not client.enabled:
        logger.warning("❌ Qwen3-4B 未启用，跳过此测试")
        logger.info("   提示: 在 .env 中设置 LOCAL_QWEN_ENABLED=true 来启用")
        return False
    
    logger.info(f"📝 配置信息:")
    logger.info(f"   - API 端点: {client.base_url}")
    logger.info(f"   - 模型名称: {client.model_name}")
    logger.info(f"   - 超时时间: {client.timeout}s")
    logger.info(f"   - 重试次数: {client.retry_times}x")
    
    # 检查服务器
    logger.info(f"\n🔍 检查服务器连接...")
    is_healthy = await client._check_server_health()
    if not is_healthy:
        logger.error("❌ Qwen3 服务器不可用")
        logger.error("   请确保 LM Studio 正在运行并且在配置的端口上监听")
        return False
    
    logger.info("✅ 服务器连接正常")
    
    # 测试简单生成
    logger.info(f"\n📝 测试简单文本生成...")
    result = await client.generate(
        prompt="请用一句话简洁介绍北京。",
        max_tokens=100
    )
    
    if result:
        logger.info(f"✅ 生成成功:")
        logger.info(f"   {result}")
        return True
    else:
        logger.error("❌ 生成失败")
        return False


async def test_json_generation():
    """测试 JSON 生成功能"""
    logger.info("\n" + "="*80)
    logger.info("🧪 测试 2: JSON 格式生成")
    logger.info("="*80)
    
    client = get_qwen_client()
    
    if not client.enabled:
        logger.warning("❌ Qwen3-4B 未启用，跳过此测试")
        return False
    
    logger.info(f"📝 测试提示词: 分析一条股票新闻并返回 JSON")
    
    prompt = """
    分析以下新闻内容，返回 JSON 格式的分析结果。
    
    新闻标题: 阿里巴巴发布新产品
    新闻内容: 阿里巴巴今日宣布推出新的云计算产品，预计将为企业客户提升 30% 的性能。
    
    (!Important)请严格按照以下JSON格式返回分析结果，不要包含任何其他文字:
    {
        "summary": "新闻摘要",
        "company": "涉及公司",
        "category": "新闻分类",
        "sentiment": "正面/中立/负面"
    }
    """
    
    result = await client.generate_json(
        prompt=prompt,
        max_tokens=4096,
    )

    print(f' ------------------------------------------------> ')

    logger.info(f"\n📝 生成结果: {result}")
    
    if result:
        logger.info(f"✅ JSON 生成成功:")
        for key, value in result.items():
            logger.info(f"   - {key}: {value}")
        return True
    else:
        logger.error("❌ JSON 生成失败")
        return False


async def test_llm_service_proxy():
    """测试 LLM 服务代理"""
    logger.info("\n" + "="*80)
    logger.info("🧪 测试 3: LLM 服务代理")
    logger.info("="*80)
    
    proxy = get_llm_service_proxy()
    
    logger.info(f"📊 代理信息:")
    logger.info(f"   - 当前提供商: {proxy.get_provider_name()}")
    logger.info(f"   - 提供商枚举: {proxy.provider.value}")
    logger.info(f"   - 是否可用: {'✅ 是' if proxy.is_available() else '❌ 否'}")
    
    if not proxy.is_available():
        logger.warning("⚠️ LLM 服务不可用")
        logger.info("   请检查 .env 中的 LOCAL_QWEN_ENABLED 或 AZURE_OPENAI 配置")
        return False
    
    logger.info(f"\n📝 通过代理生成文本...")
    
    result = await proxy.generate(
        prompt="请用一句话介绍你是什么?"
    )
    
    if result:
        logger.info(f"✅ 通过代理生成成功:")
        logger.info(f"   {result}")
        return True
    else:
        logger.error("❌ 通过代理生成失败")
        return False


async def test_provider_switching():
    """测试 LLM 提供商切换"""
    logger.info("\n" + "="*80)
    logger.info("🧪 测试 4: LLM 提供商识别")
    logger.info("="*80)
    
    # 检查环境变量
    qwen_enabled = os.getenv("LOCAL_QWEN_ENABLED", "false").lower() in ("true", "1", "yes")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OPENAI_KEY")
    
    logger.info(f"📊 环境配置检查:")
    logger.info(f"   - LOCAL_QWEN_ENABLED: {qwen_enabled}")
    logger.info(f"   - AZURE_OPENAI_ENDPOINT: {'✅ 已配置' if azure_endpoint else '❌ 未配置'}")
    logger.info(f"   - AZURE_OPENAI_KEY: {'✅ 已配置' if azure_key else '❌ 未配置'}")
    
    proxy = get_llm_service_proxy()
    
    if qwen_enabled:
        expected = LLMProvider.LOCAL_QWEN
    elif azure_endpoint and azure_key:
        expected = LLMProvider.AZURE
    else:
        expected = LLMProvider.NONE
    
    logger.info(f"\n📍 提供商选择:")
    logger.info(f"   - 预期: {expected.value}")
    logger.info(f"   - 实际: {proxy.provider.value}")
    
    if proxy.provider == expected:
        logger.info(f"✅ 提供商识别正确")
        return True
    else:
        logger.warning(f"⚠️ 提供商识别不匹配")
        return False


async def test_system_prompt():
    """测试系统提示词的使用"""
    logger.info("\n" + "="*80)
    logger.info("🧪 测试 5: 系统提示词")
    logger.info("="*80)
    
    client = get_qwen_client()
    
    if not client.enabled:
        logger.warning("❌ Qwen3-4B 未启用，跳过此测试")
        return False
    
    logger.info(f"📝 测试系统提示词的效果...")
    
    # 使用系统提示词
    result = await client.generate(
        prompt="请用中文回答: 什么是人工智能?",
        system_prompt="你是一个技术专家。请用简洁的语言（最多 50 字）回答问题。",
        max_tokens=128
    )
    
    if result:
        logger.info(f"✅ 系统提示词生成成功:")
        logger.info(f"   {result}")
        return True
    else:
        logger.error("❌ 系统提示词生成失败")
        return False


async def main():
    """运行所有测试"""
    logger.info("\n" + "█"*80)
    logger.info("█ Qwen3-4B 本地 LLM 完整测试套件")
    logger.info("█"*80)
    
    results = {}
    
    # 运行所有测试
    tests = [
        # ("基本功能", test_qwen_basic),
        ("JSON 生成", test_json_generation),
        # ("LLM 代理", test_llm_service_proxy),
        # ("提供商识别", test_provider_switching),
        # ("系统提示词", test_system_prompt),
    ]
    
    for test_name, test_func in tests:
        try:
            results[test_name] = await test_func()
        except Exception as e:
            logger.error(f"❌ 测试 '{test_name}' 异常: {e}", exc_info=True)
            results[test_name] = False
    
    # 总结
    logger.info("\n" + "="*80)
    logger.info("📊 测试总结")
    logger.info("="*80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        logger.info(f"{status}: {test_name}")
    
    logger.info(f"\n📈 总体结果: {passed}/{total} 通过")
    
    if passed == total:
        logger.info("🎉 所有测试通过！Qwen3-4B 已准备就绪")
    else:
        logger.warning(f"⚠️ 有 {total - passed} 个测试失败，请检查配置")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
