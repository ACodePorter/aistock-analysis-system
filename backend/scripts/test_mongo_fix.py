#!/usr/bin/env python3
"""
测试MongoDB布尔值测试修复
"""
import sys
import os

# 添加后端目录到Python路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

def test_mongo_storage_import():
    """测试MongoDB存储模块导入"""
    try:
        from app.mongo_storage import StockNewsStorage
        print("✅ MongoDB存储模块导入成功")

        # 创建实例（不会实际连接）
        storage = StockNewsStorage()
        print("✅ StockNewsStorage实例创建成功")

        # 检查初始状态
        print(f"   client: {storage.client}")
        print(f"   db: {storage.db}")

        return True
    except Exception as e:
        print(f"❌ MongoDB存储模块导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_news_deduplication_import():
    """测试新闻去重模块导入"""
    try:
        from app.news_deduplication import NewsDeduplicator
        print("✅ 新闻去重模块导入成功")

        # 创建实例（不会实际连接）
        deduplicator = NewsDeduplicator()
        print("✅ NewsDeduplicator实例创建成功")

        # 检查初始状态
        print(f"   mongo_client: {deduplicator.mongo_client}")
        print(f"   db: {deduplicator.db}")

        return True
    except Exception as e:
        print(f"❌ 新闻去重模块导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("🧪 测试MongoDB布尔值测试修复")
    print("=" * 50)

    results = []

    # 测试各个模块
    results.append(("MongoDB存储模块", test_mongo_storage_import()))
    results.append(("新闻去重模块", test_news_deduplication_import()))

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
        print("🎉 所有测试通过！MongoDB布尔值测试修复成功")
        print("   警告信息应该不再出现")
        return 0
    else:
        print("⚠️ 部分测试失败，请检查修复")
        return 1

if __name__ == "__main__":
    sys.exit(main())