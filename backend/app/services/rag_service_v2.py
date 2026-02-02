"""混合RAG检索服务

职责：
1. 关键词检索
2. 语义相似度搜索
3. 混合排序
4. 时间衰减
"""

import re
import math
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class RetrievalStrategy(str, Enum):
    """检索策略"""
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class RagService:
    """混合RAG检索服务"""
    
    def __init__(self):
        """初始化"""
        self.keyword_weight = 0.3
        self.semantic_weight = 0.5
        self.time_weight = 0.2
        
        # 模拟文档库（实际应该从数据库查询）
        self.documents = []
    
    def hybrid_search(
        self,
        query: str,
        documents: List[Dict],
        strategy: RetrievalStrategy = RetrievalStrategy.HYBRID,
        top_k: int = 10,
        time_decay_days: int = 30
    ) -> List[Dict]:
        """混合检索"""
        if strategy == RetrievalStrategy.KEYWORD:
            results = self.keyword_search(query, documents, top_k)
        elif strategy == RetrievalStrategy.SEMANTIC:
            results = self.semantic_search(query, documents, top_k)
        else:  # HYBRID
            results = self.hybrid_rank(
                query,
                documents,
                top_k,
                time_decay_days
            )
        
        return results
    
    def keyword_search(
        self,
        query: str,
        documents: List[Dict],
        top_k: int = 10
    ) -> List[Dict]:
        """关键词检索"""
        query_tokens = self._tokenize(query)
        
        scored_docs = []
        for doc in documents:
            doc_text = self._normalize_text(doc.get('content', ''))
            doc_tokens = self._tokenize(doc_text)
            
            # 计算TF-IDF相似度
            score = self._calculate_tf_idf_score(query_tokens, doc_tokens)
            
            scored_docs.append({
                **doc,
                'score': score,
                'retrieval_method': 'keyword'
            })
        
        # 按分数排序
        ranked = sorted(scored_docs, key=lambda x: x['score'], reverse=True)
        return ranked[:top_k]
    
    def semantic_search(
        self,
        query: str,
        documents: List[Dict],
        top_k: int = 10
    ) -> List[Dict]:
        """语义相似度检索（简化版，基于关键词相似度）"""
        query_tokens = set(self._tokenize(query.lower()))
        
        scored_docs = []
        for doc in documents:
            doc_text = self._normalize_text(doc.get('content', ''))
            doc_tokens = set(self._tokenize(doc_text.lower()))
            
            # Jaccard相似度
            if not (query_tokens or doc_tokens):
                similarity = 0
            else:
                intersection = len(query_tokens & doc_tokens)
                union = len(query_tokens | doc_tokens)
                similarity = intersection / union if union > 0 else 0
            
            scored_docs.append({
                **doc,
                'score': similarity,
                'retrieval_method': 'semantic'
            })
        
        # 按分数排序
        ranked = sorted(scored_docs, key=lambda x: x['score'], reverse=True)
        return ranked[:top_k]
    
    def hybrid_rank(
        self,
        query: str,
        documents: List[Dict],
        top_k: int = 10,
        time_decay_days: int = 30
    ) -> List[Dict]:
        """混合排序
        
        综合考虑：
        - 关键词匹配 (30%)
        - 语义相似度 (50%)
        - 时间衰减 (20%)
        """
        # 获取各种方法的结果
        keyword_results = self.keyword_search(query, documents, len(documents))
        semantic_results = self.semantic_search(query, documents, len(documents))
        
        # 创建分数字典
        doc_scores = {}
        
        # 关键词分数
        for idx, doc in enumerate(keyword_results):
            doc_id = doc.get('id', doc.get('title', str(idx)))
            normalized_score = (1 - idx / len(keyword_results)) if keyword_results else 0
            doc_scores[doc_id] = {
                'keyword': normalized_score,
                'semantic': 0,
                'time': 0,
                'doc': doc
            }
        
        # 语义分数
        for idx, doc in enumerate(semantic_results):
            doc_id = doc.get('id', doc.get('title', str(idx)))
            normalized_score = (1 - idx / len(semantic_results)) if semantic_results else 0
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {
                    'keyword': 0,
                    'semantic': 0,
                    'time': 0,
                    'doc': doc
                }
            doc_scores[doc_id]['semantic'] = normalized_score
        
        # 时间衰减分数
        for doc_id, scores in doc_scores.items():
            created_at = scores['doc'].get('created_at')
            if created_at:
                time_score = self.apply_time_decay(
                    created_at,
                    time_decay_days
                )
                scores['time'] = time_score
        
        # 计算最终分数
        final_results = []
        for doc_id, scores in doc_scores.items():
            final_score = (
                scores['keyword'] * self.keyword_weight +
                scores['semantic'] * self.semantic_weight +
                scores['time'] * self.time_weight
            )
            
            result = {
                **scores['doc'],
                'final_score': final_score,
                'component_scores': {
                    'keyword': scores['keyword'],
                    'semantic': scores['semantic'],
                    'time': scores['time']
                },
                'retrieval_method': 'hybrid'
            }
            final_results.append(result)
        
        # 按最终分数排序
        ranked = sorted(final_results, key=lambda x: x['final_score'], reverse=True)
        return ranked[:top_k]
    
    def apply_time_decay(
        self,
        created_at: str,
        decay_days: int = 30
    ) -> float:
        """时间衰减权重
        
        最近的文档权重高，时间越久权重越低
        """
        try:
            if isinstance(created_at, str):
                created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                created_dt = created_at
            
            days_ago = (datetime.utcnow() - created_dt.replace(tzinfo=None)).days
            
            # 指数衰减
            decay = math.exp(-days_ago / decay_days)
            return max(0, decay)
        except Exception as e:
            logger.error(f"Error applying time decay: {e}")
            return 0
    
    def _tokenize(self, text: str) -> List[str]:
        """分词（简化版）"""
        # 转换为小写
        text = text.lower()
        
        # 移除特殊字符
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
        
        # 按空格分割
        tokens = text.split()
        
        # 过滤空字符串
        tokens = [t for t in tokens if t]
        
        return tokens
    
    def _normalize_text(self, text: str) -> str:
        """标准化文本"""
        # 移除HTML标签
        text = re.sub(r'<[^>]+>', '', text)
        
        # 移除URL
        text = re.sub(r'https?://\S+', '', text)
        
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _calculate_tf_idf_score(
        self,
        query_tokens: List[str],
        doc_tokens: List[str]
    ) -> float:
        """计算TF-IDF相似度"""
        if not query_tokens or not doc_tokens:
            return 0
        
        # 计算TF
        term_freq = {}
        for token in doc_tokens:
            term_freq[token] = term_freq.get(token, 0) + 1
        
        # 计算匹配分数
        matched_tokens = 0
        score = 0
        
        for query_token in query_tokens:
            if query_token in term_freq:
                matched_tokens += 1
                # TF权重
                tf = term_freq[query_token] / len(doc_tokens)
                score += tf
        
        # 标准化
        if query_tokens:
            score = score / len(query_tokens)
        
        return score
