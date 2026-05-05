#!/usr/bin/env python3
"""
API集成测试 - 测试核心API端点的功能
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

import requests
import json
import time
from datetime import datetime

class APITester:
    def __init__(self, base_url="http://localhost:8081"):
        self.base_url = base_url
        self.test_symbols = ["002594.SZ", "002649.SZ"]
    
    def test_health(self):
        """测试健康检查端点"""
        print("🔍 测试健康检查...")
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            if response.status_code == 200:
                print("  ✅ 健康检查正常")
                return True
            else:
                print(f"  ❌ 健康检查失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ 连接失败: {e}")
            return False
    
    def test_stock_search(self):
        """测试股票搜索"""
        print("\n🔍 测试股票搜索...")
        try:
            response = requests.get(f"{self.base_url}/stock/search?q=比亚迪", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ 搜索成功，找到 {len(data)} 个结果")
                return True
            else:
                print(f"  ❌ 搜索失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ 搜索异常: {e}")
            return False
    
    def test_reports(self):
        """测试报告端点"""
        print("\n📋 测试报告端点...")
        success_count = 0
        
        for symbol in self.test_symbols:
            try:
                response = requests.get(f"{self.base_url}/report/{symbol}", timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    if 'symbol' in data and 'summary' in data:
                        print(f"  ✅ {symbol} 报告正常")
                        success_count += 1
                    else:
                        print(f"  ❌ {symbol} 报告数据不完整")
                else:
                    print(f"  ❌ {symbol} 报告获取失败: {response.status_code}")
            except Exception as e:
                print(f"  ❌ {symbol} 报告异常: {e}")
        
        return success_count > 0
    
    def test_manual_training(self):
        """测试手动训练端点"""
        print("\n🔄 测试手动训练...")
        try:
            response = requests.post(f"{self.base_url}/run/daily", timeout=30)
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ 手动训练启动成功: {data.get('message', 'Unknown')}")
                return True
            else:
                print(f"  ❌ 手动训练失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ 手动训练异常: {e}")
            return False
    
    def test_watchlist(self):
        """测试监控列表端点"""
        print("\n👀 测试监控列表...")
        try:
            response = requests.get(f"{self.base_url}/watchlist", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ 监控列表正常，共 {len(data)} 只股票")
                return True
            else:
                print(f"  ❌ 监控列表获取失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ 监控列表异常: {e}")
            return False
    
    def run_all_tests(self):
        """运行所有测试"""
        print("🧪 API集成测试")
        print("=" * 50)
        
        tests = [
            ("健康检查", self.test_health),
            ("股票搜索", self.test_stock_search),
            ("报告端点", self.test_reports),
            ("监控列表", self.test_watchlist),
            ("手动训练", self.test_manual_training),
        ]
        
        results = []
        for name, test_func in tests:
            result = test_func()
            results.append((name, result))
        
        # 总结结果
        print("\n" + "=" * 50)
        print("📊 测试结果总结:")
        
        passed_count = 0
        for name, passed in results:
            status = "✅ 通过" if passed else "❌ 失败"
            print(f"  {name}: {status}")
            if passed:
                passed_count += 1
        
        success_rate = (passed_count / len(results)) * 100
        print(f"\n🎯 测试通过率: {success_rate:.1f}% ({passed_count}/{len(results)})")
        
        return passed_count == len(results)

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='API集成测试')
    parser.add_argument('--url', default='http://localhost:8081', 
                       help='API服务器URL (默认: http://localhost:8081)')
    args = parser.parse_args()
    
    tester = APITester(args.url)
    
    try:
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ 测试执行失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
