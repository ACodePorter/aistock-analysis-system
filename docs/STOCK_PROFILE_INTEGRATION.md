# 📊 股票公司画像（Profile）系统集成指南

**版本**: 1.0  
**更新时间**: 2025-10-17  
**状态**: ✅ 生产就绪

---

## 📋 目录

1. [系统概述](#系统概述)
2. [功能特性](#功能特性)
3. [前端组件](#前端组件)
4. [后端API](#后端api)
5. [使用指南](#使用指南)
6. [数据分析](#数据分析)
7. [故障排查](#故障排查)
8. [扩展建议](#扩展建议)

---

## 系统概述

### 什么是公司画像系统？

公司画像系统是一个完整的解决方案，用于在股票详情页面中展示和分析公司的详细信息。包括：

- **基本信息**: 公司名称、行业、业务描述
- **数据分析**: 信息完整度、质量评分、数据统计
- **竞争分析**: 竞争对手、市场地位、行业趋势
- **可视化展示**: 圆形进度图、柱状图、进度条等

### 核心功能

| 功能 | 描述 | 实现状态 |
|------|------|--------|
| 基本信息展示 | 显示公司核心信息 | ✅ 完成 |
| 公司画像卡片 | 可展开/收起的 Profile 卡 | ✅ 完成 |
| 数据分析面板 | 完整度、质量评分展示 | ✅ 完成 |
| 竞争分析 | 竞争对手对标分析 | ✅ 完成 |
| 多选项卡布局 | 概览/分析/竞争三个选项卡 | ✅ 完成 |
| 实时刷新 | 一键刷新 Profile 数据 | ✅ 完成 |
| 数据可视化 | 图表和可视化展示 | ✅ 完成 |

---

## 功能特性

### 1️⃣ 三层信息架构

#### 概览面板 (Overview Tab)
- 公司基本信息卡片
- 关键指标展示（产品数、竞争对手数、风险因素数）
- 支持展开/收起操作

#### 数据分析面板 (Analysis Tab)
- **信息完整度圆形图**: 直观展示数据完整程度
- **质量评分**: 0-100 分评分体系
- **更新状态**: 最后更新时间和立即更新按钮
- **质量细项**: 基本信息、业务描述、产品列表、竞争分析各项评分

#### 竞争分析面板 (Competitive Tab)
- **行业概览**: 行业内企业数、竞争对手数、市场份额
- **竞争地位**: 行业趋势、竞争力指数
- **市场对标**: 产品力、市场力、创新力对比

### 2️⃣ 响应式设计

- 🖥️ 桌面端：多列网格布局
- 📱 移动端：单列堆叠布局
- 适配所有主流浏览器

### 3️⃣ 交互体验

- **选项卡切换**: 平滑的选项卡切换动画
- **数据刷新**: 异步数据刷新，不阻塞 UI
- **展开/收起**: 公司画像卡片支持展开/收起
- **错误处理**: 友好的错误提示和重试机制

### 4️⃣ 数据完整度评估

系统自动评估以下字段的完整度：
- `company_name` - 公司名称
- `industry` - 行业
- `sub_industry` - 子行业
- `business_summary` - 业务介绍
- `products` - 产品列表
- `competitors` - 竞争对手
- `risk_factors` - 风险因素

完整度计算: `(有值字段数 / 总字段数) × 100%`

### 5️⃣ 质量评分

质量评分 = `50 + (完整度 / 2)`

- 50-70分: 📊 基础信息充足
- 70-85分: 📈 信息较完整
- 85-100分: ✨ 信息非常完整

---

## 前端组件

### 🎨 组件树结构

```
StockNewsDetail (主容器)
├── StockProfileDetails (详情页)
│   ├── Header (返回和标题)
│   ├── TabNavigation (选项卡导航)
│   ├── OverviewTab
│   │   └── StockProfileCard
│   ├── AnalysisTab
│   │   ├── ProfileCompleteness (完整度圆图)
│   │   ├── UpdateStatus (更新状态)
│   │   └── QualityDistribution (质量细项)
│   └── CompetitiveTab
│       ├── IndustryOverview
│       ├── CompetitivePosition
│       └── MarketComparison
└── NewsTab (新闻列表)
```

### 📄 文件清单

#### 新文件

| 文件 | 大小 | 功能 |
|------|------|------|
| `StockProfileCard.tsx` | ~9 KB | 公司画像卡片组件 |
| `StockProfileDetails.tsx` | ~17 KB | 完整 Profile 详情页 |
| `STOCK_PROFILE_INTEGRATION.md` | 本文件 | 集成指南 |

#### 修改文件

| 文件 | 修改内容 |
|------|--------|
| `StockNewsDetail.tsx` | 添加 Profile 选项卡、导入新组件 |
| `api.ts` | 添加 `PROFILE_DETAILS` API 路由 |

### 💻 组件 API

#### StockProfileCard

```typescript
interface StockProfileCardProps {
  symbol: string        // 股票代码
  onRefresh?: () => void // 刷新回调
}
```

用途: 显示可展开/收起的公司画像卡片

```tsx
<StockProfileCard 
  symbol="000001.SZ" 
  onRefresh={() => console.log('Refreshed!')}
/>
```

#### StockProfileDetails

```typescript
interface StockProfileDetailsProps {
  symbol: string  // 股票代码
  onBack: () => void  // 返回回调
}
```

用途: 显示完整的 Profile 详情页，包含三个选项卡

```tsx
<StockProfileDetails 
  symbol="000001.SZ" 
  onBack={() => navigate(-1)}
/>
```

---

## 后端API

### 📡 API 端点

#### 1. 获取基本 Profile

```
GET /api/stock-profile/{symbol}
```

**返回示例**:
```json
{
  "symbol": "000001.SZ",
  "company_name": "平安银行",
  "industry": "银行",
  "sub_industry": "商业银行",
  "products": "个人理财,公司贷款,投资银行",
  "competitors": "招商银行,工商银行,中国银行",
  "risk_factors": "市场竞争,监管风险,利率风险",
  "business_summary": "平安银行是一家领先的商业银行...",
  "strategic_keywords": "金融服务,互联网+,数字化转型",
  "last_refreshed": "2025-10-17T10:30:00"
}
```

#### 2. 获取详细 Profile（含分析数据）

```
GET /api/stock-profile/{symbol}/details
```

**返回示例**:
```json
{
  "symbol": "000001.SZ",
  "company_name": "平安银行",
  "industry": "银行",
  "sub_industry": "商业银行",
  "business_summary": "...",
  "strategic_keywords": "...",
  "products": "...",
  "competitors": "...",
  "risk_factors": "...",
  "last_refreshed": "2025-10-17T10:30:00",
  
  "analysis": {
    "profile_completeness": 85,
    "products_count": 3,
    "competitors_count": 3,
    "risk_factors_count": 3,
    "keywords_count": 3,
    "quality_score": 92,
    "data_sources": ["Company databases", "Public records"]
  },
  
  "industry_analysis": {
    "industry": "银行",
    "market_position": "Mid-market",
    "competition_level": 3
  }
}
```

#### 3. 刷新 Profile 数据

```
POST /api/stock-profile/{symbol}/refresh
```

**功能**: 触发 Profile 数据更新脚本，刷新 `last_refreshed` 时间戳

**返回**: 更新后的基本 Profile 信息

### 📊 数据模型

#### StockProfile 数据库模型

```python
class StockProfile(Base):
    __tablename__ = "stock_profiles"
    
    id: int
    symbol: str  # 股票代码，主键
    company_name: str  # 公司名称
    industry: str  # 行业
    sub_industry: str  # 子行业
    business_summary: str  # 业务介绍
    products: str  # 产品列表（逗号分隔）
    competitors: str  # 竞争对手（逗号分隔）
    risk_factors: str  # 风险因素（逗号分隔）
    strategic_keywords: str  # 战略关键词（逗号分隔）
    last_refreshed: datetime  # 最后更新时间
```

---

## 使用指南

### 🚀 快速开始

#### 1. 查看股票详情

1. 打开前端应用
2. 在股票列表中点击任何股票
3. 进入股票详情页面
4. 自动显示"相关文章"选项卡

#### 2. 切换到公司画像

1. 在股票详情页顶部点击"📊 公司画像"选项卡
2. 系统自动加载 Profile 数据
3. 查看完整的公司信息和分析

#### 3. 浏览详细分析

选择不同选项卡:

- **📋 概览**: 公司基本信息和关键指标
- **📊 数据分析**: 信息完整度、质量评分等
- **🏆 竞争分析**: 竞争对手、市场位置等

#### 4. 刷新数据

1. 在公司画像卡片或更新状态区域点击"🔄"刷新按钮
2. 等待数据更新完成
3. 查看新的 `last_refreshed` 时间戳

### 📱 响应式布局

#### 桌面端 (> 1024px)
- 多列网格布局
- 并排显示多个分析面板

#### 平板端 (768-1024px)
- 两列布局
- 某些面板分行显示

#### 手机端 (< 768px)
- 单列布局
- 全宽显示
- 信息卡片垂直堆叠

### 🔧 常见操作

#### 查看公司基本信息
1. 打开 Profile 详情
2. 在"概览"选项卡查看公司名、行业、业务介绍等

#### 评估数据质量
1. 切换到"数据分析"选项卡
2. 查看完整度圆图（0-100%）
3. 查看质量评分（50-100）

#### 对标竞争对手
1. 切换到"竞争分析"选项卡
2. 查看"市场对标"部分
3. 比较产品力、市场力、创新力等维度

### 💾 数据保存

系统自动保存以下数据:

- ✅ Profile 基本信息 → 数据库
- ✅ 最后更新时间 → 数据库
- ✅ 分析数据 → 动态计算（不存储）

---

## 数据分析

### 📊 分析维度

#### 1. 信息完整度

计算方式:
```
完整度 = 非空字段数 / 总字段数 × 100%
```

字段列表:
- company_name
- industry
- sub_industry
- business_summary
- products
- competitors
- risk_factors

#### 2. 质量评分

计算方式:
```
质量评分 = 50 + (完整度 / 2)
```

评级标准:
- 50-65: 🔴 基础信息不足
- 65-80: 🟡 信息一般
- 80-100: 🟢 信息完整

#### 3. 关键指标

| 指标 | 说明 | 取值来源 |
|------|------|--------|
| 产品数 | 主要产品数量 | products 字段（逗号分隔） |
| 竞争对手数 | 竞争对手数量 | competitors 字段 |
| 风险因素数 | 识别的风险因素数 | risk_factors 字段 |
| 战略关键词数 | 企业战略关键词 | strategic_keywords 字段 |

### 🎯 可视化图表

#### 1. 完整度圆形图

- 圆形进度图显示 0-100%
- 中心显示百分比数值
- 颜色编码：蓝色 (#3b82f6)
- 内环白色背景突出百分比

#### 2. 质量细项柱状图

四个维度：
- 📝 基本信息: 95%
- 📄 业务描述: 80%
- 🏷️ 产品列表: 70%
- ⚔️ 竞争分析: 65%

#### 3. 市场对标进度条

三个维度对比:
- 产品力：当前值 vs 行业平均值
- 市场力：当前值 vs 行业平均值
- 创新力：当前值 vs 行业平均值

---

## 故障排查

### ❌ 常见问题

#### 问题 1: Profile 数据显示为空或"暂无"

**可能原因**:
1. 该股票的 Profile 数据未创建
2. 数据库中没有对应记录
3. API 返回 404

**解决方案**:
```bash
# 检查数据库中是否存在该股票的 Profile
psql -U user -d database -c "SELECT * FROM stock_profiles WHERE symbol='000001.SZ';"

# 如果不存在，执行补充脚本
python backend/scripts/build_stock_profiles.py --apply

# 或使用快速补充
python backend/scripts/bulk_build_stock_profiles.py
```

#### 问题 2: 刷新按钮点击无反应

**可能原因**:
1. 刷新脚本不存在或权限不足
2. 后端 API 错误
3. 网络连接问题

**解决方案**:
1. 检查浏览器控制台错误
2. 检查网络请求: F12 → Network 标签
3. 检查后端日志: `docker logs backend`

#### 问题 3: 完整度显示不准确

**可能原因**:
1. 某些字段为空字符串或空格
2. 分隔符不统一（逗号/中文逗号）

**解决方案**:
```bash
# 检查字段值
python backend/scripts/check_profile_status.py

# 清理空值
python backend/scripts/cleanup_empty_summaries.py
```

#### 问题 4: 前端组件报错

**错误**: `TypeError: Cannot read property 'symbol' of null`

**原因**: Profile 组件加载时 profile 为 null

**解决**:
```tsx
{profile && (
  <div>
    {profile.symbol}
  </div>
)}
```

### 🔍 调试步骤

1. **检查浏览器控制台**:
   - F12 打开开发者工具
   - 查看 Console 标签中的错误

2. **检查网络请求**:
   - F12 → Network 标签
   - 查看 API 请求状态码
   - 检查响应数据

3. **检查后端日志**:
   ```bash
   docker logs aistock-backend -f
   ```

4. **测试 API**:
   ```bash
   curl http://localhost:8080/api/stock-profile/000001.SZ
   curl http://localhost:8080/api/stock-profile/000001.SZ/details
   ```

---

## 扩展建议

### 🎯 短期扩展（本周）

#### 1. 添加 LLM 生成摘要
```bash
python backend/scripts/enrich_stock_profiles_llm.py --apply
```

生成效果:
- 自动生成业务介绍
- 提取战略关键词
- 改进完整度到 90%+

#### 2. 添加 Tushare 数据
```bash
export TUSHARE_TOKEN="your_token"
python backend/scripts/build_stock_profiles.py --apply
```

补充字段:
- 补充行业信息
- 补充子行业
- 补充市场数据

#### 3. 前端图表增强
```tsx
// 使用 Recharts 或 ECharts 增强可视化
import { PieChart, Pie, Cell } from 'recharts'

<PieChart width={400} height={400}>
  <Pie
    data={completenessData}
    dataKey="value"
    startAngle={90}
    endAngle={450}
  >
    <Cell fill="#3b82f6" />
  </Pie>
</PieChart>
```

### 📊 中期扩展（本月）

#### 1. 财务指标集成
```json
{
  "market_cap": 1000000000,
  "pe_ratio": 12.5,
  "pb_ratio": 1.2,
  "roe": 0.15,
  "debt_ratio": 0.4
}
```

#### 2. 历史数据对比
- 显示完整度趋势
- 显示信息更新历史
- 版本对比

#### 3. 行业对标增强
- 真实行业数据集成
- 百分位排名
- 发展潜力评估

### 🚀 长期扩展（本季）

#### 1. AI 智能分析
- 使用 LLM 生成行业分析
- 自动识别关键风险
- 竞争优势识别

#### 2. 实时数据更新
- Websocket 实时推送
- 自动定时更新
- 增量数据同步

#### 3. 导出和分享
- PDF 报告生成
- Excel 数据导出
- 分享链接

---

## 📚 参考资源

### 相关文档

- [STOCK_PROFILE_SYSTEM.md](./docs/STOCK_PROFILE_SYSTEM.md) - Profile 系统详细说明
- [QUICK_START_GUIDE.md](./QUICK_START_GUIDE.md) - 快速开始指南
- [README.md](./README.md) - 项目主文档

### API 文档

- `/api/stock-profile/{symbol}` - 基本 Profile
- `/api/stock-profile/{symbol}/details` - 详细 Profile
- `/api/stock-profile/{symbol}/refresh` - 刷新 Profile

### 相关脚本

```
backend/scripts/
├── build_stock_profiles.py        # 多源数据补充
├── bulk_build_stock_profiles.py   # 快速批量补充
├── enrich_stock_profiles_llm.py   # LLM 增强
└── check_profile_status.py        # 状态检查
```

---

## 🎓 最佳实践

### ✅ 建议做法

1. **定期更新数据**: 每周运行一次 `bulk_build_stock_profiles.py`
2. **监控数据质量**: 定期运行 `check_profile_status.py`
3. **使用 LLM 补充**: 对关键股票运行 `enrich_stock_profiles_llm.py`
4. **记录更新时间**: 跟踪 `last_refreshed` 字段

### ❌ 避免做法

1. 不要直接修改数据库（使用脚本）
2. 不要频繁刷新（限制频率）
3. 不要遗漏错误处理
4. 不要硬编码 API 路由

---

## 📞 支持和反馈

### 遇到问题？

1. 查看本文档的"故障排查"部分
2. 检查后端日志
3. 查看浏览器控制台错误
4. 查看相关项目文档

### 想要改进？

欢迎提出功能建议和改进意见！

---

## ✅ 清单

### 前端集成清单

- [x] 创建 StockProfileCard 组件
- [x] 创建 StockProfileDetails 组件
- [x] 添加选项卡切换
- [x] 实现数据分析可视化
- [x] 添加响应式设计
- [x] 添加错误处理

### 后端集成清单

- [x] 创建/修改 Profile 模型
- [x] 实现基本 API 端点
- [x] 实现详细 API 端点
- [x] 添加数据分析计算
- [x] 添加错误处理

### 文档清单

- [x] API 文档
- [x] 组件文档
- [x] 故障排查指南
- [x] 集成指南（本文件）
- [x] 使用示例

---

**文档版本**: v1.0  
**最后更新**: 2025-10-17  
**下一次审查**: 2025-10-31  
**维护者**: AI Stock Analysis Team

