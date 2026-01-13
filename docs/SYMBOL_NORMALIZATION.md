# ✅ Symbol 规范化功能完成

## 功能说明

脚本现在能够自动检测和修复 symbol 不规范的问题。当 API 返回的 symbol 与数据库中存储的 symbol 不一致时（如缺少 `.SZ` 或 `.SH` 后缀），脚本会自动将其更新为 API 返回的标准格式。

---

## 工作流程

### 检测流程

```
获取API数据
    ↓
提取 api_symbol (如 "002276.SZ")
    ↓
与数据库 symbol (如 "002276") 比较
    ↓
不一致？
    ├─ 是 → 标记为需要更新
    └─ 否 → 保持原样
    ↓
生成变更摘要
    ↓
演练/实际更新
```

---

## 日志输出示例

### 演练模式（Dry-Run）

```
[1/5] 处理股票 002268
  📌 API返回数据: {'symbol': '002268.SZ', 'name': '电科网安', ...}
  ⚠️ Symbol差异检测: 002268 → 002268.SZ
  📌 准备更新数据: {'symbol': '002268.SZ', 'company_name': '电科网安', ...}
  [DRY-RUN] 002268 将进行以下更改:
    - symbol: 002268 → 002268.SZ
    - company_name: 002268 → 电科网安
```

### 变更摘要

```
✓ 总检查: 2
✓ 已更新: 2  (将更新symbol和company_name)
✓ 已跳过: 0
✗ 失败: 0
📈 成功率: 100.0%
```

---

## 修改内容

### 修改文件
- `backend/scripts/update_stock_profiles.py`

### 修改详情

#### 1️⃣ API 数据提取部分 (第280-302行)

**添加内容：**
```python
api_symbol = api_info.get('symbol', symbol)  # 从API获取标准化的symbol

# 检查symbol是否需要更新
symbol_needs_update = False
if api_symbol and api_symbol != symbol:
    logger.info(f"  ⚠️ Symbol差异检测: {symbol} → {api_symbol}")
    print(f"  📌 Symbol差异: {symbol} → {api_symbol}")
    symbol_needs_update = True
```

**用途：** 从 API 返回的数据中提取 symbol，并检测是否与数据库中的 symbol 不一致。

#### 2️⃣ 数据准备部分 (第310-345行)

**修改内容：**
```python
# old_values 中添加 symbol
old_values = {
    "symbol": profile.symbol,
    "company_name": profile.company_name,
    ...
}

# new_values 中使用 api_symbol
new_values = {
    "symbol": api_symbol if symbol_needs_update else profile.symbol,
    "company_name": final_company_name,
    ...
}

# changes 列表中添加 symbol 检查
if old_values["symbol"] != new_values["symbol"]:
    changes.append(f"symbol: {old_values['symbol']} → {new_values['symbol']}")
```

**用途：** 在更新时将数据库中的 symbol 更新为 API 返回的标准格式。

---

## 常见 Symbol 格式

### A 股（深圳）
- **API 返回**: `002276.SZ`
- **数据库**: `002276`（需要更新）

### A 股（上海）
- **API 返回**: `600000.SH`
- **数据库**: `600000`（需要更新）

### 港股
- **API 返回**: `09988.HK`
- **数据库**: `09988`（需要更新）

### 美股
- **API 返回**: `AAPL.US`
- **数据库**: `AAPL`（需要更新）

---

## 使用示例

### 1️⃣ 演练模式（推荐先运行）

```bash
python backend\scripts\update_stock_profiles.py --dry-run --limit 50
```

**效果：** 查看会对哪些股票进行 symbol 更新，不实际修改数据库

**输出包含：**
- ⚠️ Symbol 差异检测
- 📌 具体的变更内容
- [DRY-RUN] 标记

### 2️⃣ 实际更新

```bash
# 更新前100个
python backend\scripts\update_stock_profiles.py --limit 100

# 更新所有
python backend\scripts\update_stock_profiles.py
```

**效果：** 实际修改数据库，将所有 symbol 更新为 API 返回的标准格式

