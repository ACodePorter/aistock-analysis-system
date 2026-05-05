import React, { useState, useEffect } from 'react';
import AgentPanel from './AgentPanel';
import { API_ENDPOINTS, buildApiUrl } from '../config/api';
import useMacroOverview from './hooks/useMacroOverview';
import useMacroReport from './hooks/useMacroReport';
import HelpTooltip from './components/HelpTooltip';
import { helpTips } from '../config/helpTips';

// 统一的图标组件 - 模块化设计
const RefreshIcon = ({ className = "w-4 h-4" }: { className?: string }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
  </svg>
);

const ChartIcon = ({ className = "w-4 h-4" }: { className?: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 20 20">
    <path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zM8 7a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zM14 4a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
  </svg>
);

const TaskIcon = ({ className = "w-4 h-4" }: { className?: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 20 20">
    <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
  </svg>
);

const StatsIcon = ({ className = "w-5 h-5" }: { className?: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 20 20">
    <path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z" />
  </svg>
);

const ActionIcon = ({ className = "w-4 h-4" }: { className?: string }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
  </svg>
);

const LoadingSpinner = () => (
  <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4}></circle>
    <path className="opacity-75" fill="currentColor" d="m4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
  </svg>
);

// 数据类型定义
interface DashboardData {
  totalStocks: number;
  completedReports: number;
  pendingReports: number;
  failedReports: number;
  reports: Array<{
    name?: string;
    stockCode: string;
    latestVersion: string;
    status: string;
    lastUpdate: string;
  }>;
}

const Dashboard: React.FC = () => {
  const [dashboardData, setDashboardData] = useState<DashboardData>({
    totalStocks: 0,
    completedReports: 0,
    pendingReports: 0,
    failedReports: 0,
    reports: []
  });
  
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'reports' | 'tasks' | 'macro' | 'agent'>('reports');
  const [selectedReportDate, setSelectedReportDate] = useState<'latest' | string>('latest');

  const {
    data: macroOverview,
    loading: macroLoading,
    refreshing: macroRefreshing,
    error: macroOverviewError,
    lastUpdated: macroOverviewLastUpdated,
    refresh: refreshMacroOverview,
  } = useMacroOverview({ enabled: activeTab === 'macro', autoRefreshMs: 180_000 });

  const requestedReportDate = selectedReportDate === 'latest' ? null : selectedReportDate;

  const {
    data: macroReportData,
    report: macroReport,
    loading: macroReportLoading,
    refreshing: macroReportRefreshing,
    error: macroReportError,
    lastUpdated: macroReportLastUpdated,
    refresh: refreshMacroReport,
  } = useMacroReport({
    enabled: activeTab === 'macro',
    reportDate: requestedReportDate,
    autoRefreshMs: 300_000,
  });

  const macroReportAvailableDates = macroReportData?.available_dates ?? [];
  const macroHighlights = macroReport?.highlights ?? [];
  const macroReportMetrics = macroReport?.metrics ?? {};
  const macroReportTopics = macroReport?.topics ?? [];
  const macroReportHistoryDates = macroReportAvailableDates.filter((value) => Boolean(value));
  const macroTopPositive = macroReport?.top_positive_topics ?? [];
  const macroTopNegative = macroReport?.top_negative_topics ?? [];
  const macroMostCovered = macroReport?.most_covered_topics ?? [];

  const macroTopics = macroReportTopics.length > 0 ? macroReportTopics : macroOverview?.topics ?? [];
  const macroModelRuns = macroOverview?.model_runs ?? [];
  const macroTopicCount = macroTopics.length;
  const macroTotalArticles = macroTopics.reduce((sum, topic) => sum + (topic.article_count ?? 0), 0);
  const macroAverageSentiment = macroTopicCount
    ? macroTopics.reduce((sum, topic) => sum + (topic.avg_sentiment ?? 0), 0) / macroTopicCount
    : null;
  const hasMacroData = macroTopicCount > 0 || !!macroReport;
  const macroStorageAvailable =
    macroOverview?.storage_available ?? (macroReport ? true : false);

  const macroTabLoading = (macroLoading && !macroOverview) || (macroReportLoading && !macroReport);
  const tabLoading = activeTab === 'macro' ? macroTabLoading : loading;
  const macroTabRefreshing = macroRefreshing || macroReportRefreshing;
  const tabRefreshing = activeTab === 'macro' ? macroTabRefreshing : refreshing;
  const macroErrorMessage = macroOverviewError || macroReportError;
  const macroDataLastUpdated = macroReportLastUpdated || macroOverviewLastUpdated;

  const fetchDashboardData = async (isRefresh: boolean = false) => {
    try {
      if (isRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const response = await fetch(buildApiUrl(API_ENDPOINTS.DASHBOARD.REPORTS));

      if (!response.ok) {
        throw new Error(`API请求失败: ${response.statusText}`);
      }

      const data = await response.json();
      
      // 转换数据格式 - 修复数据映射
      const transformedData: DashboardData = {
        totalStocks: data.summary?.total_stocks || 0,
        completedReports: data.summary?.with_reports || 0,
        pendingReports: data.summary?.pending_tasks || 0,
        failedReports: data.summary?.failed_tasks || 0,
        reports: data.stocks?.map((stock: any) => ({
          name: stock.name,
          stockCode: stock.symbol,
          latestVersion: stock.latest_report?.version || '未生成',
          status: stock.current_task?.status || (stock.latest_report ? 'completed' : 'unknown'),
          lastUpdate: stock.latest_report?.created_at ? 
            new Date(stock.latest_report.created_at).toLocaleString('zh-CN') : 
            stock.current_task?.completed_at ? 
              new Date(stock.current_task.completed_at).toLocaleString('zh-CN') : '未更新'
        })) || []
      };

      setDashboardData(transformedData);
    } catch (err) {
      console.error('Dashboard fetch error:', err);
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
    } finally {
      if (isRefresh) {
        setRefreshing(false);
      } else {
        setLoading(false);
      }
    }
  };

  const handleRefresh = () => {
    if (activeTab === 'macro') {
      refreshMacroOverview();
      refreshMacroReport(false);
    } else {
      fetchDashboardData(true);
    }
  };

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 30000);
    return () => clearInterval(interval);
  }, []);

  const getStatusStyle = (status: string) => {
    switch (status) {
      case 'completed': return 'dark-badge dark-badge-success';
      case 'running': return 'dark-badge dark-badge-info';
      case 'pending': return 'dark-badge dark-badge-warning';
      case 'failed': return 'dark-badge dark-badge-danger';
      default: return 'dark-badge';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'completed': return '已完成';
      case 'running': return '执行中';
      case 'pending': return '等待中';
      case 'failed': return '失败';
      default: return '未知';
    }
  };

  const retryReport = async (stockCode: string) => {
    try {
      const response = await fetch(buildApiUrl(API_ENDPOINTS.TASKS.REPORT(stockCode)), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ priority: 1 })
      });

      if (response.ok) {
        fetchDashboardData();
      }
    } catch (err) {
      console.error('Retry error:', err);
    }
  };

  const formatDateTime = (value: string | null | undefined) => {
    if (!value) {
      return '未知';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return parsed.toLocaleString('zh-CN');
  };

  const formatPercent = (value: number | null | undefined, digits = 1) => {
    if (value === null || value === undefined) {
      return '—';
    }
    return `${(value * 100).toFixed(digits)}%`;
  };

  const formatSentiment = (value: number | null | undefined) => {
    if (value === null || value === undefined) {
      return '—';
    }
    return value.toFixed(2);
  };

  const getSentimentTone = (value: number | null | undefined) => {
    if (value === null || value === undefined) {
      return {
        label: '未知',
        color: 'var(--text-muted)',
        background: 'rgba(255,255,255,0.05)',
      };
    }
    if (value >= 0.25) {
      return {
        label: '积极',
        color: 'var(--accent-lime)',
        background: 'rgba(110, 231, 183, 0.15)',
      };
    }
    if (value <= -0.25) {
      return {
        label: '偏空',
        color: 'var(--accent-red)',
        background: 'rgba(239, 68, 68, 0.15)',
      };
    }
    return {
      label: '中性',
      color: '#60a5fa',
      background: 'rgba(59, 130, 246, 0.15)',
    };
  };

  const formatMetricValue = (value: unknown) => {
    if (value === null || value === undefined) {
      return '—';
    }
    if (typeof value === 'number') {
      const abs = Math.abs(value);
      if (abs >= 100 || abs === 0) {
        return value.toFixed(2);
      }
      if (abs >= 1) {
        return value.toFixed(3);
      }
      if (abs >= 0.01) {
        return value.toFixed(4);
      }
      return value.toExponential(2);
    }
    if (typeof value === 'string') {
      return value;
    }
    try {
      return JSON.stringify(value);
    } catch (err) {
      console.error('Failed to stringify metric value', err);
      return String(value);
    }
  };

  const entityLabelMap: Record<string, string> = {
    companies: '公司',
    locations: '地区',
    people: '人物',
  };

  const getEntityLabel = (key: string) => {
    return entityLabelMap[key] || key;
  };

  const macroHighlightPalette: Record<string, { background: string; border: string; color: string }> = {
    'positive-topic': { background: 'rgba(110, 231, 183, 0.15)', border: '#6EE7B7', color: '#6EE7B7' },
    'negative-topic': { background: 'rgba(239, 68, 68, 0.15)', border: '#EF4444', color: '#EF4444' },
    'high-volume': { background: 'rgba(59, 130, 246, 0.15)', border: '#60a5fa', color: '#60a5fa' },
    'model-update': { background: 'rgba(167, 139, 250, 0.15)', border: '#a78bfa', color: '#a78bfa' },
  };

  const getHighlightStyle = (type: string) => {
    return (
      macroHighlightPalette[type] || {
        background: 'rgba(255,255,255,0.05)',
        border: 'var(--border)',
        color: 'var(--text-secondary)',
      }
    );
  };

  if (activeTab !== 'macro' && loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '300px' }}>
        <div className="dark-card" style={{ maxWidth: '400px', width: '100%', textAlign: 'center' }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '20px' }}>
            <LoadingSpinner />
          </div>
          <div style={{ fontSize: '18px', color: 'var(--text)', fontWeight: 500, marginBottom: '8px' }}>
            加载仪表板数据...
          </div>
          <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
            请稍候，正在获取最新信息
          </div>
        </div>
      </div>
    );
  }

  if (activeTab !== 'macro' && error) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '300px' }}>
        <div className="dark-card" style={{ maxWidth: '420px', width: '100%', textAlign: 'center', borderColor: 'rgba(239, 68, 68, 0.3)' }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '16px' }}>
            <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.2)', borderRadius: '50%', padding: 12, width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg style={{ width: 24, height: 24, color: 'var(--accent-red)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
          <h3 style={{ fontSize: 18, fontWeight: 600, color: 'var(--accent-red)', marginBottom: 8 }}>加载失败</h3>
          <p style={{ color: 'var(--accent-red)', marginBottom: 24, fontSize: 14 }}>{error}</p>
          <button onClick={() => fetchDashboardData(false)} className="dark-btn dark-btn-primary">
            <RefreshIcon />
            <span style={{ marginLeft: 8 }}>重试</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
        {/* 页头区域 */}
        <div className="dark-card" style={{ padding: 16, marginBottom: 16 }}>
          <div style={{ 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '16px'
          }}>
            <h1 style={{ 
              fontSize: '20px', 
              fontWeight: 'bold', 
              color: 'var(--text)',
              margin: 0
            }}>
              任务监控
            </h1>
            <div style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: '8px',
              flexWrap: 'wrap'
            }}>
              <HelpTooltip {...helpTips.refreshData}><span style={{ display: 'inline-flex' }}><button onClick={handleRefresh} disabled={tabLoading || tabRefreshing} className="dark-btn dark-btn-primary">
                {tabLoading || tabRefreshing ? <LoadingSpinner /> : <RefreshIcon />}
                <span style={{ marginLeft: 8 }}>{tabRefreshing ? '刷新中...' : tabLoading ? '加载中...' : '刷新'}</span>
              </button></span></HelpTooltip>
              <HelpTooltip {...helpTips.dashboardReports}><button onClick={() => setActiveTab('reports')} className={activeTab === 'reports' ? 'dark-btn dark-btn-primary' : 'dark-btn dark-btn-secondary'}>
                <ChartIcon />
                <span style={{ marginLeft: 8 }}>报告</span>
              </button></HelpTooltip>
              <HelpTooltip {...helpTips.dashboardStats}><button onClick={() => setActiveTab('tasks')} className={activeTab === 'tasks' ? 'dark-btn dark-btn-primary' : 'dark-btn dark-btn-secondary'}>
                <TaskIcon />
                <span style={{ marginLeft: 8 }}>统计</span>
              </button></HelpTooltip>
              <HelpTooltip {...helpTips.dashboardMacro}><button onClick={() => setActiveTab('macro')} className={activeTab === 'macro' ? 'dark-btn dark-btn-primary' : 'dark-btn dark-btn-secondary'}>
                <StatsIcon className="w-4 h-4" />
                <span style={{ marginLeft: 8 }}>宏观</span>
              </button></HelpTooltip>
              <HelpTooltip {...helpTips.dashboardAgent}><button onClick={() => setActiveTab('agent')} className={activeTab === 'agent' ? 'dark-btn dark-btn-primary' : 'dark-btn dark-btn-secondary'}>
                <StatsIcon className="w-4 h-4" />
                <span style={{ marginLeft: 8 }}>Agent</span>
              </button></HelpTooltip>
            </div>
          </div>
        </div>

        {/* 内容区域 */}
        <div className="dark-card" style={{ position: 'relative' }}>
          {/* 刷新遮罩层 */}
          {tabRefreshing && (
            <div style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: 'rgba(10, 12, 16, 0.85)',
              borderRadius: '12px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 10,
              backdropFilter: 'blur(2px)'
            }}>
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12px'
              }}>
                <LoadingSpinner />
                <div style={{
                  fontSize: '14px',
                  color: 'var(--text-muted)',
                  fontWeight: '500'
                }}>
                  正在刷新数据...
                </div>
              </div>
            </div>
          )}
          
          {activeTab === 'reports' && (
            <div style={{ padding: '16px' }}>
              {/* 统计数据区域 */}
              <div style={{ marginBottom: '24px' }}>
                <h3 style={{ 
                  fontSize: '18px', 
                  fontWeight: '500', 
                  color: 'var(--text)', 
                  marginBottom: '16px' 
                }}>
                  股票分析状态
                </h3>
                
                {/* 统计卡片 - 强制横向布局 */}
                <div style={{ 
                  display: 'flex', 
                  gap: '16px', 
                  flexWrap: 'wrap',
                  justifyContent: 'space-between',
                  opacity: refreshing ? 0.6 : 1,
                  transition: 'opacity 0.3s ease'
                }}>
                  <div className="dark-stat" style={{ 
                    flex: '1',
                    minWidth: '200px',
                    transform: refreshing ? 'scale(0.98)' : 'scale(1)',
                    transition: 'transform 0.3s ease'
                  }}>
                    <div className="dark-stat-value">{dashboardData.totalStocks}</div>
                    <div className="dark-stat-label">总数</div>
                  </div>
                  
                  <div className="dark-stat" style={{ 
                    flex: '1',
                    minWidth: '200px',
                    transform: refreshing ? 'scale(0.98)' : 'scale(1)',
                    transition: 'transform 0.3s ease',
                    '--stat-accent': 'var(--accent-lime)'
                  } as React.CSSProperties}>
                    <div className="dark-stat-value" style={{ color: 'var(--accent-lime)' }}>{dashboardData.completedReports}</div>
                    <div className="dark-stat-label">完成</div>
                  </div>
                  
                  <div className="dark-stat" style={{ 
                    flex: '1',
                    minWidth: '200px',
                    transform: refreshing ? 'scale(0.98)' : 'scale(1)',
                    transition: 'transform 0.3s ease',
                    '--stat-accent': 'var(--primary)'
                  } as React.CSSProperties}>
                    <div className="dark-stat-value" style={{ color: 'var(--primary)' }}>{dashboardData.pendingReports}</div>
                    <div className="dark-stat-label">进行</div>
                  </div>
                  
                  <div className="dark-stat" style={{ 
                    flex: '1',
                    minWidth: '200px',
                    transform: refreshing ? 'scale(0.98)' : 'scale(1)',
                    transition: 'transform 0.3s ease',
                    '--stat-accent': 'var(--accent-red)'
                  } as React.CSSProperties}>
                    <div className="dark-stat-value" style={{ color: 'var(--accent-red)' }}>{dashboardData.failedReports}</div>
                    <div className="dark-stat-label">失败</div>
                  </div>
                </div>
              </div>

              {/* 数据表格 - 优化样式 */}
              <div className="dark-table-wrap" style={{ 
                opacity: refreshing ? 0.6 : 1,
                transform: refreshing ? 'scale(0.99)' : 'scale(1)',
                transition: 'opacity 0.3s ease, transform 0.3s ease'
              }}>
                <div style={{ 
                  backgroundColor: 'var(--surface-dark)', 
                  padding: '16px', 
                  borderBottom: '1px solid var(--border-dark)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between'
                }}>
                  <h4 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text)', margin: 0 }}>
                    股票分析详情
                  </h4>
                  <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                    共 {dashboardData.reports.length} 条记录
                  </span>
                </div>
                
                <table className="dark-table">
                  <thead>
                    <tr>
                      <th>股票代码</th>
                      <th>最新版本</th>
                      <th>执行状态</th>
                      <th>更新时间</th>
                      <th style={{ textAlign: 'center' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dashboardData.reports.length === 0 ? (
                      <tr>
                        <td colSpan={5} style={{ 
                          padding: '48px 16px', 
                          textAlign: 'center', 
                          fontSize: '14px', 
                          color: 'var(--text-muted)' 
                        }}>
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                            <div style={{ 
                              backgroundColor: 'var(--surface-dark)', 
                              borderRadius: '50%', 
                              padding: '12px', 
                              marginBottom: '16px' 
                            }}>
                              <ChartIcon className="w-6 h-6" style={{ color: 'var(--text-muted)' }} />
                            </div>
                            <div style={{ fontSize: '16px', fontWeight: '500', color: 'var(--text)', marginBottom: '8px' }}>
                              暂无数据
                            </div>
                            <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                              当前没有股票报告数据
                            </div>
                          </div>
                        </td>
                      </tr>
                    ) : (
                      dashboardData.reports.map((report, index) => (
                        <tr key={report.stockCode}>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center' }}>
                              
                              <div className="dark-badge dark-badge-info">
                                {report.name ? (
                                  <span style={{ marginRight: '8px' }}>{report.name}</span>
                                ) : null}
                                (
                                {report.stockCode.slice(-2)}.
                                {report.stockCode.slice(0, -3)}
                                )

                              </div>
                            </div>
                          </td>
                          <td style={{ 
                            fontFamily: "'Space Grotesk', monospace",
                            color: 'var(--text-muted)'
                          }}>
                            {report.latestVersion || '未生成'}
                          </td>
                          <td>
                            <span className={`dark-badge ${
                              report.status === 'completed' ? 'dark-badge-success' :
                              report.status === 'running' ? 'dark-badge-info' :
                              report.status === 'pending' ? 'dark-badge-warning' :
                              report.status === 'failed' ? 'dark-badge-error' : ''
                            }`}>
                              {getStatusText(report.status)}
                            </span>
                          </td>
                          <td style={{ color: 'var(--text-muted)' }}>
                            {report.lastUpdate || '未更新'}
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            <button
                              onClick={() => retryReport(report.stockCode)}
                              disabled={report.status === 'running'}
                              className="dark-btn dark-btn-ghost"
                              style={{
                                opacity: report.status === 'running' ? 0.5 : 1,
                                cursor: report.status === 'running' ? 'not-allowed' : 'pointer'
                              }}
                            >
                              <ActionIcon className="w-3 h-3 mr-1" />
                              重新执行
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {activeTab === 'macro' && (
            <div style={{ padding: '24px' }}>
              {tabLoading && !hasMacroData ? (
                <div style={{
                  minHeight: '320px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '16px'
                }}>
                  <LoadingSpinner />
                  <div style={{ fontSize: '15px', color: 'var(--text-muted)', fontWeight: 500 }}>正在加载宏观情绪数据...</div>
                  <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>请稍候，这可能需要几秒钟</div>
                </div>
              ) : macroErrorMessage ? (
                <div style={{
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  backgroundColor: 'rgba(239, 68, 68, 0.1)',
                  borderRadius: '12px',
                  padding: '32px',
                  maxWidth: '520px',
                  margin: '0 auto',
                  textAlign: 'center'
                }}>
                  <div style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backgroundColor: 'rgba(239, 68, 68, 0.2)',
                    color: 'var(--accent-red)',
                    borderRadius: '9999px',
                    width: '48px',
                    height: '48px',
                    marginBottom: '16px'
                  }}>
                    <svg style={{ width: '24px', height: '24px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--accent-red)', marginBottom: '12px' }}>宏观数据加载失败</h3>
                  <p style={{ color: 'var(--accent-red)', fontSize: '14px', marginBottom: '20px' }}>{macroErrorMessage}</p>
                  <button
                    onClick={() => {
                      refreshMacroOverview();
                      refreshMacroReport(false);
                    }}
                    className="dark-btn dark-btn-primary"
                    style={{ backgroundColor: 'var(--accent-red)' }}
                  >
                    <RefreshIcon />
                    <span style={{ marginLeft: '8px' }}>重新获取</span>
                  </button>
                </div>
              ) : !hasMacroData ? (
                <div style={{
                  minHeight: '320px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '12px',
                  color: 'var(--text-muted)'
                }}>
                  <div style={{
                    backgroundColor: 'var(--surface-dark)',
                    borderRadius: '14px',
                    padding: '16px'
                  }}>
                    <StatsIcon className="w-6 h-6" style={{ color: 'var(--text-muted)' }} />
                  </div>
                  <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text)' }}>暂无宏观观测记录</div>
                  <div style={{ fontSize: '14px', color: 'var(--text-muted)', maxWidth: '360px', textAlign: 'center' }}>
                    宏观情绪任务尚未生成结果。请稍后重试或检查后端调度状态。
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '16px',
                    alignItems: 'flex-start'
                  }}>
                    <div>
                      <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text)', marginBottom: '8px' }}>
                        宏观情绪总览
                      </h3>
                      <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                        最后更新：{formatDateTime(macroDataLastUpdated)}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{
                        width: '10px',
                        height: '10px',
                        borderRadius: '50%',
                        backgroundColor: macroStorageAvailable ? 'var(--accent-lime)' : 'var(--accent-red)',
                        boxShadow: macroStorageAvailable
                          ? '0 0 0 4px rgba(110, 231, 183, 0.2)'
                          : '0 0 0 4px rgba(239, 68, 68, 0.2)'
                      }}></div>
                      <span style={{ fontSize: '14px', color: macroStorageAvailable ? 'var(--accent-lime)' : 'var(--accent-red)', fontWeight: 500 }}>
                        {macroStorageAvailable ? '数据连接正常' : '存储未连接'}
                      </span>
                    </div>
                  </div>

                  <div className="dark-card" style={{
                    padding: '24px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '24px'
                  }}>
                    <div style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: '16px',
                      alignItems: 'flex-start'
                    }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <span style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)' }}>每日宏观日报</span>
                        <span style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text)' }}>{macroReport?.report_date ?? '—'}</span>
                        <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                          生成时间：{formatDateTime(macroReport?.generated_at ?? null)}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                        <select
                          value={selectedReportDate}
                          onChange={(event) => setSelectedReportDate(event.target.value as 'latest' | string)}
                          className="dark-select"
                          style={{ minWidth: '160px' }}
                          disabled={tabLoading || tabRefreshing}
                        >
                          <option value="latest">最新日报</option>
                          {macroReportHistoryDates.map((dateValue) => (
                            <option key={dateValue} value={dateValue}>
                              {dateValue}
                            </option>
                          ))}
                        </select>
                        <button
                          onClick={() => refreshMacroReport(true)}
                          disabled={tabLoading || tabRefreshing}
                          className="dark-btn dark-btn-primary"
                        >
                          <RefreshIcon className="w-4 h-4" />
                          生成最新
                        </button>
                      </div>
                    </div>

                    {macroReport ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                        {macroHighlights.length > 0 && (
                          <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                            gap: '16px'
                          }}>
                            {macroHighlights.map((highlight, index) => {
                              const palette = getHighlightStyle(highlight.type);
                              return (
                                <div
                                  key={`${highlight.type}-${index}`}
                                  style={{
                                    border: `1px solid ${palette.border}`,
                                    backgroundColor: palette.background,
                                    color: palette.color,
                                    borderRadius: '12px',
                                    padding: '16px',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '8px'
                                  }}
                                >
                                  <span style={{ fontSize: '13px', fontWeight: 600 }}>{highlight.title}</span>
                                  <span style={{ fontSize: '13px', color: palette.color }}>{highlight.detail}</span>
                                </div>
                              );
                            })}
                          </div>
                        )}

                        <div style={{
                          display: 'grid',
                          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                          gap: '16px'
                        }}>
                          <div className="dark-stat">
                            <span className="dark-stat-label">文章总量</span>
                            <span className="dark-stat-value">
                              {(macroReportMetrics.article_count ?? macroTotalArticles ?? 0)}
                            </span>
                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>覆盖的新闻数量</span>
                          </div>
                          <div className="dark-stat" style={{ '--stat-accent': 'var(--accent-gold)' } as React.CSSProperties}>
                            <span className="dark-stat-label">平均情绪</span>
                            <span className="dark-stat-value" style={{ color: 'var(--accent-gold)' }}>
                              {formatSentiment(macroReportMetrics.average_sentiment ?? macroAverageSentiment)}
                            </span>
                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>范围 [-1, 1]</span>
                          </div>
                          <div className="dark-stat" style={{ '--stat-accent': 'var(--accent-lime)' } as React.CSSProperties}>
                            <span className="dark-stat-label">积极主题占比</span>
                            <span className="dark-stat-value" style={{ color: 'var(--accent-lime)' }}>
                              {formatPercent(macroReportMetrics.positive_topic_ratio ?? null)}
                            </span>
                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>最近一天</span>
                          </div>
                        </div>

                        {(macroTopPositive.length > 0 || macroTopNegative.length > 0 || macroMostCovered.length > 0) && (
                          <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                            gap: '16px'
                          }}>
                            {macroTopPositive.length > 0 && (
                              <div className="dark-card" style={{
                                borderColor: 'rgba(110, 231, 183, 0.3)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '10px'
                              }}>
                                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--accent-lime)' }}>积极焦点</span>
                                <span style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text)' }}>
                                  {macroTopPositive[0].topic_display ?? macroTopPositive[0].topic}
                                </span>
                                <div style={{ fontSize: '13px', color: 'var(--accent-lime)' }}>
                                  情绪 {formatSentiment(macroTopPositive[0].avg_sentiment)}
                                </div>
                                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                  文章数 {macroTopPositive[0].article_count ?? 0}
                                </div>
                              </div>
                            )}
                            {macroTopNegative.length > 0 && (
                              <div className="dark-card" style={{
                                borderColor: 'rgba(239, 68, 68, 0.3)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '10px'
                              }}>
                                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--accent-red)' }}>风险关注</span>
                                <span style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text)' }}>
                                  {macroTopNegative[0].topic_display ?? macroTopNegative[0].topic}
                                </span>
                                <div style={{ fontSize: '13px', color: 'var(--accent-red)' }}>
                                  情绪 {formatSentiment(macroTopNegative[0].avg_sentiment)}
                                </div>
                                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                  文章数 {macroTopNegative[0].article_count ?? 0}
                                </div>
                              </div>
                            )}
                            {macroMostCovered.length > 0 && (
                              <div className="dark-card" style={{
                                borderColor: 'rgba(17, 101, 116, 0.3)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '10px'
                              }}>
                                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--primary)' }}>热度最高</span>
                                <span style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text)' }}>
                                  {macroMostCovered[0].topic_display ?? macroMostCovered[0].topic}
                                </span>
                                <div style={{ fontSize: '13px', color: 'var(--primary)' }}>
                                  文章数 {macroMostCovered[0].article_count ?? 0}
                                </div>
                                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                  关键词 {(macroMostCovered[0].top_keywords || []).slice(0, 3).join(', ') || '—'}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div style={{
                        padding: '24px',
                        border: '1px dashed var(--border-dark)',
                        borderRadius: '12px',
                        textAlign: 'center',
                        color: 'var(--text-muted)',
                        backgroundColor: 'var(--surface-dark)'
                      }}>
                        暂无日报快照，可尝试切换日期或稍后刷新。
                      </div>
                    )}
                  </div>

                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: '16px'
                  }}>
                    <div className="dark-stat">
                      <div className="dark-stat-label">主题数量</div>
                      <div className="dark-stat-value">{macroTopicCount}</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>跟踪的宏观主题</div>
                    </div>

                    <div style={{
                      padding: '20px',
                      borderRadius: '12px',
                      border: '1px solid var(--border)',
                      background: 'rgba(163, 230, 53, 0.05)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px'
                    }}>
                      <div style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--accent-lime)' }}>文章覆盖</div>
                      <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--text)' }}>{macroTotalArticles}</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>收录的新闻篇目</div>
                    </div>

                    <div style={{
                      padding: '20px',
                      borderRadius: '12px',
                      border: '1px solid var(--border)',
                      background: 'rgba(99, 102, 241, 0.05)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '10px'
                    }}>
                      <div style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--primary)' }}>平均情绪</div>
                      {(() => {
                        const tone = getSentimentTone(macroAverageSentiment);
                        return (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <span style={{ fontSize: '28px', fontWeight: 700, color: 'var(--text)' }}>{formatSentiment(macroAverageSentiment)}</span>
                            <span style={{
                              padding: '4px 10px',
                              borderRadius: '9999px',
                              backgroundColor: tone.background,
                              color: tone.color,
                              fontSize: '12px',
                              fontWeight: 600
                            }}>
                              {tone.label}
                            </span>
                          </div>
                        );
                      })()}
                      <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>情绪范围：[-1.00, 1.00]</div>
                    </div>

                    <div style={{
                      padding: '20px',
                      borderRadius: '12px',
                      border: '1px solid var(--border)',
                      background: 'rgba(245, 158, 11, 0.05)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px'
                    }}>
                      <div style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--accent-amber)' }}>模型运行</div>
                      <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--text)' }}>{macroModelRuns.length}</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>最近的训练记录</div>
                    </div>
                  </div>

                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
                    gap: '24px'
                  }}>
                    {macroTopics.map((topic, index) => {
                      const tone = getSentimentTone(topic.avg_sentiment);
                      const positiveRatio = topic.positive_ratio ?? 0;
                      const neutralRatio = topic.neutral_ratio ?? 0;
                      const negativeRatio = topic.negative_ratio ?? 0;
                      const entityEntries = Object.entries(topic.top_entities || {}).filter(
                        ([, list]) => Array.isArray(list) && list.length > 0,
                      );
                      const summaries = (topic.summaries || []).slice(0, 3);
                      const references = (topic.references || []).slice(0, 3);

                      return (
                        <div
                          key={`${topic.topic}-${index}`}
                          style={{
                            border: '1px solid var(--border)',
                            borderRadius: '12px',
                            padding: '20px',
                            background: 'var(--surface-dark)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '16px'
                          }}
                        >
                          <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            flexWrap: 'wrap',
                            gap: '12px',
                            alignItems: 'baseline'
                          }}>
                            <div>
                              <h4 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)', marginBottom: '4px' }}>
                                {topic.topic_display || topic.topic}
                              </h4>
                              <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                                观测时间：{formatDateTime(topic.observation_date)}
                              </div>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>文章数</span>
                              <span style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{topic.article_count ?? 0}</span>
                            </div>
                          </div>

                          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span style={{ fontSize: '14px', color: 'var(--text)', fontWeight: 600 }}>情绪概览</span>
                              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text)' }}>
                                  {formatSentiment(topic.avg_sentiment)}
                                </span>
                                <span style={{
                                  padding: '4px 10px',
                                  borderRadius: '9999px',
                                  backgroundColor: tone.background,
                                  color: tone.color,
                                  fontSize: '12px',
                                  fontWeight: 600
                                }}>
                                  {tone.label}
                                </span>
                              </span>
                            </div>
                            <div style={{
                              display: 'flex',
                              width: '100%',
                              height: '10px',
                              borderRadius: '9999px',
                              overflow: 'hidden',
                              backgroundColor: 'var(--border)'
                            }}>
                              <div style={{
                                width: `${Math.min(Math.max(positiveRatio, 0), 1) * 100}%`,
                                backgroundColor: 'var(--accent-lime)'
                              }}></div>
                              <div style={{
                                width: `${Math.min(Math.max(neutralRatio, 0), 1) * 100}%`,
                                backgroundColor: 'rgba(255,255,255,0.1)'
                              }}></div>
                              <div style={{
                                width: `${Math.min(Math.max(negativeRatio, 0), 1) * 100}%`,
                                backgroundColor: 'var(--accent-red)'
                              }}></div>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-muted)' }}>
                              <span>积极 {formatPercent(positiveRatio)}</span>
                              <span>中性 {formatPercent(neutralRatio)}</span>
                              <span>消极 {formatPercent(negativeRatio)}</span>
                            </div>
                          </div>

                          {(topic.top_keywords || []).length > 0 && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                              <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>核心关键词</div>
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                {(topic.top_keywords || []).slice(0, 8).map((keyword, keywordIndex) => (
                                  <span
                                    key={`${topic.topic}-keyword-${keywordIndex}`}
                                    style={{
                                      padding: '4px 10px',
                                      borderRadius: '9999px',
                                      backgroundColor: 'rgba(99, 102, 241, 0.15)',
                                      color: 'var(--primary)',
                                      fontSize: '12px',
                                      fontWeight: 500
                                    }}
                                  >
                                    #{keyword}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {entityEntries.length > 0 && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                              <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>关联实体</div>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                {entityEntries.map(([label, values]) => (
                                  <div key={`${topic.topic}-entity-${label}`} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                                    <span style={{
                                      minWidth: '44px',
                                      fontSize: '12px',
                                      fontWeight: 600,
                                      color: 'var(--text-muted)'
                                    }}>
                                      {getEntityLabel(label)}
                                    </span>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                      {(values as string[]).slice(0, 6).map((value, valueIndex) => (
                                        <span
                                          key={`${topic.topic}-entity-${label}-${valueIndex}`}
                                          style={{
                                            padding: '3px 8px',
                                            borderRadius: '6px',
                                            backgroundColor: 'rgba(255,255,255,0.05)',
                                            color: 'var(--text-muted)',
                                            fontSize: '12px',
                                            border: '1px solid var(--border)'
                                          }}
                                        >
                                          {value}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {summaries.length > 0 && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                              <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>要点摘要</div>
                              <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--text-muted)', fontSize: '13px' }}>
                                {summaries.map((summary, summaryIndex) => (
                                  <li key={`${topic.topic}-summary-${summaryIndex}`} style={{ marginBottom: '6px' }}>
                                    {summary}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {references.length > 0 && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                              <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>相关报道</div>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                {references.map((reference, referenceIndex) => {
                                  const content = (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                      <span style={{ fontSize: '13px', color: 'var(--primary)', fontWeight: 500 }}>
                                        {reference.title || '新闻链接'}
                                      </span>
                                      <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                        {formatDateTime(reference.published_at)}
                                      </span>
                                    </div>
                                  );

                                  return reference.url ? (
                                    <a
                                      key={`${topic.topic}-reference-${referenceIndex}`}
                                      href={reference.url || undefined}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      style={{
                                        padding: '10px 12px',
                                        borderRadius: '8px',
                                        border: '1px solid rgba(99, 102, 241, 0.3)',
                                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                                        textDecoration: 'none',
                                        display: 'block'
                                      }}
                                    >
                                      {content}
                                    </a>
                                  ) : (
                                    <div
                                      key={`${topic.topic}-reference-${referenceIndex}`}
                                      style={{
                                        padding: '10px 12px',
                                        borderRadius: '8px',
                                        border: '1px solid var(--border)',
                                        backgroundColor: 'rgba(255,255,255,0.02)'
                                      }}
                                    >
                                      {content}
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {macroModelRuns.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                        <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>模型训练结果</h3>
                        <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>最新 {macroModelRuns.length} 次训练记录</span>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
                        {macroModelRuns.map((run, runIndex) => {
                          const metricEntries = Object.entries(run.metrics || {}).slice(0, 6);
                          const coefficientEntries = Object.entries(run.coefficients || {}).slice(0, 6);
                          const hasCalibration = run.calibration && Object.keys(run.calibration).length > 0;
                          const notes = (run.notes || []).slice(0, 3);

                          return (
                            <div
                              key={`${run.model_name || 'model'}-${run.run_date || runIndex}`}
                              style={{
                                border: '1px solid var(--border)',
                                borderRadius: '12px',
                                padding: '20px',
                                backgroundColor: 'var(--surface-dark)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '14px'
                              }}
                            >
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                                  <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text)' }}>
                                    {run.model_name || '未命名模型'}
                                  </div>
                                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                    {formatDateTime(run.run_date)}
                                  </span>
                                </div>
                                {metricEntries.length > 0 && (
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                    {metricEntries.map(([metricKey, metricValue]) => (
                                      <span
                                        key={`${runIndex}-metric-${metricKey}`}
                                        style={{
                                          padding: '4px 10px',
                                          borderRadius: '9999px',
                                          backgroundColor: 'rgba(99, 102, 241, 0.15)',
                                          color: 'var(--primary)',
                                          fontSize: '12px',
                                          fontWeight: 500
                                        }}
                                      >
                                        {metricKey}: {formatMetricValue(metricValue)}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>

                              {coefficientEntries.length > 0 && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>重要系数</div>
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                    {coefficientEntries.map(([coefKey, coefValue]) => (
                                      <span
                                        key={`${runIndex}-coef-${coefKey}`}
                                        style={{
                                          padding: '4px 10px',
                                          borderRadius: '9999px',
                                          backgroundColor: 'rgba(245, 158, 11, 0.15)',
                                          color: 'var(--accent-amber)',
                                          fontSize: '12px',
                                          fontWeight: 500
                                        }}
                                      >
                                        {coefKey}: {formatMetricValue(coefValue)}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {hasCalibration && (
                                <div style={{
                                  borderRadius: '8px',
                                  border: '1px dashed var(--border)',
                                  backgroundColor: 'rgba(255,255,255,0.02)',
                                  padding: '12px'
                                }}>
                                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)', marginBottom: '4px' }}>
                                    校准信息
                                  </div>
                                  <pre style={{
                                    margin: 0,
                                    fontSize: '12px',
                                    color: 'var(--text-muted)',
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-all'
                                  }}>
                                    {JSON.stringify(run.calibration, null, 2)}
                                  </pre>
                                </div>
                              )}

                              {notes.length > 0 && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>模型备注</div>
                                  <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--text-muted)', fontSize: '13px' }}>
                                    {notes.map((note, noteIndex) => (
                                      <li key={`${runIndex}-note-${noteIndex}`} style={{ marginBottom: '4px' }}>
                                        {note}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {activeTab === 'agent' && (
            <div style={{ padding: '24px' }}>
              <AgentPanel />
            </div>
          )}

          {activeTab === 'tasks' && (
            <div style={{ padding: '24px' }}>
              {/* 统计概览区域 */}
              <div style={{ marginBottom: '32px' }}>
                <h3 style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text)', marginBottom: '16px' }}>
                  任务执行统计
                </h3>
                
                {/* 统计图表区域 */}
                <div style={{ 
                  display: 'flex', 
                  gap: '24px', 
                  flexWrap: 'wrap',
                  marginBottom: '32px'
                }}>
                  {/* 成功率统计 */}
                  <div style={{ 
                    flex: '1',
                    minWidth: '300px',
                    backgroundColor: 'var(--surface-dark)', 
                    borderRadius: '12px', 
                    padding: '24px', 
                    border: '1px solid var(--border)'
                  }}>
                    <h4 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text)', marginBottom: '16px' }}>
                      总体成功率
                    </h4>
                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px' }}>
                      <div style={{ 
                        fontSize: '36px', 
                        fontWeight: 'bold', 
                        color: 'var(--accent-lime)',
                        marginRight: '12px'
                      }}>
                        {dashboardData.totalStocks > 0 ? 
                          Math.round((dashboardData.completedReports / dashboardData.totalStocks) * 100) : 0}%
                      </div>
                      <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                        {dashboardData.completedReports} / {dashboardData.totalStocks} 任务完成
                      </div>
                    </div>
                    <div style={{ 
                      width: '100%', 
                      height: '8px', 
                      backgroundColor: 'var(--border)', 
                      borderRadius: '4px',
                      overflow: 'hidden'
                    }}>
                      <div style={{ 
                        height: '100%', 
                        backgroundColor: 'var(--accent-lime)',
                        width: `${dashboardData.totalStocks > 0 ? (dashboardData.completedReports / dashboardData.totalStocks) * 100 : 0}%`,
                        transition: 'width 0.3s ease'
                      }}></div>
                    </div>
                  </div>
                  
                  {/* 任务分布统计 */}
                  <div style={{ 
                    flex: '1',
                    minWidth: '300px',
                    backgroundColor: 'var(--surface-dark)', 
                    borderRadius: '12px', 
                    padding: '24px', 
                    border: '1px solid var(--border)'
                  }}>
                    <h4 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text)', marginBottom: '16px' }}>
                      任务状态分布
                    </h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                          <div style={{ 
                            width: '12px', 
                            height: '12px', 
                            backgroundColor: 'var(--accent-lime)', 
                            borderRadius: '50%', 
                            marginRight: '8px' 
                          }}></div>
                          <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>已完成</span>
                        </div>
                        <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text)' }}>
                          {dashboardData.completedReports}
                        </span>
                      </div>
                      
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                          <div style={{ 
                            width: '12px', 
                            height: '12px', 
                            backgroundColor: 'var(--primary)', 
                            borderRadius: '50%', 
                            marginRight: '8px' 
                          }}></div>
                          <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>进行中</span>
                        </div>
                        <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text)' }}>
                          {dashboardData.pendingReports}
                        </span>
                      </div>
                      
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                          <div style={{ 
                            width: '12px', 
                            height: '12px', 
                            backgroundColor: 'var(--accent-red)', 
                            borderRadius: '50%', 
                            marginRight: '8px' 
                          }}></div>
                          <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>失败</span>
                        </div>
                        <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text)' }}>
                          {dashboardData.failedReports}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
                
                {/* 详细统计表格 */}
                <div style={{ 
                  backgroundColor: 'var(--surface-dark)', 
                  borderRadius: '12px', 
                  border: '1px solid var(--border)',
                  overflow: 'hidden'
                }}>
                  <div style={{ 
                    backgroundColor: 'rgba(255,255,255,0.02)', 
                    padding: '16px 24px', 
                    borderBottom: '1px solid var(--border)'
                  }}>
                    <h4 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text)', margin: 0 }}>
                      任务执行详情统计
                    </h4>
                  </div>
                  
                  <div style={{ padding: '24px' }}>
                    <div style={{ 
                      display: 'grid', 
                      gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', 
                      gap: '16px'
                    }}>
                      <div style={{ 
                        padding: '16px', 
                        backgroundColor: 'rgba(99, 102, 241, 0.1)', 
                        borderRadius: '8px',
                        border: '1px solid rgba(99, 102, 241, 0.3)'
                      }}>
                        <div style={{ fontSize: '14px', color: 'var(--primary)', marginBottom: '4px' }}>
                          平均执行时间
                        </div>
                        <div style={{ fontSize: '20px', fontWeight: 'bold', color: 'var(--text)' }}>
                          ~ 2.5分钟
                        </div>
                      </div>
                      
                      <div style={{ 
                        padding: '16px', 
                        backgroundColor: 'rgba(163, 230, 53, 0.1)', 
                        borderRadius: '8px',
                        border: '1px solid rgba(163, 230, 53, 0.3)'
                      }}>
                        <div style={{ fontSize: '14px', color: 'var(--accent-lime)', marginBottom: '4px' }}>
                          今日完成任务
                        </div>
                        <div style={{ fontSize: '20px', fontWeight: 'bold', color: 'var(--text)' }}>
                          {dashboardData.completedReports}
                        </div>
                      </div>
                      
                      <div style={{ 
                        padding: '16px', 
                        backgroundColor: 'rgba(245, 158, 11, 0.1)', 
                        borderRadius: '8px',
                        border: '1px solid rgba(245, 158, 11, 0.3)'
                      }}>
                        <div style={{ fontSize: '14px', color: 'var(--accent-amber)', marginBottom: '4px' }}>
                          待处理任务
                        </div>
                        <div style={{ fontSize: '20px', fontWeight: 'bold', color: 'var(--text)' }}>
                          {dashboardData.pendingReports}
                        </div>
                      </div>
                      
                      <div style={{ 
                        padding: '16px', 
                        backgroundColor: 'rgba(239, 68, 68, 0.1)', 
                        borderRadius: '8px',
                        border: '1px solid rgba(239, 68, 68, 0.3)'
                      }}>
                        <div style={{ fontSize: '14px', color: 'var(--accent-red)', marginBottom: '4px' }}>
                          失败重试次数
                        </div>
                        <div style={{ fontSize: '20px', fontWeight: 'bold', color: 'var(--text)' }}>
                          {dashboardData.failedReports}
                        </div>
                      </div>
                    </div>
                    
                    {/* 系统状态指示 */}
                    <div style={{ 
                      marginTop: '24px', 
                      padding: '16px', 
                      backgroundColor: 'rgba(255,255,255,0.02)',
                      borderRadius: '8px',
                      border: '1px solid var(--border)'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div>
                          <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text)', marginBottom: '4px' }}>
                            系统运行状态
                          </div>
                          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                            最后更新: {new Date().toLocaleString('zh-CN')}
                          </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                          <div style={{ 
                            width: '8px', 
                            height: '8px', 
                            backgroundColor: 'var(--accent-lime)', 
                            borderRadius: '50%', 
                            marginRight: '8px',
                            animation: 'pulse 2s infinite'
                          }}></div>
                          <span style={{ fontSize: '14px', color: 'var(--accent-lime)', fontWeight: '500' }}>
                            正常运行
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
