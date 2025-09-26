#!/usr/bin/env python3
"""
简化测试服务器 - 只测试新闻管理API
"""
import sys
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 添加后端目录到Python路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

app = FastAPI(title="News Management API Test")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "News Management API Test Server"}

@app.get("/api/news/stats")
async def get_news_stats():
    """测试新闻统计API"""
    return {
        "total_articles": 100,
        "today_articles": 5,
        "positive_sentiment": 60,
        "negative_sentiment": 20,
        "neutral_sentiment": 20,
        "top_sources": [
            {"source": "Test Source 1", "count": 30},
            {"source": "Test Source 2", "count": 25}
        ],
        "top_stocks": [
            {"stock": "000001", "count": 15},
            {"stock": "000002", "count": 12}
        ]
    }

@app.get("/api/news/articles")
async def get_news_articles():
    """测试获取新闻文章API"""
    return {
        "articles": [
            {
                "id": 1,
                "title": "测试新闻标题1",
                "url": "https://example.com/news1",
                "summary": "这是测试新闻的摘要",
                "published_at": "2025-01-15T10:00:00",
                "source": "Test Source",
                "sentiment_type": "positive",
                "sentiment_score": 0.8,
                "relevance_score": 0.9,
                "related_stocks": ["000001"],
                "is_bookmarked": False,
                "is_read": False
            },
            {
                "id": 2,
                "title": "测试新闻标题2",
                "url": "https://example.com/news2",
                "summary": "这是另一篇测试新闻的摘要",
                "published_at": "2025-01-15T11:00:00",
                "source": "Test Source",
                "sentiment_type": "neutral",
                "sentiment_score": 0.1,
                "relevance_score": 0.7,
                "related_stocks": ["000002"],
                "is_bookmarked": False,
                "is_read": False
            }
        ],
        "limit": 50,
        "offset": 0,
        "total_count": 2
    }

@app.post("/api/news/{article_id}/bookmark")
async def toggle_bookmark(article_id: int):
    """测试书签切换API"""
    return {
        "status": "success",
        "article_id": article_id,
        "is_bookmarked": True
    }

@app.post("/api/news/{article_id}/read")
async def toggle_read_status(article_id: int):
    """测试已读状态切换API"""
    return {
        "status": "success",
        "article_id": article_id,
        "is_read": True
    }

@app.post("/api/news/batch-update")
async def batch_update_news(article_ids: list = [], action: str = "mark_read"):
    """测试批量更新API"""
    return {
        "status": "success",
        "updated_count": len(article_ids),
        "action": action
    }

if __name__ == "__main__":
    import uvicorn
    print("🚀 启动简化测试服务器...")
    uvicorn.run(app, host="localhost", port=8080)