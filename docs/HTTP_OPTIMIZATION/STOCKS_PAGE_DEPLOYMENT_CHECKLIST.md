# ✅ 股票页面 HTTP 优化 - 实施清单

## 📋 实施前检查

### 环境准备

- [ ] 已阅读 `STOCKS_PAGE_SOLUTION_OVERVIEW.md`
- [ ] 已了解 4 个代码改动点
- [ ] 已备份原文件: `StocksNewsIndex.tsx.backup`
- [ ] 已准备 `StocksNewsIndex-OPTIMIZED.tsx` 或手动应用改动
- [ ] Node.js 和 npm 已安装
- [ ] 本地开发环境可运行

### 团队协调

- [ ] 团队成员已知晓本次优化
- [ ] Code Review 负责人已准备
- [ ] QA 测试计划已制定
- [ ] 如需部署到生产，已通知运维

---

## 🔧 实施步骤

### 步骤 1: 应用代码改动 (10 分钟)

#### 选项 A: 完整替换 (如果没有自定义修改)

```powershell
# 1. 备份原文件
Copy-Item -Path "frontend/src/ui/StocksNewsIndex.tsx" `
          -Destination "frontend/src/ui/StocksNewsIndex.tsx.backup" `
          -Force

# 2. 替换为优化版本
Copy-Item -Path "frontend/src/ui/StocksNewsIndex-OPTIMIZED.tsx" `
          -Destination "frontend/src/ui/StocksNewsIndex.tsx" `
          -Force

# 3. 验证文件已替换
Get-Item -Path "frontend/src/ui/StocksNewsIndex.tsx"
```

- [ ] 步骤 1.1: 备份完成
- [ ] 步骤 1.2: 替换完成
- [ ] 步骤 1.3: 验证完成

#### 选项 B: 手动应用改动 (如果有自定义修改)

**改动位置**: `frontend/src/ui/StocksNewsIndex.tsx`

**改动 1**: 第 47-50 行 (新增 2 行)
```tsx
// 找到现有的 loadingPagesRef 定义
const allItemsCacheRef = React.useRef<any[]>([])
const loadingPagesRef = React.useRef(new Set<number>())

// 在后面新增这两行 ✨
const cacheKeyRef = React.useRef('')
const buildCacheKey = () => `${market}_${showInvalid}`
```

- [ ] 改动 1 已应用

**改动 2**: 第 160-233 行 (修改 load 函数)
- 查找: `const load = React.useCallback(async (isInitialLoad = true)`
- 在函数开始添加缓存检查逻辑 (参考 `STOCKS_PAGE_IMPLEMENTATION_GUIDE.md`)

- [ ] 改动 2 已应用

**改动 3**: 第 225-227 行 (删除 3 行)
- 查找: `loadRemainingPages(firstPageData.total_stocks`
- 删除这段代码:
```tsx
if (isInitialLoad && (firstPageData.total_stocks || 0) > 100) {
  loadRemainingPages(firstPageData.total_stocks || 0, showInvalid)
}
```

- [ ] 改动 3 已应用

**改动 4**: 第 235-300 行 (新增 loadPageOnDemand 函数)
- 在 `loadRemainingPages` 后面新增 `loadPageOnDemand` 函数
- 参考完整代码: `frontend/src/ui/StocksNewsIndex-OPTIMIZED.tsx`

- [ ] 改动 4 已应用

### 步骤 2: 编译检查 (5 分钟)

```powershell
# 1. 进入项目目录
cd frontend

# 2. 编译/构建
npm run build

# 3. 检查输出，确保无错误
# 预期: 无 TypeScript 错误，构建成功
```

- [ ] npm 命令执行成功
- [ ] 无 TypeScript 编译错误
- [ ] 无 ESLint 警告 (或已忽略)
- [ ] 构建文件已生成

### 步骤 3: 本地开发测试 (15 分钟)

```powershell
# 1. 启动开发服务器
npm run dev

# 2. 打开浏览器
# 进入: http://localhost:5173 (或你的开发 URL)

# 3. 打开开发者工具
# 按 F12 → Network 标签
```

- [ ] 开发服务器已启动
- [ ] 页面可正常加载
- [ ] 开发者工具已打开

#### 测试 1: 首次加载市场 (5 分钟)

