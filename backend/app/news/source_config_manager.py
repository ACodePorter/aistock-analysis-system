"""
企业档案搜索服务配置管理器
Company Profile Search Service Configuration Manager

负责加载、更新和持久化域名分类配置
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import threading


class SourceConfigManager:
    """
    域名配置管理器
    
    管理以下配置：
    - preferred_sources: 优先信源白名单
    - blocked_sources: 黑名单
    - login_required_sources: 需要登录的网站
    - strict_anti_scraping_domains: 反爬虫严格的域名
    """
    
    def __init__(self, config_path: str = None):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径，默认为 backend/config/company_profile_sources.json
        """
        if config_path is None:
            # 默认路径：backend/config/company_profile_sources.json
            # 从当前文件向上两级到backend目录
            current_file = Path(__file__)  # .../backend/app/news/source_config_manager.py
            backend_dir = current_file.parent.parent.parent  # 向上三级到backend
            config_path = backend_dir / "config" / "company_profile_sources.json"
        
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """从文件加载配置"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
                print(f"✅ Loaded source config from {self.config_path}")
            else:
                print(f"⚠️ Config file not found: {self.config_path}, using defaults")
                self._config = self._get_default_config()
                self._save_config()
        except Exception as e:
            print(f"⚠️ Failed to load config: {e}, using defaults")
            self._config = self._get_default_config()
    
    def _save_config(self):
        """保存配置到文件"""
        try:
            # 确保目录存在
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with self._lock:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self._config, f, ensure_ascii=False, indent=2)
            print(f"✅ Saved source config to {self.config_path}")
        except Exception as e:
            print(f"⚠️ Failed to save config: {e}")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "version": "1.0.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "preferred_sources": {"sources": []},
            "blocked_sources": {"sources": []},
            "login_required_sources": {"sources": []},
            "strict_anti_scraping_domains": {"sources": []},
            "detection_rules": {
                "login_detection": {
                    "enabled": True,
                    "keywords": ["登录", "login", "会员帐户安全", "请先登录"],
                    "http_status_codes": [302, 401, 403]
                }
            }
        }
    
    # ==================== 优先信源管理 ====================
    
    def get_preferred_sources(self) -> List[str]:
        """
        获取优先信源域名列表（按优先级排序）
        
        Returns:
            域名列表，如 ["baike.baidu.com", "zh.wikipedia.org", ...]
        """
        sources = self._config.get("preferred_sources", {}).get("sources", [])
        # 按优先级排序
        sources_sorted = sorted(sources, key=lambda x: x.get("priority", 999))
        return [s["domain"] for s in sources_sorted]
    
    def get_preferred_source_info(self, domain: str) -> Optional[Dict[str, Any]]:
        """获取优先信源的详细信息"""
        sources = self._config.get("preferred_sources", {}).get("sources", [])
        for source in sources:
            if source["domain"] == domain:
                return source
        return None
    
    # ==================== 黑名单管理 ====================
    
    def get_blocked_sources(self) -> List[str]:
        """
        获取黑名单域名列表
        
        Returns:
            域名列表，如 ["aastocks.com", "guba.eastmoney.com", ...]
        """
        sources = self._config.get("blocked_sources", {}).get("sources", [])
        return [s["domain"] for s in sources]
    
    def add_blocked_source(self, domain: str, reason: str, category: str = "auto_detected"):
        """
        添加域名到黑名单
        
        Args:
            domain: 域名
            reason: 屏蔽原因
            category: 分类（forum/low_quality/anti_scraping/auto_detected等）
        """
        with self._lock:
            sources = self._config.get("blocked_sources", {}).get("sources", [])
            
            # 检查是否已存在
            if any(s["domain"] == domain for s in sources):
                print(f"⚠️ Domain {domain} already in blocked list")
                return
            
            sources.append({
                "domain": domain,
                "reason": reason,
                "category": category,
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            self._config.setdefault("blocked_sources", {})["sources"] = sources
            self._save_config()
            print(f"✅ Added {domain} to blocked list: {reason}")
    
    def is_blocked(self, domain: str) -> bool:
        """检查域名是否在黑名单中"""
        blocked_domains = self.get_blocked_sources()
        return any(blocked in domain for blocked in blocked_domains)
    
    # ==================== 需要登录的网站管理 ====================
    
    def get_login_required_sources(self) -> List[str]:
        """
        获取需要登录的网站域名列表
        
        Returns:
            域名列表
        """
        sources = self._config.get("login_required_sources", {}).get("sources", [])
        return [s["domain"] for s in sources]
    
    def add_login_required_source(
        self, 
        domain: str, 
        reason: str, 
        detection_keywords: List[str] = None,
        auto_detected: bool = True
    ):
        """
        添加需要登录的网站
        
        Args:
            domain: 域名
            reason: 检测原因
            detection_keywords: 检测关键词
            auto_detected: 是否自动检测
        """
        with self._lock:
            sources = self._config.get("login_required_sources", {}).get("sources", [])
            
            # 检查是否已存在
            if any(s["domain"] == domain for s in sources):
                print(f"⚠️ Domain {domain} already in login-required list")
                return
            
            sources.append({
                "domain": domain,
                "reason": reason,
                "detection_keywords": detection_keywords or [],
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "auto_detected": auto_detected
            })
            
            self._config.setdefault("login_required_sources", {})["sources"] = sources
            self._save_config()
            print(f"✅ Added {domain} to login-required list: {reason}")
    
    def is_login_required(self, domain: str) -> bool:
        """检查域名是否需要登录"""
        login_domains = self.get_login_required_sources()
        return any(login_domain in domain for login_domain in login_domains)
    
    # ==================== 反爬虫严格域名管理 ====================
    
    def get_strict_domains(self) -> List[str]:
        """
        获取反爬虫严格的域名列表
        
        Returns:
            域名列表
        """
        sources = self._config.get("strict_anti_scraping_domains", {}).get("sources", [])
        return [s["domain"] for s in sources]
    
    def get_strict_domain_info(self, domain: str) -> Optional[Dict[str, Any]]:
        """获取严格域名的详细信息（策略、延迟等）"""
        sources = self._config.get("strict_anti_scraping_domains", {}).get("sources", [])
        for source in sources:
            if source["domain"] in domain or domain in source["domain"]:
                return source
        return None
    
    def is_strict_domain(self, domain: str) -> bool:
        """检查是否为反爬虫严格的域名"""
        strict_domains = self.get_strict_domains()
        return any(strict in domain for strict in strict_domains)
    
    # ==================== 自动检测 ====================
    
    def detect_login_page(self, url: str, html_content: str, status_code: int = 200) -> bool:
        """
        检测页面是否为登录页面
        
        Args:
            url: 页面URL
            html_content: HTML内容
            status_code: HTTP状态码
            
        Returns:
            是否检测到登录页面
        """
        from urllib.parse import urlparse
        
        detection_config = self._config.get("detection_rules", {}).get("login_detection", {})
        
        if not detection_config.get("enabled", True):
            return False
        
        # 检查HTTP状态码
        if status_code in detection_config.get("http_status_codes", [302, 401, 403]):
            return True
        
        # 检查URL重定向模式
        redirect_patterns = detection_config.get("redirect_patterns", [])
        for pattern in redirect_patterns:
            if pattern in url.lower():
                return True
        
        # 检查内容关键词
        if html_content:
            keywords = detection_config.get("keywords", [])
            content_lower = html_content.lower()
            for keyword in keywords:
                if keyword.lower() in content_lower:
                    return True
        
        return False
    
    def auto_add_login_required(self, url: str, html_content: str, status_code: int = 200):
        """
        自动检测并添加需要登录的网站
        
        Args:
            url: 页面URL
            html_content: HTML内容
            status_code: HTTP状态码
        """
        from urllib.parse import urlparse
        
        if not self.detect_login_page(url, html_content, status_code):
            return
        
        domain = urlparse(url).netloc
        
        # 提取检测到的关键词
        detection_config = self._config.get("detection_rules", {}).get("login_detection", {})
        keywords = detection_config.get("keywords", [])
        detected_keywords = [kw for kw in keywords if kw.lower() in html_content.lower()]
        
        reason = f"检测到登录验证页面 (status={status_code})"
        if detected_keywords:
            reason += f": {', '.join(detected_keywords[:3])}"
        
        self.add_login_required_source(
            domain=domain,
            reason=reason,
            detection_keywords=detected_keywords,
            auto_detected=True
        )
    
    # ==================== 统计信息 ====================
    
    def get_stats(self) -> Dict[str, int]:
        """获取配置统计信息"""
        return {
            "preferred_sources": len(self.get_preferred_sources()),
            "blocked_sources": len(self.get_blocked_sources()),
            "login_required_sources": len(self.get_login_required_sources()),
            "strict_domains": len(self.get_strict_domains())
        }
    
    def print_stats(self):
        """打印配置统计信息"""
        stats = self.get_stats()
        print("\n" + "="*60)
        print("📊 Source Configuration Stats")
        print("="*60)
        print(f"  Preferred Sources:      {stats['preferred_sources']}")
        print(f"  Blocked Sources:        {stats['blocked_sources']}")
        print(f"  Login Required Sources: {stats['login_required_sources']}")
        print(f"  Strict Domains:         {stats['strict_domains']}")
        print("="*60 + "\n")


# 全局单例
_config_manager: Optional[SourceConfigManager] = None


def get_config_manager() -> SourceConfigManager:
    """获取全局配置管理器单例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = SourceConfigManager()
    return _config_manager
