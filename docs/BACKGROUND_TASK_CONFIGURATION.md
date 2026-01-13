# 🚀 后台 Profile 更新任务 - 完整配置指南

## 📋 概述

后端已经实现了**自动后台 Profile 更新任务**，可以：
- ✅ 定时自动更新所有 2990 个新闻相关股票的 Profile 数据
- ✅ 无需手动干预，应用启动即运行
- ✅ 每周一 02:00 自动执行一次
- ✅ 记录详细的执行日志和统计信息

---

## 🏗️ 架构设计

### 核心组件

```
FastAPI 应用
    ↓
启动事件 (on_event "startup")
    ↓
init_task_scheduler()
    ↓
ScheduledTaskManager (后台任务管理器)
    ↓
APScheduler (定时任务调度器)
    ↓
每周一 02:00 执行 update_all_stock_profiles()
    ↓
遍历所有 2990 个股票
    ↓
调用 StockProfileEnricher 进行 LLM 分析
    ↓
更新数据库 + 记录日志
```

---

## 🔧 当前配置

### 文件位置

| 文件 | 位置 | 功能 |
|------|------|------|
| **task_scheduler.py** | `backend/app/task_scheduler.py` | 任务管理器实现 |
| **初始化代码** | `backend/app/main.py` 第 1095-1120 行 | 应用启动/关闭时的初始化 |
| **enricher** | `backend/app/stock_profile_enrichment.py` | LLM 分析引擎 |

### 调度规则

**当前设置**:
```python
CronTrigger(day_of_week=0, hour=2, minute=0)  # 每周一 02:00
```

| 参数 | 值 | 含义 |
|------|-----|------|
| day_of_week | 0 | 周一 (0=周一, 6=周日) |
| hour | 2 | 凌晨 2:00 |
| minute | 0 | 整点执行 |

---

## 📊 工作流程

### Step 1: 股票收集

```python
从 NewsArticle.related_stocks 字段中提取所有唯一股票代码
↓
得到 ~2990 个不同的股票符号
↓
计算每个股票的 Profile 完成度 (0-100%)
```

### Step 2: 优先级排序

```python
按完成度从低到高排序
↓
完成度 < 50% 的股票优先处理 (未完成)
↓
完成度 ≥ 50% 的股票后处理 (已完成)
```

### Step 3: 批量更新

```python
逐个调用 StockProfileEnricher 进行 LLM 分析
    ↓
每个股票间隔 2 秒（防止被 ban）
    ↓
更新完成时记录 last_updated_at 时间戳
    ↓
错误不中断，继续处理下一个股票
```

### Step 4: 日志记录

```
每个步骤都会记录详细日志：
- 📊 开始任务时的统计信息
- 🔄 每只股票的处理进度
- ✅/❌ 每只股票的成功/失败状态
- 📈 任务完成后的执行报告
```

---

## 🎯 使用场景

### 场景 1: 自动定时更新（推荐）

✅ **默认行为**

```
应用启动时自动启动任务调度器
↓
每周一 02:00 自动执行一次
↓
更新所有不完整的 Profile 数据
↓
完全无需手动干预
```

### 场景 2: 手动立即执行

调用 API 手动触发更新（可选实现）：

```bash
GET /api/admin/trigger-profile-update
```

响应示例：
```json
{
  "status": "started",
  "message": "Profile update task started in background",
  "stocks_to_update": 1543,
  "expected_duration_minutes": 154.3
}
```

### 场景 3: 查看任务进度

调用 API 查看当前状态：

```bash
GET /api/admin/profile-update-status
```

响应示例：
```json
{
  "is_running": false,
  "last_run": "2025-10-18T14:30:15",
  "last_run_stats": {
    "total": 1543,
    "successful": 1540,
    "failed": 3,
    "success_rate": "99.81%",
    "duration_seconds": 3086
  },
  "next_run": "2025-10-25T02:00:00"
}
```

---

## ⚙️ 配置调整

### 修改执行时间

如果需要改变任务执行时间，编辑 `backend/app/task_scheduler.py` 第 120 行：