**操作**:
1. 刷新页面
2. 等待页面加载完成
3. 在 Network 标签中观察请求

**检查**:
- [ ] 只有 **1 个** `/api/news/stocks/progress?page=1...` 请求
- [ ] 无其他 `/api/news/stocks/progress?page=2...`, `?page=3...` 等请求
- [ ] 页面快速显示 (< 1 秒)

**浏览器控制台检查**:
- [ ] 可见日志: `✅ [首页加载成功]`
- [ ] 无错误日志 (❌ 符号)

**预期结果**: ✅ 通过 / ❌ 失败

#### 测试 2: 重复切换市场 (5 分钟)

**操作**:
1. 在 Market selector 中选择其他市场 (如 "港股")
2. 在 Network 中观察新请求
3. 再切换回 "A股"
4. 再次观察 Network

**检查**:
- [ ] 第 1 次切换到港股: **1 个新请求** (`/api/news/stocks/progress?page=1&market=港股`)
- [ ] 切换回 A股: **0 个新请求** (应该看到缓存命中日志)
- [ ] 页面立即显示 (无加载延迟)

**浏览器控制台检查**:
- [ ] 第 2 次选择 A股 时可见: `📦 [缓存命中] 使用已加载的数据`
- [ ] 无新的 fetch 请求

**预期结果**: ✅ 通过 / ❌ 失败

#### 测试 3: 翻页加载 (如果有翻页功能) (5 分钟)

**操作** (如果 UI 有翻页按钮):
1. 在 Network 中清空日志 (Ctrl+L)
2. 点击 "下一页" 按钮
3. 观察新请求

**检查**:
- [ ] 只有 **1 个** `/api/news/stocks/progress?page=2...` 请求
- [ ] 页面加载该页数据 (<500ms)
- [ ] 再次点击下一页，又是 1 个请求

**浏览器控制台检查**:
- [ ] 可见日志: `📥 [按需加载] 加载第 2 页`
- [ ] 加载成功: `✅ [页面加载成功]`

**预期结果**: ✅ 通过 / ❌ 失败

### 步骤 4: 使用监控脚本验证 (5 分钟)

**操作**:
1. 打开浏览器 DevTools → Console 标签
2. 复制 `STOCKS_PAGE_HTTP_MONITOR.js` 的内容
3. 粘贴到 Console 中并回车执行
4. 进行市场操作
5. 在 Console 中运行统计命令

```javascript
// 打印详细统计
window.__httpMonitor.printStats()

// 导出数据
window.__httpMonitor.exportJson()
```

- [ ] 监控脚本成功加载
- [ ] 统计信息已显示
- [ ] 总请求数符合预期

**验证统计结果**:
- [ ] `📈 总请求数`: **1** (一次市场选择)
- [ ] `💡 [诊断结果]`: 显示 `✅ [最优]` 标记
- [ ] 无 `❌ [严重问题]` 警告

### 步骤 5: Code Review (10 分钟)

提交代码修改供 review:

```powershell
# 1. 查看修改
git diff frontend/src/ui/StocksNewsIndex.tsx

# 2. 添加修改
git add frontend/src/ui/StocksNewsIndex.tsx

# 3. 提交修改
git commit -m "优化: 移除 StocksNewsIndex 的预加载机制

- 问题: 市场切换时触发 30+ 个后台 API 请求
- 解决: 改为只加载第1页，翻页时按需加载
- 改动:
  * 添加缓存键机制 (cacheKeyRef + buildCacheKey)
  * 在 load() 中添加缓存检查
  * 删除 loadRemainingPages() 调用
  * 新增 loadPageOnDemand() 函数
- 效果: HTTP 请求数 97% 减少 (31 → 1)，初始加载 5x 加速

测试: ✅ 一次切换 1 个请求, ✅ 重复切换 0 新请求"
```

- [ ] 修改已查看
- [ ] 修改已提交
- [ ] 提交信息清晰准确

---

## 🧪 测试结果记录

### 本地测试结果

**测试日期**: `_______`  
**测试人员**: `_______`  
**测试环境**: Node `_______`, npm `_______`

