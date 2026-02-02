import React from 'react';

export interface StatsData {
  total: number;
  today: number;
  pos: number;
  neg: number;
  neu: number;
}

interface StatsChipsProps {
  stats: StatsData;
  size?: 'sm' | 'md';
  showLabels?: boolean; // future extensibility
}

/**
 * 统一的统计徽章组件
 * 默认用于展示当前筛选集合的统计（不是全局总数）
 */
const StatsChips: React.FC<StatsChipsProps> = ({ stats, size = 'sm' }) => {
  const base: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    padding: size === 'sm' ? '2px 8px' : '4px 10px',
    fontSize: size === 'sm' ? 12 : 13,
    background: 'var(--surface-dark)',
    color: 'var(--text-muted)',
    borderRadius: 999,
    fontWeight: 600,
    lineHeight: 1.2,
    border: '1px solid var(--border)',
    whiteSpace: 'nowrap'
  };

  const chip = (label: string, value: number, style?: React.CSSProperties) => (
    <span style={{ ...base, ...style }} key={label}>{label} {value}</span>
  );

  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {chip('总数', stats.total)}
      {chip('今日', stats.today, { background: 'rgba(99, 102, 241, 0.15)', color: 'var(--primary)', borderColor: 'rgba(99, 102, 241, 0.3)' })}
      {chip('积极', stats.pos, { background: 'rgba(163, 230, 53, 0.15)', color: 'var(--accent-lime)', borderColor: 'rgba(163, 230, 53, 0.3)' })}
      {chip('消极', stats.neg, { background: 'rgba(239, 68, 68, 0.15)', color: 'var(--accent-red)', borderColor: 'rgba(239, 68, 68, 0.3)' })}
      {chip('中性', stats.neu)}
    </div>
  );
};

export default StatsChips;
