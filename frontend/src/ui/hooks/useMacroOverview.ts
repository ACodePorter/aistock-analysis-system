import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchMacroOverview,
  MacroOverviewResponse,
} from '../../config/api';

interface UseMacroOverviewOptions {
  /** 是否在组件挂载后自动请求 */
  enabled?: boolean;
  /** 自动刷新频率（毫秒）。传入 0 或 undefined 关闭自动刷新 */
  autoRefreshMs?: number;
}

interface UseMacroOverviewResult {
  data: MacroOverviewResponse | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  lastUpdated: string | null;
  refresh: () => Promise<void>;
}

const isAbortError = (error: unknown): boolean => {
  return error instanceof DOMException && error.name === 'AbortError';
};

export const useMacroOverview = (
  options: UseMacroOverviewOptions = {},
): UseMacroOverviewResult => {
  const { enabled = true, autoRefreshMs = 120_000 } = options;
  const [data, setData] = useState<MacroOverviewResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (isRefresh = false, signal?: AbortSignal) => {
      if (!enabled) {
        return;
      }

      try {
        if (isRefresh) {
          setRefreshing(true);
        } else {
          setLoading(true);
        }
        setError(null);

        const response = await fetchMacroOverview(signal);
        setData(response);
      } catch (err) {
        if (isAbortError(err)) {
          return;
        }
        console.error('Failed to load macro overview', err);
        setError(err instanceof Error ? err.message : '未知错误');
      } finally {
        if (isRefresh) {
          setRefreshing(false);
        } else {
          setLoading(false);
        }
      }
    },
    [enabled],
  );

  const refresh = useCallback(async () => {
    await load(true);
  }, [load]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const controller = new AbortController();
    load(false, controller.signal);

    let intervalId: number | undefined;
    if (autoRefreshMs && autoRefreshMs > 0) {
      intervalId = window.setInterval(() => {
        load(true);
      }, autoRefreshMs);
    }

    return () => {
      controller.abort();
      if (intervalId) {
        window.clearInterval(intervalId);
      }
    };
  }, [enabled, autoRefreshMs, load]);

  const lastUpdated = useMemo(() => {
    if (!data) {
      return null;
    }

    if (data.latest_observation_date) {
      return data.latest_observation_date;
    }

    return null;
  }, [data]);

  return {
    data,
    loading,
    refreshing,
    error,
    lastUpdated,
    refresh,
  };
};

export default useMacroOverview;
