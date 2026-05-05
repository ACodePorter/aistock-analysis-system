import React from 'react'
import ReactDOM from 'react-dom'
import type { WatchlistSearchResult } from '../HomeWatchlistSearchSection'
import type { WatchItem } from './useHomeWatchlistControls'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips } from '../../config/helpTips'

type Props = {
  current?: string
  watch: WatchItem[]
  name: string
  searching: boolean
  error?: string
  searchResults: WatchlistSearchResult[]
  showSearchModal: boolean
  professionalMode: boolean
  onNameChange: (value: string) => void
  onSearch: () => void
  onSelectSymbol: (symbol: string) => void
  onToggleSearchResultPin: (stock: WatchlistSearchResult) => void
  onCloseModal: () => void
  onOpenManager: () => void
  onModeChange: (professional: boolean) => void
  onRefresh: () => void
}

function displayName(item?: Pick<WatchItem, 'name' | 'symbol'>) {
  if (!item) return '未选择股票'
  return item.name && item.name.trim() ? `${item.name} ${item.symbol}` : item.symbol
}

export default function StockPoolSelectorBar({
  current,
  watch,
  name,
  searching,
  error,
  searchResults,
  showSearchModal,
  professionalMode,
  onNameChange,
  onSearch,
  onSelectSymbol,
  onToggleSearchResultPin,
  onCloseModal,
  onOpenManager,
  onModeChange,
  onRefresh,
}: Props) {
  const pinnedWatch = React.useMemo(() => watch.filter(item => item.pinned), [watch])
  const currentItem = watch.find(item => item.symbol === current)

  return (
    <section
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 25,
        margin: '0 12px 12px',
        border: '1px solid var(--border)',
        borderRadius: 8,
        background: 'rgba(15,23,42,0.96)',
        backdropFilter: 'blur(14px)',
        boxShadow: '0 18px 48px -34px rgba(0,0,0,0.9)',
        overflow: 'hidden',
      }}
    >
      <div style={{ padding: 12, display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) auto auto', gap: 12, alignItems: 'center' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--text-muted)', fontSize: 11, fontWeight: 850, marginBottom: 6 }}>
            股票池控制器
            <HelpTooltip {...helpTips.stockSearch} placement="right"><HelpIcon /></HelpTooltip>
          </div>
          <div style={{ position: 'relative' }}>
            <input
              value={name}
              onChange={event => onNameChange(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  onSearch()
                }
              }}
              placeholder="搜索代码/名称，回车查看匹配股票"
              className="dark-input"
              style={{ width: '100%', paddingRight: searching ? 86 : 12 }}
            />
            {searching && <span style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--primary)', fontSize: 12 }}>搜索中</span>}
          </div>
          {error && <div style={{ color: '#fca5a5', fontSize: 11, marginTop: 5 }}>{error}</div>}
        </div>

        <div style={{ minWidth: 210 }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 11, fontWeight: 850, marginBottom: 6, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            当前查看
            <HelpTooltip {...helpTips.currentSelectedStock}><HelpIcon /></HelpTooltip>
          </div>
          <div style={{ color: 'var(--text)', fontWeight: 900, fontSize: 14, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {displayName(currentItem || (current ? { symbol: current } : undefined))}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
          <div style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
            <HelpTooltip {...helpTips.normalMode}><button type="button" onClick={() => onModeChange(false)} className="dark-tab" style={{ borderRadius: 0, background: professionalMode ? 'transparent' : 'rgba(99,102,241,0.24)', color: professionalMode ? 'var(--text-muted)' : 'var(--text)' }}>普通</button></HelpTooltip>
            <HelpTooltip {...helpTips.professionalMode}><button type="button" onClick={() => onModeChange(true)} className="dark-tab" style={{ borderRadius: 0, borderLeft: '1px solid var(--border)', background: professionalMode ? 'rgba(99,102,241,0.24)' : 'transparent', color: professionalMode ? 'var(--text)' : 'var(--text-muted)' }}>专业</button></HelpTooltip>
          </div>
          <HelpTooltip {...helpTips.refreshPlaybook}><button type="button" className="dark-btn dark-btn-secondary" onClick={onRefresh}>刷新</button></HelpTooltip>
          <HelpTooltip {...helpTips.manageStockPool}><button type="button" className="dark-btn dark-btn-secondary" onClick={onOpenManager}>管理</button></HelpTooltip>
        </div>
      </div>

      <div style={{ borderTop: '1px solid var(--border)', padding: '9px 12px', display: 'flex', gap: 8, alignItems: 'center' }}>
        <HelpTooltip {...helpTips.stockPoolTags} placement="right"><HelpIcon /></HelpTooltip>
        <div style={{ display: 'flex', gap: 7, overflowX: 'auto', minWidth: 0, flex: 1, paddingBottom: 1 }}>
          {(pinnedWatch.length ? pinnedWatch : watch).slice(0, 30).map(item => {
            const active = current === item.symbol
            return (
              <button
                key={item.symbol}
                type="button"
                onClick={() => onSelectSymbol(item.symbol)}
                style={{
                  flex: '0 0 auto',
                  padding: '6px 10px',
                  borderRadius: 999,
                  border: active ? '1px solid rgba(99,102,241,0.75)' : '1px solid var(--border)',
                  background: active ? 'rgba(99,102,241,0.22)' : 'rgba(255,255,255,0.025)',
                  color: active ? 'var(--text)' : 'var(--text-muted)',
                  fontSize: 12,
                  fontWeight: active ? 850 : 650,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {item.name || item.symbol}
              </button>
            )
          })}
          {watch.length === 0 && <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>暂无股票池数据，请先添加关注股票。</span>}
        </div>
      </div>

      {showSearchModal && ReactDOM.createPortal(
        <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.62)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onCloseModal}>
          <div style={{ width: 520, maxWidth: '92vw', maxHeight: '82vh', overflow: 'auto', border: '1px solid var(--border)', background: 'var(--surface-dark)', borderRadius: 8, padding: 18 }} onClick={event => event.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 12 }}>
              <div style={{ color: 'var(--text)', fontWeight: 900 }}>{searchResults.length ? `匹配到 ${searchResults.length} 只股票` : '未找到匹配股票'}</div>
              <HelpTooltip {...helpTips.closeDialog}>
                <button type="button" className="dark-btn dark-btn-secondary" onClick={onCloseModal}>关闭</button>
              </HelpTooltip>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {searchResults.map(stock => (
                <div key={stock.ts_code} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ color: 'var(--text)', fontWeight: 850 }}>{stock.name}</div>
                    <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{stock.ts_code}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <HelpTooltip {...helpTips.stockSearchResultView}>
                      <button type="button" className="dark-btn dark-btn-primary" onClick={() => { onSelectSymbol(stock.ts_code); onCloseModal() }}>查看</button>
                    </HelpTooltip>
                    <HelpTooltip {...helpTips.stockSearchResultPin} content={stock.pinned ? '取消置顶后，这只股票仍可保留在股票池中，但不会优先出现在首页顶部。切换股票后，交易剧本、预测图表、复盘和专业数据都会同步更新。' : helpTips.stockSearchResultPin.content}>
                      <button type="button" className="dark-btn dark-btn-secondary" onClick={() => onToggleSearchResultPin(stock)}>{stock.pinned ? '取消置顶' : '置顶'}</button>
                    </HelpTooltip>
                  </div>
                </div>
              ))}
              {searchResults.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 20, textAlign: 'center' }}>请换一个名称或代码重试。</div>}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </section>
  )
}