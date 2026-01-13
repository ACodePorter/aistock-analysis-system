#!/usr/bin/env python3
"""
BaikeScraper 企业Profile集成测试脚本

演示如何使用新的企业profile提取功能
"""

import sys
import json
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.utils.baike_scraper import BaikeScraper


def test_get_company_profile():
    """测试直接获取企业profile"""
    print("\n" + "="*60)
    print("测试: 直接获取企业Profile数据")
    print("="*60)
    
    scraper = BaikeScraper(use_cache=True)
    
    test_companies = ["腾讯", "华为"]
    
    for company in test_companies:
        print(f"\n📍 获取 {company} 的profile数据...")
        profile = scraper.get_company_profile(company)
        
        if profile:
            print(f"✅ 成功获取 {company} 的profile")
            print(f"   - 成立时间: {profile.get('founded_date', 'N/A')}")
            print(f"   - 总部位置: {profile.get('headquarters', 'N/A')}")
            print(f"   - 员工人数: {profile.get('employees', 'N/A')}")
            print(f"   - 企业描述: {profile.get('description', 'N/A')[:50]}...")
        else:
            print(f"❌ 获取 {company} 的profile失败")


def test_scrape_with_profile():
    """测试完整爬取并获取profile"""
    print("\n" + "="*60)
    print("测试: 完整爬取企业信息（含profile）")
    print("="*60)
    
    scraper = BaikeScraper(use_cache=True)
    
    companies = ["阿里巴巴"]
    
    for company in companies:
        print(f"\n📍 爬取 {company}...")
        info = scraper.scrape(company, method="requests")
        
        if info.success:
            print(f"\n✅ {company} 爬取成功")
            print(f"   - 名称: {info.name}")
            print(f"   - 摘要: {info.summary[:50] if info.summary else 'N/A'}...")
            print(f"   - 基本信息字段数: {len(info.basic_info)}")
            print(f"   - 分类: {', '.join(info.categories) if info.categories else 'N/A'}")
            
            if info.profile:
                print(f"\n   🏢 企业Profile数据:")
                for key, value in info.profile.items():
                    if value and key != 'confidence':
                        print(f"      • {key}: {value}")
            else:
                print(f"\n   ⚠️  未获取到profile数据")
        else:
            print(f"\n❌ {company} 爬取失败: {info.error_message}")


def test_profile_json_output():
    """测试profile数据的JSON序列化"""
    print("\n" + "="*60)
    print("测试: Profile数据JSON序列化")
    print("="*60)
    
    scraper = BaikeScraper(use_cache=True)
    info = scraper.scrape("腾讯", method="requests")
    
    if info.success and info.profile:
        print(f"\n✅ 腾讯的profile JSON输出:")
        profile_json = json.dumps(info.profile, ensure_ascii=False, indent=2)
        print(profile_json)
    else:
        print("\n❌ 无法获取腾讯的profile数据")


def test_profile_fields():
    """测试profile各字段的提取"""
    print("\n" + "="*60)
    print("测试: Profile字段提取验证")
    print("="*60)
    
    scraper = BaikeScraper(use_cache=True)
    info = scraper.scrape("华为", method="requests")
    
    if info.success and info.profile:
        profile = info.profile
        
        print(f"\n✅ 华为的profile字段验证:")
        
        expected_fields = [
            'founded_date', 'headquarters', 'employees', 
            'business_scope', 'company_size', 'description'
        ]
        
        for field in expected_fields:
            value = profile.get(field)
            status = "✅" if value else "❌"
            print(f"   {status} {field}: {value if value else '(未获取)'}")
        
        # 统计非空字段
        non_empty_fields = sum(1 for k, v in profile.items() 
                               if v and k != 'confidence')
        print(f"\n   总共获取了 {non_empty_fields} 个非空字段")
    else:
        print("\n❌ 无法获取华为的profile数据")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("BaikeScraper 企业Profile集成测试")
    print("="*80)
    
    try:
        # 运行测试
        test_get_company_profile()
        test_scrape_with_profile()
        test_profile_json_output()
        test_profile_fields()
        
        print("\n" + "="*80)
        print("✅ 所有测试完成！")
        print("="*80 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  测试被中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
