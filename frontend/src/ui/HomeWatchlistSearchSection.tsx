import React from 'react'
import ReactDOM from 'react-dom'

export type WatchlistSearchResult = {
  ts_code: string
  symbol: string
  name: string
  market: string
  pinned?: boolean
}

type HomeWatchlistSearchSectionProps = {
  name: string
  onNameChange: (value: string) => void
  searching: boolean
  error?: string
  searchResults: WatchlistSearchResult[]
  showSearchModal: boolean
  onSearch: () => void
  onSelectResult: (stock: WatchlistSearchResult) => void
  onCloseModal: () => void
}

export default function HomeWatchlistSearchSection({
  name,
  onNameChange,
  searching,
  error,
  searchResults,
  showSearchModal,
  onSearch,
  onSelectResult,
  onCloseModal,
}: HomeWatchlistSearchSectionProps) {
  return (
    <>
      <div style={{display:'flex', gap:6, marginBottom:0, alignItems:'center'}}>
        <div style={{position:'relative', display:'flex', alignItems:'center', flex:1}}>
          <input
            placeholder="搜索自选股票池中的股票，置顶到首页看板..."
            value={name}
            onChange={event => onNameChange(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') {
                console.log('Enter pressed, searching stocks')
                event.preventDefault()
                onSearch()
              }
            }}
            autoComplete="off"
            style={{
              width:'100%',
              background: searching ? 'rgba(99, 102, 241, 0.1)' : 'var(--surface-dark)',
              borderColor: searching ? 'var(--primary)' : 'var(--border)',
              border:'1px solid',
              borderRadius:'8px',
              padding:'12px 16px',
              paddingRight: searching ? '100px' : '16px',
              fontSize:'14px',
              color:'var(--text)',
            }}
          />
          {searching && (
            <div style={{
              position:'absolute',
              right:'16px',
              top:'50%',
              transform:'translateY(-50%)',
              fontSize:'12px',
              color:'var(--primary)',
              pointerEvents:'none',
              fontWeight:'500',
            }}>
              搜索中...
            </div>
          )}
        </div>
      </div>
      {error && <div style={{color:'red', fontSize:'12px', marginBottom:12}}>{error}</div>}

      {showSearchModal && ReactDOM.createPortal(
        <div style={{position:'fixed', top:0, left:0, width:'100vw', height:'100vh', background:'rgba(0,0,0,0.5)', zIndex:9999, display:'flex', alignItems:'center', justifyContent:'center'}} onClick={onCloseModal}>
          <div style={{background:'var(--surface-dark)', borderRadius:12, padding:24, minWidth:360, maxWidth:520, border:'1px solid var(--border)'}} onClick={event => event.stopPropagation()}>
            <div style={{fontWeight:600, fontSize:16, marginBottom:12, color:'var(--text)'}}>
              {searchResults.length > 0 ? `匹配到 ${searchResults.length} 只股票` : '未找到匹配的股票'}
            </div>

            {searchResults.length === 0 && (
              <div style={{textAlign:'center', padding:'40px 0', color:'#6b7280'}}>
                <div style={{fontSize:'48px', marginBottom:'12px'}}>🔍</div>
                <div>没有找到匹配的股票</div>
                <div style={{fontSize:'12px', marginTop:'8px'}}>请尝试使用不同的关键词搜索</div>
              </div>
            )}

            {searchResults.length > 0 && (
              <div style={{maxHeight:400, overflowY:'auto'}}>
                {searchResults.map(stock => {
                  const isPinned = !!stock.pinned
                  return (
                    <div key={stock.ts_code} style={{padding:'10px 0', borderBottom:'1px solid var(--border)', display:'flex', alignItems:'center', justifyContent:'space-between'}}>
                      <div>
                        <div style={{fontWeight:500, color:'var(--text)'}}>
                          {isPinned && <span style={{marginRight:4}}>📌</span>}
                          {stock.name}
                        </div>
                        <div style={{fontSize:'12px', color:'var(--text-muted)'}}>{stock.ts_code}</div>
                      </div>
                      <button
                        style={{
                          padding:'6px 14px',
                          border: isPinned ? '1px solid rgba(245,158,11,0.3)' : '1px solid rgba(99,102,241,0.3)',
                          borderRadius:6,
                          background: isPinned ? 'rgba(245,158,11,0.1)' : 'rgba(99,102,241,0.1)',
                          color: isPinned ? '#f59e0b' : 'var(--primary)',
                          cursor:'pointer',
                          fontSize:'12px',
                          fontWeight:'500',
                        }}
                        onClick={event => {
                          event.preventDefault()
                          event.stopPropagation()
                          onSelectResult(stock)
                        }}
                      >
                        {isPinned ? '取消置顶' : '📌 置顶到看板'}
                      </button>
                    </div>
                  )
                })}
              </div>
            )}

            <button
              className="dark-btn dark-btn-secondary"
              style={{marginTop:16, cursor:'pointer', width:'100%'}}
              onClick={onCloseModal}
            >
              关闭
            </button>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}