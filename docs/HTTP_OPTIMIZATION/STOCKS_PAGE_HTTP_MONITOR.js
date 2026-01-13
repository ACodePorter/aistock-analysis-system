#!/usr/bin/env node

/**
 * 股票页面 HTTP 请求监控脚本
 * 
 * 用途: 记录并验证前端发起的 HTTP 请求数
 * 使用: 在浏览器开发者工具的 Console 中粘贴此代码
 * 
 * 功能:
 * 1. 拦截所有 fetch 请求
 * 2. 记录 /api/news/stocks/progress 的请求
 * 3. 统计请求数和耗时
 * 4. 检测是否有过多的后台加载请求
 * 5. 生成优化建议
 */

// ===== 请求监控器 =====
window.__httpMonitor = {
  requests: [],
  startTime: Date.now(),
  
  // 记录请求
  recordRequest(url, method, startTime, endTime, status) {
    const duration = endTime - startTime
    const isStocksApi = url.includes('/api/news/stocks/progress')
    
    if (isStocksApi) {
      this.requests.push({
        url,
        method,
        duration,
        status,
        timestamp: new Date().toLocaleTimeString(),
        page: this.extractPageParam(url),
        market: this.extractMarketParam(url),
      })
      
      console.log(`📡 [HTTP] ${method} ${url.split('?')[1]} (${duration}ms, 状态: ${status})`)
    }
  },
  
  // 提取页码参数
  extractPageParam(url) {
    const match = url.match(/page=(\d+)/)
    return match ? parseInt(match[1]) : 1
  },
  
  // 提取市场参数
  extractMarketParam(url) {
    const match = url.match(/market=([^&]+)/)
    if (match) {
      try {
        return decodeURIComponent(match[1])
      } catch (e) {
        return match[1]
      }
    }
    return '未知'
  },
  
  // 获取统计信息
  getStats() {
    const total = this.requests.length
    const byPage = {}
    const byMarket = {}
    const byStatus = {}
    let totalDuration = 0
    
    this.requests.forEach(req => {
      // 按页码统计
      byPage[req.page] = (byPage[req.page] || 0) + 1
      
      // 按市场统计
      byMarket[req.market] = (byMarket[req.market] || 0) + 1
      
      // 按状态统计
      byStatus[req.status] = (byStatus[req.status] || 0) + 1
      
      // 累计耗时
      totalDuration += req.duration
    })
    
    return {
      total,
      byPage,
      byMarket,
      byStatus,
      averageDuration: total > 0 ? (totalDuration / total).toFixed(2) : 0,
      totalDuration
    }
  },
  
  // 打印统计信息
  printStats() {
    const stats = this.getStats()
    
    console.clear()
    console.log('='.repeat(60))
    console.log('📊 [HTTP 请求监控统计]')
    console.log('='.repeat(60))
    console.log(``)
    
    console.log(`📈 总请求数: ${stats.total}`)
    console.log(`⏱️  平均耗时: ${stats.averageDuration}ms`)
    console.log(`🕐 总耗时: ${stats.totalDuration}ms`)
    console.log(``)
    
    console.log('📄 按页码统计:')
    Object.entries(stats.byPage).forEach(([page, count]) => {
      const isPreload = parseInt(page) > 1
      const icon = isPreload ? '⚠️  [预加载]' : '✅ [主请求]'
      console.log(`  ${icon} 第 ${page} 页: ${count} 次请求`)
    })
    console.log('')
    
    console.log('🗂️  按市场统计:')
    Object.entries(stats.byMarket).forEach(([market, count]) => {
      console.log(`  📍 ${market}: ${count} 次请求`)
    })
    console.log('')
    
    console.log('🔢 按HTTP状态统计:')
    Object.entries(stats.byStatus).forEach(([status, count]) => {
      const icon = status === 200 ? '✅' : '❌'
      console.log(`  ${icon} ${status}: ${count} 次`)
    })
    console.log('')
    
    console.log('='.repeat(60))
    console.log('💡 [诊断结果]')
    console.log('='.repeat(60))
    
    const pageCount = Object.keys(stats.byPage).length
    const preloadCount = Object.entries(stats.byPage)
      .filter(([page]) => parseInt(page) > 1)
      .reduce((sum, [, count]) => sum + count, 0)
    
    if (stats.total === 1) {
      console.log('✅ [最优] 只有 1 个请求，说明优化已完全生效')
      console.log('   用户无需等待任何后台加载')
    } else if (stats.total <= 3) {
      console.log('⚠️  [良好] 共 ' + stats.total + ' 个请求')
      console.log('   说明有少量预加载，可以接受')
    } else if (pageCount <= 3) {
      console.log('⚠️  [待改进] 共 ' + stats.total + ' 个请求，但只涉及前 ' + pageCount + ' 页')
      console.log('   这是可以接受的，说明优化部分生效')
    } else {
      console.log('❌ [严重问题] 共 ' + stats.total + ' 个请求，涉及 ' + pageCount + ' 页')
      console.log('   说明还在进行大量的后台预加载！')
      console.log('')
      console.log('📌 [建议]')
      console.log('   1. 检查 loadRemainingPages() 是否被移除')
      console.log('   2. 检查 load() 函数第 225-227 行是否已删除')
      console.log('   3. 在浏览器 DevTools 中按 Ctrl+Shift+J 找到详细错误信息')
    }
    
    if (preloadCount > 0) {
      console.log(``)
      console.log(`⚠️  [检测到预加载] 第 2 页及之后的请求数: ${preloadCount}`)
      console.log(`   这可能是 loadRemainingPages() 导致的`)
    }
    
    console.log(``)
    console.log('📋 [所有请求详情]')
    console.table(this.requests)
    
    console.log('')
    console.log('💾 [导出数据]')
    console.log(`window.__httpMonitor.exportJson()  // 导出为 JSON`)
    console.log(`window.__httpMonitor.exportCsv()   // 导出为 CSV`)
  },
  
  // 导出 JSON
  exportJson() {
    const data = {
      timestamp: new Date().toISOString(),
      stats: this.getStats(),
      requests: this.requests
    }
    const json = JSON.stringify(data, null, 2)
    console.log(json)
    return json
  },
  
  // 导出 CSV
  exportCsv() {
    let csv = '时间,方法,页码,市场,耗时(ms),状态\n'
    this.requests.forEach(req => {
      csv += `${req.timestamp},${req.method},${req.page},${req.market},${req.duration},${req.status}\n`
    })
    console.log(csv)
    return csv
  },
  
  // 重置监控
  reset() {
    this.requests = []
    this.startTime = Date.now()
    console.log('🔄 [监控已重置]')
  },
  
  // 清空请求列表但保留监控继续运行
  clear() {
    this.requests = []
    console.log('🗑️  [请求列表已清空]')
  },
}