```python
# 修改前：每周一 02:00
trigger=CronTrigger(day_of_week=0, hour=2, minute=0)

# 修改后：每天 23:00
trigger=CronTrigger(hour=23, minute=0)

# 修改后：每周五 10:00
trigger=CronTrigger(day_of_week=4, hour=10, minute=0)
```

### 修改速率控制

如果需要调整股票间的延迟时间，编辑第 148 行的函数调用：

```python
# 修改前：2 秒延迟
self.update_all_stock_profiles(delay_between_stocks=2.0)

# 修改后：5 秒延迟（更保险）
self.update_all_stock_profiles(delay_between_stocks=5.0)

# 修改后：1 秒延迟（更快）
self.update_all_stock_profiles(delay_between_stocks=1.0)
```

### 修改批处理数量

如果需要一次只处理部分股票，编辑 `_get_stocks_for_update()` 的返回语句：

```python
# 修改前：处理所有不完整的股票
return incomplete_stocks

# 修改后：一次只处理前 500 个
return incomplete_stocks[:500]

# 修改后：一次只处理前 100 个
return incomplete_stocks[:100]
```

---

## 📈 性能估算

### 处理能力

假设：
- 需要更新的股票数：2990 个
- 每个股票 LLM 分析时间：~2-3 秒
- 安全延迟：2 秒
- 总延迟：~4-5 秒/股票

**估算结果**：

| 场景 | 股票数 | 总耗时 |
|------|--------|--------|
| 首次更新（所有股票） | 2990 | ~4-5 小时 |
| 定期更新（50% 不完整） | 1500 | ~2-2.5 小时 |
| 小批量更新 | 100 | ~7-8 分钟 |

---

## 🔍 监控和调试

### 查看日志

后台任务的所有执行都会记录到应用日志：

```bash
# 查看最近的日志
tail -f logs/app.log

# 搜索任务执行日志
grep "stock_profile_update" logs/app.log

# 搜索错误日志
grep "❌" logs/app.log
```

### 典型日志输出

```
2025-10-21 02:00:00 - ✅ 后台任务调度器已启动
2025-10-21 02:00:00 - 📅 已安排任务: Weekly Stock Profile Update
2025-10-21 02:00:01 - 🚀 开始股票数据更新任务
2025-10-21 02:00:01 - ⏱️  爬虫速率: 2.0 秒/股票 (避免被ban)
2025-10-21 02:00:01 - 📊 找到 2990 只股票需要更新
2025-10-21 02:00:02 - 🔄 [1/1543] 正在更新: 比亚迪 (002594.SZ)
2025-10-21 02:00:05 - ✅ 成功更新: 002594.SZ
2025-10-21 02:00:05 - ⏳ 等待 2.0 秒后继续...
...
2025-10-21 04:15:00 - 📈 任务执行报告
2025-10-21 04:15:00 - 执行时间: 2025-10-21T04:15:00
2025-10-21 04:15:00 - 总耗时: 7500.23 秒
2025-10-21 04:15:00 - 总数: 1543
2025-10-21 04:15:00 - 成功: 1540
2025-10-21 04:15:00 - 失败: 3
2025-10-21 04:15:00 - 成功率: 99.81%
```

---

## 🛠️ 故障排除

### 问题 1: 任务没有自动运行

**检查清单**:

1. ✓ 应用是否正确启动？
   ```bash
   # 查看启动日志
   grep "后台任务调度器已初始化" logs/app.log
   ```

2. ✓ APScheduler 是否已安装？
   ```bash
   pip list | grep apscheduler
   ```

3. ✓ 当前时间是否接近周一 02:00？
   ```bash
   # 查看下次执行时间
   curl http://localhost:8000/api/admin/profile-update-status
   ```

### 问题 2: 任务运行失败

**检查步骤**:

1. 查看错误日志
   ```bash
   grep "❌" logs/app.log | tail -20
   ```

2. 检查 LLM 连接
   ```bash
   # 检查 OpenAI API 密钥
   echo $OPENAI_API_KEY
   ```

3. 检查数据库连接
   ```bash
   # 测试数据库
   python -c "from backend.app.models import db; print(db)"
   ```

