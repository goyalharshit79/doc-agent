import React, { useState, useEffect, useCallback } from 'react'
import { Users, Shield, Trash2, Crown, AlertCircle, RefreshCw, ToggleLeft, ToggleRight } from 'lucide-react'
import { getAdminUsers, updateAdminUser, deleteAdminUser } from '../api'

function formatDate(dateStr) {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function AdminConsole() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [actionLoading, setActionLoading] = useState(null) // user_id of user being updated

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getAdminUsers()
      setUsers(data)
    } catch (err) {
      setError(err.message || 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  const handleToggleUnlimited = async (user) => {
    setActionLoading(user.user_id)
    try {
      await updateAdminUser(user.user_id, { is_unlimited: !user.is_unlimited })
      setUsers(prev => prev.map(u =>
        u.user_id === user.user_id ? { ...u, is_unlimited: !u.is_unlimited } : u
      ))
    } catch (err) {
      setError(`Failed to update ${user.email}: ${err.message}`)
    } finally {
      setActionLoading(null)
    }
  }

  const handleTogglePlan = async (user) => {
    const newPlan = user.plan === 'pro' ? 'free' : 'pro'
    const newUnlimited = newPlan === 'pro'  // pro always means unlimited
    setActionLoading(user.user_id)
    try {
      await updateAdminUser(user.user_id, { plan: newPlan })
      setUsers(prev => prev.map(u =>
        u.user_id === user.user_id ? { ...u, plan: newPlan, is_unlimited: newUnlimited } : u
      ))
    } catch (err) {
      setError(`Failed to update ${user.email}: ${err.message}`)
    } finally {
      setActionLoading(null)
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteAdminUser(deleteTarget.user_id)
      setUsers(prev => prev.filter(u => u.user_id !== deleteTarget.user_id))
      setDeleteTarget(null)
    } catch (err) {
      setError(`Failed to delete ${deleteTarget.email}: ${err.message}`)
      setDeleteTarget(null)
    } finally {
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="admin-page">
        <div className="admin-loading">
          <div className="preview-spinner" />
          <p>Loading users…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="admin-page">
      <div className="admin-header">
        <div className="admin-header-left">
          <Shield size={20} color="var(--accent)" />
          <h1 className="admin-title">Admin Console</h1>
        </div>
        <div className="admin-header-right">
          <span className="admin-user-count">{users.length} user{users.length !== 1 ? 's' : ''}</span>
          <button className="admin-refresh-btn" onClick={loadUsers} title="Refresh">
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="admin-error">
          <AlertCircle size={14} />
          <span>{error}</span>
          <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Plan</th>
              <th>Unlimited</th>
              <th>Docs</th>
              <th>Status</th>
              <th>Joined</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map(user => (
              <tr key={user.user_id} className={actionLoading === user.user_id ? 'admin-row--loading' : ''}>
                <td className="admin-cell-email" title={user.email}>{user.email}</td>
                <td>
                  <button
                    className={`admin-plan-badge admin-plan-badge--${user.plan}`}
                    onClick={() => handleTogglePlan(user)}
                    disabled={actionLoading === user.user_id}
                    title={`Click to switch to ${user.plan === 'pro' ? 'free' : 'pro'}`}
                  >
                    {user.plan === 'pro' && <Crown size={10} />}
                    {user.plan}
                  </button>
                </td>
                <td>
                  <button
                    className="admin-toggle-btn"
                    onClick={() => handleToggleUnlimited(user)}
                    disabled={actionLoading === user.user_id}
                    title={user.is_unlimited ? 'Remove unlimited' : 'Grant unlimited'}
                  >
                    {user.is_unlimited
                      ? <ToggleRight size={20} color="var(--accent)" />
                      : <ToggleLeft size={20} color="var(--text-muted)" />
                    }
                  </button>
                </td>
                <td>{user.document_count}</td>
                <td>
                  <span className={`admin-status admin-status--${user.subscription_status}`}>
                    {user.subscription_status}
                  </span>
                </td>
                <td className="admin-cell-date">{formatDate(user.created_at)}</td>
                <td>
                  <button
                    className="admin-delete-btn"
                    onClick={() => setDeleteTarget(user)}
                    disabled={actionLoading === user.user_id}
                    title="Delete user"
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Delete confirmation dialog */}
      {deleteTarget && (
        <div className="delete-dialog-overlay" onClick={() => setDeleteTarget(null)}>
          <div className="delete-dialog" onClick={e => e.stopPropagation()}>
            <div className="delete-dialog-icon">
              <AlertCircle size={32} color="#c47a6a" />
            </div>
            <h3 className="delete-dialog-title">Delete user?</h3>
            <p className="delete-dialog-text">
              This will permanently delete <strong>{deleteTarget.email}</strong> — including their account, documents, and all embeddings. This action cannot be undone.
            </p>
            <div className="delete-dialog-actions">
              <button
                className="delete-dialog-cancel"
                onClick={() => setDeleteTarget(null)}
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                className="delete-dialog-confirm"
                onClick={handleDeleteConfirm}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Delete User'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
