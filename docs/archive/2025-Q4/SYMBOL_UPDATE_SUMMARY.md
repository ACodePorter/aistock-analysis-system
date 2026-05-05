# 🎉 Symbol 规范化功能已完成

## 功能概述

脚本现在能够**自动检测和修复 symbol 不规范的问题**。当 API 返回的 symbol 与数据库中存储的 symbol 不一致时（如缺少 `.SZ`、`.SH` 后缀），脚本会自动将其更新为 API 返回的标准格式。

---

## ✅ 实现效果

### 示例：演练模式输出

```
[1/5] 处理股票 002268
  ⚠️ Symbol差异检测: 002268 → 002268.SZ
  📌 Symbol差异: 002268 → 002268.SZ
  [DRY-RUN] 002268 将进行以下更改:
    - symbol: 002268 → 002268.SZ
    - company_name: 002268 → 电科网安

[2/5] 处理股票 002276
  ⚠️ Symbol差异检测: 002276 → 002276.SZ
  📌 Symbol差异: 002276 → 002276.SZ
  [DRY-RUN] 002276 将进行以下更改:
    - symbol: 002276 → 002276.SZ
    - company_name: 002276 → 万马股份
```

---

## 🔍 工作原理

### 检测流程

1. **API 返回数据** → 提取 symbol（如 `002276.SZ`）
2. **数据库 symbol** → 对比当前数据库中的 symbol（如 `002276`）
3. **不一致检测** → 如果两者不同，标记为需要更新
4. **变更摘要** → 添加到更改列表中
5. **实际更新** → 演练模式显示或实际修改数据库

---

## 🚀 立即使用

### 方式 1：演练模式（推荐先试）

```bash
python backend\scripts\update_stock_profiles.py --dry-run --limit 50
```

**效果：** 查看会有多少个 symbol 被更新，**不修改数据库**

### 方式 2：限量测试

```bash
python backend\scripts\update_stock_profiles.py --limit 100
```

**效果：** 实际更新前 100 个股票，验证效果

### 方式 3：完整更新

```bash
python backend\scripts\update_stock_profiles.py
```

**效果：** 更新所有需要更新的股票

---

## 📊 常见 Symbol 格式对应

| 市场 | 数据库中 | API 返回 | 状态 |
|------|---------|---------|------|
| A股（深圳） | `002276` | `002276.SZ` | ⚠️ 需要更新 |
| A股（上海） | `600000` | `600000.SH` | ⚠️ 需要更新 |
| 港股 | `09988` | `09988.HK` | ⚠️ 需要更新 |
| 美股 | `AAPL` | `AAPL.US` | ⚠️ 需要更新 |

---

## 📈 执行结果示例

### 演练模式（Dry-Run）

```
✓ 总检查: 50
✓ 已更新: 45   (symbol 会被更新)
✓ 已跳过: 5    (symbol 已经正确)
✗ 失败: 0
📈 成功率: 100.0%
⚠️ 这是演练模式，数据库未实际更新
```

### 实际更新

```
✓ 总检查: 50
✓ 已更新: 45   (symbol 已更新)
✓ 已跳过: 5    (symbol 已经正确)
✗ 失败: 0
📈 成功率: 100.0%
✅ 更新完成！
```

---

## 🎯 推荐执行步骤

### 第 1 步：演练查看（必做）

```bash
python backend\scripts\update_stock_profiles.py --dry-run
```

查看演练结果，确认要更新的 symbol 数量。

### 第 2 步：备份数据库（推荐）

使用数据库管理工具进行备份。

### 第 3 步：限量测试（推荐）

```bash
python backend\scripts\update_stock_profiles.py --limit 100
```

只更新前 100 个，验证更新结果是否正确。

### 第 4 步：全量更新

```bash
python backend\scripts\update_stock_profiles.py
```

更新所有剩余的股票。

### 第 5 步：验证完整性（推荐）

```bash
python backend\scripts\update_stock_profiles.py --dry-run
```

再次运行演练模式，应该看不到需要更新 symbol 的股票。

---

## 📝 日志查看

### 查看最后 50 行日志

```bash
Get-Content backend\logs\update_stock_profiles.log -Tail 50
```

### 搜索 Symbol 相关的日志

```bash
Select-String "Symbol差异" backend\logs\update_stock_profiles.log
```

### 实时监控日志

```bash
Get-Content backend\logs\update_stock_profiles.log -Wait -Tail 100
```

---

## ⚠️ 注意事项

1. **演练模式必须先运行** → 确保没有问题再进行实际更新
2. **数据库备份推荐** → 防止意外情况
3. **逐步更新** → 使用 `--limit` 分批处理，不要一次性更新所有
4. **监控日志** → 关注是否有错误信息

---

## 🔧 修改内容

**文件：** `backend/scripts/update_stock_profiles.py`

**修改了两个地方：**

1. **API 数据提取** → 添加 symbol 检测逻辑
2. **数据准备** → 添加 symbol 更新和变更跟踪

**新增检测：**
```
⚠️ Symbol差异检测: 002268 → 002268.SZ
```

**新增变更项：**
```
- symbol: 002268 → 002268.SZ
```

---

## ✨ 关键特性

✅ **自动检测** symbol 差异  
✅ **自动更新** 为 API 标准格式  
✅ **详细日志** 记录所有变更  
✅ **事务性安全** 失败自动回滚  
✅ **演练模式** 预览而不修改  
✅ **灵活配置** 支持分批处理  

---

## 🎉 现在就可以使用了！

```bash
# 从演练模式开始
python backend\scripts\update_stock_profiles.py --dry-run --limit 50

# 确认无误后进行实际更新
python backend\scripts\update_stock_profiles.py --limit 100
```

所有 symbol 现在会自动被规范化为 API 返回的标准格式！

详细说明请查看：`SYMBOL_NORMALIZATION.md`