#### 测试 1: 首次加载
- [ ] ✅ 通过 / [ ] ❌ 失败
- 观察: HTTP 请求数 = _____ (预期: 1)
- 加载时间 = _____ ms (预期: <1000)

#### 测试 2: 重复切换
- [ ] ✅ 通过 / [ ] ❌ 失败
- 港股切换请求数 = _____ (预期: 1)
- A股复切请求数 = _____ (预期: 0)

#### 测试 3: 翻页加载
- [ ] ✅ 通过 / [ ] ❌ 失败
- 翻页请求数 = _____ (预期: 1)
- 翻页时间 = _____ ms (预期: <500)

#### 测试 4: 监控脚本
- [ ] ✅ 脚本加载成功
- [ ] ✅ 统计信息显示
- [ ] ✅ 诊断结果为 "最优"

### 问题记录

如有任何失败，记录如下:

**问题 1**:
- 症状: ___________________
- 日志: ___________________
- 可能原因: ___________________
- 处理方案: ___________________

**问题 2**: ...

---

## 📦 Code Review 检查表

Code reviewer 需检查:

- [ ] **代码正确性**: 逻辑是否正确，是否有语法错误
- [ ] **缓存键机制**: 是否正确生成和使用缓存键
- [ ] **缓存检查**: `load()` 中的缓存检查逻辑是否完整
- [ ] **预加载移除**: `loadRemainingPages()` 调用是否已删除
- [ ] **按需加载**: `loadPageOnDemand()` 函数逻辑是否正确
- [ ] **错误处理**: 是否有 try-catch 和错误提示
- [ ] **日志记录**: 是否有足够的 console.log 用于调试
- [ ] **性能**: 是否没有引入新的性能问题
- [ ] **向后兼容**: 是否不影响其他功能
- [ ] **文档**: 是否有必要的注释说明

### Review 意见

审查人: `_______`  
审查日期: `_______`  
最终意见:
- [ ] ✅ 批准合并
- [ ] ❌ 需要修改
- [ ] ⚠️   建议改进

修改建议: ___________________

---

## 🚀 部署到生产

### 部署前检查

- [ ] 所有本地测试已通过
- [ ] Code Review 已批准
- [ ] 没有合并冲突
- [ ] 文档已更新
- [ ] 团队成员已知晓

### 部署步骤

```bash
# 1. 构建生产版本
npm run build

# 2. 提交到版本控制
git push origin main

# 3. (如果使用 CI/CD) 等待自动部署
# 或
# (如果手动部署) 部署到生产环境
```

- [ ] 构建成功
- [ ] 代码已推送
- [ ] 部署流程已启动

### 部署后验证

```powershell
# 1. 访问生产环境
# 进入: https://yoursite.com/stocks

# 2. 打开 DevTools → Network
# 3. 进行市场切换测试
# 4. 观察 HTTP 请求数
```

- [ ] 生产环境页面可访问
- [ ] HTTP 请求数符合预期 (1 个)
- [ ] 无错误日志
- [ ] 用户反馈无异常

### 监控计划

部署后 24-48 小时内监控:

- [ ] 错误率是否正常
- [ ] API 响应时间是否改善
- [ ] 用户反馈是否有投诉
- [ ] 浏览器兼容性是否有问题

---

## 📊 完成标志

全部检查完成 ✅:

- [ ] ✅ 代码改动已应用
- [ ] ✅ 编译无错误
- [ ] ✅ 本地测试全部通过 (4/4)
- [ ] ✅ Code Review 已批准
- [ ] ✅ 已部署到生产环境
- [ ] ✅ 生产环境验证通过
- [ ] ✅ 用户反馈无异常

---

## 📞 回滚计划 (如需要)

如果出现问题，可以快速回滚:

```bash
# 1. 恢复备份文件
cp frontend/src/ui/StocksNewsIndex.tsx.backup frontend/src/ui/StocksNewsIndex.tsx

# 2. 重新构建
npm run build

# 3. 重新部署
git push origin main
```

- [ ] 备份文件已保存
- [ ] 回滚命令已记录
- [ ] 如需回滚，可快速执行

---

**优化项目**: 股票筛选页面 HTTP 请求优化  
**开始日期**: `_______`  
**完成日期**: `_______`  
**负责人**: `_______`  

---

*此清单确保优化平稳、安全地部署到生产环境*