### 问题 3: 任务运行太慢

**优化方案**:

1. 增加每个股票的处理时间（如果超时）
   ```python
   delay_between_stocks=5.0  # 增加到 5 秒
   ```

2. 减少一次处理的股票数量
   ```python
   return incomplete_stocks[:500]  # 只处理前 500 个
   ```

3. 优化 LLM 调用（使用缓存）
   ```python
   force_refresh=True  # 改为 False 使用缓存
   ```

---

## 📝 API 端点

### 手动触发更新（可选实现）

```
POST /api/admin/trigger-profile-update

请求示例：
curl -X POST http://localhost:8000/api/admin/trigger-profile-update

响应：
{
  "status": "started",
  "message": "Profile update task started in background",
  "stocks_to_update": 1543,
  "expected_duration_minutes": 154
}
```

### 查看更新状态

```
GET /api/admin/profile-update-status

请求示例：
curl http://localhost:8000/api/admin/profile-update-status

响应：
{
  "is_running": false,
  "last_run": "2025-10-18T14:30:15",
  "last_run_stats": {
    "total": 1543,
    "successful": 1540,
    "failed": 3,
    "success_rate": "99.81%",
    "duration_seconds": 3086
  },
  "next_run": "2025-10-25T02:00:00"
}
```

### 查看计划任务

```
GET /api/admin/scheduled-tasks

响应：
[
  {
    "id": "stock_profile_update",
    "name": "Weekly Stock Profile Update",
    "trigger": "cron[day_of_week=0,hour=2,minute=0]",
    "next_run": "2025-10-25T02:00:00"
  }
]
```

---

## ✅ 验证配置

### 1. 确认调度器已启动

```python
# 在应用运行时检查
curl http://localhost:8000/api/admin/profile-update-status
```

预期响应：包含 `next_run` 字段，显示下次执行时间

### 2. 查看启动日志

```bash
# 查看应用启动日志
grep "后台任务调度器" logs/app.log
```

预期输出：
```
✅ 后台任务调度器已初始化
✅ 后台任务调度器已启动
📅 已安排任务: Weekly Stock Profile Update
```

### 3. 测试任务（可选）

编辑 `task_scheduler.py` 的第 128-132 行，取消注释测试任务：

```python
# 添加测试任务：立即执行一次
self.scheduler.add_job(
    func=self.update_all_stock_profiles,
    trigger='date',
    run_date=datetime.now() + timedelta(seconds=10),
    id='test_update'
)
```

启动应用后，10 秒内任务会自动执行一次。

---

## 📊 数据流

### Profile 数据的完整生命周期

```
1. 应用启动
   ↓
2. 初始化 ScheduledTaskManager
   ↓
3. 注册定时任务（周一 02:00）
   ↓
4. 等待触发时间...
   ↓
5. 触发时间到达（周一 02:00）
   ↓
6. 执行 update_all_stock_profiles()
   ↓
7. 从 NewsArticle 提取所有股票代码
   ↓
8. 计算每个股票的 Profile 完成度
   ↓
9. 按完成度排序（低优先）
   ↓
10. 逐个调用 StockProfileEnricher 分析
    ↓
11. LLM 提取公司信息并更新 StockProfile 表
    ↓
12. 更新 Watchlist.last_updated_at 时间戳
    ↓
13. 记录日志和统计信息
    ↓
14. 任务完成，等待下个周一
```

---

## 🎯 总结

✅ **当前状态**:
- [x] 后台任务调度器已实现
- [x] 定时任务已配置（每周一 02:00）
- [x] 应用启动时自动初始化
- [x] 支持所有 2990 个股票的 Profile 更新
- [x] 记录详细的执行日志
- [x] 错误处理和重试机制

⏳ **下一步**（可选）:
- [ ] 实现手动触发 API（`POST /api/admin/trigger-profile-update`）
- [ ] 实现状态查询 API（`GET /api/admin/profile-update-status`）
- [ ] 实现暂停/恢复功能
- [ ] 添加 Web UI 监控面板

---

**配置完成！** 🎉  
后端已经在后台准备好自动更新所有股票的 Profile 数据。

