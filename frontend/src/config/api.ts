/**
 * 统一的 API 配置
 * 所有前端组件都应该使用这个配置文件中的 API_BASE
 */

// 从全局变量获取 API_BASE，或使用默认后端地址
export const API_BASE = (window as any).API_BASE || 'http://localhost:8080';

// 导出一个函数，方便其他地方调用
export const getApiBase = (): string => {
  return API_BASE;
};

// 常用的 API 端点
export const API_ENDPOINTS = {
  // 新闻相关
  NEWS: {
    ARTICLES: '/api/news/articles',
    STOCK_NEWS: (symbol: string) => `/api/news/stock/${symbol}`,
    COMPANY_ENRICHED: (symbol: string) => `/api/news/company_enriched/${symbol}`,
    ENSURE_COUNTS: '/api/news/ensure_counts',
    BASIC_PROFILE: (symbol: string) => `/api/news/basic_profile/${symbol}`,
    COLLECT: (symbol: string) => `/api/news/collect/${symbol}`,
    INTELLIGENT_COLLECT: '/api/news/intelligent-collect',
    SEARCH: '/api/news/search',
    STRATEGIES: '/api/news/strategies',
    STATS: '/api/news/stats',
    UPDATE: (id: number | string) => `/api/news/${id}`,
    DELETE: (id: number | string) => `/api/news/${id}`,
    // Query template management
    QUERY_TEMPLATES_LIST: '/api/news/query-templates',
    QUERY_TEMPLATES_CREATE: '/api/news/query-templates',
    QUERY_TEMPLATES_UPDATE: (id: number) => `/api/news/query-templates/${id}`,
    QUERY_TEMPLATES_DELETE: (id: number) => `/api/news/query-templates/${id}`,
    QUERY_TEMPLATES_TEST: '/api/news/query-templates/test',
    STOCKS: (page:number=1, page_size:number=20, q?:string) => {
      const params = new URLSearchParams();
      params.set('page', String(page)); params.set('page_size', String(page_size));
      if(q) params.set('q', q); return `/api/news/stocks?${params.toString()}`;
    },
    CRAWLER_FEEDBACK: '/api/news/crawler/feedback',
  },
  
  // Agent 分析 & 预测相关
  AGENT: {
    // Legacy file-scan latest (fallback)
    LATEST: '/api/agent/latest',
    // Persisted daily report endpoints
    DAILY_LATEST: '/api/agent/daily/latest',
    DAILY_LIST: (limit: number = 7) => `/api/agent/daily/list?limit=${limit}`,
    RUN: '/api/agent/run',
    METRICS: '/api/agent/metrics',
  },

  // 动态股票池 & 成员/画像
  STOCK_POOL: {
    LIST: (page:number=1, page_size:number=50, industry?:string, sort?:string, order?:'asc'|'desc') => {
      const params = new URLSearchParams()
      params.set('page', String(page))
      params.set('page_size', String(page_size))
      if(industry) params.set('industry', industry)
      if(sort) params.set('sort', sort)
      if(order) params.set('order', order)
      return `/api/stock-pool?${params.toString()}`
    },
    PROFILE: (symbol:string) => `/api/stock-profile/${symbol}`,
    PROFILE_DETAILS: (symbol:string) => `/api/stock-profile/${symbol}/details`,
    PROFILE_REFRESH: (symbol:string) => `/api/stock-profile/${symbol}/refresh`,
  },

  // 机器学习模型在线预测
  MODELS: {
    PREDICT: '/api/models/predict'
  },
  
  // 仪表板相关
  DASHBOARD: {
    REPORTS: '/api/dashboard/reports',
  },

  // 宏观数据相关
  MACRO: {
    OVERVIEW: '/api/macro/overview',
    REPORT: '/api/macro/report',
  },

  // 资金流向相关
  FUNDFLOW: {
    LATEST: '/api/fundflow/latest',
  },
  
  // 任务相关
  TASKS: {
    REPORT: (stockCode: string) => `/api/tasks/report/${stockCode}`,
  },
  
  // 观察列表
  WATCHLIST: '/watchlist',
  WATCHLIST_API: {
    SNAPSHOT: '/api/watchlist/snapshot',
    ANALYSIS: '/api/watchlist/analysis',
  },

  // 动态股票相关
  MOVERS: {
    DAILY: '/api/movers/daily',
    DAILY_FLAT: (exchange: string = 'ALL', limit:number=20) => `/api/movers/daily_flat?exchange=${exchange}&limit=${limit}`,
    WEEKLY: '/api/movers/weekly',
    ANALYZE: '/api/movers/analyze',
    SERIES: (symbol: string, days=30) => `/api/movers/series/${symbol}?days=${days}`,
    EXPAND: '/api/movers/expand_keywords'
  },
} as const;

