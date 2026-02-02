import React from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'
import CompanyInfoPanel from './CompanyInfoPanel'

interface ArticleItem {
  id: number
  title: string
  url: string
  summary?: string | null
  content?: string | null
  published_at?: string | null
  source?: string | null
}

export default function StockNewsDetail({ symbol, onBack }: { symbol: string; onBack: ()=>void }){
  const [articles, setArticles] = React.useState<ArticleItem[]>([])
  const [loading, setLoading] = React.useState(false)
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(20)
  const [includeContent, setIncludeContent] = React.useState(false)
  const loadArticles = React.useCallback(async ()=>{
    setLoading(true)
    try{
      const url = new URL(buildApiUrl(API_ENDPOINTS.NEWS.ARTICLES))
      url.searchParams.set('symbol', symbol)
      url.searchParams.set('limit', String(pageSize))
      url.searchParams.set('offset', String((page-1)*pageSize))
      url.searchParams.set('include_content', includeContent? 'true':'false')
      const r = await fetch(url.toString())
      if(!r.ok) throw new Error(await r.text())
      const j = await r.json()
      setArticles(j.articles||[])
    }catch(e:any){ console.error(e) }
    finally{ setLoading(false) }
  },[symbol,page,pageSize,includeContent])

  React.useEffect(()=>{ loadArticles() },[loadArticles])

  const sendFeedback = async (url:string) => {
    try{
      const r = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.CRAWLER_FEEDBACK),{
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ url, symbol, notes: '内容不全或抽取错误' })
      })
      if(!r.ok) throw new Error(await r.text())
      alert('已反馈，我们会优化该站点解析。')
    }catch(e:any){ alert('反馈失败: '+ (e.message||e)) }
  }

  return (
    <div>
      <div className="page-container" style={{maxWidth: '1600px', margin: '0 auto'}}>
        {/* 返回按钮 */}
        <div style={{marginBottom: '16px'}}>
          <button onClick={onBack} className="dark-btn dark-btn-secondary">← 返回</button>
        </div>

        <div style={{marginBottom: '20px'}}>
          <h1 style={{margin: '0 0 8px 0', fontSize: '28px', fontWeight: 700, color: 'var(--text)'}}>
            📊 {symbol}
          </h1>
          <p style={{margin: 0, color: 'var(--text-muted)', fontSize: '14px'}}>
            股票详情 · 公司画像与相关资讯
          </p>
        </div>

        {/* 双栏布局：左侧公司信息 + 右侧新闻列表 */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '380px 1fr',
          gap: '20px',
          alignItems: 'flex-start'
        }}>
          {/* 左侧：公司画像面板 */}
          <div style={{position: 'sticky', top: '20px'}}>
            <CompanyInfoPanel symbol={symbol} />
          </div>

          {/* 右侧：相关文章 */}
          <div style={{
            background: 'var(--surface-dark)',
            borderRadius: '12px',
            border: '1px solid var(--border)',
            overflow: 'hidden'
          }}>
            {/* 文章头部 */}
            <div style={{
              padding: '24px',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div>
                <h2 style={{margin: '0 0 4px 0', fontSize: '18px', fontWeight: 700}}>
                  📰 相关资讯
                </h2>
                <p style={{margin: 0, fontSize: '13px', color: 'var(--text-muted)'}}>
                  共 {articles.length} 条资讯
                </p>
              </div>
              <label style={{fontSize: '13px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '8px'}}>
                <input 
                  type='checkbox' 
                  checked={includeContent} 
                  onChange={e=> setIncludeContent(e.target.checked)}
                  className="app-search"
                />
                <span>显示完整内容</span>
              </label>
            </div>

            {/* 文章列表 */}
            <div style={{padding: '20px'}}>
              {loading ? (
                <div style={{textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)'}}>
                  ⏳ 加载中...
                </div>
              ) : articles.length === 0 ? (
                <div style={{textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)'}}>
                  <div style={{fontSize: '32px', marginBottom: '12px'}}>📭</div>
                  暂无相关资讯
                </div>
              ) : (
                <div style={{display: 'flex', flexDirection: 'column', gap: '12px'}}>
                  {articles.map((article, idx) => (
                      <div key={`${article.id}-${idx}`} className="card-panel article-card">
                      {/* 文章标题 */}
                      <a href={article.url} target='_blank' rel='noreferrer' className="article-link">{article.title}</a>

                      {/* 摘要 */}
                      {(article.summary || (includeContent && article.content)) && (
                        <p style={{
                          margin: '8px 0',
                          fontSize: '12px',
                          lineHeight: '1.5',
                          color: 'var(--text-muted)'
                        }}>
                          {article.summary || article.content?.slice(0, 150)}...
                        </p>
                      )}

                      {/* 元数据 */}
                      <div className="article-meta">
                        <div className="meta-left">
                          {article.source && <span>📌 {article.source}</span>}
                          {article.published_at && <span>🕐 {new Date(article.published_at).toLocaleDateString('zh-CN')}</span>}
                        </div>
                        <button onClick={() => sendFeedback(article.url)} className="dark-btn dark-btn-secondary">报错</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 分页 */}
            {articles.length > 0 && (
              <div style={{
                padding: '20px',
                borderTop: '1px solid var(--border)',
                display: 'flex',
                justifyContent: 'center',
                gap: '8px',
                alignItems: 'center'
              }}>
                <button
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page === 1}
                  className="dark-btn dark-btn-secondary"
                  style={{
                    opacity: page === 1 ? 0.5 : 1,
                    cursor: page === 1 ? 'not-allowed' : 'pointer'
                  }}
                >
                  ← 上一页
                </button>
                <span style={{fontSize: '13px', color: 'var(--text-muted)'}}>
                  第 {page} 页
                </span>
                <button
                  onClick={() => setPage(page + 1)}
                  className="dark-btn dark-btn-secondary"
                >
                  下一页 →
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
