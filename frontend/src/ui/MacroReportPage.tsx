import React, { useMemo, useState } from 'react';
import useMacroReport from './hooks/useMacroReport';
import {
  MacroReportModelInsight,
  MacroReportTopic,
} from '../config/api';

const highlightPalette: Record<string, { background: string; border: string; color: string }> = {
  'positive-topic': { background: 'rgba(110, 231, 183, 0.15)', border: '#6EE7B7', color: '#6EE7B7' },
  'negative-topic': { background: 'rgba(239, 68, 68, 0.15)', border: '#EF4444', color: '#EF4444' },
  'high-volume': { background: 'rgba(59, 130, 246, 0.15)', border: '#60a5fa', color: '#60a5fa' },
  'model-update': { background: 'rgba(167, 139, 250, 0.15)', border: '#a78bfa', color: '#a78bfa' },
};

const getHighlightStyle = (type: string) => {
  return (
    highlightPalette[type] || {
      background: 'rgba(255,255,255,0.05)',
      border: 'var(--border)',
      color: 'var(--text-secondary)',
    }
  );
};

const toNumber = (value: number | string | null | undefined): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'number') {
    return Number.isNaN(value) ? null : value;
  }
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
};

const formatNumber = (value: number | string | null | undefined, fractionDigits = 0) => {
  const numericValue = toNumber(value);
  if (numericValue === null) {
    return '—';
  }
  if (Math.abs(numericValue) >= 1000) {
    return numericValue.toLocaleString('zh-CN', {
      maximumFractionDigits: Math.max(fractionDigits, 1),
    });
  }
  return numericValue.toFixed(Math.max(fractionDigits, 0));
};

const formatPercent = (value: number | string | null | undefined, fractionDigits = 1) => {
  const numericValue = toNumber(value);
  if (numericValue === null) {
    return '—';
  }
  return `${(numericValue * 100).toFixed(fractionDigits)}%`;
};

