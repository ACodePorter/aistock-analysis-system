"""
浏览器状态管理模块

管理Playwright的storage_state (cookie/session等)
"""

import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime


class StateManager:
    """浏览器状态管理器"""
    
    def __init__(self, state_paths: Optional[List[str]] = None):
        """
        初始化状态管理器
        
        Args:
            state_paths: storage_state.json文件路径列表
        """
        self.state_paths = state_paths or []
        self.current_state_index = 0
        self.state_failures = {}  # 记录每个state的失败次数
        self.state_timestamps = {}  # 记录每个state的最后使用时间
        
        # 初始化失败计数
        for path in self.state_paths:
            self.state_failures[path] = 0
            self.state_timestamps[path] = None
    
    def get_next_state(self) -> Optional[Dict[str, Any]]:
        """
        获取下一个可用的state
        
        Returns:
            storage_state字典，如果所有state都失效则返回None
        """
        if not self.state_paths:
            return None
        
        # 轮转查找未失效的state
        attempts = 0
        while attempts < len(self.state_paths):
            path = self.state_paths[self.current_state_index]
            self.current_state_index = (self.current_state_index + 1) % len(self.state_paths)
            
            # 检查state是否已被标记为失效
            if self.state_failures.get(path, 0) < 5:  # 允许失败5次后标记为失效
                state = self.load_state(path)
                if state:
                    self.state_timestamps[path] = datetime.now().isoformat()
                    return state
            
            attempts += 1
        
        return None
    
    def mark_state_failure(self, state_path: str):
        """标记state失败"""
        if state_path in self.state_failures:
            self.state_failures[state_path] += 1
    
    def mark_state_success(self, state_path: str):
        """标记state成功（重置失败计数）"""
        if state_path in self.state_failures:
            self.state_failures[state_path] = 0
    
    def get_current_state_path(self) -> Optional[str]:
        """获取当前正在使用的state路径"""
        if self.state_paths:
            idx = (self.current_state_index - 1) % len(self.state_paths)
            return self.state_paths[idx]
        return None
    
    @staticmethod
    def load_state(state_path: str) -> Optional[Dict[str, Any]]:
        """
        加载storage_state.json文件
        
        Args:
            state_path: 文件路径
            
        Returns:
            state字典，加载失败返回None
        """
        try:
            path = Path(state_path)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Failed to load state from {state_path}: {e}")
        
        return None
    
    @staticmethod
    def save_state(state: Dict[str, Any], state_path: str) -> bool:
        """
        保存storage_state到文件
        
        Args:
            state: storage_state字典
            state_path: 目标文件路径
            
        Returns:
            是否保存成功
        """
        try:
            path = Path(state_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Failed to save state to {state_path}: {e}")
            return False
    
    @staticmethod
    def convert_state_to_cookies(state: Dict[str, Any]) -> Dict[str, str]:
        """
        将storage_state转换为requests库可用的cookies字典
        
        Args:
            state: storage_state字典
            
        Returns:
            cookies字典 {name: value}
        """
        cookies = {}
        
        if 'cookies' in state:
            for cookie in state['cookies']:
                cookies[cookie.get('name')] = cookie.get('value', '')
        
        return cookies
    
    @staticmethod
    def get_auth_headers_from_state(state: Dict[str, Any]) -> Dict[str, str]:
        """
        从storage_state中提取可能的auth头
        
        Args:
            state: storage_state字典
            
        Returns:
            可能包含Authorization等auth头的字典
        """
        headers = {}
        
        # 某些网站在localStorage中存储auth token
        if 'origins' in state:
            for origin_data in state['origins']:
                if 'localStorage' in origin_data:
                    for item in origin_data['localStorage']:
                        key = item.get('name', '').lower()
                        if 'token' in key or 'auth' in key:
                            headers[f'X-{item.get("name")}'] = item.get('value', '')
        
        return headers


class StateValidator:
    """State验证器"""
    
    @staticmethod
    def is_valid_state(state: Dict[str, Any]) -> bool:
        """
        验证state是否有效
        
        Args:
            state: storage_state字典
            
        Returns:
            是否为有效的state
        """
        # 检查必要的结构
        if not isinstance(state, dict):
            return False
        
        # 必须有cookies或origins
        if 'cookies' not in state and 'origins' not in state:
            return False
        
        # cookies应该是列表
        if 'cookies' in state and not isinstance(state['cookies'], list):
            return False
        
        return True
    
    @staticmethod
    def is_state_expired(state_path: str, max_age_days: int = 7) -> bool:
        """
        检查state是否过期
        
        Args:
            state_path: state文件路径
            max_age_days: 最大有效天数
            
        Returns:
            是否已过期
        """
        try:
            path = Path(state_path)
            if path.exists():
                mtime = path.stat().st_mtime
                from datetime import datetime, timedelta
                age = datetime.now() - datetime.fromtimestamp(mtime)
                return age > timedelta(days=max_age_days)
        except:
            pass
        
        return False