---

## 数据库更新机制

### 何时更新 symbol

只有当以下条件都满足时，才会更新 symbol：

1. ✅ API 成功返回了数据
2. ✅ API 返回的 symbol 与数据库中的 symbol 不一致
3. ✅ 用户没有使用 `--dry-run` 标志

### 事务性安全

- 每个股票的更新都在单独的数据库事务中
- 如果更新失败，会自动回滚
- 不会影响其他股票的更新

---

## 监控和验证

### 查看日志

```bash
# 查看最后50行日志
Get-Content backend\logs\update_stock_profiles.log -Tail 50

# 搜索 symbol 相关的日志
Select-String "Symbol差异" backend\logs\update_stock_profiles.log

# 实时监控
Get-Content backend\logs\update_stock_profiles.log -Wait -Tail 100
```

### 验证更新结果

运行完成后，可以在数据库中检查：

```sql
-- 查看已更新的 symbol
SELECT symbol, company_name, updated_at 
FROM stock_profiles 
WHERE symbol LIKE '%.SZ' OR symbol LIKE '%.SH'
LIMIT 20;
```

---

## 故障排查

### 问题 1: Symbol 没有被更新

**可能原因：**
- 使用了 `--dry-run`（演练模式）→ 改用实际更新命令
- API 没有返回 symbol → 检查 API 是否正常工作
- Symbol 已经相同 → 检查日志确认是否有"差异检测"

**解决方案：**
```bash
# 先查看日志确认问题
Get-Content backend\logs\update_stock_profiles.log -Tail 100

# 检查是否是演练模式
python backend\scripts\update_stock_profiles.py --limit 10  # 不加 --dry-run
```

### 问题 2: Symbol 更新失败

**可能原因：**
- 数据库连接异常
- Symbol 违反了数据库约束（如唯一性约束）
- 数据库权限不足

**解决方案：**
```bash
# 查看详细的错误信息
Get-Content backend\logs\update_stock_profiles.log | Select-String "ERROR"

# 确保数据库连接正常
# 重新运行脚本
python backend\scripts\update_stock_profiles.py --limit 10
```

---

## 推荐的执行步骤

### 步骤 1️⃣：演练检查（必做）
```bash
python backend\scripts\update_stock_profiles.py --dry-run --limit 100
```
查看会有多少个 symbol 被更新，确保没有问题。

### 步骤 2️⃣：备份数据库（推荐）
使用数据库管理工具备份，防止意外情况。

### 步骤 3️⃣：限量测试（推荐）
```bash
python backend\scripts\update_stock_profiles.py --limit 100
```
只更新前100个，验证结果正确。

### 步骤 4️⃣：全量更新（最终）
```bash
python backend\scripts\update_stock_profiles.py
```
更新所有剩余的股票。

### 步骤 5️⃣：验证完整性（推荐）
```bash
python backend\scripts\update_stock_profiles.py --dry-run
```
再次运行演练模式，应该看不到需要更新的 symbol。

---

## 性能考虑

### 更新速度
- 每个股票需要调用 API：约 0.5-1 秒
- 调用 LLM 进行校对：约 2-5 秒
- 数据库更新：约 0.1 秒
- **总耗时：** 大约 3-6 秒/股票

### 优化建议
- 使用 `--limit 100` 分批处理，避免过长的运行时间
- 在非营业时间进行大规模更新
- 监控数据库性能，确保更新不会影响系统

---

## 成功标志

当您看到以下日志输出时，说明脚本正常工作：

```
✓ 总检查: 100
✓ 已更新: 85   (symbol 和/或 company_name 被更新)
✓ 已跳过: 15   (信息已是最新)
✗ 失败: 0
📈 成功率: 100.0%
```

---

## 总结

✅ Symbol 规范化功能已完全实现，包括：
- 自动检测 symbol 差异
- 自动更新为 API 返回的标准格式
- 详细的日志记录
- 事务性安全保障
- 演练模式预览

🚀 现在可以安全地执行脚本来规范化所有 symbol 了！
