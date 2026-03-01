import React, { useCallback, useState } from 'react'
import { UploadCloud } from 'lucide-react'

const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md']

export default function UploadZone({ onFilesAdded }) {
  const [isDragging, setIsDragging] = useState(false)

  const processFiles = useCallback((fileList) => {
    const valid = Array.from(fileList).filter(f => {
      const ext = '.' + f.name.split('.').pop().toLowerCase()
      return ACCEPTED_EXTENSIONS.includes(ext)
    })
    if (valid.length) onFilesAdded(valid)
  }, [onFilesAdded])

  const onDragOver  = (e) => { e.preventDefault(); setIsDragging(true) }
  const onDragLeave = (e) => { e.preventDefault(); setIsDragging(false) }
  const onDrop      = (e) => { e.preventDefault(); setIsDragging(false); processFiles(e.dataTransfer.files) }
  const onInputChange = (e) => processFiles(e.target.files)

  return (
    <div className="upload-wrapper">
      <label
        className={`upload-zone${isDragging ? ' upload-zone--dragging' : ''}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        <input
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(',')}
          onChange={onInputChange}
          style={{ display: 'none' }}
        />

        <div className="upload-icon-wrap">
          <UploadCloud size={32} color="var(--accent)" strokeWidth={1.5} />
        </div>

        <p className="upload-headline">
          {isDragging ? 'Release to upload' : 'Drop documents here'}
        </p>
        <p className="upload-sub">or <span className="upload-link">browse files</span></p>

        <div className="upload-pills">
          {ACCEPTED_EXTENSIONS.map(ext => (
            <span key={ext} className="upload-pill">{ext.toUpperCase()}</span>
          ))}
        </div>
      </label>
    </div>
  )
}
