# 🚀 快速使用指南

## 两大核心系统

### 1️⃣ 后台新闻补充系统

**用途**: 自动补充股票相关的新闻信息，使用 LLM 进行质量检查

**快速开始**:
```bash
# 查看计划（推荐首先运行此命令）
python backend/scripts/news_supplement_bg.py --dry-run

# 实际执行补充
python backend/scripts/news_supplement_bg.py --apply

# 设置定时任务（每日 2 点全量补充）
# 在 crontab 中添加:
# 0 2 * * * cd /path/to/project && python backend/scripts/news_supplement_bg.py --apply
```

**完整文档**: `docs/BACKGROUND_NEWS_SUPPLEMENT_SYSTEM.md` (800+ 行)

---

### 2️⃣ 股票 Profile 系统

**用途**: 在股票详情页面中展示和分析公司的详细信息、完整度评分、竞争分析

**核心功能**:
- ✅ 公司基本信息展示（名称、行业、业务描述）
- ✅ 三层信息架构（概览 / 数据分析 / 竞争分析）
- ✅ 实时完整度计算（0-100%）
- ✅ 质量评分系统（50-100 分）
- ✅ 竞争对标分析
- ✅ 一键刷新数据

**快速开始**:

#### 前端使用

1. **打开股票详情**
   ```
   进入任何股票详情页面 → 找到股票代码（如 000001.SZ）
   ```

2. **查看公司画像**
   ```
   点击"📊 公司画像"选项卡 → 自动加载 Profile 数据
   ```

3. **浏览三个面板**
   ```
   📋 概览     → 公司基本信息 + 关键指标
   📊 分析     → 完整度圆图 + 质量评分 + 更新状态
   🏆 竞争     → 行业概览 + 市场地位 + 对标数据
   ```

#### 后端数据补充

```bash
# 查看当前数据状态
python backend/scripts/check_profile_status.py

# 快速补充缺失数据
python backend/scripts/bulk_build_stock_profiles.py

# 针对特定股票
python backend/scripts/build_stock_profiles.py --symbol 000001.SZ --apply

# 使用 LLM 增强数据
export OPENAI_API_KEY="your_key"
python backend/scripts/enrich_stock_profiles_llm.py --apply
```

#### 数据完整度查询

```bash
# 查询特定股票的完整度
psql -U user -d database << EOF
SELECT symbol, company_name, 
       (CASE WHEN company_name IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN industry IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN business_summary IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN products IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN competitors IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN risk_factors IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN strategic_keywords IS NOT NULL THEN 1 ELSE 0 END) * 100 / 7 as completeness
FROM stock_profiles
ORDER BY completeness DESC
LIMIT 20;
EOF
```

#### API 调用示例

```bash
# 获取基本 Profile
curl http://localhost:8081/api/stock-profile/000001.SZ

# 获取详细 Profile（含分析数据）
curl http://localhost:8081/api/stock-profile/000001.SZ/details

# 刷新 Profile 数据
curl -X POST http://localhost:8081/api/stock-profile/000001.SZ/refresh
```

**完整文档**:
- **集成指南**: `docs/STOCK_PROFILE_INTEGRATION.md` (600+ 行)
- **API 参考**: `docs/API_REFERENCE.md` (400+ 行)
- **快速入门**: 本文件下方

---

### 3️⃣ 快速入门 - 公司画像系统
```bash
# 查看 profile 状态
python backend/scripts/check_profile_status.py

# 补充 company_name（已完成，3,141 支）
python backend/scripts/bulk_build_stock_profiles.py

# 补充行业信息（需要 Tushare 或网络爬取）
python backend/scripts/build_stock_profiles.py --apply

# 使用 LLM 生成业务摘要（需要 OpenAI API Key）
python backend/scripts/enrich_stock_profiles_llm.py --apply
```

**完整文档**: `docs/STOCK_PROFILE_SYSTEM.md` (600+ 行)

---

## 📋 所有可用脚本

### 新闻系统脚本
| 脚本 | 功能 | 用法 |
|------|------|------|
| `news_supplement_bg.py` | 后台补充新闻 | `--dry-run` / `--apply` |
| `schedule_news_supplement.py` | 定时任务配置 | `--daily-full` / `--daily-increment` |
| `cleanup_empty_summaries.py` | 清理空摘要 | `--dry-run` / `--apply` |
| `analyze_empty_summaries.py` | 分析数据质量 | 无参数直接运行 |

### Profile 系统脚本
| 脚本 | 功能 | 用法 |
|------|------|------|
| `bulk_build_stock_profiles.py` | 批量补充 company_name | 无参数直接运行 |
| `build_stock_profiles.py` | 补充 industry 等 | `--dry-run` / `--apply` |
| `enrich_stock_profiles_llm.py` | LLM 生成摘要 | `--dry-run` / `--apply` |
| `check_profile_status.py` | 查看状态 | 无参数直接运行 |

---

## 🎯 常见操作

### 操作 1: 补充新闻信息（推荐）
```bash
# 第一步: 查看计划
python backend/scripts/news_supplement_bg.py --dry-run

# 第二步: 实际执行
python backend/scripts/news_supplement_bg.py --apply
```

### 操作 2: 检查数据质量
```bash
# 查看 profile 完整度
python backend/scripts/check_profile_status.py

# 分析新闻数据质量
python backend/scripts/analyze_empty_summaries.py
```

