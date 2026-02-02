import React from 'react';

interface Props {
  sentiment?: 'positive' | 'negative' | 'neutral' | string | undefined;
  score?: number | null;
}

export default function SentimentBadge({ sentiment, score }: Props) {
  // localized label
  const text = sentiment === 'positive' ? '积极' : sentiment === 'negative' ? '消极' : '中性';

  // Use a compact inline-flex badge (background color block instead of border).
    // Reduced font size and padding to avoid visual crowding.
    // color scheme: green for positive, red for negative, gray for neutral.
    // Use Tailwind CSS classes for styling.
    // Add aria-label for accessibility.
    // Add title attribute for tooltip on hover.
    // Consolidate color into sentimentClasses and use existing tokens.
    const base = 'inline-flex items-center justify-center  min-w-[56px]   text-[13.5px] ';
    const sentimentClasses =
      sentiment === 'positive'
        ? 'bg-brand-emerald-200 text-brand-emerald-800'
        : sentiment === 'negative'
        ? 'bg-brand-rose-200 text-brand-rose-800'
        : '';

    // Inline color fallback ensures the badge is colored even if Tailwind token isn't yet applied
    const inlineColor = sentiment === 'positive' ? '#315c50ff' : sentiment === 'negative' ? '#d41d1dff' : '#f0f1f3ff';
    const textColor = sentiment === 'positive' ? 'white' : sentiment === 'negative' ? 'white' : '#374151';

    return (
      <div className={`${base} ${sentimentClasses}`} style={{ backgroundColor: inlineColor, color: textColor, height: '22px', borderRadius: '6px' }} aria-label={`情感: ${text}`} title={text}>
        {text}
      </div>
    );
}
