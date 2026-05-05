#!/usr/bin/env python3
"""
测试套件运行器 - 统一执行所有测试
"""

import sys
import os
import subprocess
import argparse
from datetime import datetime

class TestRunner:
    def __init__(self):
        self.tests_dir = os.path.dirname(__file__)
        self.backend_dir = os.path.dirname(self.tests_dir)
        
    def run_test(self, test_path, test_name):
        """运行单个测试"""
        print(f"\n{'='*60}")
        print(f"🧪 运行 {test_name}")
        print(f"{'='*60}")
        
        try:
            # 切换到backend目录运行测试
            result = subprocess.run(
                [sys.executable, test_path],
                cwd=self.backend_dir,
                capture_output=True,
                text=True,
                timeout=120  # 2分钟超时
            )
            
            # 打印输出
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            success = result.returncode == 0
            status = "✅ 通过" if success else "❌ 失败"
            print(f"\n{test_name}: {status}")
            
            return success
            
        except subprocess.TimeoutExpired:
            print(f"⏰ {test_name} 超时")
            return False
        except Exception as e:
            print(f"❌ {test_name} 执行异常: {e}")
            return False
    
    def run_all_tests(self, api_url=None, test_type=None):
        """运行所有测试"""
        print("🚀 股票系统测试套件")
        print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        # 定义测试列表
        unit_tests = [
            ("tests/unit/test_stock_info.py", "股票信息单元测试"),
            ("tests/unit/test_url_filtering.py", "URL过滤单元测试"),
            ("tests/unit/test_dedup.py", "去重机制单元测试"),
            ("tests/unit/test_content_quality.py", "内容质量单元测试"),
            ("tests/unit/test_macro_overview_api.py", "宏观概览API单元测试"),
            ("tests/unit/test_stock_pool.py", "股票池脚本单元测试"),
            ("tests/unit/test_stock_pool_api.py", "股票池API单元测试"),
            ("tests/unit/test_fund_flow_fallback.py", "资金流回退健壮性单元测试"),
            ("tests/unit/test_retail_decision_service.py", "散户决策服务单元测试"),
            ("tests/unit/test_trade_playbook_service.py", "交易剧本服务单元测试"),
        ]
        
        integration_tests = [
            ("tests/integration/test_services.py", "后端服务连接测试"),
            ("tests/integration/test_searxng.py", "SearXNG集成测试"),
            ("tests/integration/test_news_api.py", "新闻API集成测试"),
            ("tests/integration/test_news_smoke.py", "新闻API冒烟测试"),
            ("tests/integration/test_news_cleanup.py", "新闻清理API冒烟测试"),
            ("tests/integration/test_pipeline.py", "数据管道测试"),
        ]
        
        data_tests = [
            ("tests/data/test_data_integrity.py", "数据完整性测试"),
        ]
        
        # 根据测试类型选择要运行的测试
        if test_type == "unit":
            tests = unit_tests
        elif test_type == "integration":
            tests = integration_tests
            # 如果提供了API URL，添加API测试（仅集成测试类型）
            if api_url:
                os.environ['API_URL'] = api_url
                tests.append(("tests/integration/test_api.py", "API集成测试"))
        elif test_type == "data":
            tests = data_tests
        else:
            tests = unit_tests + integration_tests + data_tests
            # 如果提供了API URL，添加API测试（全部测试类型）
            if api_url:
                os.environ['API_URL'] = api_url
                tests.append(("tests/integration/test_api.py", "API集成测试"))
        
        results = []
        
        # 依次运行测试
        for test_path, test_name in tests:
            full_path = os.path.join(self.backend_dir, test_path)
            if os.path.exists(full_path):
                result = self.run_test(full_path, test_name)
                results.append((test_name, result))
            else:
                print(f"⚠ 测试文件不存在: {test_path}")
                results.append((test_name, False))
        
        # 生成测试报告
        self.generate_report(results)
        
        # 返回是否所有测试都通过
        return all(result for _, result in results)
    
    def generate_report(self, results):
        """生成测试报告"""
        print(f"\n{'='*60}")
        print("📊 测试报告")
        print(f"{'='*60}")
        
        passed_count = sum(1 for _, result in results if result)
        total_count = len(results)
        success_rate = (passed_count / total_count * 100) if total_count > 0 else 0
        
        print(f"⏰ 完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📈 测试结果:")
        
        for test_name, result in results:
            status = "✅ 通过" if result else "❌ 失败"
            print(f"  {test_name}: {status}")
        
        print(f"\n🎯 总体统计:")
        print(f"  通过: {passed_count}/{total_count}")
        print(f"  成功率: {success_rate:.1f}%")
        
        if success_rate == 100:
            print("\n🎉 所有测试通过！系统状态良好。")
        elif success_rate >= 80:
            print("\n⚠ 大部分测试通过，请检查失败的测试。")
        else:
            print("\n❌ 多个测试失败，系统可能存在问题。")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='股票系统测试套件')
    parser.add_argument('--api-url', 
                       help='API服务器URL，用于API测试 (例如: http://localhost:8081)')
    parser.add_argument('--data-only', action='store_true',
                       help='只运行数据相关测试，跳过API测试')
    parser.add_argument('--type', choices=['unit', 'integration', 'data'],
                       help='指定测试类型: unit(单元测试), integration(集成测试), data(数据测试)')
    
    args = parser.parse_args()
    
    runner = TestRunner()
    
    try:
        if args.data_only:
            success = runner.run_all_tests(api_url=None, test_type='data')
        elif args.type:
            # 如果指定了测试类型，则不设置默认API URL
            api_url = args.api_url
            success = runner.run_all_tests(api_url=api_url, test_type=args.type)
        else:
            # 只有在运行全部测试时才设置默认API URL
            api_url = args.api_url or "http://localhost:8081"
            success = runner.run_all_tests(api_url=api_url, test_type=args.type)
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n⏸ 测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 测试套件执行失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
