import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent } from './card';
import { Input as AntInput, Select, Button as AntButton, Tag, Checkbox, Space, List, Typography, Empty, Statistic, message, Modal } from 'antd';
import { SearchOutlined, ReloadOutlined, SettingOutlined, ClearOutlined, ExportOutlined, StarFilled, StarOutlined, EyeOutlined, SmileOutlined, FrownOutlined, MehOutlined } from '@ant-design/icons';
import { buildApiUrl, API_ENDPOINTS } from '../config/api';
import dayjs from 'dayjs';

interface NewsArticle {
  id: number;
  title: string;
  url: string;
  summary: string;
  published_at: string | number | null;
  source: string;
  sentiment_type: 'positive' | 'negative' | 'neutral';
  sentiment_score: number;
  relevance_score: number;
  related_stocks?: string[] | null;
  keywords?: string[] | null;
  is_bookmarked?: boolean;
  is_read?: boolean;
  category?: string;
  tags?: string[];
}

interface NewsStats {
  total_articles: number;
  today_articles: number;
  positive_sentiment: number;
  negative_sentiment: number;
  neutral_sentiment: number;
  top_sources: Array<{ source: string; count: number }>;
  top_stocks: Array<{ stock: string; count: number }>;
}

interface FilterOptions {
  sentiment: 'all' | 'positive' | 'negative' | 'neutral';
  source: string;
  stock: string;
  category: string;
  dateRange: 'all' | 'today' | 'week' | 'month';
  isBookmarked: boolean | null;
  isRead: boolean | null;
}

