/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // project design tokens for sentiment
        'brand-emerald-50': '#ecfdf5',
        'brand-emerald-200': '#bbf7d0',
        'brand-emerald-800': '#065f46',
        'brand-rose-50': '#fff1f2',
        'brand-rose-200': '#fecaca',
        'brand-rose-700': '#9f1239',
        'brand-rose-800': '#7f1239',
        // Dark theme color system
        'dark': {
          'bg': '#0a0c10',
          'surface': '#161b22',
          'card': '#161b22',
          'border': '#30363d',
          'border-light': 'rgba(255,255,255,0.1)',
          'hover': 'rgba(255,255,255,0.05)',
        },
        'dark-text': {
          'primary': '#e2e8f0',
          'secondary': '#94a3b8',
          'muted': '#64748b',
        },
        'accent': {
          'primary': '#116574',
          'lime': '#6EE7B7',
          'green': '#10B981',
          'red': '#EF4444',
          'orange': '#fa5f38',
          'gold': '#D4A100',
        },
      },
    },
  },
  plugins: [],
}