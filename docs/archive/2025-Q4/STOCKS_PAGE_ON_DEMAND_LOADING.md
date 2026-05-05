# 📋 股票资讯前端优化方案 - 按需加载页面

## 🎯 问题分析

### 当前问题
```
❌ 用户每次改变查询条件（market/search）都会重新加载所有页面
❌ 即使用户只看第1页，后台仍在加载2-31页
❌ 造成不必要的API调用（可能30+个请求）
❌ 浪费带宽和服务器资源
```

### 不应该的做法
```tsx
// 当前实现 - 不好的做法
当用户改变 market 或 search 条件 → 触发 load() → 加载第1页 → 自动后台加载所有页面
结果: 31个API请求，3-5秒延迟
```

### 应该的做法
```tsx
// 改进方案 - 按需加载
当用户改变条件 → 触发 load() → 只加载第1页 → 显示第1页数据
用户翻页到第N页 → 才加载第N页 → 只发1个API请求
结果: 按需发送请求，快速响应
```

---

## 🔧 改进方案详解

### 核心理念
1. **按需加载** - 用户看哪一页，才加载哪一页
2. **缓存管理** - 已加载的页面缓存，避免重复加载
3. **快速响应** - 第一页立即显示，后续页面按需加载

### 具体改进

#### 改进 1: 修改 load() 函数 - 只加载第一页

```tsx
const load = React.useCallback(async (isInitialLoad = true) => {
  // 防抖和状态检查
  const now = Date.now()
  if (now - lastLoadTimeRef.current < 5000) return
  if (isLoadingData) return
  
  setIsLoadingData(true)
  lastLoadTimeRef.current = now
  
  try {
    // ✅ 只加载第1页
    const firstPageUrl = buildApiUrl(
      `/api/news/stocks/progress?page=1&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`
    )
    
    const firstPageRes = await fetch(firstPageUrl, { cache: 'no-store' })
    if (!firstPageRes.ok) throw new Error(await firstPageRes.text())
    
    const firstPageData = await firstPageRes.json()
    const firstPageItems = firstPageData.stocks_detail || []
    
    // ✅ 清空缓存（因为市场/过滤条件变了）
    allItemsCacheRef.current = [...firstPageItems]
    loadingPagesRef.current.clear()
    
    // ✅ 立即显示第1页数据（应用前端搜索过滤）
    let displayItems = firstPageItems.map((stock: any) => ({
      symbol: stock.symbol,
      name: stock.name,
      completion_percentage: stock.completion_percentage,
      fields_filled: stock.fields_filled,
      total_fields: stock.total_fields,
      article_count: stock.article_count || 0
    }))
    
    if (q.trim()) {
      displayItems = filterBySearch(displayItems, q)
    }
    
    setItems(displayItems)
    setTotal(firstPageData.total_stocks || 0)
    setProgress({
      ...firstPageData,
      stocks_detail: firstPageItems
    })
    
    // ❌ 删除这部分：不再自动加载剩余页面
    // if (isInitialLoad && (firstPageData.total_stocks || 0) > 100) {
    //   loadRemainingPages(...)  // ← 删除这行
    // }
    
  } catch (e: any) {
    console.error('加载数据失败:', e)
  } finally {
    setIsLoadingData(false)
  }
}, [showInvalid, q, market])
```

#### 改进 2: 添加按需加载函数 - 用户翻页时调用

```tsx
// ✨ 新增：按需加载特定页面
const loadPageOnDemand = React.useCallback(async (targetPage: number) => {
  // 检查页面是否已缓存
  const pageStartIdx = (targetPage - 1) * 100
  const pageEndIdx = targetPage * 100
  
  if (allItemsCacheRef.current.length >= pageEndIdx) {
    console.log(`✅ 页面 ${targetPage} 已在缓存中，直接使用`)
    displayCachedPage(targetPage)
    return
  }
  
  // 检查是否正在加载
  if (loadingPagesRef.current.has(targetPage)) {
    console.log(`⏳ 页面 ${targetPage} 正在加载，请稍候...`)
    return
  }
  
  // 加载目标页面
  loadingPagesRef.current.add(targetPage)
  
  try {
    console.log(`📥 加载第 ${targetPage} 页...`)
    
    const pageUrl = buildApiUrl(
      `/api/news/stocks/progress?page=${targetPage}&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`
    )
    
    const pageRes = await fetch(pageUrl, { cache: 'no-store' })
    if (!pageRes.ok) throw new Error(await pageRes.text())
    
    const pageData = await pageRes.json()
    const pageItems = pageData.stocks_detail || []
    
    // 添加到缓存
    allItemsCacheRef.current.push(...pageItems)
    
    console.log(`✅ 第 ${targetPage} 页加载完成，共 ${pageItems.length} 条`)
    
    // 显示该页数据
    displayCachedPage(targetPage)
    
  } catch (e: any) {
    console.error(`❌ 加载第 ${targetPage} 页失败:`, e)
  } finally {
    loadingPagesRef.current.delete(targetPage)
  }
}, [showInvalid, q, market])

// 辅助函数：显示缓存中的某一页
const displayCachedPage = React.useCallback((pageNum: number) => {
  const pageStartIdx = (pageNum - 1) * 100
  const pageEndIdx = Math.min(pageNum * 100, allItemsCacheRef.current.length)
  
  const pageItems = allItemsCacheRef.current.slice(pageStartIdx, pageEndIdx)
  
  let displayItems = pageItems.map((stock: any) => ({
    symbol: stock.symbol,
    name: stock.name,
    completion_percentage: stock.completion_percentage,
    fields_filled: stock.fields_filled,
    total_fields: stock.total_fields,
    article_count: stock.article_count || 0
  }))
  
  // 应用前端搜索过滤
  if (q.trim()) {
    displayItems = filterBySearch(displayItems, q)
  }
  
  setItems(displayItems)
  setPage(pageNum)
}, [q])
```