export default function NewsManagement() {
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [filteredArticles, setFilteredArticles] = useState<NewsArticle[]>([]);
  const [stats, setStats] = useState<NewsStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedArticles, setSelectedArticles] = useState<Set<number>>(new Set());
  // Simplified: only list view is supported
  const [showFilters, setShowFilters] = useState(false);
  const [pageSize, setPageSize] = useState<number>(50);
  const [offset, setOffset] = useState<number>(0);
  const [hasMore, setHasMore] = useState<boolean>(true);
  const [backfilling, setBackfilling] = useState<boolean>(false);

  const [filters, setFilters] = useState<FilterOptions>({
    sentiment: 'all',
    source: '',
    stock: '',
    category: '',
    dateRange: 'all',
    isBookmarked: null,
    isRead: null,
  });

  // Helpers defined before use to avoid TDZ issues
  const formatDate = (dateVal: string | number | null | undefined) => {
    const raw = String(dateVal ?? '').trim();
    if (!raw) return '时间未知';
    let d: dayjs.Dayjs;
    if (/^\d+$/.test(raw)) { const num = Number(raw); d = dayjs(num < 1e12 ? num * 1000 : num); }
    else d = dayjs(raw);
    if (!d.isValid() || d.year() < 2000) return '时间未知';
    return d.format('YYYY-MM-DD HH:mm');
  };

  const parsePublished = (dateVal: string | number | null | undefined): dayjs.Dayjs | null => {
    const raw = String(dateVal ?? '').trim();
    if (!raw) return null;
    let d: dayjs.Dayjs;
    if (/^\d+$/.test(raw)) { const num = Number(raw); d = dayjs(num < 1e12 ? num * 1000 : num); }
    else d = dayjs(raw);
    if (!d.isValid() || d.year() < 2000) return null;
    return d;
  };

  const activeFiltersCount = useMemo(() => {
    let count = 0;
    if (filters.sentiment !== 'all') count++;
    if (filters.source) count++;
    if (filters.stock) count++;
    if (filters.category) count++;
    if (filters.dateRange !== 'all') count++;
    if (filters.isBookmarked === true) count++;
    if (filters.isRead === true) count++;
    if (searchQuery.trim()) count++;
    return count;
  }, [filters, searchQuery]);

  const resetFilters = () => {
    setFilters({ sentiment: 'all', source: '', stock: '', category: '', dateRange: 'all', isBookmarked: null, isRead: null });
    setSearchQuery('');
  };

  const loadNews = async ({ reset = false }: { reset?: boolean } = {}) => {
    if (reset) {
      setLoading(true);
      setHasMore(true);
      setOffset(0);
    } else {
      setLoadingMore(true);
    }
    try {
      const query = `?limit=${pageSize}&offset=${reset ? 0 : offset}`;
      const response = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.ARTICLES + query));
      const data = await response.json();
      let list: NewsArticle[] = [];
      if (data.articles) list = data.articles;
      else if (Array.isArray(data)) list = data as NewsArticle[];
      if (reset) {
        setArticles(list || []);
        setOffset(list.length);
      } else {
        setArticles((prev) => [...prev, ...(list || [])]);
        setOffset((prev) => prev + list.length);
      }
      // If returned less than requested, there's no more data
      if ((list?.length || 0) < pageSize) setHasMore(false);
    } catch (e) {
      console.error('Failed to load news:', e);
      if (reset) setArticles([]);
      setHasMore(false);
    } finally {
      if (reset) setLoading(false);
      else setLoadingMore(false);
    }
  };

  const loadStats = async () => {
    try {
      const res = await fetch(buildApiUrl('/api/news/stats'));
      if (res.ok) setStats(await res.json());
    } catch (e) {
      console.error('Failed to load stats:', e);
    }
  };

  const runBackfill = async () => {
    Modal.confirm({
      title: '补充文章内容与摘要',
      content: '将对缺少内容或摘要的文章进行补充处理（最多50篇）。是否继续？',
      okText: '开始',
      cancelText: '取消',
      onOk: async () => {
        setBackfilling(true);
        try {
          const url = buildApiUrl('/api/news/backfill?limit=50&only_missing_summary=true&only_missing_content=true');
          const res = await fetch(url, { method: 'POST' });
          if (!res.ok) {
            const t = await res.text();
            throw new Error(t || `HTTP ${res.status}`);
          }
          const data = await res.json();
          message.success(`补充完成：处理${data.processed}，更新内容${data.updated_content}，更新摘要${data.updated_summary}`);
          await loadNews({ reset: true });
          await loadStats();
        } catch (err: any) {
          console.error('Backfill failed:', err);
          message.error(`补充失败：${String(err?.message || err)}`);
        } finally {
          setBackfilling(false);
        }
      }
    });
  };

  const applyFilters = useMemo(() => {
    return articles.filter((a) => {
      if (filters.sentiment !== 'all' && a.sentiment_type !== filters.sentiment) return false;
      if (filters.source && a.source !== filters.source) return false;
      if (filters.stock && !a.related_stocks?.includes(filters.stock)) return false;
      if (filters.category && a.category !== filters.category) return false;
      if (filters.dateRange !== 'all') {
        const d = parsePublished(a.published_at);
        if (!d) return false;
        if (filters.dateRange === 'today') {
          if (d.isBefore(dayjs().startOf('day'))) return false;
        } else if (filters.dateRange === 'week') {
          if (d.isBefore(dayjs().subtract(7, 'day').startOf('day'))) return false;
        } else if (filters.dateRange === 'month') {
          if (d.isBefore(dayjs().subtract(30, 'day').startOf('day'))) return false;
        }
      }
      if (filters.isBookmarked !== null && a.is_bookmarked !== filters.isBookmarked) return false;
      if (filters.isRead !== null && a.is_read !== filters.isRead) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const text = `${a.title} ${a.summary} ${a.keywords?.join(' ')} ${a.related_stocks?.join(' ')}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });
  }, [articles, filters, searchQuery]);

  useEffect(() => setFilteredArticles(applyFilters), [applyFilters]);
  // When filters or search query change, reset pagination and reload from first page
  useEffect(() => {
    // Clear current list and selections, then reload
    loadNews({ reset: true });
    setSelectedArticles(new Set());
  }, [filters.sentiment, filters.source, filters.stock, filters.category, filters.dateRange, filters.isBookmarked, filters.isRead, searchQuery]);
  useEffect(() => { loadNews({ reset: true }); loadStats(); }, []);

  const toggleArticleSelection = (id: number) => {
    const s = new Set(selectedArticles);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelectedArticles(s);
  };
  const selectAllArticles = () => {
    if (selectedArticles.size === filteredArticles.length) setSelectedArticles(new Set());
    else setSelectedArticles(new Set(filteredArticles.map((a) => a.id)));
  };
  const toggleBookmark = async (id: number) => {
    try {
      const res = await fetch(buildApiUrl(`/api/news/${id}/bookmark`), { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setArticles((prev) => prev.map((a) => (a.id === id ? { ...a, is_bookmarked: data?.is_bookmarked ?? !a.is_bookmarked } : a)));
        message.success(data?.is_bookmarked ? '已添加收藏' : '已取消收藏');
      } else {
        const text = await res.text();
        message.error(`收藏操作失败: ${text || res.status}`);
      }
    } catch (e) { console.error(e); message.error('收藏操作失败'); }
  };
  const toggleReadStatus = async (id: number) => {
    try {
      const res = await fetch(buildApiUrl(`/api/news/${id}/read`), { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setArticles((prev) => prev.map((a) => (a.id === id ? { ...a, is_read: data?.is_read ?? !a.is_read } : a)));
        message.success(data?.is_read ? '已标记为已读' : '已标记为未读');
      } else {
        const text = await res.text();
        message.error(`标记阅读失败: ${text || res.status}`);
      }
    } catch (e) { console.error(e); message.error('标记阅读失败'); }
  };
  const exportArticles = async (format: 'json' | 'csv') => {
    if (!selectedArticles.size) return;
    try {
      const rows = filteredArticles.filter((a) => selectedArticles.has(a.id));
      if (format === 'json') {
        const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob); const link = document.createElement('a');
        link.href = url; link.download = `news-export-${new Date().toISOString().split('T')[0]}.json`; link.click(); URL.revokeObjectURL(url);
      } else {
        const csv = [
          ['Title','Summary','Source','Published At','Sentiment','Related Stocks','URL'],
          ...rows.map(a => [a.title,a.summary,a.source,formatDate(a.published_at),a.sentiment_type,a.related_stocks?.join('; ')||'',a.url])
        ].map(r=>r.map(c=>`"${c}"`).join(',')).join('\n');
        const blob = new Blob([csv], { type: 'text/csv' }); const url = URL.createObjectURL(blob); const link = document.createElement('a');
        link.href = url; link.download = `news-export-${new Date().toISOString().split('T')[0]}.csv`; link.click(); URL.revokeObjectURL(url);
      }
    } catch (e) { console.error(e); }
  };

  const uniqueSources = [...new Set(articles.map(a => a.source).filter(Boolean))];
  const uniqueStocks = [...new Set(articles.flatMap(a => a.related_stocks || []))];
  const uniqueCategories = [...new Set(articles.map(a => a.category).filter(Boolean))];

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="max-w-[1200px] mx-auto space-y-4">
        {/* Header */}
        <div className="bg-gray-50/80 rounded-lg shadow-sm p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h1 className="text-[20px] font-bold text-gray-900 m-0">新闻管理</h1>
              <p className="text-gray-600 mt-1 text-sm">智能新闻收集、分析与管理平台</p>
            </div>
            <div className="flex items-center gap-8">
              <AntButton loading={backfilling} onClick={runBackfill} type="default">补充内容/摘要</AntButton>
            </div>
          </div>
        </div>

        {/* Statistics Panel: always visible with nicer layout */}
        <Card variant="soft">
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex-1 min-w-[260px]">
                <div className="flex flex-row gap-3 items-stretch flex-nowrap overflow-x-auto">
                  <div className="flex-shrink-0 rounded-md bg-white/60 px-3 py-2 min-w-[140px]">
                    <Statistic title="总文章数" value={stats?.total_articles ?? 0} valueStyle={{ fontWeight: 600 }} />
                  </div>
                  <div className="flex-shrink-0 rounded-md bg-white/60 px-3 py-2 min-w-[140px]">
                    <Statistic title="今日文章" value={stats?.today_articles ?? 0} valueStyle={{ fontWeight: 600 }} />
                  </div>
                  <div className="flex-shrink-0 rounded-md bg-white/60 px-3 py-2 min-w-[140px]">
                    <Statistic title="积极" value={stats?.positive_sentiment ?? 0} suffix="%" prefix={<SmileOutlined className="text-green-600" />} valueStyle={{ color: '#16a34a', fontWeight: 600 }} />
                  </div>
                  <div className="flex-shrink-0 rounded-md bg-white/60 px-3 py-2 min-w-[140px]">
                    <Statistic title="消极" value={stats?.negative_sentiment ?? 0} suffix="%" prefix={<FrownOutlined className="text-red-600" />} valueStyle={{ color: '#dc2626', fontWeight: 600 }} />
                  </div>
                  <div className="flex-shrink-0 rounded-md bg-white/60 px-3 py-2 min-w-[140px]">
                    <Statistic title="中性" value={stats?.neutral_sentiment ?? 0} suffix="%" prefix={<MehOutlined className="text-gray-500" />} valueStyle={{ color: '#6b7280', fontWeight: 600 }} />
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-end min-w-[140px]">
                <AntButton type="primary" onClick={() => { loadNews({ reset: true }); loadStats(); setSelectedArticles(new Set()); }} loading={loading} icon={<ReloadOutlined />}>刷新</AntButton>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Toolbar: selection */}
        <div className="flex items-center justify-between rounded-lg bg-gray-100/80 px-4 py-3 shadow-sm">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2" >
                          <Checkbox checked={selectedArticles.size === filteredArticles.length && filteredArticles.length > 0} onChange={selectAllArticles} style={{ paddingBottom: 4 }} />
              <span className="text-sm text-gray-700" style={{ paddingLeft: 4, paddingBottom: 4 }} >全选 ({selectedArticles.size}/{filteredArticles.length})</span>
            </div>
            {selectedArticles.size > 0 && (
             <div className="flex items-center gap-2" style={{ paddingLeft: 8, paddingBottom: 4 }}>
                <Space size={8} align="center">
                    <AntButton onClick={() => exportArticles('json')} icon={<ExportOutlined />} style={{ transform: 'scaleY(0.95)', transformOrigin: 'center' }}>导出JSON</AntButton>
                    <AntButton onClick={() => exportArticles('csv')} icon={<ExportOutlined />} style={{ transform: 'scaleY(0.95)', transformOrigin: 'center' }}>导出CSV</AntButton>
                    <AntButton type="link" onClick={() => setSelectedArticles(new Set())} style={{ transform: 'scaleY(0.95)', transformOrigin: 'center' }}>清除选择</AntButton>
                </Space>
              </div>
            )}
          </div>
          <div />
        </div>

        {/* Filters inline */}
        <div className="bg-gray-50/80 rounded-lg shadow-sm p-4">
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="flex-1">
              <AntInput allowClear size="large" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索新闻标题、内容、关键词或相关股票..." prefix={<SearchOutlined className="text-gray-400" />} />
            </div>
            <div>
            <Space size={8} align="center" style={{ marginTop: 8 }}>
                <Select
                    value={filters.sentiment}
                    onChange={(v) => setFilters(p => ({ ...p, sentiment: v as FilterOptions['sentiment'] }))}
                    options={[
                        { value: 'all', label: '全部情感' },
                        { value: 'positive', label: '积极' },
                        { value: 'negative', label: '消极' },
                        { value: 'neutral', label: '中性' }
                    ]}
                    style={{ width: 120, height: 34, lineHeight: '34px' }}
                    size="large"
                />
                <Select
                    value={filters.dateRange}
                    onChange={(v) => setFilters(p => ({ ...p, dateRange: v as FilterOptions['dateRange'] }))}
                    options={[
                        { value: 'all', label: '全部时间' },
                        { value: 'today', label: '今日' },
                        { value: 'week', label: '本周' },
                        { value: 'month', label: '本月' }
                    ]}
                    style={{ width: 120, height: 34, lineHeight: '34px' }}
                    size="large"
                />
                <AntButton size="large" style={{ height: 34, minHeight: 34, lineHeight: '34px' }} onClick={() => setShowFilters(!showFilters)} icon={<SettingOutlined />}>
                    高级筛选{activeFiltersCount > 0 ? ` (${activeFiltersCount})` : ''}
                </AntButton>
                <AntButton size="large" style={{ height: 34, minHeight: 34, lineHeight: '34px' }} onClick={resetFilters} icon={<ClearOutlined />}>
                    重置
                </AntButton>
            </Space>
            </div>
          </div>
          {activeFiltersCount > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-2 bg-white/40 rounded-md px-3 py-2">
              {searchQuery.trim() && (<Tag color="blue" closable onClose={() => setSearchQuery('')}>关键词: {searchQuery}</Tag>)}
              {filters.sentiment !== 'all' && (<Tag closable onClose={() => setFilters(p => ({ ...p, sentiment: 'all' }))}>情感: {filters.sentiment === 'positive' ? '积极' : filters.sentiment === 'negative' ? '消极' : '中性'}</Tag>)}
              {filters.dateRange !== 'all' && (<Tag closable onClose={() => setFilters(p => ({ ...p, dateRange: 'all' }))}>时间: {filters.dateRange === 'today' ? '今日' : filters.dateRange === 'week' ? '本周' : '本月'}</Tag>)}
              {filters.source && (<Tag closable onClose={() => setFilters(p => ({ ...p, source: '' }))}>来源: {filters.source}</Tag>)}
              {filters.stock && (<Tag closable onClose={() => setFilters(p => ({ ...p, stock: '' }))}>股票: {filters.stock}</Tag>)}
              {filters.category && (<Tag closable onClose={() => setFilters(p => ({ ...p, category: '' }))}>分类: {filters.category}</Tag>)}
              {filters.isBookmarked === true && (<Tag color="gold" closable onClose={() => setFilters(p => ({ ...p, isBookmarked: null }))}>已收藏</Tag>)}
              {filters.isRead === true && (<Tag color="blue" closable onClose={() => setFilters(p => ({ ...p, isRead: null }))}>已阅读</Tag>)}
              <AntButton type="link" onClick={resetFilters}>清除全部</AntButton>
            </div>
          )}
          {showFilters && (
            <div className="mt-6">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 bg-white/40 rounded-md p-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">新闻来源</label>
                  <Select value={filters.source || undefined} onChange={(v) => setFilters(p => ({ ...p, source: v || '' }))} allowClear options={[{ value: '', label: '全部来源' }, ...uniqueSources.map(s => ({ value: s, label: s }))]} className="w-full" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">相关股票</label>
                  <Select value={filters.stock || undefined} onChange={(v) => setFilters(p => ({ ...p, stock: v || '' }))} showSearch allowClear options={[{ value: '', label: '全部股票' }, ...uniqueStocks.map(s => ({ value: s, label: s }))]} className="w-full" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">分类</label>
                  <Select value={filters.category || undefined} onChange={(v) => setFilters(p => ({ ...p, category: v || '' }))} allowClear options={[{ value: '', label: '全部分类' }, ...uniqueCategories.map(c => ({ value: c, label: c }))]} className="w-full" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">状态</label>
                  <div className="flex gap-4">
                    <Checkbox checked={filters.isBookmarked === true} onChange={(e) => setFilters(p => ({ ...p, isBookmarked: e.target.checked ? true : null }))}>已收藏</Checkbox>
                    <Checkbox checked={filters.isRead === true} onChange={(e) => setFilters(p => ({ ...p, isRead: e.target.checked ? true : null }))}>已阅读</Checkbox>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* News List */}
        <List
          loading={loading}
          dataSource={filteredArticles}
          split={false}
          loadMore={
            hasMore && filteredArticles.length > 0 ? (
              <div className="flex justify-center py-4">
                <AntButton loading={loadingMore} onClick={() => loadNews()}>
                  加载更多
                </AntButton>
              </div>
            ) : null
          }
          locale={{ emptyText: (<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={searchQuery || Object.values(filters).some(v => v !== 'all' && v !== '' && v !== null) ? '没有找到符合条件的新闻' : '暂无新闻数据'} />) }}
          renderItem={(article) => (
            <List.Item key={article.id}>
              <Card variant="bare" className={`w-full transition-all duration-200 ${selectedArticles.has(article.id) ? 'bg-blue-50' : 'bg-gray-200'} ${article.is_read ? 'opacity-85' : ''}`} style={{ backgroundColor: selectedArticles.has(article.id) ? '#eff6ff' : '#e5e7eb' }}>
                <CardContent className={`p-6`}>
                  <div className="flex items-stretch gap-6">
                    <Checkbox checked={selectedArticles.has(article.id)} onChange={() => toggleArticleSelection(article.id)} className="mt-1 self-start" style={{ paddingLeft: 4, paddingTop: 8}} />
                    {/* Column layout enables footer pinned bottom */}
                    <div className="flex-1 min-w-0 h-full min-h-[160px] flex flex-col" style={{ paddingLeft: 8, paddingRight: 8, paddingTop: 8, paddingBottom: 0 }}>
                      <div className="flex-1 min-w-0">
                        <Typography.Title level={5} style={{ margin: 0 }} ellipsis={{ tooltip: article.title }}>
                          <a href={article.url} target="_blank" rel="noopener noreferrer" className="no-underline text-gray-900 hover:underline hover:text-blue-600">{article.title}</a>
                        </Typography.Title>
                        <Space size={[16, 8]} wrap className={`mb-3 text-gray-500`}>
                          <Typography.Text type="secondary">{formatDate(article.published_at)}</Typography.Text>
                          {article.source && <Typography.Text type="secondary">{article.source}</Typography.Text>}
                                      </Space>
                                      <Space>
                                          <AntButton type="text" onClick={() => toggleBookmark(article.id)} icon={article.is_bookmarked ? <StarFilled /> : <StarOutlined />}>{article.is_bookmarked ? '已收藏' : '收藏'}</AntButton>
                                          <AntButton type="text" onClick={() => toggleReadStatus(article.id)} icon={<EyeOutlined />}>{article.is_read ? '已读' : '标记已读'}</AntButton>
                                      </Space>
                        {article.summary && (
                          <Typography.Paragraph style={{ marginBottom: 12 }} ellipsis={{ rows: 2, tooltip: article.summary }}>
                            {article.summary}
                          </Typography.Paragraph>
                        )}
                        
                      </div>
                      {/* Footer pinned to bottom */}
                      <div className="mt-auto pt-3 pb-4 pr-4 flex items-center justify-between" style={{ paddingBottom: 6, paddingRight: 8}}>
                        <Space size={[8, 8]} wrap>
                          {article.related_stocks?.slice(0, 6).map((stock, idx) => (
                            <Tag key={`stock-${idx}`} color="blue" style={{ padding: '2px 8px', fontSize: 12 }}>{stock}</Tag>
                          ))}
                          {article.keywords?.slice(0, 6).map((kw, idx) => (
                            <Tag key={`kw-${idx}`} bordered={false} color="geekblue" style={{ padding: '2px 8px', fontSize: 12 }}># {kw}</Tag>
                          ))}
                        </Space>
                        <div className="flex items-center gap-2 pr-2">
                          <Tag color={article.sentiment_type === 'positive' ? 'green' : article.sentiment_type === 'negative' ? 'red' : 'default'}>
                            {article.sentiment_type === 'positive' ? '积极' : article.sentiment_type === 'negative' ? '消极' : '中性'}
                          </Tag>
                          <AntButton type="default" href={article.url} target="_blank" className="mr-2">阅读原文</AntButton>
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </List.Item>
          )}
        />
      </div>
    </div>
  );
}