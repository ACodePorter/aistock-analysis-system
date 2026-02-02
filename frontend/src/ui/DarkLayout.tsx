import React from 'react'

interface NavItem {
  id: string
  label: string
  icon: string
}

const navItems: NavItem[] = [
  { id: 'dashboard', label: '市场总览', icon: '📊' },
  { id: 'analysis', label: '深度分析', icon: '🔍' },
  { id: 'strategy', label: '策略中心', icon: '🎯' },
  { id: 'monitor', label: '情报监控', icon: '📡' },
]

const reportItems: NavItem[] = [
  { id: 'daily', label: '每日复盘', icon: '📋' },
  { id: 'settings', label: '平台设置', icon: '⚙️' },
]

interface DarkLayoutProps {
  children: React.ReactNode
  currentPage?: string
  onNavigate?: (page: string) => void
  title?: string
  subtitle?: string
}

export default function DarkLayout({ 
  children, 
  currentPage = 'dashboard',
  onNavigate,
  title = '市场监控中心',
  subtitle = 'AI Stock Intelligence'
}: DarkLayoutProps) {
  return (
    <div className="dark-shell">
      {/* Sidebar */}
      <aside className="dark-sidebar">
        {/* Brand */}
        <div className="dark-sidebar-brand">
          <div className="dark-sidebar-brand-icon">📈</div>
          <div className="dark-sidebar-brand-text">
            <div className="dark-sidebar-brand-title">AI 监控中心</div>
            <div className="dark-sidebar-brand-sub">A-Share Intelligence</div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="dark-nav">
          {navItems.map(item => (
            <div
              key={item.id}
              className={`dark-nav-item ${currentPage === item.id ? 'active' : ''}`}
              onClick={() => onNavigate?.(item.id)}
            >
              <span className="dark-nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </div>
          ))}
          
          <div className="dark-nav-section">数据报告</div>
          
          {reportItems.map(item => (
            <div
              key={item.id}
              className={`dark-nav-item ${currentPage === item.id ? 'active' : ''}`}
              onClick={() => onNavigate?.(item.id)}
            >
              <span className="dark-nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </div>
          ))}
        </nav>

        {/* User Footer */}
        <div className="dark-sidebar-footer">
          <div className="dark-sidebar-user">
            <div className="dark-sidebar-avatar" />
            <div className="dark-sidebar-user-info">
              <div className="dark-sidebar-user-name">高级研究员</div>
              <div className="dark-sidebar-user-role">AI 节点已连接</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="dark-main">
        {/* Header */}
        <header className="dark-header">
          <div className="dark-header-indices">
            <div className="dark-header-index">
              <div className="dark-header-index-label">
                <span>上证指数</span>
                <span className="accent-lime">+0.45%</span>
              </div>
              <div className="dark-header-index-value">3,052.12</div>
            </div>
            
            <div className="dark-header-divider" />
            
            <div className="dark-header-index">
              <div className="dark-header-index-label">
                <span>深证成指</span>
                <span className="accent-red">-0.12%</span>
              </div>
              <div className="dark-header-index-value">9,414.05</div>
            </div>
            
            <div className="dark-header-divider" />
            
            <div className="dark-header-index">
              <div className="dark-header-index-label">
                <span>创业板指</span>
                <span className="accent-lime">+0.88%</span>
              </div>
              <div className="dark-header-index-value">1,820.41</div>
            </div>
          </div>

          <div className="dark-header-actions">
            <div className="dark-header-status">
              <div className="dark-header-status-dot" />
              <span className="dark-header-status-text">实时数据流</span>
            </div>
            
            <button className="dark-btn-ghost" title="通知">
              🔔
            </button>
            
            <div className="dark-search">
              <span className="dark-search-icon">🔍</span>
              <input 
                type="text" 
                className="dark-search-input" 
                placeholder="搜索代码/简称..."
              />
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="dark-content">
          <div className="dark-content-inner">
            {children}
          </div>
        </div>
      </main>
    </div>
  )
}
