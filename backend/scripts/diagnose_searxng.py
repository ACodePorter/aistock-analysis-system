#!/usr/bin/env python
"""SearXNG 完整诊断工具"""
import asyncio
import httpx
import json
import subprocess
from urllib.parse import urljoin

async def diagnose_searxng():
    """完整的SearXNG诊断工具"""
    
    searxng_url = "http://localhost:10000"
    
    print("=" * 70)
    print("🔧 SearXNG 完整诊断")
    print("=" * 70)
    
    # 1. 检查基础连接
    print("\n【步骤1】检查SearXNG基础服务...")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(searxng_url)
            print(f"✅ SearXNG服务可访问: HTTP {response.status_code}")
            print(f"   响应大小: {len(response.content)} bytes")
    except Exception as e:
        print(f"❌ 无法连接到SearXNG: {e}")
        return
    
    # 2. 获取服务信息
    print("\n【步骤2】获取SearXNG服务信息...")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            info_url = urljoin(searxng_url, "/info/en")
            response = await client.get(info_url)
            print(f"ℹ️  Info端点: HTTP {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   SearXNG版本: {data.get('version', 'unknown')}")
                engines = data.get('engines', {})
                print(f"   可用搜索引擎: {len(engines)}")
                print(f"   引擎列表: {', '.join(list(engines.keys())[:10])}")
    except Exception as e:
        print(f"⚠️  Info端点失败: {e}")
    
    # 3. 测试简单GET搜索
    print("\n【步骤3】测试简单GET搜索请求...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            search_url = urljoin(searxng_url, "/search")
            response = await client.get(
                search_url,
                params={
                    "q": "test",
                    "format": "json"
                },
                headers={"User-Agent": "Mozilla/5.0"}
            )
            print(f"✅ GET搜索: HTTP {response.status_code}")
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"   返回结果数: {len(data.get('results', []))}")
                except:
                    print(f"   响应不是JSON: {response.text[:100]}")
            elif response.status_code == 502:
                print(f"❌ 502 Bad Gateway!")
                print(f"   响应: {response.text[:300]}")
    except Exception as e:
        print(f"❌ GET搜索失败: {e}")
    
    # 4. 测试POST搜索
    print("\n【步骤4】测试POST搜索请求...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            search_url = urljoin(searxng_url, "/search")
            response = await client.post(
                search_url,
                data={
                    "q": "test",
                    "format": "json"
                },
                headers={"User-Agent": "Mozilla/5.0"}
            )
            print(f"POST搜索: HTTP {response.status_code}")
            if response.status_code == 502:
                print(f"❌ 502 Bad Gateway!")
                print(f"   这可能是 POST 请求问题")
            elif response.status_code == 200:
                print(f"✅ POST也成功")
    except Exception as e:
        print(f"❌ POST搜索失败: {e}")
    
    # 5. 测试不同的搜索引擎
    print("\n【步骤5】测试单个搜索引擎...")
    engines_to_test = ["google", "bing", "wikipedia", "baidu"]
    
    for engine in engines_to_test:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                search_url = urljoin(searxng_url, "/search")
                response = await client.get(
                    search_url,
                    params={
                        "q": "test",
                        "format": "json",
                        "engines": engine
                    },
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                status = "✅" if response.status_code == 200 else "❌"
                print(f"{status} {engine.upper()}: HTTP {response.status_code}")
                if response.status_code == 502:
                    print(f"   → {engine} 不可用或有问题")
        except Exception as e:
            print(f"❌ {engine.upper()}: {e}")
    
    # 6. 检查Docker容器状态
    print("\n【步骤6】检查Docker容器状态...")
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "status=running"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            if "searxng" in result.stdout.lower():
                print("✅ SearXNG Docker容器正在运行")
                # 获取容器ID
                lines = result.stdout.split('\n')
                for line in lines:
                    if "searxng" in line.lower():
                        print(f"   {line}")
                        
                # 查看最近日志
                print("\n   最近日志:")
                result = subprocess.run(
                    ["docker", "logs", "--tail", "20", "-f"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    input="searxng\n"
                )
                for line in result.stdout.split('\n')[-15:]:
                    if line.strip():
                        print(f"     {line}")
            else:
                print("⚠️  未找到SearXNG容器")
                print(f"   运行的容器: {result.stdout[:200]}")
        else:
            print("⚠️  无法执行docker命令")
    except Exception as e:
        print(f"⚠️  无法查看Docker状态: {e}")
    
    # 7. 推荐方案
    print("\n" + "=" * 70)
    print("【问题诊断和解决方案】")
    print("=" * 70)
    print("""
如果所有搜索都返回502，可能的原因：

1️⃣  SearXNG搜索引擎全部宕机
   → 检查Docker日志中是否有错误
   → 重启容器: docker restart searxng
   → 检查网络连接

2️⃣  SearXNG配置问题
   → 某些搜索引擎被禁用或配置错误
   → 解决: 编辑 searxng/settings.yml
   
3️⃣  POST请求问题
   → 改用GET请求而非POST
   → 或者检查SearXNG是否禁用了POST
   
4️⃣  内存或资源不足
   → 查看docker日志中是否有OOM错误
   → 增加Docker内存限制

5️⃣  SearXNG反向代理配置问题
   → 如果在Nginx后面，检查超时设置
   → 检查是否有请求体大小限制
    """)

if __name__ == "__main__":
    asyncio.run(diagnose_searxng())
