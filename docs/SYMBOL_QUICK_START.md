# 🚀 Symbol 规范化 - 快速开始指南

## ⚡ 一句话总结

脚本现在会自动检测并修复 symbol 格式不一致的问题（如 `002276` 变成 `002276.SZ`）。

---

## 🎯 三种常见场景

### 场景 1：查看会有哪些 symbol 被更新（零风险）

```bash
python backend\scripts\update_stock_profiles.py --dry-run
```

**效果：**
- 显示会有多少个 symbol 被更新
- 显示具体的变更内容
- **不修改数据库**
- 所需时间：3-5 分钟

**日志示例：**
```
⚠️ Symbol差异检测: 002268 → 002268.SZ
[DRY-RUN] 002268 将进行以下更改:
  - symbol: 002268 → 002268.SZ
  - company_name: 002268 → 电科网安
```

---

### 场景 2：测试性更新（前 100 个）

```bash
python backend\scripts\update_stock_profiles.py --limit 100
```

**效果：**
- 实际更新前 100 个股票的 symbol
- 修改数据库
- 所需时间：5-10 分钟

**日志示例：**
```
✅ 002268 更新成功:
  ✓ symbol: 002268 → 002268.SZ
  ✓ company_name: 002268 → 电科网安
```

---

### 场景 3：完整更新（所有股票）

```bash
python backend\scripts\update_stock_profiles.py
```

**效果：**
- 更新所有需要更新的股票
- 修改数据库
- 所需时间：取决于股票数量，通常 10-30 分钟

**日志示例：**
```
✓ 总检查: 1305
✓ 已更新: 1200
✓ 已跳过: 100
✗ 失败: 5
📈 成功率: 99.6%
```

---

## 📊 4 个主要参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--dry-run` | 演练模式（不修改DB） | `--dry-run` |
| `--limit N` | 限制股票数量 | `--limit 100` |
| `--market` | 按市场过滤 | `--market A股` |
| `--force` | 强制更新所有 | `--force` |

---

## 📈 常用命令组合

### 1️⃣ 演练模式 + 限量（推荐首先运行）
```bash
python backend\scripts\update_stock_profiles.py --dry-run --limit 50
```
查看前 50 个会发生什么变化。

### 2️⃣ 演练 + 只看 A 股
```bash
python backend\scripts\update_stock_profiles.py --dry-run --market A股
```
预览 A 股市场的所有变化。

### 3️⃣ 实际更新 + 限量
```bash
python backend\scripts\update_stock_profiles.py --limit 200
```
实际更新前 200 个股票。

### 4️⃣ 实际更新 + 按市场
```bash
python backend\scripts\update_stock_profiles.py --market 港股
```
只更新港股市场的股票。

---

## 📋 推荐的执行步骤（完整版）

```
第 1 步: 演练查看
  python backend\scripts\update_stock_profiles.py --dry-run --limit 50
  ↓ 确认无异常
  
第 2 步: 备份数据库
  使用数据库管理工具备份
  ↓
  
第 3 步: 限量测试
  python backend\scripts\update_stock_profiles.py --limit 100
  ↓ 登录系统检查更新结果
  ↓ 确认无误
  
第 4 步: 完整更新
  python backend\scripts\update_stock_profiles.py
  ↓ 喝杯咖啡，等待完成
  ↓
  
第 5 步: 验证完整性
  python backend\scripts\update_stock_profiles.py --dry-run
  ↓ 应该看不到需要更新的 symbol
```

---

## ✅ 执行结果示例

### 演练模式输出

