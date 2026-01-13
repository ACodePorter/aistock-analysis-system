"""
日志模块

提供结构化JSON日志功能
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Dict


class StructuredLogger:
    """结构化JSON日志记录器"""
    
    def __init__(
        self,
        name: str,
        log_file: Optional[str] = None,
        level: str = "INFO"
    ):
        """
        初始化日志记录器
        
        Args:
            name: 日志记录器名称
            log_file: 日志文件路径，如果为None则仅输出到控制台
            level: 日志级别
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level))
        
        # 清除现有处理器
        self.logger.handlers.clear()
        
        # 添加控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, level))
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # 添加文件处理器
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(getattr(logging, level))
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
    
    def _format_message(self, data: Dict[str, Any]) -> str:
        """将字典格式化为JSON字符串"""
        data['timestamp'] = datetime.utcnow().isoformat()
        return json.dumps(data, ensure_ascii=False, default=str)
    
    def info(self, message: str, **kwargs):
        """记录信息日志"""
        data = {'message': message, 'level': 'INFO', **kwargs}
        self.logger.info(self._format_message(data))
    
    def warning(self, message: str, **kwargs):
        """记录警告日志"""
        data = {'message': message, 'level': 'WARNING', **kwargs}
        self.logger.warning(self._format_message(data))
    
    def error(self, message: str, **kwargs):
        """记录错误日志"""
        data = {'message': message, 'level': 'ERROR', **kwargs}
        self.logger.error(self._format_message(data))
    
    def debug(self, message: str, **kwargs):
        """记录调试日志"""
        data = {'message': message, 'level': 'DEBUG', **kwargs}
        self.logger.debug(self._format_message(data))


def create_logger(
    name: str,
    log_file: Optional[str] = None,
    level: str = "INFO"
) -> StructuredLogger:
    """创建日志记录器"""
    return StructuredLogger(name, log_file, level)


# 记录爬虫事件
class ScraperEventLogger:
    """爬虫事件日志记录器"""
    
    def __init__(self, logger: StructuredLogger):
        self.logger = logger
    
    def log_fetch_start(self, url: str, domain: str, fetcher: str):
        """记录开始爬取"""
        self.logger.info(
            f"Start fetching: {url}",
            event="fetch_start",
            url=url,
            domain=domain,
            fetcher=fetcher
        )
    
    def log_fetch_success(
        self,
        url: str,
        domain: str,
        fetcher: str,
        elapsed_time: float,
        content_length: int,
        **metadata
    ):
        """记录爬取成功"""
        self.logger.info(
            f"Fetch successful: {url}",
            event="fetch_success",
            url=url,
            domain=domain,
            fetcher=fetcher,
            elapsed_time=elapsed_time,
            content_length=content_length,
            **metadata
        )
    
    def log_fetch_failure(
        self,
        url: str,
        domain: str,
        fetcher: str,
        reason: str,
        attempt: int,
        **metadata
    ):
        """记录爬取失败"""
        self.logger.warning(
            f"Fetch failed: {url} - {reason}",
            event="fetch_failure",
            url=url,
            domain=domain,
            fetcher=fetcher,
            reason=reason,
            attempt=attempt,
            **metadata
        )
    
    def log_login_detected(
        self,
        url: str,
        domain: str,
        fetcher: str,
        reason: str,
        state_used: Optional[str] = None
    ):
        """记录检测到登录页"""
        self.logger.warning(
            f"Login page detected: {url}",
            event="login_detected",
            url=url,
            domain=domain,
            fetcher=fetcher,
            reason=reason,
            state_used=state_used
        )
    
    def log_state_exhausted(self, domain: str, url: str):
        """记录所有state均已失效"""
        self.logger.error(
            f"All states exhausted for domain: {domain}, url: {url}",
            event="states_exhausted",
            domain=domain,
            url=url
        )
    
    def log_retry(self, url: str, attempt: int, wait_time: float, reason: str):
        """记录重试"""
        self.logger.info(
            f"Retry attempt {attempt} for {url} after {wait_time:.1f}s",
            event="retry",
            url=url,
            attempt=attempt,
            wait_time=wait_time,
            reason=reason
        )
