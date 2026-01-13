import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import SentimentBadge from '../SentimentBadge';

describe('SentimentBadge', () => {
  it('renders positive badge', () => {
    render(<SentimentBadge sentiment="positive" />);
    expect(screen.getByText('积极')).toBeInTheDocument();
  });

  it('renders negative badge', () => {
    render(<SentimentBadge sentiment="negative" />);
    expect(screen.getByText('消极')).toBeInTheDocument();
  });

  it('renders neutral badge by default', () => {
    render(<SentimentBadge />);
    expect(screen.getByText('中性')).toBeInTheDocument();
  });
});
