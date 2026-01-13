"""
Task Queue

基于SQLite的持久化任务队列，支持中断恢复
"""

import sqlite3
import json
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime
import threading


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class TaskQueue:
    """SQLite-backed task queue"""
    
    def __init__(self, db_path: str = "scraper_queue.db"):
        """
        初始化任务队列
        
        Args:
            db_path: SQLite数据库文件路径
        """
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    domain TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority INTEGER DEFAULT 0,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 5,
                    last_error TEXT,
                    error_log TEXT,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    last_failed_state TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status_priority 
                ON tasks(status, priority, created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_domain 
                ON tasks(domain)
            """)
            conn.commit()
    
    def enqueue(
        self,
        url: str,
        domain: str,
        priority: int = 0,
        max_attempts: int = 5
    ) -> int:
        """
        入队任务
        
        Args:
            url: 页面URL
            domain: 域名
            priority: 优先级（数值越大优先级越高）
            max_attempts: 最大重试次数
            
        Returns:
            任务ID
        """
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("""
                        INSERT INTO tasks (url, domain, priority, max_attempts, status)
                        VALUES (?, ?, ?, ?, ?)
                    """, (url, domain, priority, max_attempts, TaskStatus.PENDING.value))
                    conn.commit()
                    return cursor.lastrowid
            except sqlite3.IntegrityError:
                # URL已存在，返回现有任务ID
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("SELECT id FROM tasks WHERE url = ?", (url,))
                    task_id = cursor.fetchone()[0]
                    return task_id
    
    def dequeue(self) -> Optional[Dict[str, Any]]:
        """
        取出一个待处理的任务
        
        Returns:
            任务字典，如果无待处理任务返回None
        """
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT id, url, domain, attempts, max_attempts, last_failed_state
                    FROM tasks
                    WHERE status = ? AND attempts < max_attempts
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                """, (TaskStatus.PENDING.value,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                task_id, url, domain, attempts, max_attempts, last_state = row
                
                # 标记为处理中
                conn.execute("""
                    UPDATE tasks 
                    SET status = ?, attempts = ?, started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (TaskStatus.PROCESSING.value, attempts + 1, task_id))
                conn.commit()
                
                return {
                    'id': task_id,
                    'url': url,
                    'domain': domain,
                    'attempts': attempts + 1,
                    'max_attempts': max_attempts,
                    'last_failed_state': last_state,
                }
    
    def mark_success(self, task_id: int, result: Dict[str, Any]):
        """
        标记任务成功
        
        Args:
            task_id: 任务ID
            result: 获取的结果
        """
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE tasks
                    SET status = ?, result = ?, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    TaskStatus.SUCCESS.value,
                    json.dumps(result, default=str),
                    task_id
                ))
                conn.commit()
    
    def mark_failed(
        self,
        task_id: int,
        error: str,
        failed_state: Optional[str] = None
    ) -> bool:
        """
        标记任务失败
        
        Args:
            task_id: 任务ID
            error: 错误信息
            failed_state: 失败时使用的state路径
            
        Returns:
            True如果还需重试，False如果已达到最大重试次数
        """
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                # 获取当前重试次数
                cursor = conn.execute(
                    "SELECT attempts, max_attempts, error_log FROM tasks WHERE id = ?",
                    (task_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return False
                
                attempts, max_attempts, error_log = row
                
                # 附加新错误到错误日志
                try:
                    error_list = json.loads(error_log) if error_log else []
                except:
                    error_list = []
                
                error_list.append({
                    'attempt': attempts,
                    'error': error,
                    'timestamp': datetime.now().isoformat(),
                    'failed_state': failed_state,
                })
                
                # 决定下一个状态
                if attempts >= max_attempts:
                    new_status = TaskStatus.MANUAL_REVIEW.value
                else:
                    new_status = TaskStatus.PENDING.value
                
                # 更新任务
                conn.execute("""
                    UPDATE tasks
                    SET 
                        status = ?,
                        last_error = ?,
                        error_log = ?,
                        last_failed_state = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    new_status,
                    error,
                    json.dumps(error_list),
                    failed_state,
                    task_id
                ))
                conn.commit()
                
                return attempts < max_attempts
    
    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT id, url, domain, status, attempts, max_attempts, 
                           last_error, result, created_at, updated_at
                    FROM tasks WHERE id = ?
                """, (task_id,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                (task_id, url, domain, status, attempts, max_attempts,
                 last_error, result, created_at, updated_at) = row
                
                return {
                    'id': task_id,
                    'url': url,
                    'domain': domain,
                    'status': status,
                    'attempts': attempts,
                    'max_attempts': max_attempts,
                    'last_error': last_error,
                    'result': json.loads(result) if result else None,
                    'created_at': created_at,
                    'updated_at': updated_at,
                }
    
    def get_stats(self) -> Dict[str, int]:
        """获取队列统计"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                stats = {}
                for status in TaskStatus:
                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM tasks WHERE status = ?",
                        (status.value,)
                    )
                    count = cursor.fetchone()[0]
                    stats[status.value] = count
                
                # 总数
                cursor = conn.execute("SELECT COUNT(*) FROM tasks")
                stats['total'] = cursor.fetchone()[0]
                
                return stats
    
    def get_failed_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取失败的任务列表"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT id, url, domain, attempts, max_attempts, last_error, created_at
                    FROM tasks
                    WHERE status IN (?, ?)
                    ORDER BY updated_at DESC
                    LIMIT ?
                """, (TaskStatus.FAILED.value, TaskStatus.MANUAL_REVIEW.value, limit))
                
                tasks = []
                for row in cursor.fetchall():
                    task_id, url, domain, attempts, max_attempts, last_error, created_at = row
                    tasks.append({
                        'id': task_id,
                        'url': url,
                        'domain': domain,
                        'attempts': attempts,
                        'max_attempts': max_attempts,
                        'last_error': last_error,
                        'created_at': created_at,
                    })
                
                return tasks
    
    def clear_old_tasks(self, days: int = 30):
        """清理旧的已完成任务"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    DELETE FROM tasks
                    WHERE status = ? AND updated_at < datetime('now', '-' || ? || ' days')
                """, (TaskStatus.SUCCESS.value, days))
                conn.commit()
    
    def reset_stuck_tasks(self, timeout_minutes: int = 30):
        """重置卡住的任务（处理中超过timeout）"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE tasks
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE status = ? AND started_at < datetime('now', '-' || ? || ' minutes')
                """, (TaskStatus.PENDING.value, TaskStatus.PROCESSING.value, timeout_minutes))
                conn.commit()
