# 后台新闻补充系统

## 概述

本系统实现了一套完整的、定时的新闻补充流程，用于持续提升系统中新闻数据的质量和覆盖面。

### 核心特性

1. **股票名称优先搜索** - 以公司名称为主要搜索条件，而非仅依赖股票代码
2. **LLM 质量检查** - 使用大语言模型检查新闻与股票的相关性，过滤无关新闻
3. **自动去重** - 基于 URL 的去重机制，避免重复保存
4. **限流机制** - 可配置的速率限制，避免过载或被限流
5. **灵活调度** - 支持全量补充、增量补充、热点补充等多种模式

## 架构

```
后台新闻补充流程
│
├─ 1. 获取股票清单
│  └─ 从 watchlist 表获取所有被监控的股票
│
├─ 2. 批量处理每支股票
│  └─ 批大小: batch_size (默认5)
│     └─ 按 rate_limit_delay 间隔处理
│
├─ 3. 搜索新闻
│  ├─ 第一阶段: 使用公司名称搜索
│  └─ 第二阶段: 使用股票代码搜索（备选）
│
├─ 4. 爬取文章内容
│  ├─ 批量爬取 URL
│  ├─ 提取文章标题、内容、发布时间等
│  └─ 错误处理和重试机制
│
├─ 5. 内容去重
│  ├─ 检查 URL 是否已在数据库中
│  └─ 跳过重复内容
│
├─ 6. LLM 分析
│  ├─ 计算文章与股票的相关性评分 (relevance_score)
│  ├─ 检测文章主题和关键词
│  ├─ 分析情感倾向
│  └─ 质量评分
│
├─ 7. 质量筛选
│  └─ 只保留 relevance_score >= threshold (默认0.7) 的文章
│
└─ 8. 数据库持久化
   ├─ 保存到 PostgreSQL (news_articles)
   ├─ 关联到正确的股票符号
   └─ 记录元数据（来源、发布时间等）
```

## 使用方式

### 1. 命令行运行

#### 干运行模式（查看计划不执行）
```bash
python backend/scripts/news_supplement_bg.py --dry-run
```

#### 实际执行补充
```bash
python backend/scripts/news_supplement_bg.py --apply
```

#### 处理特定股票
```bash
python backend/scripts/news_supplement_bg.py --apply --stocks 300394.SZ,600519.SH
```

#### 自定义参数
```bash
python backend/scripts/news_supplement_bg.py --apply \
  --batch-size 10 \
  --max-articles 20 \
  --search-days 60 \
  --relevance-threshold 0.65
```

### 2. 定时任务运行

#### 通过 schedule_news_supplement.py

```bash
# 每日全量补充（所有股票）
python backend/scripts/schedule_news_supplement.py --daily-full

# 每日增量补充（高优先级股票）
python backend/scripts/schedule_news_supplement.py --daily-increment

# 热点股票快速补充（每4小时）
python backend/scripts/schedule_news_supplement.py --hot-stocks
```

#### Crontab 配置示例

```crontab
# 凌晨2点运行全量补充（所有股票）
0 2 * * * cd /path/to/project && python backend/scripts/schedule_news_supplement.py --daily-full 2>&1 | tee -a logs/cron.log

# 上午11点运行增量补充（高优先级股票）
0 11 * * * cd /path/to/project && python backend/scripts/schedule_news_supplement.py --daily-increment 2>&1 | tee -a logs/cron.log

# 每4小时运行热点补充
0 */4 * * * cd /path/to/project && python backend/scripts/schedule_news_supplement.py --hot-stocks 2>&1 | tee -a logs/cron.log
```

#### Python 中集成定时任务

使用 APScheduler（如果已集成）：

```python
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio
from news_supplement_bg import NewsSupplementBackgroundTask

scheduler = BackgroundScheduler()

# 每日全量补充
def run_daily_full():
    task = NewsSupplementBackgroundTask()
    asyncio.run(task.run_supplement(dry_run=False))

scheduler.add_job(run_daily_full, 'cron', hour=2, minute=0)
scheduler.start()
```

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `batch_size` | 5 | 每批处理的股票数量 |
| `max_articles_per_stock` | 10 | 每支股票最多补充的文章数 |
| `search_days` | 30 | 搜索的时间范围（天数） |
| `relevance_threshold` | 0.7 | 相关性评分阈值（0.0-1.0） |
| `rate_limit_delay` | 0.5 | 两次请求间的延迟（秒） |
| `max_retries` | 3 | 失败重试次数 |

## 工作流程示例

### 场景：补充 300394.SZ 的新闻

1. **获取股票信息**
   - 股票代码: 300394.SZ
   - 公司名称: 天孚通信

2. **搜索新闻**
   - 第一轮: 搜索 "天孚通信"
     - 找到 20 条搜索结果
   - 第二轮: 搜索 "300394"（备选）
     - 找到 15 条搜索结果

