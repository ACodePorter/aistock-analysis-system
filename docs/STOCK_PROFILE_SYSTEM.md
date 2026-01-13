# 📊 股票 Profile 系统完整文档

## 目录

1. [系统概述](#系统概述)
2. [快速开始](#快速开始)
3. [Profile 字段说明](#profile-字段说明)
4. [补充方案对比](#补充方案对比)
5. [脚本使用指南](#脚本使用指南)
6. [数据质量标准](#数据质量标准)
7. [常见问题](#常见问题)
8. [维护建议](#维护建议)

---

## 系统概述

### 什么是 Stock Profile？

Stock Profile（股票基础画像）是对上市公司的结构化信息存储，包含：

- **基础信息**: 公司名称、股票代码、所属行业
- **业务信息**: 主营业务、核心产品、竞争地位
- **补充信息**: 关键词、风险因素、历史事件、结构化 JSON

### 为什么需要 Profile？

1. **API 数据支撑** - 为前端提供公司详细信息
2. **新闻关联** - 判断新闻与公司的相关性
3. **数据分析** - 行业分类、分组分析
4. **用户体验** - 展示公司完整信息

### 系统现状

```
📊 Profile 数据统计（最新）:
  总股票数: 3,141
  有 company_name: 3,141 (100%)
  有 business_summary: 0 (0%)
  有 industry: 0 (0%)
  
待补充项:
  ✗ industry (行业) - 0/3,141 (0%)
  ✗ business_summary (业务摘要) - 0/3,141 (0%)
  ✗ strategic_keywords (关键词) - 0/3,141 (0%)
  ✗ risk_factors (风险因素) - 0/3,141 (0%)
```

---

## 快速开始

### 基础补充（仅补充 company_name）

这已自动完成！所有 3,141 支股票的 `company_name` 都已从 `stocks.name` 补充。

```bash
# 验证
python backend/scripts/check_profile_status.py
# 输出: 有 company_name 的 profiles: 3141
```

### 进阶补充（添加行业、摘要等）

#### 方案 A：从数据源补充

```bash
# 干运行查看计划
python backend/scripts/build_stock_profiles.py --dry-run

# 实际执行补充（需要 Tushare 或网络爬取）
python backend/scripts/build_stock_profiles.py --apply

# 指定处理特定股票
python backend/scripts/build_stock_profiles.py --apply \
  --stocks 300251.SZ,002594.SZ,600519.SH
```

#### 方案 B：LLM 生成摘要

```bash
# 需要配置 OpenAI API Key
export OPENAI_API_KEY="sk-..."

# 干运行
python backend/scripts/enrich_stock_profiles_llm.py --dry-run

# 实际执行
python backend/scripts/enrich_stock_profiles_llm.py --apply

# 仅处理缺少摘要的
python backend/scripts/enrich_stock_profiles_llm.py --apply

# 更新所有 profiles
python backend/scripts/enrich_stock_profiles_llm.py --apply --update-existing

# 使用特定模型
python backend/scripts/enrich_stock_profiles_llm.py --apply --model gpt-4
```

---

## Profile 字段说明

### 核心字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `symbol` | String | 股票代码 | `300251.SZ` |
| `company_name` | String | 公司名称 | `光线传媒` |
| `industry` | String | 所属行业 | `传媒娱乐` |
| `sub_industry` | String | 子行业 | `影视制作` |

### 业务信息字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `business_summary` | Text | 业务摘要 | `主要从事电影...` |
| `core_products` | Text | 核心产品 | `电影发行, 制作...` |
| `competitive_position` | Text | 竞争地位 | `国内领先的影视公司` |
| `competitors` | Text | 竞争对手 | `万达电影, 阿里影业` |

### 战略信息字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `strategic_keywords` | Text | 战略关键词 | `IP改编, 海外发行, AI技术` |
| `risk_factors` | Text | 风险因素 | `政策风险, 票房波动` |
| `history_highlights` | Text | 历史亮点 | `首家A股影视公司` |

### 元数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `profile_json` | Text | 完整结构化 JSON |
| `last_refreshed` | DateTime | 最后更新时间 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 修改时间 |

### 数据示例

```json
{
  "symbol": "300251.SZ",
  "company_name": "光线传媒",
  "industry": "传媒娱乐",
  "sub_industry": "影视制作",
  "business_summary": "光线传媒是国内领先的电影发行和制作公司，主要从事电影、电视剧、网络剧等视听作品的投资、制作和发行。",
  "core_products": "电影发行, 电视剧制作, 网络电影, IP开发",
  "competitive_position": "国内TOP3影视制作发行公司",
  "competitors": "万达电影, 阿里影业, 完美世界",
  "strategic_keywords": "IP改编, 海外发行, AI技术应用, 流媒体合作",
  "risk_factors": "电影票房波动, 政策审查风险, 版权争议",
  "history_highlights": "2010年上市, 率先进行国际化, 多部票房大片",
  "profile_json": null,
  "last_refreshed": "2025-10-17T02:15:00Z"
}
```

---

## 补充方案对比

### 方案选择矩阵

| 特性 | 基础补充 | 数据源补充 | LLM 补充 |
|------|---------|----------|---------|
| **覆盖率** | 100% | ~60-70% | 95%+ |
| **质量** | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **速度** | 极快 | 中等 | 慢 |
| **成本** | 0 | 免费 | 按调用计费 |
| **依赖** | 无 | Tushare/爬虫 | OpenAI API |
| **适用** | 必须 | 补充行业 | 生成摘要 |

### 推荐策略

```
第一阶段（已完成）: 基础补充
  ├─ company_name: 从 stocks.name 复制 ✅
  └─ 用时: 7.6 秒，3141 支股票

第二阶段（可选）: 数据源补充
  ├─ industry: 从 Tushare / 爬虫获取
  ├─ sub_industry: 细分行业分类
  └─ 用时: 30-60 分钟（含网络延迟）

第三阶段（高质量）: LLM 生成摘要
  ├─ business_summary: GPT 生成业务描述
  ├─ strategic_keywords: 关键词提取
  └─ 用时: 30-60 分钟（LLM 费用 $50-200）
```

### 最小化方案（推荐用于生产）

```bash
# 只进行基础补充（已完成）
python backend/scripts/bulk_build_stock_profiles.py

# 定期增量补充（仅处理新增股票）
# 在 crontab 中添加:
# 0 */6 * * * python backend/scripts/bulk_build_stock_profiles.py
```

### 完整方案（用于高质量场景）

```bash
# 1. 基础补充（已完成）
python backend/scripts/bulk_build_stock_profiles.py

# 2. 数据源补充（需要 Tushare Token）
export TUSHARE_TOKEN="your_token_here"
python backend/scripts/build_stock_profiles.py --apply

# 3. LLM 补充（需要 OpenAI API Key）
export OPENAI_API_KEY="sk-..."
python backend/scripts/enrich_stock_profiles_llm.py --apply
```

---

## 脚本使用指南

### 1. `bulk_build_stock_profiles.py` - 快速基础补充

**功能**: 快速补充所有股票的 `company_name`

```bash
python backend/scripts/bulk_build_stock_profiles.py

# 输出
======================================================================
⚡ 并行化 Profile 补充系统
======================================================================

🎯 处理 3141 支股票

📦 第 1/32 批 (100 支股票)... ✅
📦 第 2/32 批 (100 支股票)... ✅
...
📦 第 32/32 批 (41 支股票)... ✅

======================================================================
📊 执行统计
======================================================================
✅ 处理完成
  处理总数: 3141
  新建 profiles: 0
  更新 profiles: 3141
  总耗时: 7.6 秒
  平均速度: 415 支/秒
```

**特点**:
- ✅ 极快（3141 支仅需 7.6 秒）
- ✅ 无依赖（不需要外部 API）
- ✅ 幂等的（重复运行安全）

### 2. `build_stock_profiles.py` - 数据源补充

**功能**: 从 Tushare/网络爬取补充 industry、sub_industry 等

```bash
# 干运行查看计划
python backend/scripts/build_stock_profiles.py --dry-run

# 实际执行
python backend/scripts/build_stock_profiles.py --apply

# 指定股票
python backend/scripts/build_stock_profiles.py --apply \
  --stocks 300251.SZ,002594.SZ \
  --batch-size 3
```

**参数**:
- `--dry-run`: 干运行（默认）
- `--apply`: 实际执行
- `--stocks`: 指定符号，逗号分隔
- `--batch-size`: 批大小（默认 5）

**需求**:
- Tushare Token（可选）
- 网络连接（爬取新浪财经）

### 3. `enrich_stock_profiles_llm.py` - LLM 补充摘要

**功能**: 使用 GPT 生成高质量的业务摘要和关键词

```bash
# 需要配置 OpenAI API Key
export OPENAI_API_KEY="sk-..."

# 干运行
python backend/scripts/enrich_stock_profiles_llm.py --dry-run

# 实际执行
python backend/scripts/enrich_stock_profiles_llm.py --apply

# 更新所有（包括已有摘要的）
python backend/scripts/enrich_stock_profiles_llm.py --apply \
  --update-existing

# 使用 GPT-4（更高质量但更慢）
python backend/scripts/enrich_stock_profiles_llm.py --apply \
  --model gpt-4
```

**参数**:
- `--dry-run`: 干运行（默认）
- `--apply`: 实际执行
- `--stocks`: 指定符号，逗号分隔
- `--model`: LLM 模型（默认: gpt-3.5-turbo）
- `--update-existing`: 更新已有摘要的

**成本估算**:
- 3,141 支股票 × $0.001/个 ≈ $3
- GPT-4: 3,141 支 × $0.01 ≈ $31

---

## 数据质量标准

### 质量等级定义

```
📊 Profile 完整度评分

等级 1 - 基础 (100%)
  ✓ company_name (股票名称)
  ✗ industry (行业)
  ✗ business_summary (摘要)
  ✗ strategic_keywords (关键词)
  得分: 1/4 (25%)

等级 2 - 中等 (60-80%)
  ✓ company_name
  ✓ industry
  ✗ business_summary
  ✓ strategic_keywords
  得分: 3/4 (75%)

等级 3 - 高质 (80%+)
  ✓ company_name
  ✓ industry
  ✓ business_summary
  ✓ strategic_keywords
  ✓ risk_factors
  得分: 5/5 (100%)
```

### 当前质量指标

```
完整度分析:
  等级 1 (仅 company_name): 3,141 支 (100%)
  等级 2 (含行业信息): 0 支 (0%)
  等级 3 (含摘要和关键词): 0 支 (0%)

平均完整度: 25% (需提升至 80% 以上)
```

### 改进目标（优先级）

| 优先级 | 项目 | 现状 | 目标 | 方案 | 工作量 |
|--------|------|------|------|------|--------|
| 🔴 高 | industry | 0% | 80%+ | Tushare / 爬虫 | 中等 |
| 🔴 高 | business_summary | 0% | 90%+ | LLM 生成 | 中等 |
| 🟠 中 | strategic_keywords | 0% | 80%+ | LLM 提取 | 中等 |
| 🟠 中 | competitors | 0% | 70%+ | 网络爬取 | 低 |
| 🟡 低 | risk_factors | 0% | 50%+ | LLM 生成 | 高 |

---

## 常见问题

### Q1: 如何验证 profile 补充结果？

```bash
# 查看统计信息
python backend/scripts/check_profile_status.py

# 查看特定符号
python -c "
from backend.app.db import SessionLocal
from backend.app.models import StockProfile

with SessionLocal() as s:
    p = s.query(StockProfile).filter(StockProfile.symbol=='300251.SZ').first()
    print(f'{p.symbol}: {p.company_name}')
    print(f'行业: {p.industry}')
    print(f'摘要: {p.business_summary}')
"
```

### Q2: LLM 补充的费用如何计算？

```
假设使用 GPT-3.5-turbo:
  - Input: $0.0005 / 1K tokens
  - Output: $0.0015 / 1K tokens

3,141 支股票的估算:
  - 每个请求约 300 input tokens, 200 output tokens
  - 费用 = 3141 × (0.3 × 0.0005 + 0.2 × 0.0015) ≈ $1

使用 GPT-4o-mini (更便宜):
  - Input: $0.00015 / 1K tokens
  - Output: $0.0006 / 1K tokens
  - 费用 ≈ $0.30-0.50
```

### Q3: 如何中断长时间运行的补充？

```bash
# 方案1: 按 Ctrl+C 中断
# 脚本会自动保存已处理的数据

# 方案2: 检查已补充的部分
python -c "
from backend.app.db import SessionLocal
from backend.app.models import StockProfile
from sqlalchemy import func

with SessionLocal() as s:
    total = s.query(func.count(StockProfile.id)).scalar()
    with_summary = s.query(func.count(StockProfile.id)).filter(
        StockProfile.business_summary.isnot(None)
    ).scalar()
    print(f'总数: {total}, 已补充摘要: {with_summary}')
"
```

### Q4: 错误处理和重试

```bash
# 如果中途出现错误，可以重新运行
# 脚本会自动跳过已处理的部分（幂等性）

# 仅处理缺少摘要的部分
python backend/scripts/enrich_stock_profiles_llm.py --apply
# 会自动跳过已有 business_summary 的

# 强制更新所有
python backend/scripts/enrich_stock_profiles_llm.py --apply \
  --update-existing
```

### Q5: 如何备份和恢复 profile 数据？

```bash
# 备份
pg_dump -h localhost -U ai_stock -d aistock \
  -t stock_profiles > stock_profiles_backup.sql

# 恢复
psql -h localhost -U ai_stock -d aistock \
  < stock_profiles_backup.sql
```

---

## 维护建议

### 定期维护计划

```
周期        任务                          脚本
────────────────────────────────────────────────
每周      检查新增股票 profile          bulk_build_stock_profiles.py
每月      更新行业分类                  build_stock_profiles.py --apply
每季      刷新 LLM 生成的摘要           enrich_stock_profiles_llm.py --apply
每年      完整质量审计                  check_profile_status.py
```

### 监控指标

```bash
# 每周运行一次统计
0 2 * * 1 python backend/scripts/check_profile_status.py \
  >> /var/log/profile_weekly_stats.log

# 监控完整度
COMPLETE_PCT=$(python -c "
from backend.app.db import SessionLocal
from backend.app.models import StockProfile
from sqlalchemy import func

with SessionLocal() as s:
    with_summary = s.query(func.count(StockProfile.id)).filter(
        StockProfile.business_summary.isnot(None)
    ).scalar() or 0
    total = s.query(func.count(StockProfile.id)).scalar() or 1
    print(int(with_summary * 100 / total))
")

echo "Profile 摘要完整度: ${COMPLETE_PCT}%"
```

### 性能优化

```python
# 添加必要的索引
CREATE INDEX idx_profile_industry ON stock_profiles(industry);
CREATE INDEX idx_profile_refreshed ON stock_profiles(last_refreshed);

# 批量查询优化
profiles = session.query(StockProfile) \
    .filter(StockProfile.business_summary.isnot(None)) \
    .options(load_only(StockProfile.symbol, StockProfile.company_name)) \
    .all()
```

---

## 集成建议

### API 端点增强

```python
# 在 routers/stocks.py 中添加：

@router.get("/stocks/{symbol}/profile")
async def get_stock_profile(symbol: str):
    """获取股票的完整 profile 信息"""
    profile = session.query(StockProfile).filter(
        StockProfile.symbol == symbol
    ).first()
    
    if not profile:
        raise HTTPException(status_code=404)
    
    return {
        "symbol": profile.symbol,
        "company_name": profile.company_name,
        "industry": profile.industry,
        "business_summary": profile.business_summary,
        "strategic_keywords": profile.strategic_keywords,
        "last_refreshed": profile.last_refreshed,
    }
```

### 前端展示

```jsx
// 前端展示 profile 信息示例
function StockProfile({ symbol }) {
  const profile = useQuery(`/api/stocks/${symbol}/profile`);
  
  return (
    <Card>
      <h2>{profile.company_name}</h2>
      <p>行业: {profile.industry}</p>
      <p>概述: {profile.business_summary}</p>
      <Tags>{profile.strategic_keywords}</Tags>
      <small>最后更新: {profile.last_refreshed}</small>
    </Card>
  );
}
```

---

## 总结

### 当前完成情况 ✅

| 项目 | 状态 | 进度 |
|------|------|------|
| 基础 Profile 创建 | ✅ 完成 | 100% |
| Company name 补充 | ✅ 完成 | 100% |
| 批处理脚本 | ✅ 完成 | - |
| 数据源补充脚本 | ✅ 完成 | - |
| LLM 补充脚本 | ✅ 完成 | - |
| 文档完善 | ✅ 完成 | - |

### 后续工作（优先级）

1. 🔴 **立即** - 补充 industry (60-90 分钟)
2. 🔴 **本周** - 生成 business_summary (30-60 分钟)
3. 🟠 **本月** - 添加 strategic_keywords 和 risk_factors
4. 🟡 **持续** - 定期更新和维护

### 建议的下一步

```bash
# 1. 验证当前状态
python backend/scripts/check_profile_status.py

# 2. 补充行业信息（如有 Tushare Token）
python backend/scripts/build_stock_profiles.py --apply

# 3. 生成业务摘要（如有 OpenAI API Key）
python backend/scripts/enrich_stock_profiles_llm.py --apply

# 4. 定期运行维护脚本
# 在 crontab 中添加周期任务
```

---

**最后更新**: 2025-10-17  
**系统版本**: 1.0  
**文档版本**: 1.0
