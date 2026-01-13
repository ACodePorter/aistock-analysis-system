# 📌 Profile 更新 - 快速参考

## 三种更新方式对比

| 方式 | 触发方法 | 时间 | 何时使用 |
|-----|---------|------|---------|
| **自动更新** | 系统自动 | 每周一 02:00 | 生产环境（推荐） |
| **手动更新** | API 调用 | 立即 | 测试、紧急更新 |
| **前端 UI** | 点击按钮 | 立即 | 用户手动触发 |

---

## 🚀 快速命令

### 立即启动更新

```bash
# 方式 1: 默认设置（推荐）
curl -X POST http://localhost:8000/admin/scheduler/run-now

# 方式 2: 快速模式（0.5 秒延迟）
curl -X POST "http://localhost:8000/admin/scheduler/run-now?delay_between_stocks=0.5"

# 方式 3: 保守模式（5 秒延迟，更安全）
curl -X POST "http://localhost:8000/admin/scheduler/run-now?delay_between_stocks=5"
```

### 查询进度

```bash
# 查看最后一次运行统计
curl http://localhost:8000/admin/scheduler/task-stats

# 查看调度器状态
curl http://localhost:8000/admin/scheduler/status
```

---

## ⏱️ 性能速查表

| 延迟设置 | 处理 100 只股票耗时 | 处理全部 2990 只耗时 |
|---------|-------------------|------------------|
| 0.5 秒  | ~7 分钟           | 3.5 小时          |
| 1.0 秒  | ~10 分钟          | 5 小时            |
| 2.0 秒  | ~15 分钟          | 7.5 小时          |
| 3.0 秒  | ~20 分钟          | 10 小时           |
| 5.0 秒  | ~33 分钟          | 16 小时           |

---

## ✅ 任务运行检查

```bash
# 1. 启动更新
curl -X POST http://localhost:8000/admin/scheduler/run-now

# 2. 等待 1-2 分钟

# 3. 检查是否真的在运行
curl http://localhost:8000/admin/scheduler/task-stats | jq '.stats.is_running'
# 应该返回: true

# 4. 再等几分钟，查看已处理数量
curl http://localhost:8000/admin/scheduler/task-stats | jq '.stats'

# 5. 完成后检查
curl http://localhost:8000/admin/scheduler/task-stats
# is_running 应该变成 false
```

---

## 🔧 常见场景

### 场景 A: 刚重启后端，想快速测试修复

```bash
# 1. 立即启动一次完整更新
curl -X POST http://localhost:8000/admin/scheduler/run-now

# 2. 等待 4-5 小时...

# 3. 完成后，刷新前端查看结果
# 002594.SZ 应该显示为绿色且 ~100% 完成度
```

### 场景 B: 只想看看前 100 只股票是否能正常处理

```bash
# 手工中止（CTRL+C）任务后查询统计
curl http://localhost:8000/admin/scheduler/task-stats
# 看 processed_stocks 数量
```

### 场景 C: 上周日晚上启动更新，让周一完成

```bash
# 周日 22:00 启动，使用较长延迟
curl -X POST "http://localhost:8000/admin/scheduler/run-now?delay_between_stocks=3"

# 让它在后台静默运行 10 小时
# 周一 8:00 AM 再查询结果
curl http://localhost:8000/admin/scheduler/task-stats
```

---

## 🎯 核心指标速查

**当前系统状态**:
- 📦 股票总数: 2990
- ⏱️ 平均处理时间: 4-5 秒/股
- 🔄 推荐延迟: 2-3 秒（防止被 ban）
- 📊 最小延迟: 0.5 秒（系统强制）
- 📊 最大延迟: 10 秒（系统强制）

**自动更新**:
- 📅 计划: 每周一 02:00 (Asia/Taipei)
- 🔐 冲突保护: 同时只运行 1 个任务

---

## 🔴 红灯警告

| 警告 | 原因 | 解决 |
|------|------|------|
| ❌ `is_running: true` 超过 6h | 任务卡住或崩溃 | 重启后端 |
| ❌ `failed` > 200 | 太多股票失败 | 检查日志 |
| ❌ 自动更新未触发 | 后端未启动或调度器禁用 | 检查 ENABLE_SCHEDULER 环境变量 |
| ❌ 返回 "任务已在运行" | 上一个任务未完成 | 等待 4-5 小时或重启 |

---

## 📂 文件位置参考

- 📍 API 路由: `backend/app/main.py` 行 1458
- 📍 调度器: `backend/app/task_scheduler.py`
- 📍 Profile 富化: `backend/app/stock_profile_enrichment.py`
- 📍 前端页面: `frontend/src/ui/StocksNewsIndex.tsx`
- 📍 API 完整文档: `API_MANUAL_TRIGGER.md`

---

## 🎓 学习资源

- [完整 API 文档](./API_MANUAL_TRIGGER.md)
- [后台任务详细配置](./BACKGROUND_TASK_CONFIGURATION.md)
- [快速参考指南](./BACKGROUND_TASK_QUICK_REF.txt)

---

**上次修复状态**:
- ✅ 前端已更新：显示 Profile 完成度
- ✅ 后端 API 已修复：排序前分页
- ✅ 自动调度已实现：APScheduler 集成
- ✅ 手动 API 已实现：`/admin/scheduler/run-now`
- ⏳ 等待：后端重启以应用所有修复
