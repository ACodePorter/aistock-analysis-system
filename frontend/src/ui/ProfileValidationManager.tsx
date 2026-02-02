import React from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'

interface InvalidProfile {
  symbol: string
  company_name: string
  validation_status: string
  validation_reason: string
  last_validated_at: string | null
  industry: string | null
}

export default function ProfileValidationManager() {
  const [invalidProfiles, setInvalidProfiles] = React.useState<InvalidProfile[]>([])
  const [loading, setLoading] = React.useState(false)
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(20)
  const [total, setTotal] = React.useState(0)
  const [selectedSymbols, setSelectedSymbols] = React.useState<Set<string>>(new Set())
  const [filterStatus, setFilterStatus] = React.useState<string | null>(null)
  const [deleteInProgress, setDeleteInProgress] = React.useState(false)
  const [deleteMessage, setDeleteMessage] = React.useState('')

  // 加载无效的 Profiles
  const loadInvalidProfiles = React.useCallback(async () => {
    setLoading(true)
    try {
      const url = buildApiUrl(`/api/profile/invalid-list?page=${page}&page_size=${pageSize}`)
      const res = await fetch(url, { cache: 'no-store' })
      
      if (!res.ok) throw new Error(await res.text())
      
      const data = await res.json()
      setInvalidProfiles(data.invalid_profiles || [])
      setTotal(data.total || 0)
    } catch (err) {
      console.error('Failed to load invalid profiles:', err)
      alert('Failed to load invalid profiles')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  React.useEffect(() => {
    loadInvalidProfiles()
  }, [loadInvalidProfiles])

  // 切换选择
  const toggleSelect = (symbol: string) => {
    const newSelected = new Set(selectedSymbols)
    if (newSelected.has(symbol)) {
      newSelected.delete(symbol)
    } else {
      newSelected.add(symbol)
    }
    setSelectedSymbols(newSelected)
  }

  // 全选
  const toggleSelectAll = () => {
    if (selectedSymbols.size === invalidProfiles.length) {
      setSelectedSymbols(new Set())
    } else {
      setSelectedSymbols(new Set(invalidProfiles.map(p => p.symbol)))
    }
  }

  // 删除选中的 Profiles
  const deleteSelected = async () => {
    if (selectedSymbols.size === 0) {
      alert('Please select profiles to delete')
      return
    }

    if (!confirm(`Delete ${selectedSymbols.size} invalid profiles? This action cannot be undone.`)) {
      return
    }

    setDeleteInProgress(true)
    setDeleteMessage('')

    try {
      const url = buildApiUrl('/api/profile/delete-invalid')
      const res = await fetch(url, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: Array.from(selectedSymbols),
          confirm: true
        })
      })

      if (!res.ok) throw new Error(await res.text())

      const data = await res.json()
      setDeleteMessage(`Successfully deleted ${data.deleted} profiles`)
      setSelectedSymbols(new Set())
      
      // 刷新列表
      setTimeout(() => loadInvalidProfiles(), 1000)
    } catch (err) {
      console.error('Delete failed:', err)
      setDeleteMessage(`Delete failed: ${err}`)
    } finally {
      setDeleteInProgress(false)
    }
  }

  // 恢复选中的 Profiles
  const restoreSelected = async () => {
    if (selectedSymbols.size === 0) {
      alert('Please select profiles to restore')
      return
    }

    if (!confirm(`Restore ${selectedSymbols.size} profiles?`)) {
      return
    }

    try {
      const url = buildApiUrl('/api/profile/restore')
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: Array.from(selectedSymbols)
        })
      })

      if (!res.ok) throw new Error(await res.text())

      const data = await res.json()
      setDeleteMessage(`Successfully restored ${data.restored} profiles`)
      setSelectedSymbols(new Set())
      
      // 刷新列表
      setTimeout(() => loadInvalidProfiles(), 1000)
    } catch (err) {
      console.error('Restore failed:', err)
      alert(`Restore failed: ${err}`)
    }
  }

  const statusColors: Record<string, string> = {
    'invalid': 'dark-badge dark-badge-danger',
    'risk_alert': 'dark-badge dark-badge-warning',
    'suspended': 'dark-badge dark-badge-warning',
    'delisted': 'dark-badge dark-badge-danger',
    'unknown': 'dark-badge'
  }

  return (
    <div className="dark-card p-6">
      <h2 className="text-2xl font-bold mb-4 text-[var(--text)]">Invalid Profile Management</h2>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="dark-card p-4 border-l-4 border-l-[var(--accent-red)]">
          <div className="dark-stat-label">Invalid Profiles</div>
          <div className="dark-stat-value text-[var(--accent-red)]">{total}</div>
        </div>
        <div className="dark-card p-4 border-l-4 border-l-[var(--primary)]">
          <div className="dark-stat-label">Selected</div>
          <div className="dark-stat-value text-[var(--primary)]">{selectedSymbols.size}</div>
        </div>
        <div className="dark-card p-4 border-l-4 border-l-[var(--accent-lime)]">
          <div className="dark-stat-label">Page {page}</div>
          <div className="dark-stat-value text-[var(--accent-lime)]">{total > 0 ? Math.ceil(total / pageSize) : 0}</div>
        </div>
      </div>

      {/* Message */}
      {deleteMessage && (
        <div className={`p-3 rounded mb-4 ${deleteMessage.includes('failed') ? 'dark-badge-danger' : 'dark-badge-success'}`} style={{ display: 'block', width: '100%', borderRadius: '8px', padding: '12px' }}>
          {deleteMessage}
        </div>
      )}

      {/* Actions */}
      <div className="mb-4 flex gap-2">
        <button
          onClick={toggleSelectAll}
          className="dark-btn dark-btn-secondary"
        >
          {selectedSymbols.size === invalidProfiles.length ? 'Deselect All' : 'Select All'}
        </button>
        <button
          onClick={restoreSelected}
          disabled={selectedSymbols.size === 0 || deleteInProgress}
          className="dark-btn dark-btn-primary disabled:opacity-50"
        >
          Restore Selected ({selectedSymbols.size})
        </button>
        <button
          onClick={deleteSelected}
          disabled={selectedSymbols.size === 0 || deleteInProgress}
          className="dark-btn disabled:opacity-50"
          style={{ background: 'rgba(239,68,68,0.2)', color: 'var(--accent-red)', borderColor: 'var(--accent-red)' }}
        >
          {deleteInProgress ? 'Deleting...' : `Delete Selected (${selectedSymbols.size})`}
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="dark-table w-full">
          <thead>
            <tr>
              <th className="w-12">
                <input
                  type="checkbox"
                  checked={selectedSymbols.size > 0 && selectedSymbols.size === invalidProfiles.length}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Symbol</th>
              <th>Company</th>
              <th>Industry</th>
              <th>Status</th>
              <th>Reason</th>
              <th>Last Validated</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="p-4 text-center text-[var(--text-muted)]">
                  Loading...
                </td>
              </tr>
            ) : invalidProfiles.length === 0 ? (
              <tr>
                <td colSpan={7} className="p-4 text-center text-[var(--text-muted)]">
                  No invalid profiles found
                </td>
              </tr>
            ) : (
              invalidProfiles.map(profile => (
                <tr key={profile.symbol}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedSymbols.has(profile.symbol)}
                      onChange={() => toggleSelect(profile.symbol)}
                    />
                  </td>
                  <td className="font-mono text-sm">{profile.symbol}</td>
                  <td className="text-sm">{profile.company_name || 'N/A'}</td>
                  <td className="text-sm">{profile.industry || 'N/A'}</td>
                  <td>
                    <span className={statusColors[profile.validation_status] || statusColors['unknown']}>
                      {profile.validation_status}
                    </span>
                  </td>
                  <td className="text-sm max-w-xs truncate" title={profile.validation_reason}>
                    {profile.validation_reason || 'N/A'}
                  </td>
                  <td className="text-xs">
                    {profile.last_validated_at ? new Date(profile.last_validated_at).toLocaleDateString() : 'N/A'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="mt-4 flex justify-between items-center">
        <div className="text-sm text-[var(--text-muted)]">
          Total: {total} | Page: {page} of {Math.ceil(total / pageSize) || 1}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page <= 1}
            className="dark-btn dark-btn-secondary disabled:opacity-50"
          >
            Previous
          </button>
          <button
            onClick={() => setPage(Math.min(Math.ceil(total / pageSize), page + 1))}
            disabled={page >= Math.ceil(total / pageSize)}
            className="dark-btn dark-btn-secondary disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
