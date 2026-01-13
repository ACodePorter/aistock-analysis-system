import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchMacroReport,
  MacroReportPayload,
  MacroReportResponse,
} from '../../config/api';

interface UseMacroReportOptions {
  enabled?: boolean;
  reportDate?: string | null;
  autoRefreshMs?: number;
}

interface UseMacroReportResult {
  data: MacroReportResponse | null;
  report: MacroReportPayload | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  lastUpdated: string | null;
  refresh: (force?: boolean) => Promise<void>;
}

const isAbortError = (error: unknown): boolean => {
  return error instanceof DOMException && error.name === 'AbortError';
};

const useMacroReport = (
  options: UseMacroReportOptions = {},
): UseMacroReportResult => {
  const { enabled = true, reportDate = null, autoRefreshMs = 300_000 } = options;
  const [data, setData] = useState<MacroReportResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (isRefresh = false, force = false, signal?: AbortSignal) => {
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

        const response = await fetchMacroReport({
          reportDate: reportDate ?? undefined,
          refresh: force,
          signal,
        });
        setData(response);
      } catch (err) {
        if (isAbortError(err)) {
          return;
        }
        console.error('Failed to load macro report', err);
        setError(err instanceof Error ? err.message : '未知错误');
      } finally {
        if (isRefresh) {
          setRefreshing(false);
        } else {
          setLoading(false);
        }
      }
    },
    [enabled, reportDate],
  );

  const refresh = useCallback(
    async (force = false) => {
      await load(true, force);
    },
    [load],
  );

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const controller = new AbortController();
    load(false, false, controller.signal);

    let intervalId: number | undefined;
    if (!reportDate && autoRefreshMs && autoRefreshMs > 0) {
      intervalId = window.setInterval(() => {
        load(true, false);
      }, autoRefreshMs);
    }

    return () => {
      controller.abort();
      if (intervalId) {
        window.clearInterval(intervalId);
      }
    };
  }, [enabled, reportDate, autoRefreshMs, load]);

  const report = useMemo<MacroReportPayload | null>(() => {
    if (!data || !data.report) {
      return null;
    }
    return data.report;
  }, [data]);

  const lastUpdated = useMemo(() => {
    if (!report) {
      return null;
    }
    return report.generated_at || report.report_date;
  }, [report]);

  return {
    data,
    report,
    loading,
    refreshing,
    error,
    lastUpdated,
    refresh,
  };
};

export default useMacroReport;
