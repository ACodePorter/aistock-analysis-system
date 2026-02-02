import React, { useState, useEffect, useMemo, useRef } from 'react';
import SentimentBadge from './SentimentBadge';
import { API_ENDPOINTS, buildApiUrl } from '../config/api';
import StatsChips, { StatsData } from './StatsChips';
import dayjs from 'dayjs';
import { Input, Select, Pagination, Spin, Alert, DatePicker } from 'antd';
import type { RangePickerProps } from 'antd/es/date-picker';

interface Article {
  id: string | number;
  title: string;
  summary?: string;
  url: string;
  source?: string;
  published_at?: string | number | null;
  published_dt?: string | number | null; // API alias
  sentiment_type?: 'positive' | 'negative' | 'neutral';
  // optional numeric scores may be returned by some APIs
  sentiment_score?: number | null;
  relevance_score?: number | null;
  related_stocks?: string[] | null;
}

interface WatchlistItem {
  symbol: string;
  name?: string;
  sector?: string;
  enabled: boolean;
}

export default function ModernNewsComponent() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStock, setSelectedStock] = useState<string>('');
  const [sentimentFilter, setSentimentFilter] = useState<'all' | 'positive' | 'negative' | 'neutral'>('all');
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [isCollecting, setIsCollecting] = useState(false);
  const [isIntelligentCollecting, setIsIntelligentCollecting] = useState(false);
  const [showStockSelector, setShowStockSelector] = useState(false);
  const stockSelectorRef = useRef<HTMLDivElement | null>(null);
  const [showAllStats, setShowAllStats] = useState(false);
  const [statsOverflowing, setStatsOverflowing] = useState(false);
  const chipsContainerRef = useRef<HTMLDivElement | null>(null);
  const searchDebounceRef = useRef<number | null>(null);
  const [stockHighlightIndex, setStockHighlightIndex] = useState<number>(-1); // -1 = 所有股票按钮
  const [page, setPage] = useState(1);
  const pageSize = 10; // 统一与新闻管理页
  const [error, setError] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  // 一次性兜底标记与提示
  const attemptedFallbackRef = useRef(false);
  const [fallbackInfo, setFallbackInfo] = useState<string | null>(null);

  // 全局统计（来自后端 /api/news/stats）
  const [globalTotal, setGlobalTotal] = useState<number | null>(null);
  const [fetchingGlobal, setFetchingGlobal] = useState(false);

  const fetchGlobalStats = async () => {
    setFetchingGlobal(true);
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.STATS));
      if (res.ok) {
        const data = await res.json();
        if (typeof data.total_articles === 'number') setGlobalTotal(data.total_articles);
        else if (data?.stats?.total_articles) setGlobalTotal(data.stats.total_articles);
      }
    } catch (e) {
      // 忽略错误，UI 上仅不显示全局总数
    } finally { setFetchingGlobal(false); }
  };

  // Load news articles
  const loadNews = async () => {
    setLoading(true); setError(null); attemptedFallbackRef.current = false; setFallbackInfo(null);
    try {
      let url = buildApiUrl(API_ENDPOINTS.NEWS.ARTICLES);
      let params = '';
      // Always prefer enriched endpoint for per-stock news
      if (selectedStock) {
        // Use company_enriched endpoint with robust params
        url = buildApiUrl(`/api/news/company_enriched/${selectedStock}`);
        params = '?trigger_topup=true&wait_seconds=6&ensure_min=5&allow_placeholder=true';
        // Optionally: add extra_keywords for known sparse stocks
        // For demo: add domain keywords for 300877.SZ
        if (selectedStock === '300877.SZ') {
          params += '&extra_keywords=非织造布,无纺布,医用材料,口罩,熔喷,纺粘,热风布,卫生材料,医卫材料,擦拭';
        }
        url += params;
      }
      const response = await fetch(url);
      if (!response.ok) throw new Error(`状态码 ${response.status}`);
      const data = await response.json();
      let newsData: any[] = [];
      if (data.articles && Array.isArray(data.articles)) newsData = data.articles;
      else if (Array.isArray(data)) newsData = data;
      else if (data.stocks && Array.isArray(data.stocks)) newsData = data.stocks;
      else newsData = [];
      // If still empty, fallback to basic_profile endpoint for company info
      if (newsData.length === 0 && selectedStock && !attemptedFallbackRef.current) {
        attemptedFallbackRef.current = true;
        setFallbackInfo('未获取到相关新闻，正在尝试补充公司基础资料...');
        try {
          const profileResp = await fetch(buildApiUrl(`/api/news/basic_profile/${selectedStock}`));
          if (profileResp.ok) {
            const prof = await profileResp.json();
            // Synthesize a placeholder article from profile
            if (prof && prof.company_name) {
              setArticles([
                {
                  id: 'profile',
                  title: `${prof.company_name} 公司简介`,
                  summary: prof.business_summary || prof.crawled_snippets?.[0] || '暂无详细资料',
                  url: '',
                  source: '公司基础资料',
                  published_at: null,
                  sentiment_type: 'neutral',
                  sentiment_score: null,
                  relevance_score: null,
                  related_stocks: [selectedStock],
                },
              ]);
              setFallbackInfo('已补充公司基础资料。');
              return;
            }
          }
        } catch (e) {
          // Ignore
        }
      }
      setArticles(newsData);
    } catch (e: any) {
      setError(e?.message || String(e));
      setArticles([]);
    } finally { setLoading(false); }
  };

  // Load watchlist
  const loadWatchlist = async () => {
    try {
      console.log('Loading watchlist from:', buildApiUrl(API_ENDPOINTS.WATCHLIST));
      const response = await fetch(buildApiUrl(API_ENDPOINTS.WATCHLIST));
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      console.log('Watchlist API response:', data);

      // API返回的是直接的数组，不是包含stocks字段的对象
      if (Array.isArray(data)) {
        setWatchlist(data);
        console.log('Watchlist loaded successfully:', data.length, 'items');
      } else {
        console.warn('Unexpected watchlist response format:', data);
        setWatchlist([]);
      }
    } catch (error) {
      console.error('Failed to load watchlist:', error);
      setWatchlist([]);
    }
  };

  // Load strategies
  useEffect(() => {
    loadNews();
    loadWatchlist();
    fetchGlobalStats();
  }, [selectedStock]);

  // Search news
  const searchNews = async () => {
    if (!searchQuery.trim()) { loadNews(); return; }
    setLoading(true); setError(null);
    try {
      const response = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.SEARCH), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: searchQuery }) });
      if (!response.ok) throw new Error(`搜索失败 ${response.status}`);
      const data = await response.json();
      setArticles(data.articles || []);
    } catch (e:any) {
      setError(e?.message || String(e));
      setArticles([]);
    } finally { setLoading(false); }
  };

  // 防抖自动搜索 (500ms)
  useEffect(() => {
    if (searchDebounceRef.current) {
      window.clearTimeout(searchDebounceRef.current);
    }
    searchDebounceRef.current = window.setTimeout(() => {
      if (searchQuery.trim()) {
        searchNews();
      } else {
        loadNews();
      }
    }, 500);
    return () => {
      if (searchDebounceRef.current) window.clearTimeout(searchDebounceRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, selectedStock]);

  // Collect news for selected stock
  const collectNews = async () => {
    if (!selectedStock) return;

    setIsCollecting(true);
    try {
      const response = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.COLLECT(selectedStock)), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });

      if (response.ok) {
        console.log('News collection successful for', selectedStock);
        await loadNews(); // Reload news after collection
      } else {
        console.error('News collection failed:', response.status, response.statusText);
      }
    } catch (error) {
      console.error('News collection failed:', error);
    } finally {
      setIsCollecting(false);
    }
  };

  // Sync latest news: intelligent collect + refresh
  const syncLatestNews = async () => {
    setIsIntelligentCollecting(true);
    try {
      const response = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.INTELLIGENT_COLLECT), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      // 无论成功与否都刷新
      await loadNews();
      fetchGlobalStats();
      if (response.ok) {
        console.log('Intelligent news collection successful');
      } else {
        console.error('Intelligent news collection failed:', response.status, response.statusText);
      }
    } catch (error) {
      console.error('Intelligent collection failed:', error);
      await loadNews();
      fetchGlobalStats();
    } finally {
      setIsIntelligentCollecting(false);
    }
  };

  // Date utils aligned with NewsManagement
  const formatDate = (dateVal: string | number | null | undefined) => {
    // prefer published_at, fallback to published_dt
    const rawInput = String(dateVal ?? '').trim();
    if (!rawInput) return '时间未知';
    let d: dayjs.Dayjs;
    if (/^\d+$/.test(rawInput)) { const num = Number(rawInput); d = dayjs(num < 1e12 ? num * 1000 : num); }
    else d = dayjs(rawInput);
    if (!d.isValid() || d.year() < 2000) return '时间未知';
    return d.format('YYYY-MM-DD HH:mm');
  };

  const parsePublished = (dateVal: string | number | null | undefined): dayjs.Dayjs | null => {
    const rawInput = String(dateVal ?? '').trim();
    if (!rawInput) return null;
    let d: dayjs.Dayjs;
    if (/^\d+$/.test(rawInput)) { const num = Number(rawInput); d = dayjs(num < 1e12 ? num * 1000 : num); }
    else d = dayjs(rawInput);
    if (!d.isValid() || d.year() < 2000) return null;
    return d;
  };

  const sources = useMemo(() => Array.from(new Set(articles.map(a => a.source || '').filter(Boolean))), [articles]);

  const filteredArticles = useMemo(() => {
    let list = (articles || []).slice();
    if (sentimentFilter !== 'all') list = list.filter(a => a.sentiment_type === sentimentFilter);
    if (sourceFilter !== 'all') list = list.filter(a => (a.source || '') === sourceFilter);
    if (dateRange && dateRange[0] && dateRange[1]) {
      const start = dateRange[0]!.startOf('day');
      const end = dateRange[1]!.endOf('day');
      list = list.filter(a => {
        const d = parsePublished(a.published_at ?? a.published_dt);
        return d && (d.isAfter(start) || d.isSame(start)) && (d.isBefore(end) || d.isSame(end));
      });
    }
    return list;
  }, [articles, sentimentFilter, sourceFilter, dateRange]);

  // 当前分页数据
  const pagedArticles = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredArticles.slice(start, start + pageSize);
  }, [filteredArticles, page, pageSize]);

  useEffect(() => { setPage(1); }, [searchQuery, sentimentFilter, selectedStock, sourceFilter, dateRange]);

  // 统计：总数 / 今日新增 / 情感分类
  // 统计改为基于筛选后的集合（用户需求 #2）
  const stats: StatsData = useMemo(() => {
    const now = dayjs();
    let total = filteredArticles.length;
    let today = 0, pos = 0, neg = 0, neu = 0;
    for (const a of filteredArticles) {
      const d = parsePublished(a.published_at ?? a.published_dt);
      if (d && d.isAfter(now.startOf('day'))) today++;
      switch (a.sentiment_type) {
        case 'positive': pos++; break;
        case 'negative': neg++; break;
        case 'neutral': neu++; break;
      }
    }
    return { total, today, pos, neg, neu };
  }, [filteredArticles]);

  // CSV 导出（导出当前筛选全部，而非仅当前分页）
  const exportCsv = () => {
    if (!filteredArticles.length) return;
    const headers = ['id','title','source','published_at','sentiment_type','sentiment_score','relevance_score','related_stocks','summary'];
    const rows = filteredArticles.map(a => {
      const relStocks = (a.related_stocks || []).join('|');
      const fields = [
        a.id,
        a.title,
        a.source || '',
        formatDate(a.published_at ?? a.published_dt ?? null),
        a.sentiment_type || '',
        (a as any).sentiment_score ?? '',
        (a as any).relevance_score ?? '',
        relStocks,
        (a.summary || '').replace(/\s+/g,' ')
      ];
      return fields.map(v => {
        const s = String(v).replace(/"/g,'""');
        return `"${s}"`;
      }).join(',');
    });
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' }); // BOM for Excel
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const dateStr = dayjs().format('YYYYMMDD_HHmmss');
    a.download = `news_export_${dateStr}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleStockSelect = (stockSymbol: string) => {
    setSelectedStock(stockSymbol);
    setShowStockSelector(false);
  };

  // 点击外部关闭股票选择下拉
  useEffect(() => {
    if (!showStockSelector) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (stockSelectorRef.current && !stockSelectorRef.current.contains(e.target as Node)) {
        setShowStockSelector(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowStockSelector(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [showStockSelector]);

  // 监控统计 chips 是否溢出（动态控制“统计/收起”按钮显示）
  useEffect(() => {
    const el = chipsContainerRef.current;
    if (!el) return;
    const check = () => {
      // 在小屏（<640px）下，如果滚动宽度大于可视宽度则显示
      if (window.innerWidth < 640) {
        setStatsOverflowing(el.scrollWidth > el.clientWidth + 8);
      } else {
        setStatsOverflowing(false); // 大屏不需要按钮
      }
    };
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    window.addEventListener('resize', check);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', check);
    };
  }, [articles]);

  const getSentimentColor = (sentiment: string) => {
    switch (sentiment) {
      case 'positive':
        return 'dark-badge dark-badge-success';
      case 'negative':
        return 'dark-badge dark-badge-danger';
      case 'neutral':
        return 'dark-badge';
      default:
        return 'dark-badge';
    }
  };

  const getSentimentText = (sentiment: string) => {
    switch (sentiment) {
      case 'positive':
        return '积极';
      case 'negative':
        return '消极';
      case 'neutral':
        return '中性';
      default:
        return '未知';
    }
  };

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--background-dark)', padding: 24, fontFamily: "'Inter','Noto Sans SC',sans-serif", color: 'var(--text)' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>财经新闻 · 实时流</div>
            <h2 style={{ margin: 0, fontSize: 22, color: 'var(--text)' }}>财经新闻中枢</h2>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <Input.Search
              placeholder="按关键词搜索标题或摘要"
              allowClear
              enterButton
              value={searchQuery}
              onSearch={(v) => { setSearchQuery(v || ''); setPage(1); if (v) searchNews(); else loadNews(); }}
              onChange={e => { const v = e.target.value; setSearchQuery(v); if (!v) { setPage(1); loadNews(); } }}
              style={{ minWidth: 320 }}
            />
            <button onClick={exportCsv} disabled={!filteredArticles.length} className="dark-btn dark-btn-secondary" style={{ fontSize: 12 }}>导出CSV</button>
            <button onClick={syncLatestNews} disabled={isIntelligentCollecting} className="dark-btn dark-btn-primary" style={{ fontSize: 12 }}>
              {isIntelligentCollecting ? '同步中...' : '同步最新新闻'}
            </button>
          </div>
        </div>

        {error && <Alert type="error" message="加载新闻失败" description={error} />}
        {loading && <div style={{ padding: 40, textAlign: 'center' }}><Spin /></div>}

        {!loading && !error && (
          <div style={{ display: 'flex', gap: 18 }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div style={{ fontSize: 14, color: '#6b7280', display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span>{filteredArticles.length} 条新闻{globalTotal !== null && <span style={{ marginLeft: 8, color: '#4b5563' }}>（全局总数 {globalTotal}{fetchingGlobal ? '…' : ''}）</span>}</span>
                  <StatsChips stats={stats} />
                </div>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  {/* 股票选择下拉保留原自定义，不转 antd 以免破坏键盘导航逻辑 */}
                  <div style={{ position: 'relative' }} ref={stockSelectorRef}>
                    <button onClick={() => setShowStockSelector(!showStockSelector)} className="dark-btn dark-btn-secondary" style={{ padding: '6px 12px', fontSize: 12, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4, minWidth: 120 }}>
                      <span>{selectedStock || '选择股票'}</span>
                      <span style={{ fontSize: 10, transform: showStockSelector ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }}>▼</span>
                    </button>
                    {showStockSelector && (
                      <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 8, width: 240, background: 'var(--surface-dark)', border: '1px solid var(--border)', borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,0.3)', zIndex: 50, maxHeight: 260, overflow: 'hidden' }}>
                        <div style={{ overflowY: 'auto', maxHeight: 220 }}>
                          {watchlist.length === 0 ? (
                            <div style={{ padding: 12, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>暂无关注股票</div>
                          ) : (
                            <div style={{ padding: 8 }}>
                              <button onClick={() => handleStockSelect('')} style={{ width: '100%', textAlign: 'left', padding: '8px 10px', fontSize: 12, borderRadius: 6, border: '1px solid var(--border)', marginBottom: 6, background: selectedStock === '' ? 'rgba(99,102,241,0.2)' : stockHighlightIndex === -1 ? 'rgba(255,255,255,0.02)' : 'transparent', fontWeight: 600, cursor: 'pointer', color: 'var(--text)' }}>所有股票{stockHighlightIndex === -1 && selectedStock !== '' && ' ←'}</button>
                              {watchlist.map((stock, idx) => (
                                <button key={stock.symbol} onClick={() => handleStockSelect(stock.symbol)} style={{ width: '100%', textAlign: 'left', padding: '8px 10px', fontSize: 12, borderRadius: 6, border: '1px solid var(--border)', marginBottom: 4, background: selectedStock === stock.symbol ? '#2563eb' : stockHighlightIndex === idx ? 'rgba(255,255,255,0.02)' : 'transparent', color: selectedStock === stock.symbol ? '#fff' : 'var(--text)', cursor: 'pointer' }}>
                                  <div style={{ fontWeight: 600, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span>{stock.symbol}</span>
                                    {stockHighlightIndex === idx && selectedStock !== stock.symbol && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Enter 选择</span>}
                                  </div>
                                  {stock.name && <div style={{ fontSize: 10, color: selectedStock === stock.symbol ? '#bfdbfe' : 'var(--text-muted)', marginTop: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{stock.name}</div>}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  <Select value={sourceFilter} onChange={(v) => { setSourceFilter(v); setPage(1); }} placeholder="来源" allowClear style={{ width: 140 }}>
                    <Select.Option value="all">所有来源</Select.Option>
                    {sources.map(s => <Select.Option key={s} value={s}>{s}</Select.Option>)}
                  </Select>
                  <Select value={sentimentFilter} onChange={v => { setSentimentFilter(v as any); setPage(1); }} style={{ width: 120 }}>
                    <Select.Option value="all">全部情感</Select.Option>
                    <Select.Option value="positive">积极</Select.Option>
                    <Select.Option value="negative">消极</Select.Option>
                    <Select.Option value="neutral">中性</Select.Option>
                  </Select>
                  <DatePicker.RangePicker
                    value={dateRange as any}
                    onChange={(r) => { setDateRange(r as any); setPage(1); }}
                    style={{ width: 250 }}
                  />
                </div>
              </div>

              <div className="mt-4 flex flex-col">
    {loading ? (
      <>
        {[...Array(4)].map((_, i) => (
          <div key={i} className="news-card" style={{ marginBottom: i !== 3 ? 16 : 0 }}>
            <div className="flex flex-col gap-4">
              <div className="skeleton-bar h-5 w-3/4 rounded"></div>
              <div className="space-y-2">
                <div className="skeleton-bar h-3 w-full rounded"></div>
                <div className="skeleton-bar h-3 w-11/12 rounded"></div>
                <div className="skeleton-bar h-3 w-2/3 rounded"></div>
              </div>
              <div className="flex gap-3 mt-2">
                <div className="skeleton-bar h-4 w-20 rounded-full"></div>
                <div className="skeleton-bar h-4 w-16 rounded-full"></div>
                <div className="skeleton-bar h-4 w-24 rounded-full"></div>
              </div>
              <div className="flex justify-end mt-2 gap-3 items-center">
                <div className="skeleton-bar h-6 w-16 rounded"></div>
                <div className="skeleton-bar h-6 w-20 rounded-full"></div>
              </div>
            </div>
          </div>
        ))}
      </>
    ) : filteredArticles.length === 0 ? (
      <div className="news-card text-center py-16">
        <div className="text-6xl mb-6">📰</div>
        <div className="text-xl font-semibold text-[var(--text)] mb-3">
          {searchQuery || selectedStock || sentimentFilter !== 'all' ? '没有找到符合条件的新闻' : '暂无新闻数据'}
        </div>
        <div className="text-[var(--text-muted)] max-w-md mx-auto leading-relaxed">
          {selectedStock ? `没有找到关于 ${selectedStock} 的相关新闻。` : '请选择股票进行新闻收集，或使用智能收集功能获取最新财经资讯。'}
        </div>
        {fallbackInfo && (
          <div className="text-[var(--text-muted)] mt-3 text-sm">{fallbackInfo}</div>
        )}
      </div>
                ) : (
                  pagedArticles.map((article, idx) => (
                    <div key={article.id} className="news-card" style={{ marginBottom: idx !== pagedArticles.length - 1 ? 16 : 0 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', lineHeight: '1.4' }}>
                            {article.url ? <a href={article.url} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>{article.title}</a> : article.title}
                          </div>
                          <div style={{ marginTop: 6, fontSize: 13, color: 'var(--text-muted)' }}>
                            {article.source || '未知来源'} · {formatDate(article.published_at ?? article.published_dt)}
                          </div>
                          {article.summary && <div style={{ marginTop: 10, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{article.summary}</div>}
                          {article.related_stocks && article.related_stocks.length > 0 && (
                            <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                              <span className="dark-badge">相关: {article.related_stocks.slice(0,3).join(', ')}{article.related_stocks.length > 3 ? ` +${article.related_stocks.length - 3}` : ''}</span>
                            </div>
                          )}
                        </div>
                        <div style={{ minWidth: 120, textAlign: 'right', display: 'flex', flexDirection: 'column', gap: 8 }}>
                          <SentimentBadge sentiment={article.sentiment_type} />
                          <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}>得分: {typeof article.sentiment_score === 'number' ? article.sentiment_score.toFixed(2) : '暂无'}</div>
                          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>相关度: {article.relevance_score ?? '—'}</div>
                        </div>
                      </div>
                    </div>
                  ))
                )}
                <div style={{ textAlign: 'center', marginTop: 8 }}>
                  <Pagination current={page} pageSize={pageSize} total={filteredArticles.length} onChange={(p) => setPage(p)} showSizeChanger={false} />
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
      {/* 样式 */}
      <style>{`
        .news-card {
          background: var(--surface-dark);
          border-radius:12px;
          padding:16px 18px 18px;
          border:1px solid var(--border);
          transition: border-color .25s ease;
        }
        .news-card:hover {
          border-color: rgba(255,255,255,0.15);
        }
        .chips-scroll::-webkit-scrollbar { height: 6px; }
        .chips-scroll::-webkit-scrollbar-track { background: transparent; }
        .chips-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 4px; }
        .chip-stat { @apply px-3 py-1.5 rounded-full text-[11px] font-semibold shadow-sm whitespace-nowrap select-none; background: rgba(255,255,255,0.05); color: var(--text-secondary); }
        /* Skeleton shimmer (仅作用于灰条) */
        .skeleton-bar {
          background: linear-gradient(90deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0.05) 40%, rgba(255,255,255,0.02) 80%);
          background-size: 200% 100%;
          animation: skeleton-shimmer 1.8s ease-in-out infinite;
        }
        @keyframes skeleton-shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        @keyframes spin { from { transform: rotate(0deg);} to { transform: rotate(360deg);} }
      `}</style>
    </div>
  );
}