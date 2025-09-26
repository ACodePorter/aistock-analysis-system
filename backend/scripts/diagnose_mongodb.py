#!/usr/bin/env python3
"""
MongoDB连接诊断脚本
"""
import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def diagnose_mongodb():
    """诊断MongoDB连接问题"""
    print("🔍 MongoDB连接诊断")
    print("=" * 50)

    # 检查环境变量
    mongo_host = os.getenv("MONGO_HOST", "localhost")
    mongo_port = os.getenv("MONGO_PORT", "27017")
    mongo_user = os.getenv("MONGO_USER", "")
    mongo_password = os.getenv("MONGO_PASSWORD", "")
    mongo_db = os.getenv("MONGO_DB", "aistock_news")

    print(f"📋 当前配置:")
    print(f"   MONGO_HOST: {mongo_host}")
    print(f"   MONGO_PORT: {mongo_port}")
    print(f"   MONGO_USER: {'***' if mongo_user else '(empty)'}")
    print(f"   MONGO_PASSWORD: {'***' if mongo_password else '(empty)'}")
    print(f"   MONGO_DB: {mongo_db}")
    print()

    # 构造连接URI
    if mongo_user and mongo_password:
        uri = f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/{mongo_db}"
        print("🔐 使用带认证的连接")
    else:
        uri = f"mongodb://{mongo_host}:{mongo_port}/{mongo_db}"
        print("🔓 使用无认证的连接")

    print(f"📡 连接URI: {uri}")
    print()

    # 测试连接
    try:
        import pymongo
        print("🔌 尝试连接MongoDB...")

        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)

        # 测试连接
        client.server_info()
        print("✅ MongoDB连接成功")

        # 测试数据库访问
        db = client[mongo_db]
        print(f"✅ 数据库 '{mongo_db}' 访问成功")

        # 测试创建索引（这会触发认证错误）
        try:
            test_collection = db["test_connection"]
            test_collection.create_index("test_field")
            print("✅ 索引创建成功")
            # 清理测试索引
            test_collection.drop_index("test_field_1")
        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
                print("❌ 认证失败 - 请检查用户名和密码")
                print(f"   错误详情: {e}")
                return False
            else:
                print(f"⚠️ 索引创建失败 (非认证问题): {e}")

        client.close()
        print("✅ MongoDB诊断完成 - 连接正常")
        return True

    except pymongo.errors.ServerSelectionTimeoutError:
        print("❌ 连接超时 - 请检查MongoDB服务是否运行")
        print("   解决方案:")
        print("   1. 确保MongoDB服务正在运行")
        print("   2. 检查网络连接")
        print("   3. 验证主机和端口配置")
        return False

    except pymongo.errors.ConfigurationError as e:
        print(f"❌ 配置错误: {e}")
        return False

    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
            print("❌ 认证失败 - 请检查用户名和密码")
            print(f"   错误详情: {e}")
            print("   解决方案:")
            print("   1. 在.env文件中设置正确的MONGO_USER和MONGO_PASSWORD")
            print("   2. 或者在MongoDB中禁用认证")
            return False
        else:
            print(f"❌ 连接失败: {e}")
            return False

def main():
    """主函数"""
    try:
        success = diagnose_mongodb()
        print()
        if success:
            print("🎉 MongoDB连接正常！后端应该可以正常启动了。")
        else:
            print("⚠️ MongoDB连接存在问题，请根据上述建议解决。")
            print("   如果不需要MongoDB功能，可以继续使用PostgreSQL。")
        return 0 if success else 1
    except ImportError:
        print("❌ 缺少pymongo库，请安装: pip install pymongo")
        return 1

if __name__ == "__main__":
    sys.exit(main())