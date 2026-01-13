import React from 'react';
import SentimentBadge from '../ui/SentimentBadge';

export default function SentimentBadgeStory() {
  return (
    <div style={{ display: 'flex', gap: 12 }}>
      <SentimentBadge sentiment="positive" />
      <SentimentBadge sentiment="negative" />
      <SentimentBadge sentiment="neutral" />
    </div>
  );
}
