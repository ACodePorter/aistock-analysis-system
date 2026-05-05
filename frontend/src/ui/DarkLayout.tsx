import React from 'react'
import {
  BellOutlined,
  DashboardOutlined,
  FileTextOutlined,
  LineChartOutlined,
  MessageOutlined,
  RadarChartOutlined,
  SearchOutlined,
  SettingOutlined,
  ShareAltOutlined,
  SlidersOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../config/helpTips'

interface NavItem {
  id: string
  label: string
  icon: React.ComponentType
  tip: HelpTipKey
  badge?: string
  badgeTone?: 'info' | 'neutral'
  disabled?: boolean
}

interface NavSection {
  title: string
  items: NavItem[]
}

interface MarketIndexItem {
  label: string
  value: string
  changePct: string
  tone?: 'up' | 'down' | 'flat'
}

const navSections: NavSection[] = [
  {
    title: '核心',
    items: [
      { id: 'dashboard', label: '市场总览', icon: DashboardOutlined, tip: 'menuMarketOverview' },
      { id: 'analysis', label: '深度分析', icon: SearchOutlined, tip: 'menuDeepAnalysis' },
      { id: 'strategy', label: '策略中心', icon: SlidersOutlined, tip: 'menuStrategyCenter' },
      { id: 'monitor', label: '情报监控', icon: RadarChartOutlined, tip: 'menuIntelligence' },
    ],
  },
  {
    title: '报告',
    items: [
      { id: 'daily', label: '每日复盘', icon: FileTextOutlined, tip: 'menuDailyReview' },
      { id: 'settings', label: '平台设置', icon: SettingOutlined, tip: 'menuSettings' },
    ],
  },
  {
    title: 'Agent',
    items: [
      { id: 'agent-chat', label: 'Agent Chat', icon: MessageOutlined, tip: 'menuSettings', badge: 'Ask', badgeTone: 'info' },
      { id: 'agent-skills', label: 'Skill 管理', icon: ToolOutlined, tip: 'menuSettings' },
      { id: 'agent-logs', label: 'Agent 日志', icon: ShareAltOutlined, tip: 'menuSettings' },
    ],
  },
]

const defaultMarketIndices: MarketIndexItem[] = [
  { label: '上证指数', value: '3,052.12', changePct: '+0.45%', tone: 'up' },
  { label: '深证成指', value: '9,414.05', changePct: '-0.12%', tone: 'down' },
  { label: '创业板指', value: '1,820.41', changePct: '+0.88%', tone: 'up' },
]

interface DarkLayoutProps {
  children: React.ReactNode
  currentPage?: string
  onNavigate?: (page: string) => void
  title?: string
  subtitle?: string
  marketIndices?: MarketIndexItem[]
}

function SidebarNavItem({ item, active, onNavigate }: Readonly<{ item: NavItem; active: boolean; onNavigate?: (page: string) => void }>) {
  const Icon = item.icon
  const className = ['dark-nav-item', active ? 'active' : '', item.disabled ? 'dark-nav-item-disabled' : ''].filter(Boolean).join(' ')
  return (
    <HelpTooltip {...helpTips[item.tip]} placement="right">
      <button
        type="button"
        className={className}
        aria-current={active ? 'page' : undefined}
        disabled={item.disabled}
        onClick={() => {
          if (!item.disabled) onNavigate?.(item.id)
        }}
      >
        <span className="dark-nav-icon" aria-hidden="true"><Icon /></span>
        <span className="dark-nav-label">{item.label}</span>
        {item.badge && <span className="dark-nav-badge" data-tone={item.badgeTone || 'neutral'}>{item.badge}</span>}
      </button>
    </HelpTooltip>
  )
}

function SidebarSection({ section, currentPage, onNavigate }: Readonly<{ section: NavSection; currentPage: string; onNavigate?: (page: string) => void }>) {
  return (
    <div className="dark-nav-group">
      <div className="dark-nav-section">{section.title}</div>
      {section.items.map(item => (
        <SidebarNavItem key={item.id} item={item} active={currentPage === item.id} onNavigate={onNavigate} />
      ))}
    </div>
  )
}

function AppSidebar({ currentPage, onNavigate }: Readonly<{ currentPage: string; onNavigate?: (page: string) => void }>) {
  return (
    <aside className="dark-sidebar">
      <div className="dark-sidebar-brand">
        <div className="dark-sidebar-brand-icon"><LineChartOutlined /></div>
        <div className="dark-sidebar-brand-text">
          <div className="dark-sidebar-brand-title">AI 监控中心</div>
          <div className="dark-sidebar-brand-sub">A-Share Intelligence</div>
        </div>
      </div>

      <nav className="dark-nav">
        {navSections.map(section => (
          <SidebarSection key={section.title} section={section} currentPage={currentPage} onNavigate={onNavigate} />
        ))}
      </nav>

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
  )
}

export default function DarkLayout({ 
  children, 
  currentPage = 'dashboard',
  onNavigate,
  title = '市场监控中心',
  subtitle = 'AI Stock Intelligence',
  marketIndices = defaultMarketIndices,
}: Readonly<DarkLayoutProps>) {
  return (
    <div className="dark-shell">
      <AppSidebar currentPage={currentPage} onNavigate={onNavigate} />

      {/* Main Content */}
      <main className="dark-main">
        {/* Header */}
        <header className="dark-header">
          <div className="dark-header-left">
            <div className="dark-header-title-block">
              <div className="dark-header-title">{title}</div>
              <div className="dark-header-subtitle">{subtitle}</div>
            </div>

            <HelpTooltip {...helpTips.marketIndices}>
              <div className="dark-header-indices" aria-label="主要市场指数">
              {marketIndices.map((item, index) => (
                <React.Fragment key={item.label}>
                  <div className="dark-header-index">
                    <div className="dark-header-index-label">
                      <span>{item.label}</span>
                      <span className={`dark-header-index-change ${item.tone || 'flat'}`}>{item.changePct}</span>
                    </div>
                    <div className="dark-header-index-value">{item.value}</div>
                  </div>
                  {index < marketIndices.length - 1 && <div className="dark-header-divider" />}
                </React.Fragment>
              ))}
              </div>
            </HelpTooltip>
          </div>

          <div className="dark-header-actions">
            <HelpTooltip {...helpTips.realtimeDataStatus}>
              <div className="dark-header-status">
                <div className="dark-header-status-dot" />
                <span className="dark-header-status-text">实时数据流</span>
              </div>
            </HelpTooltip>
            
            <HelpTooltip {...helpTips.notificationCenter}>
              <button className="dark-btn-ghost" aria-label="通知中心">
                <BellOutlined />
              </button>
            </HelpTooltip>
            
            <HelpTooltip {...helpTips.headerSearch}>
              <div className="dark-search">
                <span className="dark-search-icon"><SearchOutlined /></span>
                <input 
                  type="text" 
                  className="dark-search-input" 
                  placeholder="搜索代码/简称..."
                />
                <HelpIcon />
              </div>
            </HelpTooltip>
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
