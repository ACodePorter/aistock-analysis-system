import React, { useEffect, useMemo, useState } from 'react'
import { List, Spin, Alert, Input, Pagination, Select, DatePicker, Modal, Form, Button, message, Tag, Popconfirm } from 'antd'
import dayjs from 'dayjs'
import { buildApiUrl, API_ENDPOINTS } from '../config/api'

type Article = {
  id: number | string
  title: string
  url?: string
  source?: string
  published_at?: string | null
  summary?: string | null
  sentiment_type?: string | null
  sentiment_score?: number | null
  related_stocks?: string[] | null
}

export default function NewsManagement() {
  const [articles, setArticles] = useState<Article[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState<string>('')
  const [page, setPage] = useState<number>(1)
  const pageSize = 10
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [sentimentFilter, setSentimentFilter] = useState<string>('all')
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null)
  const [globalTotal, setGlobalTotal] = useState<number | null>(null)
  const [fetchingGlobal, setFetchingGlobal] = useState(false)
  const [editing, setEditing] = useState<Article | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const sources = useMemo(() => Array.from(new Set(articles.map(a => a.source || '').filter(Boolean))), [articles])

  // Compute filtered list and current page items with stable hook order
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    let filtered = q
      ? articles.filter(a => (a.title || '').toLowerCase().includes(q) || (a.summary || '').toLowerCase().includes(q))
      : articles.slice()

    if (sourceFilter !== 'all') filtered = filtered.filter(a => (a.source || '') === sourceFilter)

    if (sentimentFilter !== 'all') {
      filtered = filtered.filter(a => {
        const s = (a as any).sentiment ?? 0
        if (sentimentFilter === 'positive') return s > 0.1
        if (sentimentFilter === 'neutral') return Math.abs(s) <= 0.1
        return s < -0.1
      })
    }

    if (dateRange && dateRange[0] && dateRange[1]) {
      const start = dateRange[0]!.startOf('day')
      const end = dateRange[1]!.endOf('day')
      filtered = filtered.filter(a => {
        if (!a.published_at) return false
        const d = dayjs(a.published_at)
        return d.isValid() && (d.isAfter(start) || d.isSame(start)) && (d.isBefore(end) || d.isSame(end))
      })
    }

    return filtered
  }, [articles, query, sourceFilter, sentimentFilter, dateRange])

  const pageArticles = useMemo(() => {
    const start = (page - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, page, pageSize])

  const openEdit = (article: Article) => {
    setEditing(article)
    form.setFieldsValue({
      title: article.title,
      summary: article.summary,
      sentiment_type: article.sentiment_type || undefined,
      sentiment_score: article.sentiment_score,
      related_stocks: (article.related_stocks || []).join(',')
    })
  }

  const handleDelete = async (id: number | string) => {
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.DELETE(id)), { method: 'DELETE' })
      if (!res.ok) throw new Error('删除失败')
      setArticles(prev => prev.filter(a => a.id !== id))
      message.success('已删除')
    } catch (e:any) {
      message.error(e.message || '删除失败')
    }
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      if (!editing) return
      setSaving(true)
      const payload: any = {}
      ;['title','summary','sentiment_type','sentiment_score'].forEach(k => {
        if (values[k] !== undefined && values[k] !== editing[k as keyof Article]) payload[k] = values[k]
      })
      if (values.related_stocks !== undefined) {
        const arr = String(values.related_stocks).split(',').map((s:string)=>s.trim()).filter(Boolean)
        payload.related_stocks = arr
      }
      const res = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.UPDATE(editing.id)), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!res.ok) throw new Error('保存失败')
      const data = await res.json()
      if (data.status === 'success') {
        setArticles(prev => prev.map(a => a.id === editing.id ? { ...a, ...data.article } : a))
        message.success('已保存')
        setEditing(null)
      } else {
        message.info(data.message || '无更新')
      }
    } catch (e:any) {
      if (e?.errorFields) return; // 表单验证错误
      message.error(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    let mounted = true
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.ARTICLES))
        if (!res.ok) throw new Error(`状态码 ${res.status}`)
        const data = await res.json()
        if (!mounted) return
        // Expecting an array at top-level or { articles: [...] }
        if (Array.isArray(data)) setArticles(data)
        else if (Array.isArray(data.articles)) setArticles(data.articles)
        else setArticles([])
      } catch (e: any) {
        if (!mounted) return
        setError(e?.message || String(e))
        setArticles([])
      } finally {
        if (mounted) setLoading(false)
      }
    }

    load()
    const loadGlobal = async () => {
      setFetchingGlobal(true)
      try {
        const r = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.STATS))
        if (r.ok) {
          const d = await r.json()
            if (typeof d.total_articles === 'number') setGlobalTotal(d.total_articles)
            else if (d?.stats?.total_articles) setGlobalTotal(d.stats.total_articles)
        }
      } catch (e) { /* ignore */ } finally { setFetchingGlobal(false) }
    }
    loadGlobal()
    return () => { mounted = false }
  }, [])

  return (
    <>
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: 'var(--surface-dark)',
        padding: '24px',
        fontFamily: "'Inter', 'Noto Sans SC', sans-serif",
        color: 'var(--text)',
      }}
    >
      <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>新闻管理 · 实时索引</div>
            <h2 style={{ margin: 0, fontSize: 22, color: 'var(--text)' }}>新闻管理中枢</h2>
          </div>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <Input.Search
              placeholder="按关键词搜索标题或摘要"
              allowClear
              enterButton
              onSearch={(v) => { setQuery(v || ''); setPage(1) }}
              onChange={e => { if (!e.target.value) setQuery('') }}
              style={{ minWidth: 320 }}
            />
          </div>
        </div>

        {error && <Alert type="error" message="加载新闻失败" description={error} />}

        {loading && <div style={{ padding: 40, textAlign: 'center' }}><Spin /></div>}

        {!loading && !error && (
          <div style={{ display: 'flex', gap: 18 }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div style={{ fontSize: 14, color: '#6b7280' }}>
                  {filtered.length} 条新闻{globalTotal !== null && <span style={{ marginLeft: 8, color: '#4b5563' }}>（全局总数 {globalTotal}{fetchingGlobal ? '…' : ''}）</span>}
                </div>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <Select value={sourceFilter} onChange={v => { setSourceFilter(v); setPage(1) }} style={{ minWidth: 140 }}>
                    <Select.Option value="all">所有来源</Select.Option>
                    {sources.map(s => <Select.Option key={s} value={s}>{s}</Select.Option>)}
                  </Select>
                  <Select value={sentimentFilter} onChange={v => { setSentimentFilter(v); setPage(1) }} style={{ width: 140 }}>
                    <Select.Option value="all">全部情绪</Select.Option>
                    <Select.Option value="positive">正面</Select.Option>
                    <Select.Option value="neutral">中性</Select.Option>
                    <Select.Option value="negative">负面</Select.Option>
                  </Select>
                  <DatePicker.RangePicker value={dateRange as any} onChange={(r) => { setDateRange(r as any); setPage(1) }} />
                </div>
              </div>

              <List
                grid={{ gutter: 16, column: 1 }}
                dataSource={pageArticles}
                renderItem={(item: Article) => {
                  const sentimentColor = item.sentiment_type === 'positive' ? 'green' : item.sentiment_type === 'negative' ? 'red' : 'default'
                  return (
                    <List.Item key={String(item.id)}>
                      <div className="card-panel" style={{ padding: 16 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
                              {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : item.title}
                            </div>
                            <div style={{ marginTop: 6, fontSize: 13, color: '#6b7280', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                              <span>{item.source || '未知来源'} {item.published_at ? '· ' + item.published_at : ''}</span>
                              {item.sentiment_type && <Tag color={sentimentColor}>{item.sentiment_type}</Tag>}
                              {typeof item.sentiment_score === 'number' && <Tag>{item.sentiment_score.toFixed(2)}</Tag>}
                              {(item.related_stocks || []).slice(0,3).map(s => <Tag key={s}>{s}</Tag>)}
                            </div>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <Button size="small" onClick={() => openEdit(item)}>编辑</Button>
                            <Popconfirm title="确认删除?" okText="删除" cancelText="取消" onConfirm={() => handleDelete(item.id)}>
                              <Button size="small" danger>删除</Button>
                            </Popconfirm>
                          </div>
                        </div>
                        <div style={{ marginTop: 12, color: '#374151', fontSize: 14 }}>{item.summary}</div>
                      </div>
                    </List.Item>
                  )
                }}
              />

              <div style={{ textAlign: 'center', marginTop: 8 }}>
                <Pagination current={page} pageSize={pageSize} total={filtered.length} onChange={(p) => setPage(p)} showSizeChanger={false} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
    <Modal
      open={!!editing}
      title={`编辑新闻 #${editing?.id}`}
      onCancel={() => setEditing(null)}
      onOk={handleSave}
      confirmLoading={saving}
      width={720}
      destroyOnClose
    >
      <Form layout="vertical" form={form} preserve={false}>
        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
          <Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} />
        </Form.Item>
        <Form.Item name="summary" label="摘要">
          <Input.TextArea autoSize={{ minRows: 3, maxRows: 6 }} />
        </Form.Item>
        <Form.Item name="sentiment_type" label="情绪类型">
          <Select allowClear placeholder="选择情绪">
            <Select.Option value="positive">positive</Select.Option>
            <Select.Option value="neutral">neutral</Select.Option>
            <Select.Option value="negative">negative</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="sentiment_score" label="情绪分值">
          <Input type="number" step={0.01} placeholder="-1 ~ 1" />
        </Form.Item>
        <Form.Item name="related_stocks" label="关联股票 (逗号分隔)">
          <Input placeholder="000001.SZ,600519.SH" />
        </Form.Item>
      </Form>
    </Modal>
    </>
  )
}