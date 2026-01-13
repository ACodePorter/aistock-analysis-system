# 🚀 手动触发 Profile 更新 API 使用指南

## 概述

系统已经完整实现了**手动触发**和**自动调度**的 Profile 更新功能。您可以：

1. **自动更新**：每周一 02:00 自动执行（无需干预）
2. **手动更新**：通过 API 立即执行更新任务
3. **查询进度**：检查最近一次任务的执行统计

---

## 📍 API 端点列表

### 1. 立即执行更新任务

**端点**: `POST /admin/scheduler/run-now`

**描述**: 立即在后台启动一次异步更新任务，无需等待计划时间

**参数**:
| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `delay_between_stocks` | float | 2.0 | 相邻两只股票更新之间的延迟时间（秒） |

**延迟参数范围**:
- 最小值: 0.5 秒（系统会自动调整，避免爬虫被 ban）
- 最大值: 10 秒
- 推荐值: 2-3 秒

**请求示例**:
```bash
# 默认延迟 2 秒启动更新
curl -X POST http://localhost:8000/admin/scheduler/run-now

# 自定义延迟 3 秒启动更新
curl -X POST "http://localhost:8000/admin/scheduler/run-now?delay_between_stocks=3.0"

# 快速更新 1 秒延迟（系统会自动调整为最小值 0.5s）
curl -X POST "http://localhost:8000/admin/scheduler/run-now?delay_between_stocks=0.5"
```

**响应示例** (成功):
```json
{
  "success": true,
  "message": "异步更新任务已启动",
  "is_running": true,
  "delay_between_stocks": 2.0,
  "stats": {
    "last_run_at": "2025-10-18T14:30:00",
    "processed_stocks": 2990,
    "successful": 2950,
    "failed": 40,
    "duration_minutes": 245,
    "next_run": "2025-10-25T02:00:00",
    "is_running": true
  }
}
```

**响应示例** (任务已在运行):
```json
{
  "success": false,
  "message": "任务已在运行中，请稍后重试",
  "is_running": true
}
```

---

### 2. 获取任务执行统计

**端点**: `GET /admin/scheduler/task-stats`

**描述**: 获取最后一次任务的执行统计信息

**参数**: 无

**请求示例**:
```bash
curl http://localhost:8000/admin/scheduler/task-stats
```

**响应示例**:
```json
{
  "success": true,
  "timestamp": "2025-10-18T14:30:00",
  "stats": {
    "last_run_at": "2025-10-18T10:00:00",
    "processed_stocks": 2990,
    "successful": 2950,
    "failed": 40,
    "duration_minutes": 245,
    "next_run": "2025-10-25T02:00:00",
    "is_running": false
  }
}
```

---

### 3. 查询任务调度器状态

**端点**: `GET /admin/scheduler/status`

**描述**: 查询任务调度器状态与已注册作业

**参数**: 无

**请求示例**:
```bash
curl http://localhost:8000/admin/scheduler/status
```

**响应示例**:
```json
{
  "enabled": true,
  "timezone": "Asia/Taipei",
  "jobs": [
    {
      "id": "update_all_stock_profiles",
      "next_run": "2025-10-20T02:00:00",
      "trigger": "cron[day_of_week=0, hour=2, minute=0, second=0]"
    }
  ]
}
```

---

## 🔄 工作流程

### 自动更新流程（每周一 02:00）

```
系统启动
  ↓
初始化 APScheduler
  ↓
注册 CronTrigger (周一 02:00)
  ↓
等待计划时间...
  ↓
自动执行 update_all_stock_profiles()
  ↓
处理 2990 只股票
  ↓
写入数据库 + 日志
```

### 手动更新流程（即时）

```
POST /admin/scheduler/run-now
  ↓
检查是否已有任务运行
  ↓
在后台线程启动新任务
  ↓
处理 2990 只股票（带延迟）
  ↓
写入数据库 + 日志
  ↓
任务完成，可再次调用
```

---

## 📊 性能指标

| 指标 | 值 | 说明 |
|------|-----|------|
| 股票总数 | 2990 | 从 NewsArticle.related_stocks 提取 |
| 平均处理时间 | 4-5 秒/股 | 含 LLM 调用 + 数据库写入 |
| 总耗时 | 4-5 小时 | 对所有 2990 只股票的初次更新 |
| 默认延迟 | 2 秒 | 防止爬虫被 ban |
| 并发度 | 1 | 同一时刻仅处理 1 只股票 |

---

## 🛡️ 安全机制

### 1. 并发控制

- 系统确保**同一时刻仅运行一个更新任务**
- 若任务已在运行，新请求会返回 `is_running: true` 错误
- 防止多个后台任务相互干扰

### 2. 爬虫延迟防护

- 每两只股票间自动延迟 2 秒（可自定义）
- 系统强制最小延迟 **0.5 秒**，防止爬虫被 ban
- 系统强制最大延迟 **10 秒**，防止任务耗时过长

### 3. 错误处理

- 单个股票失败不会中断整体流程
- 记录失败原因便于调试
- 自动重试机制（通过 LLM enricher 实现）