// ===== 拦截 fetch =====
const originalFetch = window.fetch
window.fetch = function(...args) {
  const startTime = Date.now()
  const url = typeof args[0] === 'string' ? args[0] : args[0].url
  const method = (args[1]?.method || 'GET').toUpperCase()
  
  return originalFetch.apply(this, args)
    .then(response => {
      const endTime = Date.now()
      const status = response.status
      
      // 记录请求
      window.__httpMonitor.recordRequest(url, method, startTime, endTime, status)
      
      return response
    })
    .catch(error => {
      const endTime = Date.now()
      
      // 记录失败的请求
      window.__httpMonitor.recordRequest(url, method, startTime, endTime, 'ERROR')
      
      throw error
    })
}

// ===== 快捷命令 =====
console.log(`
╔════════════════════════════════════════════════════════════╗
║        股票页面 HTTP 请求监控 - 已激活 ✅                 ║
╚════════════════════════════════════════════════════════════╝

📊 监控已启动，所有 /api/news/stocks/progress 请求都会被记录

📋 快速命令:

  window.__httpMonitor.printStats()     // 打印详细统计信息
  window.__httpMonitor.reset()          // 重置监控（清空数据）
  window.__httpMonitor.clear()          // 仅清空数据但继续监控
  window.__httpMonitor.exportJson()     // 导出为 JSON 格式
  window.__httpMonitor.exportCsv()      // 导出为 CSV 格式

🧪 测试步骤:

  1. 打开此网页
  2. 执行此脚本 (Ctrl+Shift+J → 粘贴)
  3. 选择市场 (如 "A股")
  4. 等待 3 秒加载完成
  5. 执行: window.__httpMonitor.printStats()
  6. 查看结果

✅ 优化目标:
  - 第一次选择市场: 1 个请求
  - 重复选择同市场: 0 个请求 (缓存)
  - 翻页: 1 个请求/页

❌ 问题标志:
  - 选择市场时 30+ 个请求 → 说明还有后台预加载
  - 涉及 page=2,3,4... 的大量请求 → loadRemainingPages() 未移除

推荐: 在浏览器 DevTools → Network 标签配合查看效果更直观

`)

// 立即执行一次空的初始化，确保脚本成功加载
console.log('✨ 监控已准备好，可以开始测试了')
