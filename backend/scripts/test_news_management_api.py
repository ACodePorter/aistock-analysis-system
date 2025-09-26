#!/usr/bin/env python3
"""
测试新闻管理API端点
"""
import requests
import json
import time
import sys
import os

# 添加后端目录到Python路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

BASE_URL = "http://localhost:8080"

def test_news_stats():
    """测试新闻统计API"""
    print("🧪 测试新闻统计API...")
    try:
        response = requests.get(f"{BASE_URL}/api/news/stats")
        if response.status_code == 200:
            data = response.json()
            print("✅ 新闻统计API正常")
            print(f"   总文章数: {data.get('total_articles', 0)}")
            print(f"   今日文章数: {data.get('today_articles', 0)}")
            return True
        else:
            print(f"❌ 新闻统计API失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"❌ 新闻统计API异常: {e}")
        return False

def test_get_news_articles():
    """测试获取新闻文章API"""
    print("🧪 测试获取新闻文章API...")
    try:
        response = requests.get(f"{BASE_URL}/api/news/articles?limit=5")
        if response.status_code == 200:
            data = response.json()
            print("✅ 获取新闻文章API正常")
            print(f"   返回文章数: {len(data.get('articles', []))}")
            if data.get('articles'):
                first_article = data['articles'][0]
                print(f"   示例文章: {first_article.get('title', '')[:50]}...")
                return first_article.get('id')
            return None
        else:
            print(f"❌ 获取新闻文章API失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return None
    except Exception as e:
        print(f"❌ 获取新闻文章API异常: {e}")
        return None

def test_bookmark_toggle(article_id):
    """测试书签切换API"""
    if not article_id:
        print("⚠️ 跳过书签测试 - 没有可用的文章ID")
        return False

    print(f"🧪 测试书签切换API (文章ID: {article_id})...")
    try:
        response = requests.post(f"{BASE_URL}/api/news/{article_id}/bookmark")
        if response.status_code == 200:
            data = response.json()
            print("✅ 书签切换API正常")
            print(f"   书签状态: {data.get('is_bookmarked', 'unknown')}")
            return True
        else:
            print(f"❌ 书签切换API失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"❌ 书签切换API异常: {e}")
        return False

def test_read_status_toggle(article_id):
    """测试已读状态切换API"""
    if not article_id:
        print("⚠️ 跳过已读状态测试 - 没有可用的文章ID")
        return False

    print(f"🧪 测试已读状态切换API (文章ID: {article_id})...")
    try:
        response = requests.post(f"{BASE_URL}/api/news/{article_id}/read")
        if response.status_code == 200:
            data = response.json()
            print("✅ 已读状态切换API正常")
            print(f"   已读状态: {data.get('is_read', 'unknown')}")
            return True
        else:
            print(f"❌ 已读状态切换API失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"❌ 已读状态切换API异常: {e}")
        return False

def test_batch_update():
    """测试批量更新API"""
    print("🧪 测试批量更新API...")
    try:
        # 首先获取一些文章ID
        response = requests.get(f"{BASE_URL}/api/news/articles?limit=3")
        if response.status_code != 200:
            print("⚠️ 跳过批量更新测试 - 无法获取文章列表")
            return False

        data = response.json()
        articles = data.get('articles', [])
        if not articles:
            print("⚠️ 跳过批量更新测试 - 没有文章")
            return False

        article_ids = [article['id'] for article in articles[:2]]  # 取前2个

        # 测试批量标记为已读
        response = requests.post(
            f"{BASE_URL}/api/news/batch-update?action=mark_read&article_ids={','.join(map(str, article_ids))}"
        )

        if response.status_code == 200:
            data = response.json()
            print("✅ 批量更新API正常")
            print(f"   更新数量: {data.get('updated_count', 0)}")
            return True
        else:
            print(f"❌ 批量更新API失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"❌ 批量更新API异常: {e}")
        return False

def check_server_running():
    """检查服务器是否在运行"""
    try:
        response = requests.get("http://localhost:8080/", timeout=5)
        return response.status_code == 200
    except:
        return False

def main():
    """主测试函数"""
    print("🚀 开始测试新闻管理API端点")
    print("=" * 50)

    # 检查服务器是否在运行
    if not check_server_running():
        print("❌ 服务器没有运行，请先启动服务器")
        print("   运行命令: cd backend/scripts && python simple_test_server.py")
        return 1

    print("✅ 服务器正在运行")

    results = []

    # 测试各个API端点
    results.append(("新闻统计", test_news_stats()))
    article_id = test_get_news_articles()
    results.append(("获取文章", article_id is not None))
    results.append(("书签切换", test_bookmark_toggle(article_id)))
    results.append(("已读状态切换", test_read_status_toggle(article_id)))
    results.append(("批量更新", test_batch_update()))

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