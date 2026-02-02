"""
实体识别与链接服务

职责：
1. 公司识别（symbol/名称/别名匹配）
2. 消歧（同名不同公司）
3. 关键词抽取
4. 命名实体识别（NER）
"""

from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


class EntityLinkService:
    """实体识别和链接服务"""
    
    def __init__(self):
        """初始化"""
        pass
    
    def extract_entities(self, text: str) -> dict:
        """
        从文本提取命名实体
        
        Returns:
            {
                "companies": [{"symbol": "600519.SH", "name": "贵州茅台", "confidence": 0.95}],
                "persons": [...],
                "locations": [...],
                "amounts": [...],
            }
        """
        # TODO: 使用NLP模型
        pass
    
    def link_to_stock(self, text: str) -> List[dict]:
        """
        识别文本中提到的股票
        
        Returns:
            [
                {"symbol": "600519.SH", "name": "贵州茅台", "mention_count": 2, "confidence": 0.95},
                ...
            ]
        """
        # TODO: 基于别名库和规则
        pass
    
    def extract_keywords(self, text: str) -> List[str]:
        """
        提取文本关键词
        
        Returns:
            ["业绩", "增长", "策略调整", ...]
        """
        # TODO: 实现
        pass
    
    def disambiguate(self, entity_name: str, context: Optional[str] = None) -> Optional[str]:
        """
        消歧：给定实体名和上下文，返回标准化symbol
        
        例：
        - "茅台" -> "600519.SH"
        - "贵州茅台" -> "600519.SH"
        """
        # TODO: 实现
        pass
    
    def get_company_aliases(self, symbol: str) -> List[str]:
        """获取公司的所有别名（用于搜索）"""
        # TODO: 从数据库加载
        pass
