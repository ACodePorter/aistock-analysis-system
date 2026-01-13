"""
CompanyProfileSearchService 使用示例和测试

演示如何使用企业Profile搜索服务获取企业信息
"""

import asyncio
import json
import sys
import time
from typing import List, Optional
from pathlib import Path

# 添加backend目录到路径，以便导入app模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.news.company_profile_service import CompanyProfileSearchService


async def test_company_profile_search_quick():
    """
    快速演示模式 - 使用本地数据库（无需LLM验证，几秒钟完成）
    """
    print("✨ 使用快速模式（本地数据库查询）...\n")
    service = CompanyProfileSearchService()
    
    test_companies = [
        {"company_name": "阿里巴巴", "stock_symbol": "SH600000"},
        {"company_name": "腾讯", "stock_symbol": "HK00700"},
    ]
    
    for company in test_companies[:1]:
        print(f"📊 查询企业: {company['company_name']}")
        
        # 直接调用本地数据库查询（快速）
        profile = service._search_local_database(company["company_name"])
        
        if profile:
            print(f"\n   ✅ 本地数据库找到!")
            print(f"   企业名称: {profile.get('name', 'N/A')}")
            print(f"   行业: {profile.get('industry', 'N/A')}")
            if profile.get('sector'):
                print(f"   细分行业: {profile.get('sector')}")
            if profile.get('business_scope'):
                print(f"   主营业务: {profile.get('business_scope')[:80]}...")
            print(f"   来源: {profile.get('source', 'N/A')}")
        else:
            print(f"   ℹ️  本地数据库中无此企业信息")
        
        print("-" * 80)


async def test_company_profile_search():
    """
    测试企业Profile搜索
    """
    print("正在初始化企业Profile搜索服务...")
    service = CompanyProfileSearchService()
    print("✅ 企业Profile搜索服务已初始化\n")
    
    # 测试用例：多个不同类型的企业
    test_cases = [
        {
            "company_name": "阿里巴巴",
            "stock_symbol": "SH600000",
            "description": "中国电商巨头"
        },
        {
            "company_name": "腾讯",
            "stock_symbol": "HK00700",
            "description": "中国互联网巨头"
        },
        {
            "company_name": "华为",
            "stock_symbol": None,
            "description": "非上市企业"
        },
        {
            "company_name": "Apple Inc",
            "stock_symbol": "NASDAQ:AAPL",
            "description": "国际企业"
        },
    ]
    
    print("=" * 80)
    print("企业Profile搜索服务 - 功能演示")
    print("=" * 80)
    
    for test_case in test_cases[:1]:  # 🔥 只演示第1个企业，节省时间（API验证较慢）
        print(f"\n📊 搜索企业: {test_case['company_name']}")
        print(f"   描述: {test_case['description']}")
        if test_case['stock_symbol']:
            print(f"   股票代码: {test_case['stock_symbol']}")
        
        print("   正在搜索... (请稍候，正在进行LLM验证，预计需要5-10分钟)")
        print("   💡 提示: 搜索结果需要逐个用LLM验证真伪，这需要多个API调用")
        start_time = time.time()
        
        try:
            profile = await asyncio.wait_for(
                service.search_company_profile(
                    company_name=test_case["company_name"],
                    stock_symbol=test_case.get("stock_symbol"),
                    limit=3  # 🔥 极少化结果数，加快LLM验证速度
                ),
                timeout=600  # 10分钟超时（LLM验证确实很慢）
            )
            elapsed = time.time() - start_time
            print(f"   ⏱️ 搜索耗时: {elapsed:.1f}秒")
        except asyncio.TimeoutError:
            print(f"   ⚠️ 搜索超时（超过10分钟，LLM验证太慢）")
            profile = None
        
        if profile:
            print(f"\n   ✅ 搜索成功！")
            print(f"   企业名称: {profile.get('name', 'N/A')}")
            print(f"   行业: {profile.get('industry', 'N/A')}")
            if profile.get('sector'):
                print(f"   细分行业: {profile.get('sector')}")
            if profile.get('founded_date'):
                print(f"   成立日期: {profile.get('founded_date')}")
            if profile.get('headquarters'):
                print(f"   总部位置: {profile.get('headquarters')}")
            if profile.get('employees'):
                print(f"   员工数: {profile.get('employees')}")
            if profile.get('business_scope'):
                print(f"   主营业务: {profile.get('business_scope')}")
            if profile.get('description'):
                print(f"   公司简介: {profile.get('description')}")
            
            
            print(f"\n   📚 信息来源 ({len(profile.get('sources', []))} 个):")
            for source in profile.get('sources', [])[:3]:
                print(f"      - {source['domain']}")
                # 处理本地数据库和网络搜索的不同返回格式
                if 'extracted_fields' in source:
                    print(f"        提取字段: {', '.join(source['extracted_fields'][:3])}")
            
            # 标注来源类型
            if profile.get('_from_local_db'):
                print(f"\n   🗂️ 信息来源: 本地数据库 (SearXNG 服务不可用时的 fallback)")
            
            print(f"\n   📈 置信度: {profile.get('confidence', 0):.2%}")
        else:
            print(f"\n   ❌ 搜索失败")
        
        print("-" * 80)
        # await asyncio.sleep(2)  # 避免请求过快




def main():
    """
    主程序入口，并确保正确清理资源
    """
    print("\n" + "=" * 80)
    print("🚀 启动企业Profile搜索服务演示")
    print("=" * 80)
    print("📌 当前模式: 快速演示 (本地数据库查询)")
    print("   - 如需网络搜索+LLM验证，请修改脚本中的循环模式")
    print("="* 80 + "\n")
    
    demo_start = time.time()
    
    try:
        # 创建事件循环并运行演示
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 运行搜索演示
            print("📌 第1步: 执行企业Profile搜索...\n")
            
            # 选择运行模式:
            loop.run_until_complete(test_company_profile_search())  # 完整模式（很慢）
            
            elapsed = time.time() - demo_start
            print(f"\n✅ 演示完成！总耗时: {elapsed:.1f}秒")
        finally:
            print("\n📌 清理资源...")
            # 关闭循环，清理所有待处理任务和executor
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            
            # 给任务一点时间来处理取消请求
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            
            # 关闭event loop（这会清理ThreadPoolExecutor）
            loop.close()
            print("✅ 资源清理完毕")
        
    except KeyboardInterrupt:
        print("\n⏹️  演示中断 (用户按 Ctrl+C)")
    except Exception as e:
        print(f"\n❌ 演示出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
    print("\n✨ 脚本正常退出")
    sys.exit(0)
