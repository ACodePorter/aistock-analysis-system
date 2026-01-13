import React, { useState, useEffect } from 'react';
import { buildApiUrl } from '../config/api';

interface AgentStatus {
  status: string;
  created_at?: string;
  strict?: boolean;
  return_code?: number;
  stdout_tail?: string[];
  stderr_tail?: string[];
  reports_detected?: string[];
  duration_sec?: number;
  queue_position?: number;
  concurrency_limit?: number;
  error?: string;
}

const AgentPanel: React.FC = () => {
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [strict, setStrict] = useState(true);
  const [withMarkdown, setWithMarkdown] = useState(true);
  const [latestReport, setLatestReport] = useState<any | null>(null);
  const [latestMarkdown, setLatestMarkdown] = useState<string | null>(null);
  const [fetchingReport, setFetchingReport] = useState(false);

  const runAgent = async () => {
    try {
      setLoading(true);
      const url = buildApiUrl(`/api/agent/run?strict_json=${strict ? 'true' : 'false'}`);
      const resp = await fetch(url, { method: 'POST' });
      if (!resp.ok) throw new Error(`启动失败: ${resp.status}`);
      const data = await resp.json();
      setJobId(data.job_id);
      setStatus({ status: data.status, concurrency_limit: data.concurrency_limit, queue_position: data.queue_position });
    } catch (e:any) {
      setStatus({ status: 'error', error: e.message });
    } finally {
      setLoading(false);
    }
  };

  const pollStatus = async () => {
    if (!jobId) return;
    try {
      const resp = await fetch(buildApiUrl(`/api/agent/status/${jobId}`));
      if (!resp.ok) throw new Error('查询失败');
      const data = await resp.json();
      setStatus(data);
    } catch (e:any) {
      // ignore transient
    }
  };

  const fetchLatestReport = async () => {
    try {
      setFetchingReport(true);
      const resp = await fetch(buildApiUrl(`/api/agent/latest?with_markdown=${withMarkdown ? 'true':'false'}`));
      if (!resp.ok) throw new Error('获取报告失败');
      const data = await resp.json();
      setLatestReport(data.report || data.reports?.[0]?.report || data);
      const md = (data.markdown) || (data.reports?.[0]?.markdown) || null;
      setLatestMarkdown(md);
    } catch (e:any) {
      // eslint-disable-next-line no-console
      console.warn(e);
    } finally {
      setFetchingReport(false);
    }
  };

  useEffect(() => {
    if (!jobId) return;
    const id = setInterval(pollStatus, 2500);
    return () => clearInterval(id);
  }, [jobId]);

  const canFetchReport = status && ['finished','failed'].includes(status.status);

  return (
    <div className="border rounded p-4 space-y-4 bg-white shadow-sm">
      <h2 className="text-lg font-semibold">Top20 智能分析 Agent</h2>
      <div className="flex items-center gap-3 flex-wrap">
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={strict} onChange={e=>setStrict(e.target.checked)} /> 严格JSON
        </label>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={withMarkdown} onChange={e=>setWithMarkdown(e.target.checked)} /> 带Markdown
        </label>
        <button disabled={loading} onClick={runAgent} className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded disabled:opacity-50">
          {loading ? '启动中...' : '启动运行'}
        </button>
        <button disabled={!canFetchReport || fetchingReport} onClick={fetchLatestReport} className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded disabled:opacity-40">
          {fetchingReport ? '获取中...' : '拉取最新报告'}
        </button>
        {jobId && <span className="text-xs text-gray-500">Job: {jobId.slice(0,10)}...</span>}
      </div>
      {status && (
        <div className="text-sm space-y-1">
          <div>状态: <span className="font-medium">{status.status}</span>{status.queue_position ? ` (队列#${status.queue_position})` : ''}</div>
          {status.duration_sec !== undefined && <div>耗时: {status.duration_sec}s</div>}
          {status.return_code !== undefined && <div>返回码: {status.return_code}</div>}
          {status.concurrency_limit && <div>并发上限: {status.concurrency_limit}</div>}
          {status.error && <div className="text-red-600">错误: {status.error}</div>}
          {status.stdout_tail && status.stdout_tail.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-blue-600">stdout尾部</summary>
              <pre className="max-h-48 overflow-auto text-xs bg-gray-50 p-2 border">{status.stdout_tail.join('\n')}</pre>
            </details>
          )}
          {status.stderr_tail && status.stderr_tail.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-red-600">stderr尾部</summary>
              <pre className="max-h-48 overflow-auto text-xs bg-red-50 p-2 border">{status.stderr_tail.join('\n')}</pre>
            </details>
          )}
        </div>
      )}
      {latestReport && (
        <div className="text-sm space-y-2">
          <h3 className="font-medium">最新报告 JSON 概览</h3>
          <pre className="max-h-64 overflow-auto text-xs bg-gray-50 p-2 border">{JSON.stringify({
            started_at: latestReport.started_at,
            finished_at: latestReport.finished_at,
            top20_count: latestReport.top20_count,
            warnings: latestReport.diagnostics?.warnings,
            fallback_ratio: latestReport.diagnostics?.fallback_ratio
          }, null, 2)}</pre>
          {latestMarkdown && (
            <details>
              <summary className="cursor-pointer text-indigo-600">Markdown 预览</summary>
              <pre className="max-h-72 overflow-auto text-xs bg-white p-2 border whitespace-pre-wrap">{latestMarkdown}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
};

export default AgentPanel;
