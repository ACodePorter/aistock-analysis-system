# 📰 后台新闻补充系统完整文档

## 目录
1. [系统概述](#系统概述)
2. [快速开始](#快速开始)
3. [工作流程](#工作流程)
4. [脚本详解](#脚本详解)
5. [参数配置](#参数配置)
6. [监控和日志](#监控和日志)
7. [故障排查](#故障排查)
8. [性能优化](#性能优化)

---

## 系统概述

### 设计目标
- **自动化**: 后台定时补充新闻数据，无需人工干预
- **质量优先**: 使用 LLM 进行相关性评分，过滤低质量文章
- **智能搜索**: 以公司名称为主要搜索条件，优于单纯股票代码
- **可控执行**: 支持干运行、指定股票、参数微调等多种运行模式
- **可追踪**: 完整的日志记录和统计信息

### 系统架构

```
┌─────────────────────────────────────────────────────────┐
│        后台新闻补充系统架构 (Background News System)    │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
    ┌───▼──┐          ┌───▼──┐          ┌──▼──┐
    │ 获取 │          │干运行 │          │应用 │
    │股票清│          │  模式 │          │模式 │
    │单   │          │      │          │     │
    └───┬──┘          └──────┘          └──┬──┘
        │                                   │
        └───────────────┬───────────────────┘
                        │ 每支股票处理
        ┌───────────────▼──────────────────┐
        │   第1步: 搜索阶段 (Search)       │
        │  - 以公司名称搜索 (主力)          │
        │  - 以股票代码搜索 (备选)          │
        │  - 跨多个数据源检索               │
        └───────────────┬──────────────────┘
                        │ 搜索结果
        ┌───────────────▼──────────────────┐
        │   第2步: 爬取阶段 (Crawl)        │
        │  - 获取文章完整内容               │
        │  - 提取HTML/文本                 │
        │  - 处理编码问题                   │
        └───────────────┬──────────────────┘
                        │ 文章内容
        ┌───────────────▼──────────────────┐
        │   第3步: 去重阶段 (Dedup)        │
        │  - 检查URL是否已存在              │
        │  - 跳过重复文章                   │
        │  - 避免数据库冗余                 │
        └───────────────┬──────────────────┘
                        │ 新文章
        ┌───────────────▼──────────────────┐
        │   第4步: 分析阶段 (LLM Analyze)  │
        │  - 提取关键词                     │
        │  - 计算相关性评分                 │
        │  - 生成摘要                       │
        │  - 判断情感倾向                   │
        └───────────────┬──────────────────┘
                        │ 相关性评分
        ┌───────────────▼──────────────────┐
        │   第5步: 过滤阶段 (Filter)       │
        │  - 比较与阈值                     │
        │  - relevance_score >= 0.7        │
        │  - 保留高质量文章                 │
        └───────────────┬──────────────────┘
                        │ 高质量文章
        ┌───────────────▼──────────────────┐
        │   第6步: 保存阶段 (Save)         │
        │  - 写入news_articles表            │
        │  - 关联stock_pools表              │
        │  - 更新计数器                     │
        └───────────────┬──────────────────┘
                        │
        ┌───────────────▼──────────────────┐
        │      生成执行报告和统计           │
        │  - articles_saved: 保存文章数     │
        │  - duplicates_skipped: 去重      │
        │  - low_relevance_skipped: 过滤   │
        │  - errors: 错误数                │
        └──────────────────────────────────┘
```

### 核心概念

#### 相关性评分 (Relevance Score)

LLM 对每篇文章计算一个 0-1 的相关性评分：

| 分数范围 | 含义 | 示例 |
|---------|------|------|
| 0.9-1.0 | 完全相关 | "天孚通信获新订单" - 直接关于该公司 |
| 0.7-0.9 | 高度相关 | "光学芯片行业发展，天孚为主要参与者" - 相关行业发展 |
| 0.5-0.7 | 中等相关 | "5G技术进展" - 涉及间接相关领域 |
| 0.3-0.5 | 低度相关 | "总体经济形势" - 宏观无关信息 |
| 0.0-0.3 | 不相关 | "完全无关话题" - 明确无关 |

**默认阈值**: 0.7（保留高质量文章）

#### 搜索策略

1. **主力搜索**: 以公司名称为主
   - 优势：更精准匹配公司信息
   - 示例：搜索"天孚通信"而非"300394.SZ"

2. **备选搜索**: 以股票代码为辅
   - 作用：补充不被直接提及的相关信息
   - 使用场景：新闻中未明确提公司名

3. **多源检索**: 跨多个新闻源
   - 新浪财经、东方财富、同花顺等
   - 提高覆盖率和多样性

---

## 快速开始

### 安装依赖

脚本使用的主要依赖已在项目中配置：

```bash
# 检查依赖是否完整
pip list | grep -E "sqlalchemy|requests|beautifulsoup"

# 如需重新安装
pip install sqlalchemy requests beautifulsoup4 lxml
```

### 最简单的用法

#### 1. 干运行（查看计划，不修改数据库）

```bash
cd d:\workspace\mpj\aistock-full-project
python backend/scripts/news_supplement_bg.py --dry-run
```

**输出示例**:
```
======================================================================
📰 后台新闻补充系统
======================================================================
🎯 计划处理: 5 支股票
📊 批量大小: 5
⏱️  相关性阈值: 0.7

🔍 【干运行模式】- 仅显示计划，不实际执行
----------------------------------------------------------------------
300251.SZ    光线传媒
000829.SZ    天音控股
300394.SZ    天孚通信
002649.SZ    博彦科技
002594.SZ    比亚迪

💡 提示: 使用 --apply 标志来实际执行补充
```

#### 2. 实际执行（处理所有监控股票）

```bash
python backend/scripts/news_supplement_bg.py --apply
```

**输出示例**:
```
======================================================================
📰 后台新闻补充系统
======================================================================
🎯 计划处理: 5 支股票
📊 批量大小: 5
⏱️  相关性阈值: 0.7

🔄 执行模式 - 实际处理并保存数据
----------------------------------------------------------------------
[1/5] 处理 300251.SZ (光线传媒)...
  🔍 搜索 "光线传媒" ... 找到 3 篇
  ⏳ 爬取内容 ... 3 篇成功
  ✅ 去重 ... 保留 3 篇
  🤖 LLM 分析 ... 相关性评分完成
  💾 保存 ... 2 篇高质量文章 (relevance >= 0.7)
  ⏭️ 跳过 1 篇 (relevance = 0.45)

[2/5] 处理 000829.SZ (天音控股)...
  ...

======================================================================
📊 执行统计
======================================================================
✅ 处理完成
  搜索执行次数: 10
  查询文章总数: 25
  爬取成功: 22
  去重后保留: 20
  LLM 分析完成: 20
  最终保存: 12 篇新文章
  跳过低相关性: 8 篇
  发生错误: 0
```

#### 3. 处理指定股票

```bash
# 单个股票
python backend/scripts/news_supplement_bg.py --apply --stocks 300394.SZ

# 多个股票
python backend/scripts/news_supplement_bg.py --apply --stocks 300394.SZ,002594.SZ,300251.SZ
```

#### 4. 自定义参数

```bash
# 降低相关性阈值，接受更多文章
python backend/scripts/news_supplement_bg.py --apply \
  --relevance-threshold 0.65

# 增加每支股票的文章数量
python backend/scripts/news_supplement_bg.py --apply \
  --max-articles-per-stock 20

# 增加搜索时间范围
python backend/scripts/news_supplement_bg.py --apply \
  --search-days 60

# 减少批处理大小，降低内存占用
python backend/scripts/news_supplement_bg.py --apply \
  --batch-size 3

# 增加请求延迟，避免被限流
python backend/scripts/news_supplement_bg.py --apply \
  --rate-limit-delay 2.0
```

---

## 工作流程

### 详细执行流程

#### 第1步: 股票获取与初始化

```python
# 从 watchlist 或 stock_pools 获取目标股票
symbols = get_monitored_stocks()
# 返回: ['300251.SZ', '000829.SZ', '300394.SZ', ...]

# 转换为公司信息对象
for symbol in symbols:
    stock_info = get_stock_info(symbol)  # {'symbol': '300251.SZ', 'name': '光线传媒'}
    process_stock(stock_info)
```

#### 第2步: 信息搜索

```python
# 主力搜索：公司名称
query_primary = stock_info['name']  # "光线传媒"
results_primary = search_news(query_primary)  # 返回 [article1, article2, ...]

# 备选搜索：股票代码
query_fallback = stock_info['symbol']  # "300251.SZ"
results_fallback = search_news(query_fallback)

# 合并结果
all_results = deduplicate_search_results(results_primary + results_fallback)
```

#### 第3步: 内容爬取

```python
for article in all_results:
    try:
        # 爬取 article.url 的内容
        content = crawl_article_content(article.url)
        # 更新 article.content = content
        article.content = content
    except Exception as e:
        # 记录失败
        log_error(f"爬取失败: {article.url}, 原因: {e}")
        articles_failed += 1
```

#### 第4步: 去重检查

```python
for article in articles_with_content:
    # 检查 URL 是否已存在
    if article_exists_by_url(article.url):
        # 跳过重复
        duplicates_skipped += 1
        continue
    
    # 保留新文章
    unique_articles.append(article)
```

#### 第5步: LLM 质量分析

```python
for article in unique_articles:
    # 调用 LLM 进行分析
    analysis = llm_analyze_article(
        article.content,
        symbol=stock_info['symbol'],
        company_name=stock_info['name']
    )
    # 返回结构:
    # {
    #   'relevance_score': 0.85,  # 0-1
    #   'keywords': ['芯片', '光学', '订单'],
    #   'summary': '...',
    #   'sentiment': 'positive'
    # }
    
    article.analysis = analysis
```

#### 第6步: 相关性过滤

```python
THRESHOLD = 0.7  # 参数可配置

for article in analyzed_articles:
    if article.analysis['relevance_score'] >= THRESHOLD:
        # 保留高质量文章
        final_articles.append(article)
    else:
        # 跳过低相关性
        low_relevance_skipped += 1
        log_info(f"跳过低相关性文章: {article.title} (score={article.analysis['relevance_score']})")
```

#### 第7步: 数据保存

```python
for article in final_articles:
    # 创建数据库记录
    db_article = NewsArticle(
        url=article.url,
        title=article.title,
        summary=article.analysis['summary'],
        content=article.content,
        source=article.source,
        published_at=article.published_at,
        scraped_at=datetime.now(),
        related_stocks=[stock_info['symbol']],
        keywords=article.analysis['keywords'],
        sentiment=article.analysis['sentiment']
    )
    
    # 保存到数据库
    session.add(db_article)
    session.commit()
    
    articles_saved += 1
```

### 错误处理

系统在各个阶段都有错误处理：

```
搜索失败 ────► 记录错误，继续下一支股票
                ↓
爬取失败 ────► 跳过该文章，继续下一篇
                ↓
LLM超时 ────► 重试 3 次，仍失败则跳过
                ↓
数据库错误 ───► 回滚事务，记录详情
```

---

## 脚本详解

### `news_supplement_bg.py` - 主脚本

#### 核心类：`NewsSupplementBackgroundTask`

```python
class NewsSupplementBackgroundTask:
    """后台新闻补充任务主类"""
    
    def __init__(self, config=None):
        """初始化，可传入自定义配置"""
        self.config = config or self.get_default_config()
    
    async def run_supplement(self, dry_run=True, stock_symbols=None):
        """
        主执行方法
        
        参数:
          dry_run: True=干运行，False=实际执行
          stock_symbols: None=处理所有，或指定符号列表 ['300251.SZ', ...]
        
        返回:
          statistics: {'articles_saved': 12, 'duplicates_skipped': 3, ...}
        """
    
    async def _process_stock(self, stock):
        """处理单个股票的完整流程"""
    
    async def _search_news(self, query, symbol):
        """搜索新闻"""
    
    async def _crawl_article(self, article):
        """爬取文章内容"""
    
    async def _analyze_article(self, article, symbol, company_name):
        """LLM 分析文章"""
    
    async def _save_article(self, article, analysis, symbol):
        """保存到数据库"""
```

#### 使用示例

```python
# 创建任务实例
task = NewsSupplementBackgroundTask()

# 干运行
await task.run_supplement(dry_run=True)

# 实际执行
stats = await task.run_supplement(dry_run=False)
print(f"已保存 {stats['articles_saved']} 篇文章")

# 指定股票
await task.run_supplement(
    dry_run=False,
    stock_symbols=['300251.SZ', '002594.SZ']
)
```

### `schedule_news_supplement.py` - 定时任务脚本

#### 支持的运行模式

```bash
# 模式1: 每日全量补充（处理所有股票）
python backend/scripts/schedule_news_supplement.py --daily-full
# 推荐时间：凌晨 2 点（低峰）

# 模式2: 每日增量补充（仅处理优先级高的股票）
python backend/scripts/schedule_news_supplement.py --daily-increment
# 推荐时间：上午 11 点（市场交易中期）

# 模式3: 热点快速补充（快速响应热点股票）
python backend/scripts/schedule_news_supplement.py --hot-stocks
# 推荐时间：每 4 小时运行一次
```

#### Crontab 集成

```bash
# 编辑 crontab
crontab -e

# 添加下列任务
# 凌晨 2 点 - 全量补充所有股票
0 2 * * * cd /path/to/project && python backend/scripts/schedule_news_supplement.py --daily-full >> /var/log/news_supplement.log 2>&1

# 上午 11 点 - 增量补充优先级股票
0 11 * * * cd /path/to/project && python backend/scripts/schedule_news_supplement.py --daily-increment >> /var/log/news_supplement.log 2>&1

# 每 4 小时 - 热点补充
0 */4 * * * cd /path/to/project && python backend/scripts/schedule_news_supplement.py --hot-stocks >> /var/log/news_supplement.log 2>&1
```

#### APScheduler 集成

如需在 Python 应用中集成定时任务：

```python
from apscheduler.schedulers.background import BackgroundScheduler
from backend.scripts.schedule_news_supplement import NewsSupplementScheduler

scheduler = BackgroundScheduler()
supplement_scheduler = NewsSupplementScheduler()

# 添加定时任务
scheduler.add_job(
    supplement_scheduler.run_daily_full,
    'cron', hour=2, minute=0,
    id='daily_full_supplement'
)

scheduler.add_job(
    supplement_scheduler.run_daily_increment,
    'cron', hour=11, minute=0,
    id='daily_increment_supplement'
)

scheduler.add_job(
    supplement_scheduler.run_hot_stocks,
    'cron', hour='*/4',
    id='hot_stocks_supplement'
)

scheduler.start()
```

---

## 参数配置

### 命令行参数

| 参数 | 默认值 | 类型 | 说明 |
|------|--------|------|------|
| `--dry-run` | True | bool | 干运行模式，不修改数据库 |
| `--apply` | False | bool | 实际执行模式 |
| `--stocks` | None | str | 指定处理的股票，逗号分隔。如: `300251.SZ,002594.SZ` |
| `--batch-size` | 5 | int | 每批处理的股票数量 |
| `--max-articles-per-stock` | 10 | int | 每支股票最多补充的文章数 |
| `--search-days` | 30 | int | 搜索的时间范围（天数） |
| `--relevance-threshold` | 0.7 | float | 相关性评分阈值，0-1 之间 |
| `--rate-limit-delay` | 0.5 | float | 请求间延迟（秒），避免限流 |

### 高级配置

在脚本中直接修改配置：

```python
# backend/scripts/news_supplement_bg.py

config = {
    'batch_size': 5,
    'max_articles_per_stock': 10,
    'search_days': 30,
    'relevance_threshold': 0.7,
    'rate_limit_delay': 0.5,
    
    # 搜索源配置
    'search_sources': [
        'sina',
        'eastmoney',
        'sohu',
        'xueqiu'
    ],
    
    # LLM 配置
    'llm_model': 'gpt-3.5-turbo',  # 或其他模型
    'llm_timeout': 30,  # 秒
    'llm_retries': 3,
    
    # 日志配置
    'log_level': 'INFO',
    'log_file': 'logs/news_supplement.log'
}

task = NewsSupplementBackgroundTask(config)
```

---

## 监控和日志

### 查看日志

```bash
# 实时查看最新日志
tail -f logs/news_supplement.log

# 查看最近的 100 行
tail -100 logs/news_supplement.log

# 搜索错误
grep ERROR logs/news_supplement.log

# 查看特定日期的日志
grep "2025-10-17" logs/news_supplement.log

# 统计保存的文章数
grep "articles_saved" logs/news_supplement.log
```

### 日志示例

```
2025-10-17 02:00:01 [INFO] 启动后台新闻补充系统
2025-10-17 02:00:01 [INFO] 配置: batch_size=5, threshold=0.7
2025-10-17 02:00:02 [INFO] 获取监控股票列表: 5 支
2025-10-17 02:00:03 [INFO] [1/5] 处理 300251.SZ (光线传媒)
2025-10-17 02:00:05 [INFO]   搜索 "光线传媒" 找到 3 篇
2025-10-17 02:00:10 [INFO]   爬取完成: 3 篇
2025-10-17 02:00:12 [INFO]   去重检查: 保留 3 篇
2025-10-17 02:00:25 [INFO]   LLM 分析完成，相关性评分 [0.92, 0.68, 0.45]
2025-10-17 02:00:26 [INFO]   保存 2 篇 (relevance >= 0.7)
2025-10-17 02:00:35 [INFO] [2/5] 处理 000829.SZ ...
2025-10-17 02:15:00 [INFO] 处理完成
2025-10-17 02:15:01 [INFO] 统计: 保存 12 篇, 跳过 3 篇, 错误 0 个
```

### 监控指标

| 指标 | 含义 | 正常范围 |
|------|------|---------|
| `articles_saved` | 本次运行保存的新文章数 | > 0 |
| `duplicates_skipped` | 去重跳过的数量 | 0-50% |
| `low_relevance_skipped` | 低相关性跳过的数量 | 10-40% |
| `errors` | 处理中发生的错误数 | = 0 |
| `avg_relevance_score` | 平均相关性评分 | 0.7-0.95 |
| `execution_time` | 总执行时间 | 5-60 分钟 |

---

## 故障排查

### 问题1: "相关性不足"的文章太多

**表现**: 
```
低相关性跳过: 18 篇
保存文章: 2 篇
```

**原因**: 
- LLM 评分过严格
- 相关性阈值设置过高

**解决方案**:
```bash
# 降低阈值到 0.65
python backend/scripts/news_supplement_bg.py --apply \
  --relevance-threshold 0.65

# 或更激进地设置为 0.6
python backend/scripts/news_supplement_bg.py --apply \
  --relevance-threshold 0.6
```

### 问题2: LLM 调用超时或失败

**表现**:
```
❌ LLM 分析失败: timeout
❌ LLM 分析失败: rate_limit_exceeded
```

**原因**:
- LLM API 超时
- 被限流（调用过于频繁）

**解决方案**:
```bash
# 方案1: 增加延迟
python backend/scripts/news_supplement_bg.py --apply \
  --rate-limit-delay 2.0

# 方案2: 减少批大小，降低并发
python backend/scripts/news_supplement_bg.py --apply \
  --batch-size 2

# 方案3: 选择低峰时间运行
# 编辑 crontab，改为凌晨 3-4 点
```

### 问题3: 爬虫被限流

**表现**:
```
❌ HTTP 429: Too Many Requests
❌ HTTP 403: Forbidden
```

**原因**:
- 请求频率过高
- 未设置 User-Agent
- 被网站识别为爬虫

**解决方案**:
```bash
# 增加延迟到 3 秒
python backend/scripts/news_supplement_bg.py --apply \
  --rate-limit-delay 3.0

# 代码中添加随机延迟
# 在 backend/scripts/news_supplement_bg.py 修改:
import random
await asyncio.sleep(random.uniform(1, 3))  # 随机延迟 1-3 秒

# 或减少每支股票的文章数
python backend/scripts/news_supplement_bg.py --apply \
  --max-articles-per-stock 5
```

### 问题4: 数据库连接错误

**表现**:
```
❌ psycopg2.OperationalError: could not translate host name
❌ psycopg2.OperationalError: connection refused
```

**原因**:
- 数据库未启动
- 连接信息不正确

**解决方案**:
```bash
# 检查 PostgreSQL 是否运行
psql -h localhost -U ai_stock -d aistock -c "SELECT 1"

# 或启动 Docker 容器
docker-compose up -d postgres

# 检查 .env 文件中的数据库配置
cat .env | grep DATABASE
```

### 问题5: 内存占用过高

**表现**:
```
进程被 OOM killer 杀死
内存占用超过可用内存
```

**原因**:
- batch_size 过大
- 同时处理太多文章

**解决方案**:
```bash
# 减少批大小
python backend/scripts/news_supplement_bg.py --apply \
  --batch-size 2 \
  --max-articles-per-stock 5
```

---

## 性能优化

### 优化1: 调整批处理大小

```bash
# 小 batch: 内存占用低，但执行慢
python backend/scripts/news_supplement_bg.py --apply --batch-size 2

# 中 batch: 平衡性能和内存（推荐）
python backend/scripts/news_supplement_bg.py --apply --batch-size 5

# 大 batch: 执行快，但内存占用高（需谨慎）
python backend/scripts/news_supplement_bg.py --apply --batch-size 10
```

### 优化2: 调整搜索范围

```bash
# 搜索最近 7 天（快速）
python backend/scripts/news_supplement_bg.py --apply --search-days 7

# 搜索最近 30 天（平衡）- 默认
python backend/scripts/news_supplement_bg.py --apply --search-days 30

# 搜索最近 90 天（全面但慢）
python backend/scripts/news_supplement_bg.py --apply --search-days 90
```

### 优化3: 增量补充策略

```bash
# 仅补充高优先级股票（增量）
python backend/scripts/schedule_news_supplement.py --daily-increment

# 理由：
# - 避免处理全部 3000+ 股票
# - 节省时间和资源
# - 优先关注热点股票
# - 定期进行全量补充（凌晨 2 点）
```

### 优化4: 异步并发

脚本已使用 asyncio 异步处理，自动优化网络 I/O 性能。

```python
# 同时发送 5 个爬取请求
tasks = [
    crawl_article(article1),
    crawl_article(article2),
    crawl_article(article3),
    crawl_article(article4),
    crawl_article(article5),
]
results = await asyncio.gather(*tasks)
```

### 优化5: 缓存策略

系统自动缓存：
- URL 去重信息（避免重复爬取）
- LLM 分析结果（相同文本复用分析）
- 公司信息（避免重复查询）

---

## 最佳实践

### ✅ 推荐做法

1. **定期运行**
   ```bash
   # 每日 2 点全量补充
   0 2 * * * cd /project && python backend/scripts/schedule_news_supplement.py --daily-full
   
   # 每日 11 点增量补充
   0 11 * * * cd /project && python backend/scripts/schedule_news_supplement.py --daily-increment
   ```

2. **监控日志**
   ```bash
   # 定期查看统计
   grep "统计:" logs/news_supplement.log | tail -10
   ```

3. **备份数据**
   ```bash
   # 定期备份数据库
   pg_dump -h localhost -U ai_stock aistock > backup_$(date +%Y%m%d).sql
   ```

### ❌ 不推荐做法

1. **频繁全量运行**
   - ❌ 每小时运行一次全量补充
   - ✅ 每日 1-2 次，配合增量模式

2. **不合理的参数**
   - ❌ `--batch-size 100` (内存爆炸)
   - ✅ `--batch-size 5-10` (平衡性能)

3. **忽视错误日志**
   - ❌ 不查看日志，默认一切正常
   - ✅ 定期检查错误，及时调整

---

## 常见问题 (FAQ)

**Q: 需要多长时间补充一遍所有股票？**
A: 取决于股票数量和网络情况。通常：
- 100 支股票：10-15 分钟
- 500 支股票：1-2 小时
- 3000 支股票：6-12 小时（建议分批或在低峰时段运行）

**Q: 相关性阈值应该设多高？**
A: 推荐 0.7（默认值）。根据需求调整：
- 0.8-1.0：仅保留高度相关的文章（严格）
- 0.7-0.8：保留高度和中度相关文章（推荐）
- 0.6-0.7：包含一些边界案例（宽松）
- < 0.6：包含大量弱相关内容（不推荐）

**Q: 如何处理特定股票的爬虫限流？**
A: 
```bash
# 仅处理该股票，增加延迟
python backend/scripts/news_supplement_bg.py --apply \
  --stocks 300251.SZ \
  --rate-limit-delay 3.0
```

**Q: 是否可以手动取消执行？**
A: 是。按 `Ctrl+C` 中断。数据库事务会自动回滚，已保存的数据保留。

---

## 相关命令速查

```bash
# 快速查看系统状态
python backend/scripts/check_profile_status.py

# 分析数据质量
python backend/scripts/analyze_empty_summaries.py

# 清理空摘要文章
python backend/scripts/cleanup_empty_summaries.py --apply

# 干运行测试
python backend/scripts/news_supplement_bg.py --dry-run

# 实际执行补充
python backend/scripts/news_supplement_bg.py --apply

# 查看实时日志
tail -f logs/news_supplement.log

# 搜索错误
grep ERROR logs/news_supplement.log

# 统计已保存文章
grep "articles_saved" logs/news_supplement.log | tail -5
```

---

**最后更新**: 2025-10-17  
**系统版本**: 1.0  
**文档版本**: 2.0
