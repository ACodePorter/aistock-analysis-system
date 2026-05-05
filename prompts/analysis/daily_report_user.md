# 日报生成 — 用户提示词模板

| 字段 | 值 |
|------|-----|
| **version** | v1.0 |
| **用途** | 每日投资分析报告的用户输入模板，动态填充股票数据 |
| **调用方** | `backend/app/analysis/report_generator.py` → `_build_analysis_prompt()` |
| **模型要求** | GPT-4o 及以上 |
| **占位符** | `{stock_count}`, `{buy_count}`, `{hold_count}`, `{sell_count}`, `{avg_score}`, `{buy_details}`, `{sell_details}` |

---

## User Prompt Template

```
请根据以下A股股票分析数据，生成一份专业、可操作的每日投资分析报告。报告须具有明确的买卖指导价值。

## 今日分析概况
- 分析股票数：{stock_count}只
- 推荐买入：{buy_count}只 | 建议持有：{hold_count}只 | 建议卖出：{sell_count}只
- 平均评分：{avg_score}分

## 推荐买入股票详细数据
{buy_details}

## 建议卖出/高风险股票
{sell_details}

## 报告要求（严格按以下结构输出）

### 一、市场整体研判
- 用2-3句话概括今日A股市场走势和资金动向
- 明确给出短期（1-3天）市场方向判断

### 二、重点推荐股票分析（选2-3只评分最高的详细分析）
对每只股票须包含：
- **买入逻辑**：为什么现在值得买入（技术面+基本面+消息面综合判断）
- **参考介入价位**：基于MA和支撑位给出合理买入区间
- **目标价位**：基于阻力位和趋势给出短期目标
- **止损位**：给出明确的止损参考价位
- **仓位建议**：建议占总仓位的百分比

### 三、风险警示
- 对高风险/建议卖出的股票给出明确的操作建议
- 如持有则给出减仓/止损建议

### 四、今日操作策略
- 给出2-3条具体可执行的操作建议
- 整体仓位建议（轻仓/半仓/重仓）

请用中文输出，专业客观，控制在800字以内。数据驱动，不说空话。
```

## 动态数据字段说明

每只买入推荐股票包含以下数据行：

```
- **{name}**({symbol}): 综合{total_score}分, 置信度{confidence}
  收盘¥{close_price}, 涨跌{pct_change}%, MA5={ma5}, MA20={ma20}, RSI={rsi}
  五维评分: 技术{technical}/基本面{fundamental}/情绪{sentiment}/资金{fund_flow}/周期{cycle}
  利好因素: {key_factors}
  风险因素: {risk_factors}
  新闻情报: {news_count}篇, 情感均值{news_sentiment_avg}
```

每只卖出股票包含：

```
- **{name}**({symbol}): 综合{total_score}分, 收盘¥{close_price}, 涨跌{pct_change}%
  风险因素: {risk_factors}
```

---

## 变更日志

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2025-10-08 | 初始版本，从 report_generator.py 提取 |