3. **爬取文章**
   - 从搜索结果中选择 10 篇（max_articles_per_stock）
   - 爬取每篇文章的完整内容
   - 成功爬取: 8 篇

4. **去重检查**
   - 检查 URL 是否已在数据库中
   - 跳过: 2 篇（重复）
   - 保留: 6 篇

5. **LLM 分析**
   - 对每篇文章进行分析
   - 计算 relevance_score
     - 文章 A: 0.92 ✅ （保留）
     - 文章 B: 0.45 ❌ （低于阈值）
     - 文章 C: 0.78 ✅ （保留）
     - ...

6. **质量筛选**
   - 相关性 >= 0.7: 4 篇
   - 相关性 < 0.7: 2 篇（跳过）

7. **保存到数据库**
   - 最终保存: 4 篇新闻文章
   - 关联股票: 300394.SZ
   - 记录元数据

## 统计输出示例

```
======================================================================
📊 补充结果摘要
======================================================================
⏱️  耗时: 45.3 秒

📈 统计信息:
  处理股票数: 5
  执行搜索: 10 次
  发现文章: 150 篇
  成功爬取: 120 篇
  LLM 分析: 120 篇
  最终保存: 85 篇

⚠️  处理情况:
  去重跳过: 20 篇
  相关性不足: 15 篇
  处理错误: 0 次
======================================================================
```

## 相关性评分说明

LLM 在分析文章时会计算一个相关性评分（0.0-1.0）：

| 评分范围 | 说明 | 决策 |
|---------|------|------|
| 0.9-1.0 | 完全相关 | ✅ 保留 |
| 0.7-0.9 | 高度相关 | ✅ 保留 |
| 0.5-0.7 | 中等相关 | ⚠️ 根据阈值决定 |
| 0.3-0.5 | 低度相关 | ❌ 通常跳过 |
| 0.0-0.3 | 不相关 | ❌ 跳过 |

### 评分示例

```
文章: "天孚通信与思科合作发布光学芯片方案"
- 标题相关性: 高 ✅
- 内容相关性: 完全匹配 ✅
- 实体识别: 公司名、产品线一致 ✅
→ relevance_score: 0.95 ✅ 保留

文章: "5G 技术发展前景展望"
- 标题相关性: 低 ❌
- 内容相关性: 天孚通信未在文章中直接出现 ❌
- 实体识别: 无明确关联 ❌
→ relevance_score: 0.35 ❌ 跳过
```

## 监控和日志

### 日志文件位置
```
logs/news_supplement.log
```

### 日志级别
- INFO: 任务进度、统计信息
- WARNING: 轻微错误、跳过事项
- ERROR: 严重错误、异常停止

### 查看日志
```bash
tail -f logs/news_supplement.log
```

## 故障排查

### 问题1: "相关性不足"的文章过多

**原因**: 相关性阈值设置过高

**解决方案**:
```bash
python backend/scripts/news_supplement_bg.py --apply \
  --relevance-threshold 0.65
```

### 问题2: LLM 调用超时

**原因**: LLM 服务响应慢或过载

**解决方案**:
- 减少 batch_size
- 增加 rate_limit_delay
- 检查 LLM 服务状态

### 问题3: 被搜索引擎限流

**原因**: 请求过于频繁

**解决方案**:
```bash
python backend/scripts/news_supplement_bg.py --apply \
  --rate-limit-delay 2.0  # 增加延迟到2秒
```

## 性能优化建议

1. **调整批大小**
   - 大批大小 → 更快但更吃内存
   - 小批大小 → 更慢但更稳定

2. **增量补充**
   - 而不是总是全量补充
   - 定期清理老旧数据

3. **优先级管理**
   - 热点股票更频繁更新
   - 冷门股票定期更新

4. **并行处理**
   - 使用异步 IO
   - 利用多进程处理

## 与现有系统的集成

### API 端点自动过滤

所有新闻返回接口已自动过滤摘要为空的文章：

- `/api/news/stock/{symbol}`
- `/api/news/company_enriched/{symbol}`
- `/api/news/articles`
- `/api/news/stocks`

### 不需要额外修改

现有业务逻辑无需修改，系统自动享受新闻质量提升的好处。

## 下一步计划

- [ ] 集成高级 LLM 模型提升相关性判断准确度
- [ ] 支持自定义搜索策略（按行业、按主题等）
- [ ] 实现 A/B 测试框架，优化相关性阈值
- [ ] 构建新闻热点检测系统
- [ ] 添加用户反馈机制改进模型

## 相关文件

- `backend/scripts/news_supplement_bg.py` - 主补充脚本
- `backend/scripts/schedule_news_supplement.py` - 定时任务配置
- `backend/scripts/cleanup_empty_summaries.py` - 清理空摘要脚本
- `backend/scripts/analyze_empty_summaries.py` - 分析空摘要脚本
- `backend/app/routers/news.py` - API 路由（已集成过滤逻辑）

## 支持

如有问题，请参考日志文件或检查相关配置。
