#!/usr/bin/env python3
"""
MongoDB用户创建脚本
用于在MongoDB中创建应用程序用户
"""
import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def create_mongo_user():
    """在MongoDB中创建用户"""
    print("👤 MongoDB用户创建工具")
    print("=" * 50)

    # MongoDB管理员凭据（需要先手动创建admin用户）
    admin_user = input("输入MongoDB管理员用户名 (默认: admin): ").strip() or "admin"
    admin_password = input("输入MongoDB管理员密码: ").strip()

    if not admin_password:
        print("❌ 需要管理员密码来创建用户")
        return False

    # 新用户配置
    new_user = os.getenv("MONGO_USER", "admin")
    new_password = os.getenv("MONGO_PASSWORD", "password123")
    database = os.getenv("MONGO_DB", "aistock_news")

    print(f"📋 将创建用户:")
    print(f"   用户名: {new_user}")
    print(f"   数据库: {database}")
    print(f"   权限: readWrite")
    print()

    try:
        import pymongo

        # 连接到admin数据库
        admin_uri = f"mongodb://{admin_user}:{admin_password}@localhost:27017/admin"
        print("🔌 连接到MongoDB admin数据库...")

        client = pymongo.MongoClient(admin_uri, serverSelectionTimeoutMS=5000)
        client.server_info()
        print("✅ 管理员连接成功")

        # 创建用户
        admin_db = client.admin
        result = admin_db.command({
            "createUser": new_user,
            "pwd": new_password,
            "roles": [
                {
                    "role": "readWrite",
                    "db": database
                }
            ]
        })

        if result.get("ok") == 1:
            print(f"✅ 用户 '{new_user}' 创建成功")
            print(f"   可以在数据库 '{database}' 中进行读写操作")
            client.close()
            return True
        else:
            print(f"❌ 用户创建失败: {result}")
            return False

    except pymongo.errors.ServerSelectionTimeoutError:
        print("❌ 连接超时 - 请检查MongoDB服务是否运行")
        return False

    except pymongo.errors.OperationFailure as e:
        error_msg = str(e)
        if "Authentication failed" in error_msg:
            print("❌ 管理员认证失败 - 请检查管理员用户名和密码")
        else:
            print(f"❌ 操作失败: {e}")
        return False

    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def disable_auth():
    """提供禁用认证的指导"""
    print("🔓 禁用MongoDB认证的步骤:")
    print("=" * 50)
    print("1. 停止MongoDB服务:")
    print("   sudo systemctl stop mongod  # Linux")
    print("   # 或在Windows服务管理器中停止MongoDB")
    print()
    print("2. 以无认证模式启动MongoDB:")
    print("   mongod --dbpath /path/to/your/db --noauth")
    print()
    print("3. 或者修改MongoDB配置文件:")
    print("   - 找到mongod.conf文件")
    print("   - 设置 security.authorization: disabled")
    print("   - 重启MongoDB服务")
    print()
    print("⚠️ 警告: 在生产环境中禁用认证是不安全的")
    print("   只在开发环境中使用")

def main():
    """主函数"""
    try:
        print("选择操作:")
        print("1. 创建MongoDB用户")
        print("2. 查看禁用认证的指导")
        print("3. 退出")
        print()

        choice = input("请输入选择 (1-3): ").strip()

        if choice == "1":
            success = create_mongo_user()
            if success:
                print("\n🎉 用户创建完成！现在可以重新运行诊断脚本。")
            return 0 if success else 1
        elif choice == "2":
            disable_auth()
            return 0
        elif choice == "3":
            print("👋 再见！")
            return 0
        else:
            print("❌ 无效选择")
            return 1

    except KeyboardInterrupt:
        print("\n👋 操作已取消")
        return 0
    except ImportError:
        print("❌ 缺少pymongo库，请安装: pip install pymongo")
        return 1

if __name__ == "__main__":
    sys.exit(main())