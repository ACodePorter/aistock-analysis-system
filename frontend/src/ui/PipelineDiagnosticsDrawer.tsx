import React, { useCallback, useEffect, useState } from 'react'
import { Drawer, Table, Tag, Button, message, Spin, Alert } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  fetchPipelineHistory,
  type PipelineRunDetail,
  type PipelineStatus,
} from '../api/pipelineStatus'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../config/helpTips'

interface Props {
  symbol: string | null
  open: boolean
  onClose: () => void
}

const STATUS_TAG: Record<PipelineStatus, { color: string; text: string }> = {
  success: { color: 'green', text: '成功' },
  running: { color: 'processing', text: '执行中' },
  skipped: { color: 'gold', text: '跳过' },
  failed:  { color: 'red', text: '失败' },
}

const RUN_TYPE_LABELS: Record<string, string> = {
  daily_pipeline: '日线管道',
  fetch_daily: '行情补数',
  compute_signal: '信号',
  predict: '预测',
  full_report: '完整报告',
}

function withHelp(label: string, tip: HelpTipKey) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      {label}
      <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>
    </span>
  )
}

function copyText(text: string) {
  try {
    navigator.clipboard.writeText(text)
    message.success('已复制到剪贴板')
  } catch {
    message.warning('当前环境不支持剪贴板')
  }
}

export const PipelineDiagnosticsDrawer: React.FC<Props> = ({ symbol, open, onClose }) => {
  const [loading, setLoading] = useState(false)
  const [rows, setRows] = useState<PipelineRunDetail[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!symbol || !open) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetchPipelineHistory(symbol, 50)
      setRows(res.items || [])
    } catch (err: any) {
      setError(err?.message ?? String(err))
    } finally {
      setLoading(false)
    }
  }, [symbol, open])

  useEffect(() => { load() }, [load])

  const columns: ColumnsType<PipelineRunDetail> = [
    {
      title: withHelp('时间', 'pipelineRunTime'),
      dataIndex: 'run_at',
      width: 170,
      render: v => (v ? new Date(v).toLocaleString() : '—'),
    },
    {
      title: withHelp('类型', 'pipelineRunType'),
      dataIndex: 'run_type',
      width: 120,
      render: v => RUN_TYPE_LABELS[v] || v,
    },
    {
      title: withHelp('状态', 'status'),
      dataIndex: 'status',
      width: 90,
      render: (v: PipelineStatus) => {
        const t = STATUS_TAG[v] ?? { color: 'default', text: v }
        return <Tag color={t.color}>{t.text}</Tag>
      },
    },
    {
      title: withHelp('耗时(ms)', 'duration'),
      dataIndex: 'duration_ms',
      width: 100,
      align: 'right',
      render: v => (v == null ? '—' : v),
    },
    {
      title: withHelp('触发源', 'triggerSource'),
      dataIndex: 'trigger',
      width: 110,
    },
    {
      title: withHelp('摘要', 'successFailure'),
      dataIndex: 'message',
      ellipsis: true,
      render: v => v || '—',
    },
  ]

  return (
    <Drawer
      title={(
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {symbol ? `数据管道诊断 · ${symbol}` : '数据管道诊断'}
          <HelpTooltip {...helpTips.dataPipelineDiagnosis}><HelpIcon /></HelpTooltip>
        </span>
      )}
      placement="right"
      width={720}
      open={open}
      onClose={onClose}
      extra={
        <HelpTooltip {...helpTips.refreshData}>
          <span style={{ display: 'inline-flex' }}>
            <Button size="small" onClick={load} disabled={!symbol || loading}>
              刷新
            </Button>
          </span>
        </HelpTooltip>
      }
    >
      {error && (
        <Alert type="error" message={error} style={{ marginBottom: 12 }} showIcon closable />
      )}
      <Spin spinning={loading}>
        <Table<PipelineRunDetail>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          expandable={{
            expandedRowRender: (record) => (
              <div style={{ fontSize: 12 }}>
                {record.error_message && (
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ fontWeight: 500, color: '#ef4444', marginBottom: 4 }}>
                      错误：
                      <HelpTooltip {...helpTips.copyError}>
                        <Button
                          size="small"
                          type="link"
                          onClick={() => copyText(record.error_message ?? '')}
                        >
                          复制
                        </Button>
                      </HelpTooltip>
                    </div>
                    <pre
                      style={{
                        background: '#1f1f1f',
                        color: '#fca5a5',
                        padding: 8,
                        borderRadius: 4,
                        maxHeight: 120,
                        overflow: 'auto',
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {record.error_message}
                    </pre>
                  </div>
                )}
                <div>
                  <div style={{ fontWeight: 500, marginBottom: 4 }}>
                    日志尾部：
                    <HelpTooltip {...helpTips.copyLog}>
                      <span style={{ display: 'inline-flex' }}>
                        <Button
                          size="small"
                          type="link"
                          onClick={() => copyText(record.log_excerpt ?? '')}
                          disabled={!record.log_excerpt}
                        >
                          复制
                        </Button>
                      </span>
                    </HelpTooltip>
                  </div>
                  <pre
                    style={{
                      background: '#111',
                      color: '#cbd5e1',
                      padding: 8,
                      borderRadius: 4,
                      maxHeight: 220,
                      overflow: 'auto',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {record.log_excerpt || '(无日志捕获)'}
                  </pre>
                </div>
              </div>
            ),
          }}
          locale={{ emptyText: symbol ? '暂无执行记录' : '请选择股票' }}
        />
      </Spin>
      <div style={{ marginTop: 16, fontSize: 12, color: '#888' }}>
        更多任务执行信息可在
        {' '}
        <a href="/api/dashboard/reports" target="_blank" rel="noreferrer">/api/dashboard/reports</a>
        {' '}查看。
      </div>
    </Drawer>
  )
}

export default PipelineDiagnosticsDrawer
