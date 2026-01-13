"""
后台异步任务队列系统
用于将耗时操作（如 Profile 更新）从前端请求中分离出来，
避免阻塞前端的 HTTP 请求和后端的定时任务。
"""

import asyncio
import logging
import threading
from typing import Callable, Any, Optional, Dict
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import deque
import time

logger = logging.getLogger(__name__)


@dataclass
class QueuedTask:
    """队列中的任务"""
    task_id: str
    name: str
    func: Callable
    args: tuple
    kwargs: dict
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: Optional[str] = None


class BackgroundTaskQueue:
    """
    后台异步任务队列
    
    功能：
    1. 接收长时间运行的任务
    2. 异步执行，不阻塞主请求线程
    3. 维护任务状态和历史
    4. 支持优先级控制
    
    用法示例：
        queue = BackgroundTaskQueue(max_workers=2)
        queue.start()
        
        # 提交任务
        task_id = queue.submit(
            func=some_long_running_function,
            args=(arg1, arg2),
            kwargs={'key': 'value'},
            priority=1  # 优先级 (越低越优先)
        )
        
        # 查询任务状态
        status = queue.get_task_status(task_id)
    """
    
    def __init__(self, max_workers: int = 2, max_queue_size: int = 100):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        
        # 任务队列（按优先级排序）
        self.task_queue: deque = deque()
        self.task_queue_lock = threading.Lock()
        
        # 正在执行的任务
        self.running_tasks: Dict[str, QueuedTask] = {}
        self.running_tasks_lock = threading.Lock()
        
        # 已完成任务历史（保留最近 100 个）
        self.completed_tasks: deque = deque(maxlen=100)
        self.completed_tasks_lock = threading.Lock()
        
        # 控制标志
        self.is_running = False
        self.stop_event = threading.Event()
        
        # 工作线程
        self.worker_threads = []
        
        # 任务计数器
        self.task_counter = 0
        self.task_counter_lock = threading.Lock()
    
    def start(self):
        """启动任务队列处理"""
        if self.is_running:
            return
        
        self.is_running = True
        self.stop_event.clear()
        
        # 启动工作线程
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"TaskQueueWorker-{i}",
                daemon=True
            )
            worker.start()
            self.worker_threads.append(worker)
        
        logger.info(f"✅ 后台任务队列已启动，工作线程数: {self.max_workers}")
    
    def stop(self):
        """停止任务队列处理"""
        if not self.is_running:
            return
        
        self.stop_event.set()
        
        # 等待所有工作线程结束
        for worker in self.worker_threads:
            worker.join(timeout=5)
        
        self.is_running = False
        logger.info("⛔ 后台任务队列已停止")
    
    def submit(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        priority: int = 5,
        name: str = None
    ) -> str:
        """
        提交一个任务到队列
        
        参数：
            func: 要执行的函数
            args: 位置参数
            kwargs: 关键字参数
            priority: 优先级 (0=最高优先级，越大越低)
            name: 任务名称（用于日志）
        
        返回：任务 ID
        """
        if not self.is_running:
            raise RuntimeError("Task queue is not running")
        
        with self.task_queue_lock:
            if len(self.task_queue) >= self.max_queue_size:
                raise RuntimeError(f"Task queue is full (max={self.max_queue_size})")
        
        # 生成任务 ID
        with self.task_counter_lock:
            self.task_counter += 1
            task_id = f"task_{self.task_counter}_{int(time.time() * 1000)}"
        
        task = QueuedTask(
            task_id=task_id,
            name=name or func.__name__,
            func=func,
            args=args,
            kwargs=kwargs or {},
            created_at=datetime.now(),
            status="pending"
        )
        
        with self.task_queue_lock:
            self.task_queue.append((priority, task))
            # 按优先级排序
            queue_list = list(self.task_queue)
            queue_list.sort(key=lambda x: x[0])
            self.task_queue.clear()
            self.task_queue.extend(queue_list)
        
        logger.info(f"📝 任务已提交: {task_id} ({name or func.__name__})")
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        
        # 检查正在运行的任务
        with self.running_tasks_lock:
            if task_id in self.running_tasks:
                task = self.running_tasks[task_id]
                return {
                    'task_id': task.task_id,
                    'name': task.name,
                    'status': task.status,
                    'created_at': task.created_at.isoformat(),
                    'started_at': task.started_at.isoformat() if task.started_at else None,
                    'completed_at': task.completed_at.isoformat() if task.completed_at else None
                }
        
        # 检查已完成的任务
        with self.completed_tasks_lock:
            for task in self.completed_tasks:
                if task.task_id == task_id:
                    return {
                        'task_id': task.task_id,
                        'name': task.name,
                        'status': task.status,
                        'created_at': task.created_at.isoformat(),
                        'started_at': task.started_at.isoformat() if task.started_at else None,
                        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                        'result': task.result if task.status == 'completed' else None,
                        'error': task.error if task.status == 'failed' else None
                    }
        
        return None
    
    def get_queue_status(self) -> Dict[str, Any]:
        """获取整个队列的状态"""
        with self.task_queue_lock:
            queue_size = len(self.task_queue)
        
        with self.running_tasks_lock:
            running_size = len(self.running_tasks)
        
        with self.completed_tasks_lock:
            completed_size = len(self.completed_tasks)
        
        return {
            'is_running': self.is_running,
            'queue_size': queue_size,
            'running_tasks': running_size,
            'max_workers': self.max_workers,
            'total_processed': self.task_counter,
            'completed_tasks_history': completed_size
        }
    
    def _worker_loop(self):
        """工作线程的主循环"""
        while not self.stop_event.is_set():
            try:
                # 尝试从队列获取任务
                task = None
                with self.task_queue_lock:
                    if self.task_queue:
                        priority, task = self.task_queue.popleft()
                
                if not task:
                    # 队列为空，休眠
                    time.sleep(0.1)
                    continue
                
                # 执行任务
                self._execute_task(task)
                
            except Exception as e:
                logger.error(f"❌ 工作线程异常: {e}", exc_info=True)
    
    def _execute_task(self, task: QueuedTask):
        """执行单个任务"""
        task.status = "running"
        task.started_at = datetime.now()
        
        # 移到运行中列表
        with self.running_tasks_lock:
            self.running_tasks[task.task_id] = task
        
        logger.info(f"🚀 开始执行任务: {task.task_id} ({task.name})")
        
        try:
            # 如果是 async 函数，需要运行 event loop
            import inspect
            if inspect.iscoroutinefunction(task.func):
                result = asyncio.run(task.func(*task.args, **task.kwargs))
            else:
                result = task.func(*task.args, **task.kwargs)
            
            task.status = "completed"
            task.result = result
            logger.info(f"✅ 任务完成: {task.task_id} ({task.name})")
            
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.error(f"❌ 任务失败: {task.task_id} ({task.name}): {e}", exc_info=True)
        
        finally:
            task.completed_at = datetime.now()
            
            # 从运行中移到已完成
            with self.running_tasks_lock:
                if task.task_id in self.running_tasks:
                    del self.running_tasks[task.task_id]
            
            with self.completed_tasks_lock:
                self.completed_tasks.append(task)


# 全局任务队列实例
_global_task_queue: Optional[BackgroundTaskQueue] = None
_queue_lock = threading.Lock()


def get_background_queue() -> BackgroundTaskQueue:
    """获取全局任务队列实例"""
    global _global_task_queue
    
    if _global_task_queue is None:
        with _queue_lock:
            if _global_task_queue is None:
                _global_task_queue = BackgroundTaskQueue(max_workers=2)
                _global_task_queue.start()
    
    return _global_task_queue
