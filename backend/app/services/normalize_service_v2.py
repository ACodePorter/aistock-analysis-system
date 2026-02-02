"""内容标准化服务

职责：
1. 文本标准化
2. 质量评分
3. 去重检测
4. 关键词提取
"""

import re
import hashlib
import logging
from typing import Optional, Tuple, List
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class NormalizeService:
    """内容标准化服务"""
    
    def __init__(self):
        """初始化"""
        self.min_quality_score = 0.4
        self.similarity_threshold = 0.85
    
    def normalize_text(self, text: str) -> str:
        """文本标准化"""
        if not text:
            return ""
        
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 转换为小写
        text = text.lower()
        
        return text
    
    def compute_quality_score(self, article) -> float:
        """计算文章质量评分"""
        # 支持 dict 或 str 输入
        if isinstance(article, dict):
            text = article.get('content', '')
            title = article.get('title', '')
        else:
            text = article
            title = ''
        
        if not text:
            return 0.0
        
        text_len = len(text)
        score = 0.0
        
        # 长度评分
        if 300 <= text_len <= 2000:
            length_score = 1.0
        elif text_len < 100:
            length_score = 0.2
        else:
            length_score = max(0.3, min(1.0, text_len / 2000))
        score += length_score * 0.4
        
        # 词汇丰富度
        words = text.split()
        if len(words) > 0:
            unique_words = len(set(words))
            vocab_score = min(1.0, unique_words / max(len(words), 1) * 2)
        else:
            vocab_score = 0.0
        score += vocab_score * 0.3
        
        # 标点符号评分
        punctuation_count = len(re.findall(r'[。！？，、；：]', text))
        punctuation_score = min(1.0, punctuation_count / max(text_len / 50, 1))
        score += punctuation_score * 0.2
        
        # 标题质量
        if title:
            title_len = len(title)
            if 8 <= title_len <= 100:
                title_score = 1.0
            else:
                title_score = max(0.5, min(1.0, title_len / 50))
        else:
            title_score = 0.5
        score += title_score * 0.1
        
        return round(score, 3)
    
    def is_duplicate(self, text1: str, text2: str) -> bool:
        """检测是否重复"""
        if not text1 or not text2:
            return False
        
        norm1 = self.normalize_text(text1)
        norm2 = self.normalize_text(text2)
        
        similarity = SequenceMatcher(None, norm1, norm2).ratio()
        
        return similarity >= self.similarity_threshold
    
    def compute_content_hash(self, content: str) -> str:
        """计算内容 SHA256 哈希"""
        norm_text = self.normalize_text(content)
        return hashlib.sha256(norm_text.encode()).hexdigest()
    
    def extract_keywords(self, text: str, num_keywords: int = 10) -> List[str]:
        """提取关键词"""
        if not text:
            return []
        
        words = text.split()
        stopwords = {'的', '是', '了', '在', '和', '人', '有', '为', '不', '一'}
        words = [w for w in words if len(w) > 1 and w not in stopwords]
        
        word_freq = {}
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1
        
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [w[0] for w in sorted_words[:num_keywords]]
    
    def normalize_url(self, url: str) -> str:
        """URL规范化"""
        if not url:
            return ""
        
        url = url.lower()
        if '#' in url:
            url = url[:url.index('#')]
        
        return url
    
    def normalize_batch(self, articles: list) -> dict:
        """批量清洗"""
        results = {"success": 0, "failed": 0, "cleaned": []}
        
        for article in articles:
            try:
                quality_score = self.compute_quality_score(article)
                if quality_score >= self.min_quality_score:
                    article["quality_score"] = quality_score
                    article["content_hash"] = self.compute_content_hash(article.get('content', ''))
                    results["cleaned"].append(article)
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                logger.error(f"Error normalizing article: {e}")
                results["failed"] += 1
        
        return results
