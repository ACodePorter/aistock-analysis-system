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
    background: '#f3f4f6',
    color: '#374151',
    borderRadius: 999,
    fontWeight: 600,
    lineHeight: 1.2,
    border: '1px solid #e5e7eb',
    whiteSpace: 'nowrap'
  };

  const chip = (label: string, value: number, style?: React.CSSProperties) => (
    <span style={{ ...base, ...style }} key={label}>{label} {value}</span>
  );

  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {chip('总数', stats.total)}
      {chip('今日', stats.today, { background: '#dbeafe', color: '#1d4ed8', borderColor: '#bfdbfe' })}
      {chip('积极', stats.pos, { background: '#dcfce7', color: '#15803d', borderColor: '#bbf7d0' })}
      {chip('消极', stats.neg, { background: '#fee2e2', color: '#b91c1c', borderColor: '#fecaca' })}
      {chip('中性', stats.neu)}
    </div>
  );
};

export default StatsChips;
