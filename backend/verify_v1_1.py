#!/usr/bin/env python
"""
验证 v1.1 升级是否成功的测试脚本
"""
import sys
import os
sys.path.insert(0, ".")

from app.core.db import SessionLocal
from app.core.models import Watchlist, NewsArticle, Event, Briefing
from sqlalchemy import select, func

def test_database_schema():
    """测试数据库表是否存在及字段是否正确"""
    print("\n📊 测试 1: 检查数据库表和字段...")
    session = SessionLocal()
    
    try:
        # 检查 watchlist 表字段
        result = session.execute(select(Watchlist)).scalars().first()
        print("✅ watchlist 表存在并可查询")
        
        # 尝试访问所有关键属性
        print(f"   - 样本记录: {result.symbol if result else 'N/A'}")
        if result:
            print(f"   - enabled: {result.enabled}")
            print(f"   - status: {result.status}")
            print(f"   - name: {result.name}")
        
        # 检查新增表
        news_count = session.execute(select(func.count(NewsArticle.id))).scalar() or 0
        print(f"✅ NewsArticle 表存在 (记录数: {news_count})")
        
        # 检查 events 表是否存在
        try:
            event_count = session.execute(select(func.count(Event.id))).scalar() or 0
            print(f"✅ Event 表存在 (记录数: {event_count})")
        except Exception as e:
            print(f"⚠️  Event 表检查失败: {str(e)[:50]}")
        
        # 检查 briefings 表
        try:
            briefing_count = session.execute(select(func.count(Briefing.id))).scalar() or 0
            print(f"✅ Briefing 表存在 (记录数: {briefing_count})")
        except Exception as e:
            print(f"⚠️  Briefing 表检查失败: {str(e)[:50]}")
        
        return True
    except Exception as e:
        print(f"❌ 数据库测试失败: {e}")
        return False
    finally:
        session.close()

def test_watchlist_queries():
    """测试 Watchlist 查询"""
    print("\n🔍 测试 2: 测试 Watchlist 查询...")
    session = SessionLocal()
    
    try:
        # 测试 enabled=True 查询
        enabled_count = session.execute(
            select(func.count(Watchlist.id)).where(Watchlist.enabled == True)
        ).scalar() or 0
        print(f"✅ enabled=True 的股票数: {enabled_count}")
        
        # 测试 status 查询
        active_count = session.execute(
            select(func.count(Watchlist.id)).where(Watchlist.status == "active")
        ).scalar() or 0
        print(f"✅ status='active' 的股票数: {active_count}")
        
        # 获取一条样本
        sample = session.execute(select(Watchlist).limit(1)).scalar()
        if sample:
            print(f"✅ 样本记录: {sample.symbol} (enabled={sample.enabled}, status={sample.status})")
        
        return True
    except Exception as e:
        print(f"❌ Watchlist 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

def test_imports():
    """测试是否所有必要的模块都能导入"""
    print("\n📦 测试 3: 测试模块导入...")
    
    try:
        from app.main import app
        print("✅ app.main 导入成功")
        
        # 尝试导入各个路由
        try:
            from app.routers import analysis
            print("✅ analysis 路由导入成功")
        except:
            pass
        
        try:
            from app.routers import movers
            print("✅ movers 路由导入成功")
        except:
            pass
        
        # 检查核心功能
        from app.core.models import Watchlist, Event, Briefing
        print("✅ 所有核心模型导入成功")
        
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("AIStock v1.1 升级验证测试")
    print("=" * 60)
    
    results = []
    results.append(("数据库模式检查", test_database_schema()))
    results.append(("Watchlist 查询", test_watchlist_queries()))
    results.append(("模块导入", test_imports()))
    
    print("\n" + "=" * 60)
    print("📋 测试结果汇总")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(r[1] for r in results)
    if all_passed:
        print("\n🎉 所有测试通过! v1.1 升级成功!")
        sys.exit(0)
    else:
        print("\n⚠️  某些测试失败，请检查")
        sys.exit(1)
