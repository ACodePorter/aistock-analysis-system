import React, { useState, useEffect, useMemo } from 'react';
import { API_ENDPOINTS, buildApiUrl } from '../config/api';
import { Card, CardContent } from './card';
import { Input as AntInput, Select, Button as AntButton, Tag, List, Typography, Empty, Space } from 'antd';
import { SearchOutlined, ReloadOutlined, ExportOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';

interface Article {
  id: string | number;
  title: string;
  summary?: string;
  url: string;
  source?: string;
  published_at?: string | number | null;
  published_dt?: string | number | null; // API alias
  sentiment_type?: 'positive' | 'negative' | 'neutral';
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

  // Load news articles
  const loadNews = async () => {
    setLoading(true);
    try {
      let url = buildApiUrl(API_ENDPOINTS.NEWS.ARTICLES);
      if (selectedStock) {
        url = buildApiUrl(API_ENDPOINTS.NEWS.STOCK_NEWS(selectedStock));
      }

      console.log('Loading news from:', url);
      const response = await fetch(url);
      const data = await response.json();
      
      console.log('News API Response:', data);
      
      // 处理不同的响应格式
      let newsData = [];
      if (data.articles && Array.isArray(data.articles)) {
        newsData = data.articles;
      } else if (Array.isArray(data)) {
        newsData = data;
      } else if (data.stocks && Array.isArray(data.stocks)) {
        newsData = data.stocks;
      } else {
        console.warn('Unexpected news response format:', data);
        newsData = [];
      }

      setArticles(newsData);
      console.log('News loaded successfully:', newsData.length, 'articles');
    } catch (error) {
      console.error('Failed to load news:', error);
      setArticles([]);
    } finally {
      setLoading(false);
    }
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
  }, [selectedStock]);

  // Search news
  const searchNews = async () => {
    if (!searchQuery.trim()) {
      loadNews();
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.SEARCH), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery })
      });
      const data = await response.json();
      setArticles(data.articles || []);
    } catch (error) {
      console.error('Search failed:', error);
      setArticles([]);
    } finally {
      setLoading(false);
    }
  };

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

  // Intelligent news collection
  const runIntelligentCollection = async () => {
    setIsIntelligentCollecting(true);
    try {
      const response = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.INTELLIGENT_COLLECT), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      
      if (response.ok) {
        console.log('Intelligent news collection successful');
        await loadNews(); // Reload news after collection
      } else {
        console.error('Intelligent news collection failed:', response.status, response.statusText);
      }
    } catch (error) {
      console.error('Intelligent collection failed:', error);
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

  const filteredArticles = useMemo(() => {
    return (articles || []).filter((a) => {
      if (sentimentFilter !== 'all' && a.sentiment_type !== sentimentFilter) return false;
      return true;
    });
  }, [articles, sentimentFilter]);

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="max-w-[1200px] mx-auto space-y-4">
        {/* Header */}
        <div className="bg-gray-50/80 rounded-lg shadow-sm p-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-[20px] font-bold text-gray-900 m-0">{selectedStock ? `${selectedStock} 财经新闻` : '财经新闻'}</h1>
              <p className="text-gray-600 mt-1 text-sm">最新财经资讯与个股相关新闻</p>
            </div>
            <Space>
              <AntButton type="primary" onClick={loadNews} loading={loading} icon={<ReloadOutlined />}>刷新</AntButton>
            </Space>
          </div>
        </div>

        {/* Filters inline */}
        <div className="bg-gray-50/80 rounded-lg shadow-sm p-4">
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="flex-1">
              <AntInput allowClear size="large" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onPressEnter={searchNews} placeholder="搜索新闻标题、内容或股票..." prefix={<SearchOutlined className="text-gray-400" />} />
            </div>
            <div className="flex items-center gap-3">
              <Select value={selectedStock || undefined} onChange={(v) => setSelectedStock(v || '')} allowClear placeholder="选择股票" showSearch options={watchlist.map(w => ({ value: w.symbol, label: `${w.symbol}${w.name ? ` - ${w.name}` : ''}` }))} className="w-[220px]" size="large" />
              <Select value={sentimentFilter} onChange={(v) => setSentimentFilter(v)} options={[{ value: 'all', label: '全部情感' },{ value: 'positive', label: '积极' },{ value: 'negative', label: '消极' },{ value: 'neutral', label: '中性' }]} style={{ width: 120 }} size="large" />
              {selectedStock ? (
                <AntButton onClick={collectNews} loading={isCollecting} type="default">收集新闻</AntButton>
              ) : (
                <AntButton onClick={runIntelligentCollection} loading={isIntelligentCollecting} type="default">智能收集</AntButton>
              )}
              <AntButton onClick={searchNews} loading={loading} type="default">搜索</AntButton>
            </div>
          </div>
        </div>

        {/* News List */}
        <List
          loading={loading}
          dataSource={filteredArticles}
          split={false}
          locale={{ emptyText: (<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={searchQuery || selectedStock || sentimentFilter !== 'all' ? '没有找到符合条件的新闻' : '暂无新闻数据'} />) }}
          renderItem={(article) => (
            <List.Item key={article.id}>
              <Card variant="bare" className={`w-full transition-all duration-200 bg-gray-200`} style={{ backgroundColor: '#e5e7eb' }}>
                <CardContent className="p-6">
                  {/* Column layout enables footer pinned bottom */}
                  <div className="flex-1 min-w-0 h-full min-h-[140px] flex flex-col">
                    <div className="flex-1 min-w-0">
                      <Typography.Title level={5} style={{ margin: 0 }} ellipsis={{ tooltip: article.title }}>
                        <a href={article.url} target="_blank" rel="noopener noreferrer" className="no-underline text-gray-900 hover:underline hover:text-blue-600">{article.title}</a>
                      </Typography.Title>
                      <Space size={[16, 8]} wrap className={`mb-3 text-gray-500`}>
                        <Typography.Text type="secondary">{formatDate(article.published_at ?? article.published_dt)}</Typography.Text>
                        {article.source && <Typography.Text type="secondary">{article.source}</Typography.Text>}
                      </Space>
                      {article.summary && (
                        <Typography.Paragraph style={{ marginBottom: 12 }} ellipsis={{ rows: 2, tooltip: article.summary }}>
                          {article.summary}
                        </Typography.Paragraph>
                      )}
                    </div>
                    {/* Footer pinned to bottom */}
                    <div className="mt-auto pt-3 pb-2 pr-2 flex items-center justify-between">
                      <Space size={[8, 8]} wrap>
                        {article.related_stocks?.slice(0, 6).map((stock, idx) => (
                          <Tag key={`stock-${idx}`} color="blue" style={{ padding: '2px 8px', fontSize: 12 }}>{stock}</Tag>
                        ))}
                      </Space>
                      <div className="flex items-center gap-2 pr-2">
                        <Tag color={article.sentiment_type === 'positive' ? 'green' : article.sentiment_type === 'negative' ? 'red' : 'default'}>
                          {article.sentiment_type === 'positive' ? '积极' : article.sentiment_type === 'negative' ? '消极' : '中性'}
                        </Tag>
                        <AntButton type="default" href={article.url} target="_blank">阅读原文</AntButton>
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