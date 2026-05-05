# 股票画像富化 — 提示词模板

| 字段 | 值 |
|------|-----|
| **version** | v1.0 |
| **用途** | 基于多源公开信息为股票生成结构化企业画像 |
| **调用方** | `backend/app/utils/stock_profile_enrichment.py` → `StockProfileEnricher._profile_prompt` |
| **模型要求** | GPT-4o 或本地 Qwen |
| **占位符** | `{company_name}`, `{symbol}`, `{collected_info}` |

---

## User Prompt Template

```
你是专业的财经分析师。基于以下关于公司 {company_name} ({symbol}) 的公开信息，生成结构化的企业画像。

【公司基本信息】
- 名称: {company_name}
- 代码: {symbol}

【搜集到的公开资料】
{collected_info}

请严格基于上述资料，按以下 JSON 格式返回分析结果：
{{
    "industry": "所属行业",
    "sub_industry": "细分行业",
    "business_summary": "业务概述（80-200字，必须具体描述：主营业务/产品服务/商业模式/主要客户或应用场景/收入来源至少2项）",
    "core_products": "核心产品或服务，逗号分隔",
    "competitive_position": "市场地位或竞争优势",
    "competitors": "主要竞争对手，逗号分隔",
    "risk_factors": "主要风险因素，逗号分隔",
    "strategic_keywords": "战略关键词，逗号分隔",
    "market_position": "市场表现评价",
    "history_highlights": "历史亮点/里程碑（3-6条，按时间顺序，用分号分隔；没有就留空）"
}}

要求：
- 只基于上面提供的资料分析，资料中没有的信息对应字段留空字符串 ""
- 绝对不要使用"暂无"、"待补充"、"未找到"等占位词
- 如果某字段确实无法从资料中提取，直接写空字符串 ""
- 确保输出为有效 JSON 格式
```

## 输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `industry` | string | 所属行业 |
| `sub_industry` | string | 细分行业 |
| `business_summary` | string | 80-200 字业务概述 |
| `core_products` | string | 核心产品/服务，逗号分隔 |
| `competitive_position` | string | 市场地位/竞争优势 |
| `competitors` | string | 主要竞争对手，逗号分隔 |
| `risk_factors` | string | 风险因素，逗号分隔 |
| `strategic_keywords` | string | 战略关键词，逗号分隔 |
| `market_position` | string | 市场表现评价 |
| `history_highlights` | string | 历史里程碑，分号分隔 |

## 关键约束

- 严格基于提供的资料，不得引入外部知识
- 信息缺失时留空字符串 `""`，禁止使用占位词
- `business_summary` 要求至少涵盖主营业务、产品服务、商业模式、客户场景、收入来源中的 2 项

---

## 变更日志

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2025-10-08 | 初始版本，从 stock_profile_enrichment.py 提取 |