```
🚀 启动股票信息批量更新
配置: dry_run=True, limit=50, market=全部, force=False

[1/50] 处理股票 002268
  ⚠️ Symbol差异检测: 002268 → 002268.SZ
  [DRY-RUN] 002268 将进行以下更改:
    - symbol: 002268 → 002268.SZ
    - company_name: 002268 → 电科网安

[2/50] 处理股票 002276
  ⚠️ Symbol差异检测: 002276 → 002276.SZ
  [DRY-RUN] 002276 将进行以下更改:
    - symbol: 002276 → 002276.SZ
    - company_name: 002276 → 万马股份

================================================================================
📊 执行摘要
✓ 总检查: 50
✓ 已更新: 45
✓ 已跳过: 5
✗ 失败: 0
📈 成功率: 100.0%
⚠️ 这是演练模式，数据库未实际更新
```

### 实际更新输出

```
✅ 002268 更新成功:
  ✓ symbol: 002268 → 002268.SZ
  ✓ company_name: 002268 → 电科网安

✅ 002276 更新成功:
  ✓ symbol: 002276 → 002276.SZ
  ✓ company_name: 002276 → 万马股份

================================================================================
📊 执行摘要
✓ 总检查: 50
✓ 已更新: 45        (已修改数据库)
✓ 已跳过: 5
✗ 失败: 0
📈 成功率: 100.0%
✅ 更新完成！
```

---

## 🔍 检查日志

### 查看实时日志
```bash
Get-Content backend\logs\update_stock_profiles.log -Wait -Tail 50
```

### 查看最后 100 行
```bash
Get-Content backend\logs\update_stock_profiles.log -Tail 100
```

### 搜索错误
```bash
Select-String "ERROR" backend\logs\update_stock_profiles.log
```

### 搜索 symbol 变化
```bash
Select-String "Symbol差异" backend\logs\update_stock_profiles.log
```

---

## ⚠️ 重要提醒

1. **一定要先运行演练模式** → 确保理解要更新什么
2. **建议备份数据库** → 防止意外情况
3. **分批处理** → 不要一次性更新所有股票，先用 `--limit 100` 测试
4. **监控日志** → 关注是否有错误信息
5. **验证结果** → 更新后登录系统检查几个股票

---

## 🎯 Symbol 格式速查

| 市场 | 变化 | 示例 |
|------|------|------|
| A股（深圳） | `002268` → `002268.SZ` | 深交所 |
| A股（上海） | `600000` → `600000.SH` | 上交所 |
| 港股 | `09988` → `09988.HK` | 港交所 |
| 美股 | `AAPL` → `AAPL.US` | 纳斯达克 |

---

## 🆘 遇到问题怎么办

### Q: 脚本在演练模式下卡住了？
A: 这是正常的，因为要调用 API 和 LLM。请耐心等待 1-2 分钟。

### Q: 看不到 symbol 变化的日志？
A: 可能所有 symbol 都已经是正确格式。可以用 `--force` 强制重新检查：
```bash
python backend\scripts\update_stock_profiles.py --dry-run --force
```

### Q: 数据库中没有看到更新？
A: 确保没有使用 `--dry-run`。演练模式不会修改数据库。

### Q: 更新失败了怎么办？
A: 检查日志文件中的错误信息：
```bash
Select-String "ERROR" backend\logs\update_stock_profiles.log
```

---

## ✨ 核心特性

✅ **自动检测** symbol 差异  
✅ **自动更新** 为标准格式  
✅ **零数据丢失** 失败自动回滚  
✅ **详细日志** 完整记录所有变更  
✅ **预览模式** 演练而不修改  
✅ **灵活控制** 支持分批处理  

---

## 🎉 立即开始

```bash
# 第一步：查看演练结果
python backend\scripts\update_stock_profiles.py --dry-run --limit 50

# 第二步：（如果演练结果正确）进行实际更新
python backend\scripts\update_stock_profiles.py --limit 100

# 第三步：（如果前 100 个没问题）更新所有
python backend\scripts\update_stock_profiles.py
```

---

## 📚 更多信息

- **详细文档：** `SYMBOL_NORMALIZATION.md`
- **实现报告：** `SYMBOL_IMPLEMENTATION_REPORT.md`
- **日志文件：** `backend/logs/update_stock_profiles.log`

---

**祝您使用愉快！** 🎊