---

## 🧪 测试场景

### 场景 1: 快速测试（首次验证）

```bash
# 使用最小延迟进行快速测试
curl -X POST "http://localhost:8000/admin/scheduler/run-now?delay_between_stocks=0.5"

# 2-3 分钟后检查进度
curl http://localhost:8000/admin/scheduler/task-stats
```

预期：约 10-15 只股票已处理

### 场景 2: 标准更新（生产环境）

```bash
# 使用推荐延迟启动更新
curl -X POST "http://localhost:8000/admin/scheduler/run-now?delay_between_stocks=2.0"

# 检查状态
curl http://localhost:8000/admin/scheduler/status
```

预期：4-5 小时内完成全部 2990 只股票更新

### 场景 3: 保守更新（避免被 ban）

```bash
# 使用较大延迟进行保守更新
curl -X POST "http://localhost:8000/admin/scheduler/run-now?delay_between_stocks=5.0"
```

预期：耗时约 10-12 小时，但更安全

---

## 🐛 故障排除

### 问题 1: 返回 "任务已在运行中"

**原因**: 前一个更新任务未完成

**解决方案**:
1. 等待前一个任务完成（4-5 小时）
2. 查看日志确认进度
3. 如需强制停止，重启后端服务

```bash
# 查看是否还在运行
curl http://localhost:8000/admin/scheduler/task-stats
```

### 问题 2: 自动更新未触发（周一 02:00）

**原因**: 后端服务未启动，或调度器未初始化

**解决方案**:
1. 检查后端服务是否正常运行
2. 查看日志中的 "后台任务调度器已初始化" 消息
3. 确认时区配置正确（环境变量 `TZ`）

```bash
# 检查调度器状态
curl http://localhost:8000/admin/scheduler/status
```

### 问题 3: 任务执行失败或停止

**原因**: 网络问题、LLM API 超时、数据库连接错误等

**解决方案**:
1. 检查后端日志中的错误信息
2. 验证数据库连接
3. 确认 LLM API 可用
4. 重试更新（系统会从失败的股票继续）

```bash
# 重新启动更新
curl -X POST "http://localhost:8000/admin/scheduler/run-now"
```

---

## 📝 配置项

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TZ` | `Asia/Taipei` | 时区设置（影响自动更新时间） |
| `ENABLE_SCHEDULER` | `1` | 是否启用调度器 (1=启用, 0=禁用) |
| `DELAY_BETWEEN_STOCKS` | `2.0` | 爬虫延迟（秒）|

### 配置示例

```bash
# .env 或环境变量设置

# 启用调度器
ENABLE_SCHEDULER=1

# 设置时区为北京时间（自动更新时间 = 北京时间 每周一 02:00）
TZ=Asia/Shanghai

# 默认爬虫延迟为 3 秒
DELAY_BETWEEN_STOCKS=3.0
```

---

## 🔍 监控建议

### 建议 1: 定期检查任务状态

```bash
# 每 5 分钟检查一次
watch -n 300 'curl http://localhost:8000/admin/scheduler/task-stats'
```

### 建议 2: 监控日志输出

```bash
# 从日志中查找 Profile 更新相关信息
tail -f logs/app.log | grep -i "profile\|update\|scheduler"
```

### 建议 3: 设置告警规则

- 如果 `is_running` 超过 6 小时，可能出现问题
- 如果 `failed` 数量超过 200，需要调查
- 确认 `next_run` 时间是否正确

---

## 📚 相关文件

| 文件 | 位置 | 说明 |
|------|------|------|
| 任务调度器 | `backend/app/task_scheduler.py` | 核心调度逻辑 |
| API 路由 | `backend/app/main.py` 行 1458 起 | 手动触发 API |
| 启动事件 | `backend/app/main.py` 行 1095 起 | 自动初始化 |
| Profile 富化 | `backend/app/stock_profile_enrichment.py` | LLM 分析逻辑 |

---

## ✅ 系统完整性检查清单

- [x] 自动调度器已实现（APScheduler）
- [x] 手动触发 API 已实现 (`/admin/scheduler/run-now`)
- [x] 任务统计 API 已实现 (`/admin/scheduler/task-stats`)
- [x] 并发控制已实现（防止重复运行）
- [x] 爬虫延迟防护已实现（防止 ban）
- [x] 错误处理已实现（失败不中断）
- [x] 日志记录已实现（完整可追踪）
- [x] 前端 UI 已支持（显示 Profile 完成度）
- [x] 后端 API 已修复（排序前分页）

---

## 🎉 总结

系统已经完全支持：

1. **自动更新** - 每周一 02:00 自动执行
2. **手动更新** - 通过 API 立即执行
3. **进度查询** - 实时获取任务执行状态
4. **安全防护** - 并发控制、爬虫延迟、错误处理
5. **前端展示** - Profile 完成度实时显示
6. **后端支持** - 正确排序和分页

**用户只需要**：
- 等待后端重启以应用上次的 API 排序修复
- 调用 `/admin/scheduler/run-now` 手动更新（可选）
- 系统会在每周一 02:00 自动更新所有股票
