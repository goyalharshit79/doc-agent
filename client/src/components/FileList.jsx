import React from 'react'
import { FileText, FileType, File, Trash2, Plus, Zap, Check, AlertCircle, Eye } from 'lucide-react'

const EXT_ICON = {
  pdf:  { icon: FileType, color: '#c47a6a' },
  docx: { icon: FileText, color: '#6a8fb5' },
  txt:  { icon: File,     color: '#8a7ab5' },
  md:   { icon: FileText, color: '#6aab8a' },
}

function formatSize(bytes) {
  if (bytes < 1024)        return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

export default function FileList({ files, activeIndex, onSelect, onRemove, onAddMore, onProcess, pendingCount, isProcessing }) {
  const totalFiles = files.length
  const doneCount = files.filter(f => f.status === 'processed' || f.status === 'error').length

  return (
    <aside className="file-sidebar">
      <div className="file-sidebar-header">
        <span className="file-sidebar-label">Documents</span>
        <span className="file-sidebar-count">{files.length}</span>
      </div>

      <div className="file-list">
        {files.map((entry, i) => {
          const name = entry.file?.name || 'Unknown'
          const size = entry.file?.size
          const ext = name.split('.').pop().toLowerCase()
          const { icon: Icon, color } = EXT_ICON[ext] || { icon: File, color: '#b0a59a' }

          const statusClass = entry.status === 'pending' ? ' file-item--pending'
            : entry.status === 'uploading' ? ' file-item--uploading'
            : entry.status === 'error' ? ' file-item--error'
            : ''

          return (
            <div
              key={entry.docId || i}
              className={`file-item${i === activeIndex ? ' file-item--active' : ''}${statusClass}`}
              onClick={() => onSelect(i)}
            >
              <div
                className="file-icon-box"
                style={{ background: color + '18', border: `1px solid ${color}30` }}
              >
                <Icon size={14} color={color} strokeWidth={1.5} />
              </div>

              <div className="file-item-info">
                <p className="file-item-name" title={name}>{name}</p>
                <p className="file-item-meta">
                  <span className="file-ext-tag" style={{ color }}>{ext.toUpperCase()}</span>
                  {size != null && <span>{formatSize(size)}</span>}
                  {entry.status === 'error' && (
                    <span className="file-error-tag" title={entry.error || 'Unknown error'}>
                      <AlertCircle size={10} style={{ marginRight: 2, verticalAlign: 'middle' }} />
                      {entry.error?.startsWith('4') ? entry.error.split(':')[0] : 'Failed'}
                    </span>
                  )}
                </p>
              </div>

              {entry.status === 'processed' && (
                <span className="file-status-check" title="Processed">
                  <Check size={13} />
                </span>
              )}

              <button
                className="file-remove-btn"
                onClick={e => { e.stopPropagation(); onRemove(i) }}
                title="Remove"
              >
                <Trash2 size={12} />
              </button>
            </div>
          )
        })}
      </div>

      {/* Progress bar during processing */}
      {isProcessing && (
        <div className="process-progress">
          <div className="process-progress-bar">
            <div
              className="process-progress-fill"
              style={{ width: `${totalFiles > 0 ? (doneCount / totalFiles) * 100 : 0}%` }}
            />
          </div>
          <span className="process-progress-label">
            {doneCount} / {totalFiles} processed
          </span>
        </div>
      )}

      {/* Process button */}
      {(pendingCount > 0 || isProcessing) && (
        <button
          className={`file-process-btn${isProcessing ? ' file-process-btn--loading' : ''}`}
          onClick={onProcess}
          disabled={isProcessing}
        >
          {isProcessing ? (
            <>
              <span className="process-spinner" />
              <span>Processing documents…</span>
            </>
          ) : (
            <>
              <Zap size={14} />
              <span>Process {pendingCount} document{pendingCount > 1 ? 's' : ''}</span>
            </>
          )}
        </button>
      )}

      {/* Mobile: explicit preview button when a file is selected */}
      {files[activeIndex] && !isProcessing && (
        <button className="file-preview-btn" onClick={() => onSelect(activeIndex)}>
          <Eye size={14} />
          <span>Preview: {files[activeIndex].file?.name}</span>
        </button>
      )}

      <button className="file-add-btn" onClick={onAddMore}>
        <Plus size={14} />
        <span>Add more</span>
      </button>
    </aside>
  )
}