#### 改进 3: 修改分页组件 - 翻页时调用按需加载

```tsx
// 当用户点击翻页时调用
const handlePageChange = (newPage: number) => {
  if (newPage === page) return  // 同一页，不用加载
  
  console.log(`📄 用户翻页到第 ${newPage} 页`)
  
  setPage(newPage)
  loadPageOnDemand(newPage)  // ✨ 按需加载
  
  // 滚动到顶部
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
```

#### 改进 4: 优化搜索 - 在已加载的缓存中搜索

```tsx
const performFrontendSearch = React.useCallback((searchQuery: string) => {
  console.log(`🔍 在 ${allItemsCacheRef.current.length} 条已加载数据中搜索: "${searchQuery}"`)
  
  if (!searchQuery.trim()) {
    // 搜索框为空：显示当前页数据
    displayCachedPage(page)
    return
  }
  
  // 在缓存中搜索
  const filtered = filterBySearch(allItemsCacheRef.current, searchQuery)
  
  let displayItems = filtered.map((stock: any) => ({
    symbol: stock.symbol,
    name: stock.name,
    completion_percentage: stock.completion_percentage,
    fields_filled: stock.fields_filled,
    total_fields: stock.total_fields,
    article_count: stock.article_count || 0
  }))
  
  setItems(displayItems)
  setPage(1)  // 重置到第1页
  
  console.log(`✅ 找到 ${displayItems.length} 条匹配结果`)
}, [page])

// 辅助函数：按搜索词过滤
const filterBySearch = (items: any[], searchQuery: string) => {
  const searchLower = searchQuery.toLowerCase()
  const looksLikeCode = /^[0-9.]+$/.test(searchLower)
  
  return items.filter((stock: any) => {
    if (looksLikeCode) {
      return stock.symbol.toLowerCase() === searchLower || 
             stock.symbol.toLowerCase().startsWith(searchLower)
    } else {
      return stock.name?.toLowerCase().includes(searchLower)
    }
  })
}
```

---

## 📊 改进前后对比

| 指标 | 改进前 | 改进后 | 改进 |
|------|--------|--------|------|
| **初始加载** | 30+ 个请求 | 1 个请求 | 97% ⬇️ |
| **初始加载时间** | 3-5 秒 | <0.5 秒 | 6-10x ⬆️ |
| **翻到第2页** | 已加载（预加载） | 按需加载 | 用户才需要才加载 |
| **改变市场** | 重新加载30+页 | 只加载第1页 | 97% ⬇️ |
| **改变搜索条件** | 重新加载30+页 | 在已加载数据中搜索 | 97% ⬇️ |
| **用户体验** | 初始卡顿3-5秒 | 快速响应 + 按需加载 | 显著改善 ✨ |

---

## 🎯 实施步骤

### 步骤1: 修改 load() 函数
- 删除 `loadRemainingPages()` 的自动调用
- 只保留加载第1页的逻辑

### 步骤2: 添加新的 loadPageOnDemand() 函数
- 检查缓存是否已有
- 按需调用API加载

### 步骤3: 修改分页组件
- 翻页时调用 `loadPageOnDemand()`

### 步骤4: 测试验证
- 打开开发者工具 > Network 标签
- 改变市场、搜索条件 → 验证只发1个请求
- 翻页到第2页 → 验证才发起1个请求

---

## 💡 关键要点

✅ **用户看第1页** → 加载第1页 (1个请求)  
✅ **用户翻到第2页** → 加载第2页 (1个请求，共2个)  
✅ **用户改变市场** → 清空缓存重新加载第1页 (1个请求)  
✅ **用户搜索** → 在已加载数据中搜索 (0个请求)  
✅ **用户翻回第1页** → 从缓存读取 (0个请求)

---

## 🔍 HTTP监控验证

使用浏览器开发者工具验证优化效果：

```javascript
// 在浏览器Console中运行
let requestCount = 0;
const originalFetch = window.fetch;
window.fetch = function(...args) {
  if (args[0].includes('/api/news/stocks/progress')) {
    requestCount++;
    console.log(`📊 第 ${requestCount} 个请求: ${args[0]}`);
  }
  return originalFetch.apply(this, args);
};

// 现在改变市场或搜索条件，观察请求数
// 改进后应该只看到 1 个请求，不是 30+ 个
```

---

## 📝 注意事项

1. **缓存大小** - 根据内存情况考虑限制缓存页数
2. **缓存失效** - 改变市场/过滤条件时清空缓存
3. **加载状态** - 提示用户正在加载该页
4. **错误处理** - 某页加载失败时提示用户重试
5. **搜索范围** - 搜索只在已加载的数据中进行（可以提示用户"仅搜索已加载数据"）

---

## 🚀 额外优化建议

### 1. 智能预加载（可选）
```tsx
// 用户快到底时才预加载下一页
const handleScroll = () => {
  if (isNearBottom && nextPage < totalPages && !loadingPagesRef.current.has(nextPage)) {
    loadPageOnDemand(nextPage);
  }
}
```

### 2. 搜索提示
```tsx
// 提示用户搜索范围
if (q.trim() && allItemsCacheRef.current.length < total) {
  return <div>仅搜索已加载的 {allItemsCacheRef.current.length} 条数据，共 {total} 条</div>
}
```

### 3. 虚拟滚动（高级）
```tsx
// 使用虚拟滚动库处理大数据量
// 只渲染可见区域的行，大幅提升性能
```

---

**改进效果**: 从每次30+个请求 → 按需1个请求，API调用减少 97%，用户体验大幅改善！🎉
