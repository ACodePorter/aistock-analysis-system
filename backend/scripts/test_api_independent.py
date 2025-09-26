#!/usr/bin/env python3
"""
独立测试新闻管理API端点 - 不依赖服务器运行状态
"""
import requests
import json
import time
import sys
import os

BASE_URL = "http://localhost:8080"

def test_api_endpoint(name, method, url, expected_status=200, **kwargs):
    """测试单个API端点"""
    print(f"🧪 测试{name}...")
    try:
        if method.upper() == "GET":
            response = requests.get(url, **kwargs)
        elif method.upper() == "POST":
            response = requests.post(url, **kwargs)
        else:
            print(f"❌ 不支持的HTTP方法: {method}")
            return False

        if response.status_code == expected_status:
            print(f"✅ {name}正常")
            try:
                data = response.json()
                print(f"   响应: {json.dumps(data, indent=2, ensure_ascii=False)[:200]}...")
            except:
                print(f"   响应: {response.text[:200]}...")
            return True
        else:
            print(f"❌ {name}失败: {response.status_code}")
            print(f"   响应: {response.text[:200]}...")
            return False
    except Exception as e:
        print(f"❌ {name}异常: {e}")
        return False

def main():
    """主测试函数"""
    print("🚀 开始独立测试新闻管理API端点")
    print("=" * 50)

    # 检查服务器是否在运行
    try:
        response = requests.get("http://localhost:8080/", timeout=5)
        if response.status_code != 200:
            print("❌ 服务器响应异常")
            return 1
    except:
        print("❌ 无法连接到服务器，请确保服务器正在运行在 http://localhost:8080")
        print("   启动命令: cd backend/scripts && python simple_test_server.py")
        return 1

    print("✅ 服务器正在运行")

    results = []

    # 测试各个API端点
    results.append(("根路径", test_api_endpoint("根路径", "GET", f"{BASE_URL}/")))
    results.append(("新闻统计", test_api_endpoint("新闻统计", "GET", f"{BASE_URL}/api/news/stats")))
    results.append(("获取文章", test_api_endpoint("获取文章", "GET", f"{BASE_URL}/api/news/articles")))

    # 测试书签切换 (使用示例ID)
    results.append(("书签切换", test_api_endpoint("书签切换", "POST", f"{BASE_URL}/api/news/1/bookmark")))

    # 测试已读状态切换
    results.append(("已读状态切换", test_api_endpoint("已读状态切换", "POST", f"{BASE_URL}/api/news/1/read")))

    # 测试批量更新
    results.append(("批量更新", test_api_endpoint("批量更新", "POST",
        f"{BASE_URL}/api/news/batch-update",
        params={"action": "mark_read", "article_ids": "1,2"}
    )))

    # 汇总结果
    print("\n" + "=" * 50)
    print("📊 测试结果汇总:")
    passed = 0
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {name}: {status}")
        if result:
            passed += 1

    print(f"\n🎯 总体结果: {passed}/{total} 个测试通过")

    if passed == total:
        print("🎉 所有测试通过！新闻管理API端点工作正常")
        return 0
    else:
        print("⚠️ 部分测试失败，请检查API端点实现")
        return 1

if __name__ == "__main__":
    sys.exit(main())