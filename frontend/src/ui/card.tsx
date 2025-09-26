import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'soft' | 'ghost' | 'bare';
  style?: React.CSSProperties;
}

export function Card({ children, className = '', variant = 'default', style }: CardProps) {
  const base = {
    default: 'bg-white rounded-lg border border-gray-200 shadow-sm',
    soft: 'bg-gray-50/80 rounded-lg shadow-sm border-0',
    ghost: 'bg-transparent rounded-lg border-0 shadow-none',
    bare: 'rounded-lg shadow-sm border-0',
  }[variant];
  return (
    <div className={`${base} ${className}`} style={style}>
      {children}
    </div>
  );
}

export function CardHeader({ children, className = '' }: CardProps) {
  return (
    <div className={`p-6 pb-4 ${className}`}>
      {children}
    </div>
  );
}

export function CardTitle({ children, className = '' }: CardProps) {
  return (
    <h3 className={`text-lg font-semibold ${className}`}>
      {children}
    </h3>
  );
}

export function CardContent({ children, className = '' }: CardProps) {
  return (
    <div className={`p-6 pt-0 ${className}`}>
      {children}
    </div>
  );
}