const formatDateTime = (value: string | null | undefined) => {
  if (!value) {
    return '未知';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString('zh-CN');
};

const sentimentLabel = (value: number | string | null | undefined) => {
  const numericValue = toNumber(value);
  if (numericValue === null) {
    return '未知';
  }
  if (numericValue >= 0.25) {
    return '积极';
  }
  if (numericValue <= -0.25) {
    return '偏空';
  }
  return '中性';
};

const MacroReportPage: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState<'latest' | string>('latest');
  const reportDate = selectedDate === 'latest' ? null : selectedDate;
  const autoRefreshMs = selectedDate === 'latest' ? 300_000 : 0;

  const {
    report,
    data,
    loading,
    refreshing,
    error,
    lastUpdated,
    refresh,
  } = useMacroReport({
    enabled: true,
    reportDate,
    autoRefreshMs,
  });

  const availableDates = useMemo(() => {
    const dates = data?.available_dates ?? [];
    const unique = Array.from(new Set(dates.filter((value): value is string => Boolean(value))));
    return unique;
  }, [data]);

  const metrics = report?.metrics ?? {};
  const highlights = report?.highlights ?? [];
  const topics = report?.topics ?? [];
  const topPositive = report?.top_positive_topics ?? [];
  const topNegative = report?.top_negative_topics ?? [];
  const mostCovered = report?.most_covered_topics ?? [];
  const modelInsights = report?.model_insights ?? null;

  const handleDateChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    if (!value) {
      setSelectedDate('latest');
      return;
    }
    if (value === 'latest') {
      setSelectedDate('latest');
    } else {
      setSelectedDate(value);
    }
  };

  const handleRefresh = (force = false) => {
    void refresh(force);
  };

  const hasReport = Boolean(report);

  return (
    <div>
      <div className="page-container">
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 16,
            justifyContent: 'space-between',
            alignItems: 'flex-start',
          }}
        >
          <div>
            <div style={{ fontSize: 14, color: 'var(--text-muted)', marginBottom: 4 }}>宏观洞察 · 每日更新</div>
            <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: 'var(--text)' }}>每日宏观日报</h1>
            {report?.report_date && (
              <div style={{ marginTop: 8, fontSize: 14, color: 'var(--text)' }}>
                报告日期：{report.report_date}
              </div>
            )}
            {lastUpdated && (
              <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-muted)' }}>
                最近更新：{formatDateTime(lastUpdated)}
              </div>
            )}
          </div>

          <div className="page-actions">
            <select value={selectedDate === 'latest' ? 'latest' : selectedDate} onChange={handleDateChange} className="app-search">
              <option value="latest">最新日报</option>
              {availableDates.map((date) => (
                <option key={date} value={date}>
                  {date}
                </option>
              ))}
            </select>
            <button onClick={() => handleRefresh(false)} disabled={loading} className="dark-btn dark-btn-secondary">{refreshing ? '刷新中…' : '重新加载'}</button>
            <button onClick={() => handleRefresh(true)} disabled={loading} className="dark-btn dark-btn-primary">{loading ? '生成中…' : '立即生成'}</button>
          </div>
        </div>

        {error && (
          <div
            style={{
              backgroundColor: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: 12,
              padding: '16px 20px',
              color: 'var(--accent-red)',
              fontSize: 14,
            }}
          >
            ⚠️ 获取宏观日报失败：{error}
          </div>
        )}

        {!loading && !hasReport && !error && (
          <div
            className="card-panel"
            style={{
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: 14,
            }}
          >
            暂无可用的宏观日报，请尝试点击“立即生成”。
          </div>
        )}

        {loading && !hasReport && (
          <div
            className="card-panel"
            style={{
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: 14,
            }}
          >
            正在加载最新宏观日报，请稍候…
          </div>
        )}

        {hasReport && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <section className="card-panel">
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'var(--text)' }}>宏观情绪概览</h2>
              <div
                style={{
                  display: 'grid',
                  gap: 16,
                  marginTop: 20,
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                }}
              >
                <MetricCard label="主题数量" value={formatNumber(metrics.topic_count, 0)} />
                <MetricCard label="文章数量" value={formatNumber(metrics.article_count, 0)} />
                <MetricCard
                  label="平均情绪"
                  value={`${formatNumber(metrics.average_sentiment ?? null, 2)} · ${sentimentLabel(
                    metrics.average_sentiment ?? null,
                  )}`}
                />
                <MetricCard label="积极主题占比" value={formatPercent(metrics.positive_topic_ratio ?? null, 1)} />
                {metrics.negative_topic_ratio !== undefined && (
                  <MetricCard label="偏空主题占比" value={formatPercent(metrics.negative_topic_ratio ?? null, 1)} />
                )}
                {metrics.neutral_topic_ratio !== undefined && (
                  <MetricCard label="中性主题占比" value={formatPercent(metrics.neutral_topic_ratio ?? null, 1)} />
                )}
              </div>
            </section>

            {highlights.length > 0 && (
              <section className="card-panel">
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                  <span style={{ fontSize: 20, fontWeight: 600, color: 'var(--text)' }}>今日亮点</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>从情绪波动和模型洞察抓取的关键信号</span>
                </div>
                <div
                  style={{
                    display: 'grid',
                    gap: 16,
                    gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                  }}
                >
                  {highlights.map((item, index) => {
                    const style = getHighlightStyle(item.type);
                    return (
                      <div
                        key={`${item.title}-${index}`}
                        style={{
                          border: `1px solid ${style.border}`,
                          backgroundColor: style.background,
                          color: style.color,
                          borderRadius: 14,
                          padding: '18px 20px',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 8,
                        }}
                      >
                        <div style={{ fontSize: 13, opacity: 0.9 }}>#{item.type}</div>
                        <div style={{ fontSize: 16, fontWeight: 600 }}>{item.title}</div>
                        <div style={{ fontSize: 13, lineHeight: 1.6, opacity: 0.85 }}>{item.detail}</div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            <section style={{ display: 'grid', gap: 20, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
              <TopicListCard title="积极主题 Top" subtitle="情绪高涨的关注焦点" topics={topPositive} />
              <TopicListCard title="偏空主题 Top" subtitle="需关注的负面信号" topics={topNegative} sentimentTone="negative" />
              <TopicListCard title="高关注度主题" subtitle="媒体覆盖最广" topics={mostCovered} />
            </section>

            <section className="card-panel">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'var(--text)' }}>主题详情</h2>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>共 {topics.length} 个主题</span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 720 }}>
                  <thead>
                    <tr style={{ backgroundColor: 'rgba(255,255,255,0.02)', textAlign: 'left' }}>
                      <th style={tableHeaderStyle}>主题</th>
                      <th style={tableHeaderStyle}>情绪</th>
                      <th style={tableHeaderStyle}>文章数</th>
                      <th style={tableHeaderStyle}>正向占比</th>
                      <th style={tableHeaderStyle}>负向占比</th>
                      <th style={tableHeaderStyle}>关键词</th>
                      <th style={tableHeaderStyle}>关联实体</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topics.map((topic) => (
                      <tr key={topic.topic} style={{ borderBottom: '1px solid var(--border)', backgroundColor: 'transparent' }}>
                        <td style={tableCellStyle}>
                          <div style={{ fontWeight: 600, color: 'var(--text)' }}>{topic.topic_display || topic.topic}</div>
                          {topic.summaries && topic.summaries.length > 0 && (
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>{topic.summaries.slice(0, 2).join('；')}</div>
                          )}
                        </td>
                        <td style={tableCellStyle}>
                          <div style={{ fontWeight: 600 }}>{formatNumber(topic.avg_sentiment ?? null, 2)}</div>
                          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{sentimentLabel(topic.avg_sentiment ?? null)}</div>
                        </td>
                        <td style={tableCellStyle}>{formatNumber(topic.article_count ?? null, 0)}</td>
                        <td style={tableCellStyle}>{formatPercent(topic.positive_ratio ?? null, 1)}</td>
                        <td style={tableCellStyle}>{formatPercent(topic.negative_ratio ?? null, 1)}</td>
                        <td style={tableCellStyle}>
                          {topic.top_keywords && topic.top_keywords.length > 0 ? topic.top_keywords.slice(0, 5).join('、') : '—'}
                        </td>
                        <td style={tableCellStyle}>
                          {renderEntities(topic.top_entities)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {modelInsights && (modelInsights.latest_run || modelInsights.best_validation_run) && (
              <section className="card-panel">
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'var(--text)', marginBottom: 16 }}>模型洞察</h2>
                <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
                  {modelInsights.latest_run && (
                    <ModelInsightCard title="最新运行" insight={modelInsights.latest_run} />
                  )}
                  {modelInsights.best_validation_run && (
                    <ModelInsightCard title="最优验证" insight={modelInsights.best_validation_run} />
                  )}
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
}

const MetricCard: React.FC<MetricCardProps> = ({ label, value }) => {
  return (
    <div className="card-panel metric-card">
      <div className="metric-title">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
};

interface TopicListCardProps {
  title: string;
  subtitle?: string;
  topics: MacroReportTopic[];
  sentimentTone?: 'positive' | 'negative';
}

const TopicListCard: React.FC<TopicListCardProps> = ({ title, subtitle, topics, sentimentTone = 'positive' }) => {
  return (
    <div className="card-panel topic-list-card" style={{ minHeight: 260 }}>
      <div className="topic-list-title">{title}</div>
      {subtitle && <div className="topic-list-subtitle">{subtitle}</div>}
      <div className="topic-list">
        {topics.length === 0 && <div className="no-data">暂无数据</div>}
        {topics.map((topic) => (
          <div key={topic.topic} className="topic-item">
            <div className="topic-name">{topic.topic_display || topic.topic}</div>
            <div className="topic-score">{formatNumber(topic.avg_sentiment ?? null, 2)}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

interface ModelInsightCardProps {
  title: string;
  insight: MacroReportModelInsight;
}

const ModelInsightCard: React.FC<ModelInsightCardProps> = ({ title, insight }) => {
  const { model_name, run_date, metrics, coefficients, calibration, notes } = insight;

  return (
    <div
      style={{
        borderRadius: 16,
        border: '1px solid var(--border)',
        backgroundColor: 'var(--surface-dark)',
        padding: '20px 22px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: 'var(--text)' }}>{title}</h3>
        {run_date && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{run_date}</span>}
      </div>
      {model_name && <div style={{ fontSize: 13, color: 'var(--text)' }}>模型：{model_name}</div>}
      {metrics && Object.keys(metrics).length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>关键指标</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.entries(metrics).map(([key, value]) => (
              <span
                key={key}
                style={{
                  fontSize: 12,
                  backgroundColor: 'rgba(255,255,255,0.05)',
                  borderRadius: 999,
                  padding: '6px 10px',
                  border: '1px solid var(--border)',
                }}
              >
                {key}: {typeof value === 'number' ? value.toFixed(3) : String(value)}
              </span>
            ))}
          </div>
        </div>
      )}
      {coefficients && Object.keys(coefficients).length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>权重系数</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.entries(coefficients).map(([key, value]) => (
              <span
                key={key}
                style={{
                  fontSize: 12,
                  backgroundColor: 'rgba(255,255,255,0.05)',
                  borderRadius: 999,
                  padding: '6px 10px',
                  border: '1px solid var(--border)',
                }}
              >
                {key}: {typeof value === 'number' ? value.toFixed(4) : String(value)}
              </span>
            ))}
          </div>
        </div>
      )}
      {calibration && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>校准信息：{JSON.stringify(calibration)}</div>
      )}
      {notes && notes.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--text)', fontSize: 12 }}>
          {notes.map((note, idx) => (
            <li key={`${note}-${idx}`}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
};

const tableHeaderStyle: React.CSSProperties = {
  padding: '12px 14px',
  fontSize: 12,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
};

const tableCellStyle: React.CSSProperties = {
  padding: '14px 14px',
  verticalAlign: 'top',
  color: 'var(--text)',
  fontSize: 13,
};

const renderEntities = (entities: Record<string, string[] | undefined> | undefined) => {
  if (!entities) {
    return '—';
  }
  const parts: string[] = [];
  Object.entries(entities).forEach(([key, value]) => {
    if (!value || value.length === 0) {
      return;
    }
    const label = entityLabel(key);
    parts.push(`${label}: ${value.slice(0, 4).join('、')}`);
  });
  if (parts.length === 0) {
    return '—';
  }
  return parts.join(' | ');
};

const entityLabel = (key: string) => {
  const mapping: Record<string, string> = {
    companies: '公司',
    locations: '地区',
    people: '人物',
    institutions: '机构',
  };
  return mapping[key] || key;
};

export default MacroReportPage;
