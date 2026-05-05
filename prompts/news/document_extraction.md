# 公告/文档结构化提取 — 提示词模板

| 字段 | 值 |
|------|-----|
| **version** | v1.0 |
| **用途** | 从上市公司公告、报告等文档中提取结构化信息 |
| **调用方** | `backend/app/news/document_manager.py` → `LLMExtractor.EXTRACTION_PROMPT` |
| **模型要求** | GPT-4o 或本地 Qwen |
| **占位符** | `{title}`, `{source}`, `{symbol}`, `{content}` |
| **内容截断** | 文档内容截取前 8000 字 |

---

## User Prompt Template

```
请分析以下文档内容，提取结构化信息。

文档标题：{title}
文档来源：{source}
关联股票：{symbol}

文档内容（截取前8000字）：
{content}

请以 JSON 格式返回以下信息：
{{
    "document_type": "文档类型（如：定期报告/临时公告/风险提示/招募说明书/业绩预告/董事会决议等）",
    "industry": ["相关行业1", "相关行业2"],
    "themes": ["主题标签1", "主题标签2"],
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "entities": {{
        "companies": ["公司名1"],
        "people": ["人名1"],
        "amounts": ["金额1"],
        "dates": ["日期1"]
    }},
    "sentiment": "positive/negative/neutral",
    "sentiment_score": 0.5,
    "importance": "high/normal/low",
    "summary": "100-200字的核心摘要",
    "key_points": ["要点1", "要点2", "要点3"],
    "financial_data": {{
    }},
    "risk_factors": ["风险因素1"],
    "action_items": ["需关注事项1"]
}}

只返回 JSON，不要其他文字。
```

## 输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `document_type` | string | 定期报告/临时公告/风险提示/招募说明书/业绩预告/董事会决议 等 |
| `industry` | string[] | 相关行业 |
| `themes` | string[] | 并购重组/分红派息/业绩变动/风险提示/人事变动/股权激励 等 |
| `keywords` | string[] | 文档关键词 |
| `entities` | object | 实体抽取（公司/人物/金额/日期） |
| `sentiment` | enum | positive/negative/neutral |
| `sentiment_score` | float | 情感得分 -1 到 1 |
| `importance` | enum | high/normal/low |
| `summary` | string | 100-200 字核心摘要 |
| `key_points` | string[] | 关键要点列表 |
| `financial_data` | object | 营收、利润、同比增长等财务数据（如有） |
| `risk_factors` | string[] | 风险因素 |
| `action_items` | string[] | 投资者需关注的事项 |

---

## 变更日志

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2025-10-08 | 初始版本，从 document_manager.py LLMExtractor 提取 |
