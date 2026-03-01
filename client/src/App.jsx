import React, { useState, useRef, useCallback } from 'react'
import { Menu, X, BookOpen, FileOutput, PanelLeft } from 'lucide-react'
import AuthPage from './components/AuthPage'
import UploadZone from './components/UploadZone'
import FileList from './components/FileList'
import DocumentPreview from './components/DocumentPreview'
import AskPage from './components/AskPage'
import { uploadDocument } from './api'

// ── Placeholder pages for upcoming features ──────────────────────────────────
const PAGE_ICONS = { study: BookOpen, extract: FileOutput }

function PlaceholderPage({ page }) {
  const Icon = PAGE_ICONS[page]
  return (
    <div className="placeholder-page">
      <div className="placeholder-content">
        {Icon && <Icon size={48} strokeWidth={1} color="var(--accent-dim)" />}
        <h2 className="placeholder-title">{page.charAt(0).toUpperCase() + page.slice(1)}</h2>
        <p className="placeholder-subtitle">Coming soon</p>
      </div>
    </div>
  )
}

// ── Nav pages ────────────────────────────────────────────────────────────────
const PAGES = ['upload', 'ask', 'study', 'extract']

export default function App() {
  // ── Auth state ─────────────────────────────────────────────────────────────
  const storedToken = localStorage.getItem('docagent_token')
  const [user, setUser] = useState(storedToken ? { token: storedToken } : null)

  const handleAuth = (userData) => setUser(userData)

  const handleLogout = () => {
    localStorage.removeItem('docagent_token')
    setUser(null)
    setFiles([])
    setActiveIndex(0)
    setActivePage('upload')
    setMobileMenuOpen(false)
  }

  // ── Navigation state ───────────────────────────────────────────────────────
  const [activePage, setActivePage]       = useState('upload')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen]     = useState(true)

  // ── File state ─────────────────────────────────────────────────────────────
  // status: 'pending' | 'uploading' | 'processed' | 'error'
  const [files, setFiles]             = useState([])
  const [activeIndex, setActiveIndex] = useState(0)
  const addInputRef = useRef(null)

  // Derived state
  const pendingCount    = files.filter(f => f.status === 'pending').length
  const processedFiles  = files.filter(f => f.status === 'processed')
  const hasFiles        = files.length > 0

  // ── Add files (deferred — no backend call) ─────────────────────────────────
  const handleFilesAdded = useCallback((newFiles) => {
    const existingNames = new Set(files.map(f => f.file.name))
    const unique = newFiles.filter(f => !existingNames.has(f.name))
    if (!unique.length) return

    const entries = unique.map(f => ({ file: f, docId: null, status: 'pending', error: null }))
    setFiles(prev => {
      const updated = [...prev, ...entries]
      setActiveIndex(prev.length)
      return updated
    })
  }, [files])

  // ── Process pending files (sends to backend) ──────────────────────────────
  const handleProcessDocuments = useCallback(async () => {
    // Snapshot pending entries from current state (avoids stale closure)
    const pendingEntries = []
    setFiles(prev => {
      const updated = prev.map((e, i) => {
        if (e.status === 'pending') {
          pendingEntries.push({ index: i, file: e.file })
          return { ...e, status: 'uploading' }
        }
        return e
      })
      return updated
    })

    for (const { index, file } of pendingEntries) {
      if (!file) continue
      try {
        const res = await uploadDocument(file)
        setFiles(prev => prev.map((e, i) =>
          i === index ? { ...e, docId: res.doc_id, status: 'processed', error: null } : e
        ))
      } catch (err) {
        setFiles(prev => prev.map((e, i) =>
          i === index ? { ...e, status: 'error', error: err.message } : e
        ))
      }
    }
  }, [])

  const handleRemove = useCallback((index) => {
    setFiles(prev => {
      const updated = prev.filter((_, i) => i !== index)
      setActiveIndex(i => Math.min(i, Math.max(0, updated.length - 1)))
      return updated
    })
  }, [])

  const handleAddMore = () => addInputRef.current?.click()
  const handleAddInput = (e) => {
    const newFiles = Array.from(e.target.files)
    if (newFiles.length) handleFilesAdded(newFiles)
    e.target.value = ''
  }

  // ── Auth gate ──────────────────────────────────────────────────────────────
  if (!user) return <AuthPage onAuth={handleAuth} />

  return (
    <div className="app-root">
      <input
        ref={addInputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.txt,.md"
        onChange={handleAddInput}
        style={{ display: 'none' }}
      />

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <header className="app-header">
        <div className="logo">
          <span className="logo-mark">D</span>
          <span className="logo-text">oc<em>Agent</em></span>
        </div>

        <button
          className="mobile-menu-btn"
          onClick={() => setMobileMenuOpen(prev => !prev)}
          aria-label="Toggle menu"
        >
          {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        <nav className={`app-nav${mobileMenuOpen ? ' app-nav--open' : ''}`}>
          {PAGES.map((page) => (
            <span
              key={page}
              className={`nav-item${activePage === page ? ' nav-item--active' : ''}`}
              onClick={() => { setActivePage(page); setMobileMenuOpen(false) }}
            >
              {page.charAt(0).toUpperCase() + page.slice(1)}
            </span>
          ))}
        </nav>

        <div className="header-right">
          <div className="status-pill">
            <span className="status-dot" />
            <span className="status-text">
              {hasFiles
                ? `${processedFiles.length}/${files.length} processed`
                : 'No documents'}
            </span>
          </div>
          <button className="auth-logout-btn" onClick={handleLogout} title="Sign out">
            Sign out
          </button>
        </div>
      </header>

      {/* ── Main content ────────────────────────────────────────────────────── */}
      <main
        className="app-main"
        onClick={() => mobileMenuOpen && setMobileMenuOpen(false)}
      >
        {activePage === 'upload' && (
          <>
            {!hasFiles ? (
              <div className="empty-state">
                <div className="empty-top">
                  <h1 className="empty-headline">
                    Your documents,<br /><em>intelligently indexed.</em>
                  </h1>
                  <p className="empty-subheadline">
                    Upload PDFs, Word docs, or text files. Ask questions, study, extract — all with exact citations.
                  </p>
                </div>
                <UploadZone onFilesAdded={handleFilesAdded} />
              </div>
            ) : (
              <div className={`workspace${!sidebarOpen ? ' workspace--sidebar-hidden' : ''}`}>
                <FileList
                  files={files}
                  activeIndex={activeIndex}
                  onSelect={(i) => { setActiveIndex(i); setSidebarOpen(false) }}
                  onRemove={handleRemove}
                  onAddMore={handleAddMore}
                  onProcess={handleProcessDocuments}
                  pendingCount={pendingCount}
                />
                <div className="preview-area">
                  <button
                    className="sidebar-toggle-btn"
                    onClick={() => setSidebarOpen(prev => !prev)}
                    aria-label="Toggle file list"
                  >
                    <PanelLeft size={16} />
                    <span>{sidebarOpen ? 'Hide files' : 'Show files'}</span>
                  </button>
                  <DocumentPreview file={files[activeIndex]?.file} />
                </div>
              </div>
            )}
          </>
        )}

        {activePage === 'ask' && (
          <AskPage
            files={files}
            processedFiles={processedFiles}
            onNavigateToUpload={() => setActivePage('upload')}
          />
        )}

        {activePage !== 'upload' && activePage !== 'ask' && (
          <PlaceholderPage page={activePage} />
        )}
      </main>
    </div>
  )
}
