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
    <div style={{
      fontFamily: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial',
      background: '#f9fafb',
      minHeight: '100vh',
      color: '#111827',
      padding: '16px'
    }}>
      <div style={{maxWidth: '1600px', margin: '0 auto'}}>
        {/* 返回按钮 */}
        <div style={{marginBottom: '16px'}}>
          <button 
            onClick={onBack} 
            style={{
              padding: '8px 16px',
              border: '1px solid #e5e7eb',
              borderRadius: '8px',
              background: '#fff',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 600,
              color: '#374151',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'all 0.2s'
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = '#f3f4f6';
              (e.currentTarget as HTMLButtonElement).style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = '#fff';
              (e.currentTarget as HTMLButtonElement).style.boxShadow = 'none';
            }}
          >
            ← 返回
          </button>
        </div>

        <div style={{marginBottom: '20px'}}>
          <h1 style={{margin: '0 0 8px 0', fontSize: '28px', fontWeight: 700}}>
            📊 {symbol}
          </h1>
          <p style={{margin: 0, color: '#6b7280', fontSize: '14px'}}>
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
            background: '#fff',
            borderRadius: '12px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            overflow: 'hidden'
          }}>
            {/* 文章头部 */}
            <div style={{
              padding: '24px',
              borderBottom: '1px solid #e5e7eb',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div>
                <h2 style={{margin: '0 0 4px 0', fontSize: '18px', fontWeight: 700}}>
                  📰 相关资讯
                </h2>
                <p style={{margin: 0, fontSize: '13px', color: '#6b7280'}}>
                  共 {articles.length} 条资讯
                </p>
              </div>
              <label style={{fontSize: '13px', color: '#6b7280', display: 'flex', alignItems: 'center', gap: '8px'}}>
                <input 
                  type='checkbox' 
                  checked={includeContent} 
                  onChange={e=> setIncludeContent(e.target.checked)}
                  style={{cursor: 'pointer'}}
                />
                <span>显示完整内容</span>
              </label>
            </div>

            {/* 文章列表 */}
            <div style={{padding: '20px'}}>
              {loading ? (
                <div style={{textAlign: 'center', padding: '40px 20px', color: '#9ca3af'}}>
                  ⏳ 加载中...
                </div>
              ) : articles.length === 0 ? (
                <div style={{textAlign: 'center', padding: '40px 20px', color: '#9ca3af'}}>
                  <div style={{fontSize: '32px', marginBottom: '12px'}}>📭</div>
                  暂无相关资讯
                </div>
              ) : (
                <div style={{display: 'flex', flexDirection: 'column', gap: '12px'}}>
                  {articles.map((article, idx) => (
                    <div
                      key={`${article.id}-${idx}`}
                      style={{
                        padding: '16px',
                        background: '#f9fafb',
                        borderRadius: '10px',
                        border: '1px solid #e5e7eb',
                        transition: 'all 0.2s',
                        cursor: 'pointer'
                      }}
                      onMouseEnter={(e) => {
                        (e.currentTarget as HTMLDivElement).style.background = '#f0f9ff';
                        (e.currentTarget as HTMLDivElement).style.borderColor = '#0ea5e9';
                        (e.currentTarget as HTMLDivElement).style.boxShadow = '0 4px 12px rgba(6,182,212,0.1)';
                      }}
                      onMouseLeave={(e) => {
                        (e.currentTarget as HTMLDivElement).style.background = '#f9fafb';
                        (e.currentTarget as HTMLDivElement).style.borderColor = '#e5e7eb';
                        (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
                      }}
                    >
                      {/* 文章标题 */}
                      <a
                        href={article.url}
                        target='_blank'
                        rel='noreferrer'
                        style={{
                          textDecoration: 'none',
                          color: '#1f2937',
                          fontSize: '14px',
                          fontWeight: 600,
                          lineHeight: '1.5',
                          display: 'block',
                          marginBottom: '8px',
                          transition: 'color 0.2s'
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLAnchorElement).style.color = '#0ea5e9';
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLAnchorElement).style.color = '#1f2937';
                        }}
                      >
                        {article.title}
                      </a>

                      {/* 摘要 */}
                      {(article.summary || (includeContent && article.content)) && (
                        <p style={{
                          margin: '8px 0',
                          fontSize: '12px',
                          lineHeight: '1.5',
                          color: '#6b7280'
                        }}>
                          {article.summary || article.content?.slice(0, 150)}...
                        </p>
                      )}

                      {/* 元数据 */}
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginTop: '10px',
                        paddingTop: '10px',
                        borderTop: '1px solid #e5e7eb',
                        fontSize: '11px',
                        color: '#9ca3af'
                      }}>
                        <div style={{display: 'flex', gap: '12px'}}>
                          {article.source && <span>📌 {article.source}</span>}
                          {article.published_at && (
                            <span>🕐 {new Date(article.published_at).toLocaleDateString('zh-CN')}</span>
                          )}
                        </div>
                        <button
                          onClick={() => sendFeedback(article.url)}
                          style={{
                            padding: '4px 8px',
                            fontSize: '11px',
                            border: '1px solid #d1d5db',
                            background: '#fff',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            color: '#6b7280',
                            transition: 'all 0.2s'
                          }}
                          onMouseEnter={(e) => {
                            (e.currentTarget as HTMLButtonElement).style.background = '#f3f4f6';
                            (e.currentTarget as HTMLButtonElement).style.borderColor = '#9ca3af';
                          }}
                          onMouseLeave={(e) => {
                            (e.currentTarget as HTMLButtonElement).style.background = '#fff';
                            (e.currentTarget as HTMLButtonElement).style.borderColor = '#d1d5db';
                          }}
                        >
                          报错
                        </button>
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
                borderTop: '1px solid #e5e7eb',
                display: 'flex',
                justifyContent: 'center',
                gap: '8px',
                alignItems: 'center'
              }}>
                <button
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page === 1}
                  style={{
                    padding: '6px 12px',
                    fontSize: '13px',
                    border: '1px solid #d1d5db',
                    borderRadius: '6px',
                    background: page === 1 ? '#f3f4f6' : '#fff',
                    cursor: page === 1 ? 'not-allowed' : 'pointer',
                    opacity: page === 1 ? 0.5 : 1
                  }}
                >
                  ← 上一页
                </button>
                <span style={{fontSize: '13px', color: '#6b7280'}}>
                  第 {page} 页
                </span>
                <button
                  onClick={() => setPage(page + 1)}
                  style={{
                    padding: '6px 12px',
                    fontSize: '13px',
                    border: '1px solid #d1d5db',
                    borderRadius: '6px',
                    background: '#fff',
                    cursor: 'pointer'
                  }}
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
