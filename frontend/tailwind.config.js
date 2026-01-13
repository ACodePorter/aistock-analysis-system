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
      },
    },
  },
  plugins: [],
}