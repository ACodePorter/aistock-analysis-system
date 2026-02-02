"""
RAG问答路由 - API端点

Endpoints:
- POST /api/rag/query
- GET  /api/rag/evidences/{query_hash}
"""

from fastapi import APIRouter
from typing import Optional, List
from pydantic import BaseModel

router = APIRouter(prefix="/api/rag", tags=["rag"])


class QueryRequest(BaseModel):
    """问答请求"""
    question: str
    symbol: str
    include_evidence: bool = True
    top_k: int = 10


class QueryResponse(BaseModel):
    """问答响应"""
    answer: str
    evidence: List[dict]
    confidence: float
    caveats: Optional[str] = None


@router.post("/query", response_model=QueryResponse)
async def ask_question(request: QueryRequest):
    """
    对特定股票进行RAG问答
    
    Request:
    {
        "question": "这只股票最近有什么重大风险吗？",
        "symbol": "600519.SH",
        "include_evidence": true,
        "top_k": 10
    }
    
    Response:
    {
        "answer": "...",
        "evidence": [
            {
                "title": "...",
                "url": "...",
                "source_level": "L1",
                "relevance": 0.95
            }
        ],
        "confidence": 0.85,
        "caveats": "..."
    }
    """
    # TODO: 实现
    pass


@router.get("/status")
async def get_rag_status():
    """获取RAG系统状态（向量库、索引等）"""
    # TODO: 实现
    pass


@router.post("/reindex")
async def reindex_vectors():
    """
    手动重建向量索引
    
    （用于调试或大规模更新）
    """
    # TODO: 实现
    pass
