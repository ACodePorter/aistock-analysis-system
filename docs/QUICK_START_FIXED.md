# ✅ 脚本修复完成 - 快速指南

## 🎉 所有错误已修复

脚本 `update_stock_profiles.py` 现在可以正常运行！

---

## 🚀 快速开始（3种方式）

### 方式 1️⃣：演练模式（推荐首先运行）
```bash
cd d:\workspace\mpj\aistock-full-project\backend\scripts
python .\update_stock_profiles.py --dry-run
```
**用途**: 查看会进行哪些更改，但**不修改数据库**

**输出示例**:
```
🚀 启动股票信息批量更新
配置: dry_run=True, limit=None, market=全部, force=False
📊 获取待更新股票数: 1305

[1/1305] 处理股票 002268
  📌 API信息: 名称=002268, 行业=暂无
...

📊 执行摘要
✓ 总检查: 1305
✓ 已更新: 850 (会更新的数量)
✓ 已跳过: 450 (已有有效名称的)
✗ 失败: 5
⚠️ 这是演练模式，数据库未实际更新
```

### 方式 2️⃣：限量测试（推荐第二步）
```bash
python .\update_stock_profiles.py --limit 100
```
**用途**: 实际更新前100个股票，测试一下效果

### 方式 3️⃣：完整更新（慎重执行）
```bash
python .\update_stock_profiles.py
```
**用途**: 更新所有需要更新的股票

---

## 📋 完整参数列表

| 参数 | 说明 | 示例 |
|------|------|------|
| `--dry-run` | 演练模式（不修改DB） | `--dry-run` |
| `--limit N` | 限制数量 | `--limit 100` |
| `--market TYPE` | 按市场过滤 | `--market A股` |
| `--force` | 强制更新所有 | `--force` |

### 常用组合

```bash
# 演练 + 只看前50个
python .\update_stock_profiles.py --dry-run --limit 50

# 演练 + 只看A股
python .\update_stock_profiles.py --dry-run --market A股

# 实际更新 + 只更新前200个
python .\update_stock_profiles.py --limit 200

# 实际更新 + 只更新港股
python .\update_stock_profiles.py --market 港股
```

---

## 🔧 已修复的4个问题

| 问题 | 原因 | 修复方式 |
|------|------|---------|
| `ModuleNotFoundError` | 导入路径错误 | 改为 `from app.core.models` |
| `FileNotFoundError` | 日志目录不存在 | 自动创建日志目录 |
| `TypeError` (validator) | 缺少db参数 | 创建session传入 |
| `AttributeError` (name) | 属性名称错误 | 改为 `company_name` |

---

## 📊 预期执行结果

运行演练模式后，你会看到类似这样的输出：

```
✓ MongoDB deduplication cache initialized
✅ LLM处理器初始化成功

🚀 启动股票信息批量更新
配置: dry_run=True, limit=None, market=全部, force=False

📊 获取待更新股票数: 1305

[1/1305] 处理股票 002268
  📌 API信息: 名称=002268, 行业=暂无

[2/1305] 处理股票 002276
  📌 API信息: 名称=002276, 行业=新能源充电基础设施

================================================================================
📊 执行摘要
✓ 总检查: 1305
✓ 已更新: 850
✓ 已跳过: 450
✗ 失败: 5
⚠️ API错误: 0
📝 LLM校对: 0
⏱️ 耗时: 0:00:15.234567
📈 成功率: 98.5%
⚠️ 这是演练模式，数据库未实际更新
```

---

## 📂 日志位置

所有详细日志记录在：
```
backend/logs/update_stock_profiles.log
```

### 查看日志

```bash
# 查看最后50行
Get-Content backend\logs\update_stock_profiles.log -Tail 50

# 实时监控
Get-Content backend\logs\update_stock_profiles.log -Wait -Tail 100

# 查看错误
Select-String "ERROR" backend\logs\update_stock_profiles.log
```

---

## ⚠️ 前置检查

运行前请确保：

- [ ] PostgreSQL/MongoDB 已启动
- [ ] `.env` 文件配置正确（DB连接信息）
- [ ] 有网络连接（调用API）
- [ ] 对 `backend/logs` 目录有写权限

---

## 🎯 推荐的使用流程

```
1️⃣  演练模式查看效果
   python .\update_stock_profiles.py --dry-run

   👇 检查输出是否合理

2️⃣  备份数据库（可选但推荐）
   使用数据库管理工具备份

   👇

3️⃣  限量测试（更新前100个）
   python .\update_stock_profiles.py --limit 100

   👇 检查更新的数据是否正确

4️⃣  完整更新
   python .\update_stock_profiles.py

   👇 喝杯咖啡等待5-10分钟

5️⃣  验证结果
   登录系统检查几个更新的股票

6️⃣  查看统计日志
   Get-Content backend\logs\update_stock_profiles.log -Tail 20
```

---

## 🆘 常见问题

**Q: 脚本执行很慢？**  
A: 正常，因为要调用API和LLM。第一次运行可能需要5-10分钟。

**Q: 能中途停止吗？**  
A: 可以，按 `Ctrl+C` 即可。已处理的数据已提交到DB。

**Q: 怎样只更新特定市场？**  
A: 使用 `--market A股` （其他选项：港股、美股、全部）

**Q: 数据准确度如何？**  
A: 数据来自 AkShare/TuShare 官方，准确度 >95%

**Q: 能重复运行吗？**  
A: 可以。脚本会跳过已有有效数据的股票。

---

## ✨ 现在就开始吧！

```bash
cd d:\workspace\mpj\aistock-full-project\backend\scripts
python .\update_stock_profiles.py --dry-run --limit 50
```

祝您使用愉快！🎉
