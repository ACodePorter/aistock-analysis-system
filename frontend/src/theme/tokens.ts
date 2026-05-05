import type { ThemeConfig } from 'antd'

export const themeTokens = {
  colors: {
    bgApp: '#070B12',
    bgSidebar: '#0B111C',
    bgPanel: '#101827',
    bgPanelElevated: '#151F31',
    bgCard: '#111A2B',
    bgCardHover: '#172338',
    bgInput: '#0D1524',
    borderSubtle: '#22304A',
    borderStrong: '#344563',
    textPrimary: '#F3F7FF',
    textSecondary: '#AAB7CC',
    textMuted: '#68758A',
    accent: '#6CA7FF',
    accentSoft: 'rgba(108,167,255,0.14)',
    positive: '#3DDC97',
    negative: '#FF5C5C',
    warning: '#F5B84B',
    info: '#5BA7FF',
    neutral: '#8FA3BF',
    buy: '#3DDC97',
    sell: '#FF5C5C',
    wait: '#F5B84B',
    avoid: '#A871FF',
    risk: '#FF8A4C',
  },
  radius: {
    sm: 6,
    md: 8,
    lg: 12,
  },
  spacing: {
    xs: 4,
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24,
  },
} as const

export const antdThemeConfig: ThemeConfig = {
  token: {
    colorPrimary: themeTokens.colors.accent,
    colorSuccess: themeTokens.colors.positive,
    colorError: themeTokens.colors.negative,
    colorWarning: themeTokens.colors.warning,
    colorInfo: themeTokens.colors.info,
    colorBgBase: themeTokens.colors.bgApp,
    colorBgContainer: themeTokens.colors.bgPanel,
    colorBgElevated: themeTokens.colors.bgPanelElevated,
    colorBorder: themeTokens.colors.borderSubtle,
    colorText: themeTokens.colors.textPrimary,
    colorTextSecondary: themeTokens.colors.textSecondary,
    colorTextTertiary: themeTokens.colors.textMuted,
    borderRadius: themeTokens.radius.md,
    borderRadiusLG: themeTokens.radius.lg,
    controlHeight: 34,
    fontFamily: "'Noto Sans SC', 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  },
  components: {
    Button: {
      colorPrimary: themeTokens.colors.accent,
      primaryShadow: 'none',
    },
    Card: {
      colorBgContainer: themeTokens.colors.bgPanel,
      colorBorderSecondary: themeTokens.colors.borderSubtle,
    },
    Drawer: {
      colorBgElevated: themeTokens.colors.bgPanelElevated,
    },
    Modal: {
      contentBg: themeTokens.colors.bgPanelElevated,
      headerBg: themeTokens.colors.bgPanelElevated,
    },
    Table: {
      colorBgContainer: themeTokens.colors.bgPanel,
      headerBg: themeTokens.colors.bgCard,
      rowHoverBg: themeTokens.colors.bgCardHover,
      borderColor: themeTokens.colors.borderSubtle,
    },
    Tabs: {
      itemColor: themeTokens.colors.textSecondary,
      itemSelectedColor: themeTokens.colors.textPrimary,
      inkBarColor: themeTokens.colors.accent,
    },
    Tag: {
      defaultBg: themeTokens.colors.bgCard,
      defaultColor: themeTokens.colors.textSecondary,
    },
    Tooltip: {
      colorBgSpotlight: themeTokens.colors.bgPanelElevated,
      colorTextLightSolid: themeTokens.colors.textPrimary,
    },
  },
}