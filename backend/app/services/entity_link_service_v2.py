"""实体链接与识别服务

职责：
1. 公司名称识别
2. 消歧义（一名多家、多名一家）
3. 映射到股票代码
4. NER命名实体识别
"""

import re
import logging
from typing import List, Dict, Optional, Set

logger = logging.getLogger(__name__)


class EntityLinkService:
    """实体链接服务"""
    
    def __init__(self):
        """初始化"""
        # 常见公司名称映射（简化版）
        self.company_mappings = {
            "贵州茅台": "600519.SH",
            "茅台": "600519.SH",
            "中国平安": "601318.SH",
            "平安": "601318.SH",
            "阿里巴巴": "009988.HK",
            "阿里": "009988.HK",
            "腾讯": "00700.HK",
            "腾讯控股": "00700.HK",
            "招商银行": "600036.SH",
            "恒生电子": "600570.SH",
        }
        
        # 人物关键词
        self.person_keywords = {'CEO', '董事长', '总经理', '创始人', '掌舵人', '首席'}
        
        # 地点关键词
        self.location_keywords = {'北京', '上海', '深圳', '杭州', '南京', '广州'}
    
    def extract_entities(self, text: str) -> List[dict]:
        """从文本中提取实体"""
        entities = []
        
        # 提取公司
        company_entities = self.extract_company_entities(text)
        entities.extend(company_entities)
        
        # 提取人物
        person_entities = self.extract_person_entities(text)
        entities.extend(person_entities)
        
        # 提取地点
        location_entities = self.extract_location_entities(text)
        entities.extend(location_entities)
        
        return entities
    
    def extract_company_entities(self, text: str) -> List[dict]:
        """提取公司实体"""
        entities = []
        
        # 按长度排序（长的先匹配）
        sorted_companies = sorted(
            self.company_mappings.keys(),
            key=len,
            reverse=True
        )
        
        for company_name in sorted_companies:
            pattern = re.escape(company_name)
            matches = re.finditer(pattern, text)
            
            for match in matches:
                symbol = self.company_mappings[company_name]
                entities.append({
                    "text": company_name,
                    "type": "company",
                    "symbol": symbol,
                    "start": match.start(),
                    "end": match.end(),
                })
        
        # 去重
        unique_entities = []
        seen_positions = set()
        for entity in sorted(entities, key=lambda x: x['start']):
            pos = (entity['start'], entity['end'])
            if pos not in seen_positions:
                unique_entities.append(entity)
                seen_positions.add(pos)
        
        return unique_entities
    
    def extract_person_entities(self, text: str) -> List[dict]:
        """提取人物实体"""
        entities = []
        
        for keyword in self.person_keywords:
            pattern = f'([\\u4e00-\\u9fff]+)({re.escape(keyword)})'
            matches = re.finditer(pattern, text)
            
            for match in matches:
                person_name = match.group(1) + match.group(2)
                entities.append({
                    "text": person_name,
                    "type": "person",
                    "role": keyword,
                    "start": match.start(),
                    "end": match.end(),
                })
        
        return entities
    
    def extract_location_entities(self, text: str) -> List[dict]:
        """提取地点实体"""
        entities = []
        
        for location in self.location_keywords:
            pattern = re.escape(location)
            matches = re.finditer(pattern, text)
            
            for match in matches:
                entities.append({
                    "text": location,
                    "type": "location",
                    "start": match.start(),
                    "end": match.end(),
                })
        
        return entities
    
    def company_to_symbol(self, company_name: str) -> Optional[str]:
        """将公司名称映射到股票代码"""
        # 精确匹配
        if company_name in self.company_mappings:
            return self.company_mappings[company_name]
        
        # 模糊匹配
        for key, symbol in self.company_mappings.items():
            if key in company_name or company_name in key:
                return symbol
        
        return None
    
    def disambiguate_company_name(self, name: str, context: str = None) -> Optional[str]:
        """消歧义处理"""
        symbol = self.company_to_symbol(name)
        if symbol:
            return symbol
        
        if context:
            if 'H股' in context or 'HK' in context or '港股' in context:
                for key, sym in self.company_mappings.items():
                    if key in name and '.HK' in sym:
                        return sym
            elif 'A股' in context or 'SH' in context or '沪深' in context:
                for key, sym in self.company_mappings.items():
                    if key in name and '.SH' in sym:
                        return sym
        
        return None
