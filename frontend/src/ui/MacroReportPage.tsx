import React, { useMemo, useState } from 'react';
import useMacroReport from './hooks/useMacroReport';
import {
  MacroReportDiagnosticsItem,
  MacroReportModelInsight,
  MacroReportSignal,
  MacroTopicDetail,
  MacroTrendAnalysis,
  MacroHotKeyword,
} from '../config/api';

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

const formatSignedNumber = (value: number | string | null | undefined, digits = 2) => {
  const numericValue = toNumber(value);
  if (numericValue === null) {
    return '—';
  }
  if (numericValue > 0) {
    return `+${numericValue.toFixed(digits)}`;
  }
  return numericValue.toFixed(digits);
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
    return '偏乐观';
  }
  if (numericValue <= -0.25) {
    return '偏悲观';
  }
  return '比较平稳';
};

const marketRegimeFromMetrics = (averageSentiment: number | string | null | undefined) => {
  const value = toNumber(averageSentiment);
  if (value == null) {
    return '未知';
  }
  if (value >= 0.2) {
    return '偏乐观';
  }
  if (value <= -0.2) {
    return '偏悲观';
  }
  return '比较平稳';
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
  const topics = report?.topics ?? [];
  const modelInsights = report?.model_insights ?? null;
  const outline = report?.outline ?? [];
  const validation = report?.validation;
  const reportValid = validation?.is_valid === true;
  const featureEnabled = validation?.feature_enabled === true;

  const opportunitySignals = useMemo<MacroReportSignal[]>(() => {
    if (report?.opportunity_signals && report.opportunity_signals.length > 0) {
      return report.opportunity_signals;
    }
    return topics
      .filter((topic) => toNumber(topic.avg_sentiment) != null && (toNumber(topic.avg_sentiment) as number) >= 0.2)
      .sort((a, b) => (toNumber(b.avg_sentiment) ?? 0) - (toNumber(a.avg_sentiment) ?? 0))
      .slice(0, 5)
      .map((topic) => ({
        topic: topic.topic_display || topic.topic,
        severity: (toNumber(topic.avg_sentiment) ?? 0) >= 0.35 ? 'high' : 'medium',
        confidence: toNumber((topic as any).confidence) ?? Math.min((toNumber(topic.article_count) ?? 0) / 10, 0.9),
        reason: `情绪 ${formatNumber(topic.avg_sentiment ?? null, 2)}，样本 ${formatNumber(topic.article_count ?? null, 0)} 篇`,
      }));
  }, [report, topics]);

  const riskSignals = useMemo<MacroReportSignal[]>(() => {
    if (report?.risk_signals && report.risk_signals.length > 0) {
      return report.risk_signals;
    }
    return topics
      .filter((topic) => toNumber(topic.avg_sentiment) != null && (toNumber(topic.avg_sentiment) as number) <= -0.2)
      .sort((a, b) => (toNumber(a.avg_sentiment) ?? 0) - (toNumber(b.avg_sentiment) ?? 0))
      .slice(0, 5)
      .map((topic) => ({
        topic: topic.topic_display || topic.topic,
        severity: (toNumber(topic.avg_sentiment) ?? 0) <= -0.35 ? 'high' : 'medium',
        confidence: toNumber((topic as any).confidence) ?? Math.min((toNumber(topic.article_count) ?? 0) / 10, 0.9),
        reason: `情绪 ${formatNumber(topic.avg_sentiment ?? null, 2)}，样本 ${formatNumber(topic.article_count ?? null, 0)} 篇`,
      }));
  }, [report, topics]);

  const executiveSummary = useMemo<string[]>(() => {
    if (report?.executive_summary && report.executive_summary.length > 0) {
      return report.executive_summary;
    }
    return [
      `今天的市场整体氛围${marketRegimeFromMetrics(metrics.average_sentiment ?? null)}。`,
      `我们分析了 ${formatNumber(metrics.topic_count ?? null, 0)} 个话题方向，共 ${formatNumber(metrics.article_count ?? null, 0)} 篇相关文章。`,
      `正面消息占比约 ${formatPercent(metrics.positive_topic_ratio ?? null, 0)}，负面消息占比约 ${formatPercent(metrics.negative_topic_ratio ?? null, 0)}。`,
    ];
  }, [report, metrics]);

  const actionItems = useMemo(() => {
    if (report?.action_items) {
      return report.action_items;
    }

    const focus = opportunitySignals.length > 0
      ? opportunitySignals.slice(0, 3).map((signal) => `可以关注「${signal.topic}」——${signal.reason}`)
      : ['今天没有特别突出的利好方向，建议保持观望，不急于操作。'];

    const avoid = riskSignals.length > 0
      ? riskSignals.slice(0, 3).map((signal) => `注意「${signal.topic}」的风险——${signal.reason}`)
      : ['今天没有发现明显的风险信号，但仍需保持关注。'];

    const verify: string[] = [];
    const concentration = toNumber(metrics.attention_concentration ?? null);
    if (concentration != null && concentration >= 0.55) {
      verify.push('今天大家的注意力都集中在少数几个话题上，需要注意是否被单一新闻事件带动了情绪。');
    }
    const delta = toNumber(metrics.delta_avg_sentiment ?? null);
    if (delta != null && Math.abs(delta) >= 0.08) {
      verify.push('今天市场情绪变化比较大，建议观察明天的走势来确认方向。');
    }
    if (verify.length === 0) {
      verify.push('今天的数据整体平稳，可以按正常节奏关注市场变化。');
    }

    return { focus, avoid, verify };
  }, [report, opportunitySignals, riskSignals, metrics]);

  const dataDiagnostics = report?.data_diagnostics ?? [];
  const topicDetails = report?.topic_details ?? [];
  const trendAnalysis = report?.trend_analysis ?? null;
  const hotKeywords = report?.hot_keywords ?? [];

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
            <div style={{ fontSize: 14, color: 'var(--text-muted)', marginBottom: 4 }}>每日解读 · 通俗易懂</div>
            <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: 'var(--text)' }}>今日宏观速览</h1>
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
            暂无可用的报告，请尝试点击"立即生成"来获取今日市场分析。
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
            正在分析今日宏观新闻，请稍候…
          </div>
        )}

        {hasReport && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {!reportValid || !featureEnabled ? (
              <div
                style={{
                  padding: '10px 16px',
                  borderRadius: 8,
                  border: '1px solid rgba(245, 158, 11, 0.25)',
                  background: 'rgba(245, 158, 11, 0.06)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  fontSize: 13,
                  color: 'var(--text-secondary)',
                }}
              >
                <span style={{ fontSize: 16 }}>⚠️</span>
                <span>
                  {validation?.message || '以下内容仅供参考'}
                  {' · '}
                  <span
                    style={{ color: 'var(--accent)', cursor: 'pointer' }}
                    onClick={() => handleRefresh(true)}
                  >
                    点击刷新数据
                  </span>
                </span>
              </div>
            ) : null}

            {/* 今日总结 - 最核心的通俗段落 */}
            {report?.plain_summary && (
              <section
                className="card-panel"
                style={{
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  background: 'rgba(59, 130, 246, 0.06)',
                }}
              >
                <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: 'var(--text)' }}>📋 今日总结</h2>
                <div style={{ marginTop: 14, fontSize: 15, color: 'var(--text)', lineHeight: 1.9 }}>
                  {report.plain_summary}
                </div>
                {validation?.quality_notes && validation.quality_notes.length > 0 && (
                  <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                    💡 {validation.quality_notes.join('；')}
                  </div>
                )}
              </section>
            )}
            {/* 热门关键词 */}
            {hotKeywords.length > 0 && (
              <section className="card-panel">
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>🔥 今日热门关键词</h2>
                <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {hotKeywords.map((kw, idx) => (
                    <span
                      key={`${kw.keyword}-${idx}`}
                      style={{
                        fontSize: idx < 3 ? 15 : 13,
                        fontWeight: idx < 3 ? 700 : 400,
                        color: idx < 3 ? 'var(--accent-blue, #60a5fa)' : 'var(--text)',
                        background: idx < 3 ? 'rgba(59,130,246,0.12)' : 'rgba(255,255,255,0.04)',
                        border: '1px solid var(--border)',
                        borderRadius: 999,
                        padding: '6px 14px',
                      }}
                    >
                      {kw.keyword}
                      {kw.count > 1 && <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>×{kw.count}</span>}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {/* 各话题详情 */}
            {topicDetails.length > 0 && (
              <section style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>📰 各话题详情</h2>
                {topicDetails.map((td, idx) => (
                  <TopicDetailCard key={`${td.topic}-${idx}`} detail={td} />
                ))}
              </section>
            )}

            {/* 近期趋势 */}
            {trendAnalysis && trendAnalysis.days_covered >= 2 && (
              <section className="card-panel">
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>📈 近期趋势</h2>
                <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text-muted)' }}>
                  过去 {trendAnalysis.days_covered} 天的市场情绪变化，整体趋势：
                  <strong style={{ color: 'var(--text)', marginLeft: 4 }}>
                    {trendAnalysis.trend_direction === 'improving' ? '逐步好转 ↑' :
                     trendAnalysis.trend_direction === 'deteriorating' ? '逐步走弱 ↓' : '基本平稳 →'}
                  </strong>
                </div>
                {/* 每日情绪简表 */}
                {trendAnalysis.daily_overall.length > 0 && (
                  <div style={{ marginTop: 14, display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 4 }}>
                    {trendAnalysis.daily_overall.map((day) => {
                      const s = day.avg_sentiment;
                      const barColor = s >= 0.15 ? '#10b981' : s <= -0.15 ? '#ef4444' : '#6b7280';
                      return (
                        <div key={day.date} style={{ textAlign: 'center', minWidth: 56, flex: '0 0 auto' }}>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>{day.date.slice(5)}</div>
                          <div style={{
                            height: 40,
                            display: 'flex',
                            alignItems: 'flex-end',
                            justifyContent: 'center',
                          }}>
                            <div style={{
                              width: 24,
                              height: `${Math.max(6, Math.abs(s) * 80)}px`,
                              background: barColor,
                              borderRadius: 4,
                              opacity: 0.8,
                            }} />
                          </div>
                          <div style={{ fontSize: 11, color: barColor, marginTop: 2, fontWeight: 600 }}>
                            {s >= 0 ? '+' : ''}{s.toFixed(2)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                {/* 变化最大的话题 */}
                {trendAnalysis.biggest_movers.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>变化最明显的方向：</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {trendAnalysis.biggest_movers.map((m, idx) => (
                        <div key={`${m.topic}-${idx}`} style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
                          <span style={{ color: m.delta > 0 ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                            {m.direction === '好转' ? '↑' : '↓'}
                          </span>
                          {' '}「{m.topic}」{m.direction}（{m.from_sentiment >= 0 ? '+' : ''}{m.from_sentiment.toFixed(2)} → {m.to_sentiment >= 0 ? '+' : ''}{m.to_sentiment.toFixed(2)}）
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            )}

            <section style={{ display: 'grid', gap: 20, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
              <SignalPanel title="利好方向" subtitle="这些话题的报道比较正面，可以多留意" signals={opportunitySignals} type="opportunity" />
              <SignalPanel title="需要注意" subtitle="这些话题的报道偏负面，建议谨慎对待" signals={riskSignals} type="risk" />
            </section>

            <section style={{ display: 'grid', gap: 20, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
              <ActionListCard
                title="值得关注"
                tone="positive"
                items={actionItems?.focus ?? ['暂无建议']}
              />
              <ActionListCard
                title="建议回避"
                tone="negative"
                items={actionItems?.avoid ?? ['暂无建议']}
              />
              <ActionListCard
                title="明天再看看"
                tone="neutral"
                items={actionItems?.verify ?? ['暂无建议']}
              />
            </section>

            <section className="card-panel">
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'var(--text)' }}>数据一览</h2>
              <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text-muted)' }}>以下数字帮你了解今天分析的范围和结果</div>
              <div
                style={{
                  display: 'grid',
                  gap: 16,
                  marginTop: 20,
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                }}
              >
                <MetricCard label="分析话题数" value={formatNumber(metrics.topic_count, 0)} />
                <MetricCard label="参考文章数" value={formatNumber(metrics.article_count, 0)} />
                <MetricCard
                  label="整体氛围"
                  value={sentimentLabel(metrics.average_sentiment ?? null)}
                />
                <MetricCard label="正面消息占比" value={formatPercent(metrics.positive_topic_ratio ?? null, 0)} />
                <MetricCard label="观点分歧程度" value={
                  (() => {
                    const v = toNumber(metrics.sentiment_dispersion ?? null);
                    if (v === null) return '—';
                    if (v >= 0.35) return '分歧较大';
                    if (v >= 0.15) return '有一定分歧';
                    return '观点较一致';
                  })()
                } />
                <MetricCard label="关注集中度" value={
                  (() => {
                    const v = toNumber(metrics.attention_concentration ?? null);
                    if (v === null) return '—';
                    if (v >= 0.6) return '非常集中';
                    if (v >= 0.4) return '比较集中';
                    return '比较分散';
                  })()
                } />
                <MetricCard label="和昨天比" value={
                  (() => {
                    const v = toNumber(metrics.delta_avg_sentiment ?? null);
                    if (v === null) return '暂无对比';
                    if (v >= 0.08) return '明显好转';
                    if (v >= 0.02) return '稍有好转';
                    if (v <= -0.08) return '明显变差';
                    if (v <= -0.02) return '稍有下滑';
                    return '基本不变';
                  })()
                } />
                {metrics.negative_topic_ratio !== undefined && (
                  <MetricCard label="负面消息占比" value={formatPercent(metrics.negative_topic_ratio ?? null, 0)} />
                )}
                {metrics.neutral_topic_ratio !== undefined && (
                  <MetricCard label="中性消息占比" value={formatPercent(metrics.neutral_topic_ratio ?? null, 0)} />
                )}
              </div>
            </section>

            <section className="card-panel">
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'var(--text)' }}>分析质量</h2>
              <div style={{ marginTop: 4, fontSize: 13, color: 'var(--text-muted)' }}>帮你判断今天的分析结论有多可靠</div>
              <div style={{ display: 'grid', gap: 12, marginTop: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
                {(dataDiagnostics.length > 0 ? dataDiagnostics : [
                  { name: '数据可靠度', value: toNumber(metrics.avg_topic_confidence ?? null), status: 'warn', detail: '暂无详细诊断数据' },
                  { name: '信息完整度', value: toNumber(metrics.summary_quality_ratio ?? null), status: 'warn', detail: '暂无详细诊断数据' },
                ]).map((item, idx) => (
                  <DiagnosticsCard key={`${item.name}-${idx}`} item={item as MacroReportDiagnosticsItem} />
                ))}
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

/* ---- 话题详情卡片 ---- */
const TopicDetailCard: React.FC<{ detail: MacroTopicDetail }> = ({ detail }) => {
  const [expanded, setExpanded] = useState(false);
  const moodColor = detail.mood.includes('乐观') || detail.mood.includes('正面')
    ? '#10b981'
    : detail.mood.includes('悲观') || detail.mood.includes('负面')
    ? '#ef4444'
    : '#6b7280';

  return (
    <div className="card-panel" style={{ padding: '16px 20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: 17, fontWeight: 700, color: 'var(--text)' }}>{detail.cn_name}</span>
          <span style={{
            marginLeft: 10,
            fontSize: 12,
            color: moodColor,
            border: `1px solid ${moodColor}`,
            borderRadius: 999,
            padding: '2px 10px',
            fontWeight: 600,
          }}>{detail.mood}</span>
        </div>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{detail.article_count} 篇文章</span>
      </div>

      {/* 摘要 */}
      {detail.summary_text && (
        <div style={{ marginTop: 10, fontSize: 14, color: 'var(--text)', lineHeight: 1.8 }}>
          {detail.summary_text}
        </div>
      )}

      {/* 关键词 */}
      {detail.keywords.length > 0 && (
        <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {detail.keywords.map((kw) => (
            <span key={kw} style={{
              fontSize: 12,
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid var(--border)',
              borderRadius: 999,
              padding: '3px 10px',
              color: 'var(--text-secondary)',
            }}>{kw}</span>
          ))}
        </div>
      )}

      {/* 涉及公司/人物 */}
      {(detail.companies.length > 0 || detail.people.length > 0) && (
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
          {detail.companies.length > 0 && <span>涉及机构：{detail.companies.join('、')}　</span>}
          {detail.people.length > 0 && <span>涉及人物：{detail.people.join('、')}</span>}
        </div>
      )}

      {/* 展开/收起关键新闻 */}
      {detail.key_news.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--accent-blue, #60a5fa)',
              cursor: 'pointer',
              fontSize: 13,
              padding: 0,
              textDecoration: 'underline',
            }}
          >
            {expanded ? '收起新闻来源 ▲' : `查看 ${detail.key_news.length} 条新闻来源 ▼`}
          </button>
          {expanded && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {detail.key_news.map((news, idx) => (
                <div key={`${news.title}-${idx}`} style={{
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  padding: '10px 12px',
                  background: 'rgba(0,0,0,0.1)',
                }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
                    {news.url ? (
                      <a href={news.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-blue, #60a5fa)', textDecoration: 'none' }}>
                        {news.title}
                      </a>
                    ) : news.title}
                  </div>
                  {news.summary && (
                    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                      {news.summary}
                    </div>
                  )}
                  {news.sentiment_type && (
                    <span style={{
                      marginTop: 4,
                      display: 'inline-block',
                      fontSize: 11,
                      color: news.sentiment_type === 'positive' ? '#10b981' : news.sentiment_type === 'negative' ? '#ef4444' : '#6b7280',
                    }}>
                      {news.sentiment_type === 'positive' ? '正面' : news.sentiment_type === 'negative' ? '负面' : '中性'}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

interface SignalPanelProps {
  title: string;
  subtitle?: string;
  signals: MacroReportSignal[];
  type: 'risk' | 'opportunity';
}

const SignalPanel: React.FC<SignalPanelProps> = ({ title, subtitle, signals, type }) => {
  const borderColor = type === 'risk' ? 'rgba(239, 68, 68, 0.35)' : 'rgba(16, 185, 129, 0.35)';
  const backgroundColor = type === 'risk' ? 'rgba(239, 68, 68, 0.08)' : 'rgba(16, 185, 129, 0.08)';

  return (
    <div className="card-panel" style={{ borderColor, background: backgroundColor }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
      {subtitle && <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-muted)' }}>{subtitle}</div>}
      <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {signals.length === 0 && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>今天暂无相关信号</div>}
        {signals.map((signal, index) => (
          <div key={`${signal.topic}-${index}`} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px', background: 'rgba(0,0,0,0.15)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{signal.topic}</div>
              <SeverityBadge severity={signal.severity} />
            </div>
            <div style={{ marginTop: 6, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{signal.reason}</div>
            <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-muted)' }}>可信度 {formatPercent(signal.confidence, 0)}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

const SeverityBadge: React.FC<{ severity: string }> = ({ severity }) => {
  const normalized = severity?.toLowerCase?.() || 'medium';
  const color = normalized === 'high' ? '#ef4444' : normalized === 'low' ? '#6b7280' : '#f59e0b';
  const text = normalized === 'high' ? '重要' : normalized === 'low' ? '一般' : '留意';

  return (
    <span
      style={{
        fontSize: 11,
        color,
        border: `1px solid ${color}`,
        borderRadius: 999,
        padding: '3px 8px',
        fontWeight: 600,
      }}
    >
      {text}
    </span>
  );
};

interface ActionListCardProps {
  title: string;
  tone: 'positive' | 'negative' | 'neutral';
  items: string[];
}

const ActionListCard: React.FC<ActionListCardProps> = ({ title, tone, items }) => {
  const toneMap = {
    positive: { border: 'rgba(16, 185, 129, 0.35)', bg: 'rgba(16, 185, 129, 0.08)' },
    negative: { border: 'rgba(239, 68, 68, 0.35)', bg: 'rgba(239, 68, 68, 0.08)' },
    neutral: { border: 'rgba(59, 130, 246, 0.35)', bg: 'rgba(59, 130, 246, 0.08)' },
  } as const;

  const style = toneMap[tone];

  return (
    <div className="card-panel" style={{ borderColor: style.border, background: style.bg }}>
      <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map((item, index) => (
          <div key={`${title}-${index}`} style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
            {index + 1}. {item}
          </div>
        ))}
      </div>
    </div>
  );
};

const DiagnosticsCard: React.FC<{ item: MacroReportDiagnosticsItem }> = ({ item }) => {
  const status = (item.status || 'warn').toLowerCase();
  const color = status === 'good' ? '#10b981' : status === 'risk' ? '#ef4444' : '#f59e0b';
  const label = status === 'good' ? '良好' : status === 'risk' ? '不足' : '一般';

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 12, padding: '12px 14px', background: 'rgba(255,255,255,0.02)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 13, color: 'var(--text)', fontWeight: 600 }}>{item.name}</div>
        <span style={{ fontSize: 11, color, border: `1px solid ${color}`, borderRadius: 999, padding: '2px 8px' }}>{label}</span>
      </div>
      <div style={{ marginTop: 8, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>
        {item.value == null ? '—' : (item.value <= 1 && item.value >= 0 ? formatPercent(item.value, 1) : String(item.value))}
      </div>
      {item.detail && <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-muted)' }}>{item.detail}</div>}
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

export default MacroReportPage;