### 操作 3: 设置定时任务
```bash
# 编辑 crontab
crontab -e

# 添加以下行:
# 凌晨 2 点补充新闻
0 2 * * * cd /path/to/project && python backend/scripts/news_supplement_bg.py --apply

# 周一早上检查状态
0 9 * * 1 cd /path/to/project && python backend/scripts/check_profile_status.py
```

### 操作 4: 补充高质量数据
```bash
# 补充 company_name（已完成）
python backend/scripts/bulk_build_stock_profiles.py

# 补充行业信息
export TUSHARE_TOKEN="your_token"
python backend/scripts/build_stock_profiles.py --apply

# 生成业务摘要
export OPENAI_API_KEY="sk-..."
python backend/scripts/enrich_stock_profiles_llm.py --apply
```

---

## 📊 当前系统状态

### 新闻系统
- ✅ 47 篇空摘要文章已清理
- ✅ 3 个 API 端点已添加过滤逻辑
- ✅ 后台补充系统已完全就绪
- ✅ 定时任务已配置模板

### Profile 系统
- ✅ 3,141 支股票 profile 已创建
- ✅ company_name 补充率: 100%
- ⏳ industry 补充率: 0% (可选)
- ⏳ business_summary 补充率: 0% (可选)

---

## 💡 建议的使用流程

### 本周（第一优先级）
```bash
# 1. 验证现有系统
python backend/scripts/check_profile_status.py
python backend/scripts/analyze_empty_summaries.py

# 2. 启用新闻补充
python backend/scripts/news_supplement_bg.py --apply

# 3. 设置定时任务
# 编辑 crontab 添加定时执行
```

### 本月（第二优先级）
```bash
# 1. 补充行业信息（如需要）
export TUSHARE_TOKEN="your_token"
python backend/scripts/build_stock_profiles.py --apply

# 2. 或者使用 LLM 生成高质量摘要
export OPENAI_API_KEY="sk-..."
python backend/scripts/enrich_stock_profiles_llm.py --apply
```

### 持续维护
```bash
# 每周检查新增股票
0 3 * * 1 python backend/scripts/bulk_build_stock_profiles.py

# 每月检查数据质量
0 3 1 * * python backend/scripts/check_profile_status.py
```

---

## 📚 详细文档

| 文档 | 内容 | 行数 |
|------|------|------|
| `docs/BACKGROUND_NEWS_SUPPLEMENT_SYSTEM.md` | 新闻补充系统完整指南 | 800+ |
| `docs/STOCK_PROFILE_SYSTEM.md` | Profile 系统完整指南 | 600+ |
| `docs/NEWS_SUPPLEMENT_SYSTEM.md` | 新闻补充简明指南 | 300+ |
| `PROJECT_COMPLETION_REPORT.md` | 第一阶段完成总结 | 300+ |
| `PHASE_2_COMPLETION_SUMMARY.md` | 第二阶段完成总结 | 400+ |

---

## ⚙️ 环境配置（可选）

### 如需使用 Tushare API
```bash
export TUSHARE_TOKEN="your_tushare_token_here"
```

### 如需使用 OpenAI API
```bash
export OPENAI_API_KEY="sk-your-key-here"
```

### 如需使用 Tushare API
```bash
export TUSHARE_TOKEN="your_token"
```

---

## 🔍 故障排查

### 问题：新闻补充速度很慢
```bash
# 增加延迟参数避免限流
python backend/scripts/news_supplement_bg.py --apply \
  --rate-limit-delay 2.0
```

### 问题：LLM 相关性评分过严格
```bash
# 降低阈值
python backend/scripts/news_supplement_bg.py --apply \
  --relevance-threshold 0.65
```

### 问题：要查看详细日志
```bash
# 查看实时日志
tail -f logs/news_supplement.log

# 搜索错误
grep ERROR logs/news_supplement.log
```

---

## ✨ 核心特性总结

### 新闻补充系统
- ✅ 后台自动运行，无需人工干预
- ✅ LLM 质量检查，相关性评分 0.7+ 才保存
- ✅ 支持干运行验证，无风险
- ✅ 可定时运行，支持多种调度方式
- ✅ 完整的日志记录和错误处理

### Profile 系统
- ✅ 3,141 支股票全覆盖
- ✅ 支持多种数据源（Tushare、爬虫、LLM）
- ✅ 模块化设计，易于扩展
- ✅ 幂等性设计，重复运行安全
- ✅ 完整的质量检查工具

---

## 🚀 立即开始

### 最简单的开始方式
```bash
# 1. 查看系统状态
python backend/scripts/check_profile_status.py

# 2. 运行新闻补充（干运行）
python backend/scripts/news_supplement_bg.py --dry-run

# 3. 如果满意，执行实际补充
python backend/scripts/news_supplement_bg.py --apply
```

### 预期结果
```
新闻补充完成后：
  - 新增: 10-50 篇高质量文章
  - 关联股票数: 5-20 支
  - LLM 调用次数: 10-50 次
  - 总耗时: 5-15 分钟
```

---

**完成时间**: 2025-10-17  
**系统状态**: ✅ 完全就绪  
**建议行动**: 立即运行新闻补充和数据验证

---

## 📞 支持文档

- 遇到问题？查看: `docs/BACKGROUND_NEWS_SUPPLEMENT_SYSTEM.md` 的故障排查部分
- 想了解细节？查看: `docs/STOCK_PROFILE_SYSTEM.md` 的完整说明
- 需要配置？查看: 各脚本文件的 docstring 或 `--help` 帮助信息

**一切准备就绪，开始使用吧！🎉**