// 辅助函数：构建完整的 API URL
export const buildApiUrl = (endpoint: string): string => {
  return `${API_BASE}${endpoint}`;
};

// ---------------------- 宏观数据类型定义 ----------------------

export interface MacroReference {
  title?: string | null;
  url?: string | null;
  published_at?: string | null;
  sentiment_score?: number | null;
  sentiment_type?: string | null;
  relevance?: number | null;
  summary?: string | null;
}

export interface MacroTopicSummary {
  topic: string;
  topic_display: string;
  observation_date: string | null;
  article_count: number | null;
  avg_sentiment: number | null;
  positive_ratio: number | null;
  negative_ratio: number | null;
  neutral_ratio: number | null;
  relevance_mean: number | null;
  top_keywords: string[];
  top_entities: {
    companies?: string[];
    locations?: string[];
    people?: string[];
    [key: string]: string[] | undefined;
  };
  summaries: string[];
  references: MacroReference[];
}

export interface MacroModelRun {
  model_name?: string | null;
  run_date?: string | null;
  metrics: Record<string, number | string | null>;
  coefficients: Record<string, number | string | null>;
  calibration: Record<string, unknown> | null;
  notes: string[];
}

export interface MacroOverviewResponse {
  storage_available: boolean;
  latest_observation_date: string | null;
  topics: MacroTopicSummary[];
  model_runs: MacroModelRun[];
}

export interface MacroReportHighlight {
  type: string;
  title: string;
  detail: string;
}

export interface MacroReportMetrics {
  average_sentiment?: number | null;
  topic_count?: number | null;
  article_count?: number | null;
  positive_topic_ratio?: number | null;
  [key: string]: number | string | null | undefined;
}

export interface MacroReportModelInsight {
  model_name?: string | null;
  run_date?: string | null;
  metrics?: Record<string, number | string | null>;
  coefficients?: Record<string, number | string | null>;
  calibration?: Record<string, unknown> | null;
  notes?: string[];
}

export interface MacroReportModelInsights {
  latest_run: MacroReportModelInsight | null;
  best_validation_run: MacroReportModelInsight | null;
}

export interface MacroReportTopic extends MacroTopicSummary {
  sentiment_label?: string;
}

export interface MacroReportPayload {
  report_date: string;
  generated_at: string;
  metrics: MacroReportMetrics;
  topics: MacroReportTopic[];
  top_positive_topics: MacroReportTopic[];
  top_negative_topics: MacroReportTopic[];
  most_covered_topics: MacroReportTopic[];
  model_insights: MacroReportModelInsights;
  highlights: MacroReportHighlight[];
}

export interface MacroReportResponse {
  report: MacroReportPayload | null;
  available_dates: string[];
}

export const fetchMacroOverview = async (
  signal?: AbortSignal,
): Promise<MacroOverviewResponse> => {
  const response = await fetch(buildApiUrl(API_ENDPOINTS.MACRO.OVERVIEW), { signal });

  if (!response.ok) {
    throw new Error(`获取宏观数据失败: ${response.status} ${response.statusText}`);
  }

  const data = (await response.json()) as MacroOverviewResponse;
  return data;
};

interface FetchMacroReportOptions {
  reportDate?: string | null;
  refresh?: boolean;
  signal?: AbortSignal;
}

export const fetchMacroReport = async (
  options: FetchMacroReportOptions = {},
): Promise<MacroReportResponse> => {
  const { reportDate, refresh = false, signal } = options;
  const url = new URL(buildApiUrl(API_ENDPOINTS.MACRO.REPORT));

  if (reportDate) {
    url.searchParams.set('report_date', reportDate);
  }
  if (refresh) {
    url.searchParams.set('refresh', 'true');
  }

  const response = await fetch(url.toString(), { signal });

  if (response.status === 404) {
    return { report: null, available_dates: [] };
  }

  if (!response.ok) {
    throw new Error(`获取宏观日报失败: ${response.status} ${response.statusText}`);
  }

  const data = (await response.json()) as MacroReportResponse;
  return data;
};