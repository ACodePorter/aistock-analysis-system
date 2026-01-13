#!/usr/bin/env python3
"""
后台任务队列测试脚本

用于验证 BackgroundTaskQueue 的功能：
1. 任务提交和执行
2. 防抖机制
3. 优先级控制
4. 状态追踪
"""

import sys
import time
import asyncio
from pathlib import Path

# 添加 backend 到路径
current_dir = Path(__file__).parent.parent
sys.path.insert(0, str(current_dir))

from app.utils.background_task_queue import BackgroundTaskQueue


def test_simple_task():
    """测试简单任务执行"""
    print("\n✅ 测试 1：简单任务执行")
    print("-" * 50)
    
    queue = BackgroundTaskQueue(max_workers=2)
    queue.start()
    
    def simple_func(name: str, delay: float = 0.5):
        time.sleep(delay)
        print(f"  ✓ 任务完成: {name}")
        return f"Result: {name}"
    
    # 提交 3 个任务
    task_ids = []
    for i in range(3):
        task_id = queue.submit(
            func=simple_func,
            args=(f"任务{i+1}",),
            kwargs={'delay': 0.5},
            name=f"测试任务{i+1}"
        )
        task_ids.append(task_id)
        print(f"  📝 任务已提交: {task_id}")
    
    # 等待任务完成
    print("\n  ⏳ 等待任务执行...")
    time.sleep(3)
    
    # 检查任务状态
    for task_id in task_ids:
        status = queue.get_task_status(task_id)
        if status:
            print(f"  ✓ {status['name']}: {status['status']}")
    
    queue.stop()
    print("\n✅ 测试 1 完成！\n")


def test_priority():
    """测试优先级队列"""
    print("✅ 测试 2：优先级控制")
    print("-" * 50)
    
    queue = BackgroundTaskQueue(max_workers=1)
    queue.start()
    
    execution_order = []
    
    def tracked_task(name: str):
        execution_order.append(name)
        print(f"  ✓ 执行: {name}")
        time.sleep(0.2)
    
    # 按优先级提交任务
    print("  📝 提交任务 (优先级: 高→低)")
    queue.submit(func=tracked_task, args=("低优先级",), priority=10)
    print("    - 低优先级 (priority=10)")
    
    queue.submit(func=tracked_task, args=("高优先级",), priority=1)
    print("    - 高优先级 (priority=1)")
    
    queue.submit(func=tracked_task, args=("中优先级",), priority=5)
    print("    - 中优先级 (priority=5)")
    
    # 等待执行
    print("\n  ⏳ 等待按优先级执行...")
    time.sleep(2)
    
    print(f"\n  执行顺序: {' → '.join(execution_order)}")
    print(f"  ✓ 优先级控制正确: {execution_order[0] == '高优先级'}")
    
    queue.stop()
    print("\n✅ 测试 2 完成！\n")


def test_queue_status():
    """测试队列状态监控"""
    print("✅ 测试 3：队列状态监控")
    print("-" * 50)
    
    queue = BackgroundTaskQueue(max_workers=1)
    queue.start()
    
    def slow_task():
        time.sleep(1)
    
    # 提交多个任务
    print("  📝 提交 5 个任务...")
    for i in range(5):
        queue.submit(func=slow_task, name=f"任务{i+1}")
    
    # 检查队列状态
    status = queue.get_queue_status()
    print(f"\n  队列状态:")
    print(f"    - 待处理任务: {status['queue_size']}")
    print(f"    - 运行中任务: {status['running_tasks']}")
    print(f"    - 最大工作线程: {status['max_workers']}")
    
    # 等待一段时间再检查
    time.sleep(2)
    status = queue.get_queue_status()
    print(f"\n  2 秒后队列状态:")
    print(f"    - 待处理任务: {status['queue_size']}")
    print(f"    - 已完成任务: {status['completed_tasks_history']}")
    
    queue.stop()
    print("\n✅ 测试 3 完成！\n")


def test_async_function():
    """测试异步函数支持"""
    print("✅ 测试 4：异步函数支持")
    print("-" * 50)
    
    queue = BackgroundTaskQueue(max_workers=2)
    queue.start()
    
    async def async_task(name: str):
        await asyncio.sleep(0.5)
        print(f"  ✓ 异步任务完成: {name}")
        return f"Async result: {name}"
    
    # 提交异步任务
    print("  📝 提交异步任务...")
    task_id = queue.submit(
        func=async_task,
        args=("异步操作",),
        name="异步任务"
    )
    
    # 等待完成
    print("  ⏳ 等待异步任务...")
    time.sleep(1)
    
    status = queue.get_task_status(task_id)
    if status:
        print(f"  ✓ 任务状态: {status['status']}")
        if status['status'] == 'completed':
            print(f"  ✓ 任务结果: {status.get('result')}")
    
    queue.stop()
    print("\n✅ 测试 4 完成！\n")


def test_error_handling():
    """测试错误处理"""
    print("✅ 测试 5：错误处理")
    print("-" * 50)
    
    queue = BackgroundTaskQueue(max_workers=1)
    queue.start()
    
    def failing_task():
        raise ValueError("模拟任务错误")
    
    # 提交会失败的任务
    print("  📝 提交会失败的任务...")
    task_id = queue.submit(func=failing_task, name="失败的任务")
    
    # 等待任务执行
    print("  ⏳ 等待任务执行...")
    time.sleep(1)
    
    # 检查错误状态
    status = queue.get_task_status(task_id)
    if status:
        print(f"  ✓ 任务状态: {status['status']}")
        if status['status'] == 'failed':
            print(f"  ✓ 错误信息: {status.get('error')}")
    
    queue.stop()
    print("\n✅ 测试 5 完成！\n")


def main():
    """运行所有测试"""
    print("\n" + "=" * 50)
    print("🧪 后台任务队列测试套件")
    print("=" * 50)
    
    try:
        test_simple_task()
        test_priority()
        test_queue_status()
        test_async_function()
        test_error_handling()
        
        print("=" * 50)
        print("✅ 所有测试完成！")
        print("=" * 50 + "\n")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
