# 新闻结构化分析 — 提示词模板

| 字段 | 值 |
|------|-----|
| **version** | v1.0 |
| **用途** | 对财经新闻进行结构化分析，提取实体、情感、影响等维度 |
| **调用方** | `backend/app/news/llm_processor.py` → `_get_analysis_prompt()` |
| **模型要求** | GPT-4o 或本地 Qwen |
| **占位符** | `{title}`, `{content}` |

---

## User Prompt Template

```
你是专业的财经编辑，输出结构化分析并保持"新闻纪要"口吻。

新闻标题: {title}
新闻内容: {content}

按以下 JSON 返回：
{{
    "summary": "50-120字简明摘要。禁止出现：本文/文章/本页面/该页面/我们/模型 等措辞；不要解释方法；用客观、简短的事实句。若页面为行情/模板/数据页，请基于可见参数生成'数据分析式摘要'，提炼指数涨跌与涨跌幅、成交额/量、资金流向、ETF/板块表现等；不要写'无实质新闻'。",
    "category": "finance/policy/industry/company/market/economic 之一",
    "companies": ["涉及公司"],
    "people": ["涉及人物"],
    "locations": ["涉及地点"],
    "stock_symbols": ["股票代码，如 002649.SZ"],
    "sentiment_type": "positive/negative/neutral",
    "sentiment_score": -1~1,
    "sentiment_confidence": 0~1,
    "main_topics": ["主要话题"],
    "keywords": ["关键词"],
    "financial_metrics": {{
        "mentioned_values": ["数值"],
        "percentages": ["百分比"],
        "financial_terms": ["术语"]
    }},
    "market_impact": "high/medium/low",
    "relevance_score": 0~1,
    "time_references": ["时间引用"],
    "content_quality": 0~1,
    "reliability_assessment": "high/medium/low"
}}

约束：
- 摘要不得使用"本文/文章/该页面/本页面/网页"等元信息表述；不得出现"综上/我们认为/模型判断"等主观或流程性语言。
- 若页面主要为行情/模板/数据页，缺少新闻事实，请直接生成基于数值的"数据分析式摘要"（例如概括指数涨跌、涨跌幅、成交额/量、资金流向、ETF/板块表现等），切勿返回"无实质新闻"。
- 只输出 JSON。
```

## 输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `summary` | string | 50-120字客观摘要 |
| `category` | enum | finance/policy/industry/company/market/economic |
| `companies` | string[] | 涉及公司名称列表 |
| `stock_symbols` | string[] | 股票代码（如 002649.SZ） |
| `sentiment_type` | enum | positive/negative/neutral |
| `sentiment_score` | float | 情感得分 -1 到 1 |
| `market_impact` | enum | high/medium/low |
| `content_quality` | float | 内容质量 0 到 1 |
| `reliability_assessment` | enum | high/medium/low |

## 关键约束

- 摘要必须客观事实导向，禁止元信息表述
- 行情数据页也必须生成有意义的摘要，不得返回"无实质新闻"
- 仅输出 JSON，不附加任何额外文字

---

## 变更日志

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2025-10-08 | 初始版本，从 llm_processor.py 提取 |
