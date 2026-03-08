import React, { useState, useEffect, useCallback } from 'react'
import { FileText, FileType, File, Trash2, MessageSquare, AlertCircle, RefreshCw } from 'lucide-react'
import { listDocuments, deleteDocument } from '../api'

const EXT_ICON = {
  pdf:  { icon: FileType, color: '#c47a6a' },
  docx: { icon: FileText, color: '#6a8fb5' },
  txt:  { icon: File,     color: '#8a7ab5' },
  md:   { icon: FileText, color: '#6aab8a' },
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function YourDocuments({ onSelectDoc, user, onUsageChanged }) {
  const [docs, setDocs]           = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)  // doc to confirm delete
  const [deleting, setDeleting]   = useState(false)

  // Load documents (extracted so it can be called from Retry button too)
  const loadDocs = useCallback(async (signal) => {
    setLoading(true)
    setError(null)
    try {
      // Race against a 15-second timeout so the page never hangs forever
      const timeout = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 15000)
      )
      const result = await Promise.race([listDocuments(), timeout])
      if (!signal?.aborted) setDocs(result)
    } catch (err) {
      if (!signal?.aborted) {
        setError(
          err.message === 'timeout'
            ? 'Loading took too long. Please try again.'
            : 'Could not load your documents. Please try again.'
        )
      }
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!user) return
    const controller = new AbortController()
    loadDocs(controller.signal)
    return () => controller.abort()
  }, [user, loadDocs])

  // ── Delete with confirmation ──────────────────────────────────────────────
  const handleDeleteClick = (e, doc) => {
    e.stopPropagation()
    setDeleteTarget(doc)
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteDocument(deleteTarget.doc_id)
      setDocs(prev => prev.filter(d => d.doc_id !== deleteTarget.doc_id))
      setDeleteTarget(null)
      // Refresh usage after delete (frees up a document slot)
      if (onUsageChanged) onUsageChanged()
    } catch (err) {
      setError('Could not delete the document. Please try again.')
      setDeleteTarget(null)
    } finally {
      setDeleting(false)
    }
  }

  const handleDeleteCancel = () => {
    setDeleteTarget(null)
  }

  // ── Select a doc → navigate to Ask page with that single doc ──────────────
  const handleDocClick = (doc) => {
    onSelectDoc(doc)
  }

  // ── Loading state ─────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="your-docs-page">
        <div className="your-docs-loading">
          <div className="preview-spinner" />
          <p>Loading your documents…</p>
        </div>
      </div>
    )
  }

  // ── Error state (must come BEFORE empty state) ─────────────────────────
  if (error && docs.length === 0) {
    return (
      <div className="your-docs-page">
        <div className="your-docs-empty">
          <AlertCircle size={48} strokeWidth={1} color="#c47a6a" />
          <h2>Something went wrong</h2>
          <p>{error}</p>
          <button
            className="your-docs-retry-btn"
            onClick={() => loadDocs()}
            style={{
              marginTop: '1rem', padding: '0.5rem 1.25rem',
              background: 'var(--accent)', color: '#fff',
              border: 'none', borderRadius: '6px', cursor: 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              fontSize: '0.85rem',
            }}
          >
            <RefreshCw size={14} /> Try again
          </button>
        </div>
      </div>
    )
  }

  // ── Empty state ───────────────────────────────────────────────────────────
  if (docs.length === 0) {
    return (
      <div className="your-docs-page">
        <div className="your-docs-empty">
          <FileText size={48} strokeWidth={1} color="var(--accent-dim)" />
          <h2>No documents yet</h2>
          <p>Upload and process documents on the Upload page. They'll appear here for quick access.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="your-docs-page">
      <div className="your-docs-header">
        <h1 className="your-docs-title">Your Documents</h1>
        <p className="your-docs-subtitle">{docs.length} document{docs.length !== 1 ? 's' : ''} in your library</p>
      </div>

      {error && (
        <div className="your-docs-error">
          <AlertCircle size={14} />
          <span>{error}</span>
          <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      <div className="your-docs-grid">
        {docs.map(doc => {
          const ext = doc.doc_name.split('.').pop().toLowerCase()
          const { icon: Icon, color } = EXT_ICON[ext] || { icon: File, color: '#b0a59a' }

          return (
            <div
              key={doc.doc_id}
              className="your-docs-card"
              onClick={() => handleDocClick(doc)}
            >
              <div className="your-docs-card-icon" style={{ background: color + '18', border: `1px solid ${color}30` }}>
                <Icon size={24} color={color} strokeWidth={1.5} />
              </div>

              <div className="your-docs-card-info">
                <p className="your-docs-card-name" title={doc.doc_name}>{doc.doc_name}</p>
                <p className="your-docs-card-meta">
                  <span className="file-ext-tag" style={{ color }}>{ext.toUpperCase()}</span>
                  <span>{doc.num_chunks} chunks</span>
                  {doc.created_at && <span>{formatDate(doc.created_at)}</span>}
                </p>
              </div>

              <div className="your-docs-card-actions">
                <button
                  className="your-docs-ask-btn"
                  onClick={(e) => { e.stopPropagation(); handleDocClick(doc) }}
                  title="Ask questions about this document"
                >
                  <MessageSquare size={14} />
                </button>
                <button
                  className="your-docs-delete-btn"
                  onClick={(e) => handleDeleteClick(e, doc)}
                  title="Delete document"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* ── Delete confirmation dialog ──────────────────────────────────────── */}
      {deleteTarget && (
        <div className="delete-dialog-overlay" onClick={handleDeleteCancel}>
          <div className="delete-dialog" onClick={e => e.stopPropagation()}>
            <div className="delete-dialog-icon">
              <AlertCircle size={32} color="#c47a6a" />
            </div>
            <h3 className="delete-dialog-title">Delete document?</h3>
            <p className="delete-dialog-text">
              This will permanently delete <strong>{deleteTarget.doc_name}</strong> — including all embeddings and metadata. This action cannot be undone.
            </p>
            <div className="delete-dialog-actions">
              <button
                className="delete-dialog-cancel"
                onClick={handleDeleteCancel}
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                className="delete-dialog-confirm"
                onClick={handleDeleteConfirm}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
