import React, { useState, useRef, useEffect } from 'react'
import { MessageSquare, Send, FileText, Eye, X, Upload, Trash2, FolderOpen } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ask } from '../api'
import DocumentPreview from './DocumentPreview'

// ── Module-level: survives component unmount/remount ────────────────────────
// Stores the in-flight ask promise so we can re-subscribe on remount.
let _pendingAsk = null

// ── Typing indicator ──────────────────────────────────────────────────────────
function TypingIndicator() {
  return (
    <div className="chat-msg chat-msg--assistant">
      <div className="chat-msg-bubble">
        <div className="typing-indicator">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
        </div>
      </div>
    </div>
  )
}

// ── Single chat message ───────────────────────────────────────────────────────
function ChatMessage({ msg, onCitationClick, activeCitationId }) {
  const isUser = msg.role === 'user'

  return (
    <div className={`chat-msg chat-msg--${msg.role}`}>
      <div className="chat-msg-bubble">
        {isUser ? (
          <p className="chat-msg-text">{msg.content}</p>
        ) : (
          <div className="chat-msg-text markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
          </div>
        )}
      </div>

      {!isUser && msg.citations?.length > 0 && (
        <div className="chat-citations">
          {msg.citations.map((c, i) => (
            <button
              key={i}
              className={`citation-chip${activeCitationId === c.chunk_id ? ' citation-chip--active' : ''}`}
              onClick={() => onCitationClick(c)}
              title={c.quote?.slice(0, 120) + '…'}
            >
              <FileText size={11} />
              <span className="citation-name">{c.doc_name}</span>
              {c.page && <span className="citation-page">p.{c.page}</span>}
              {!c.page && c.heading && <span className="citation-page">{c.heading}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main AskPage ──────────────────────────────────────────────────────────────
export default function AskPage({ activeDoc, onNavigateToUpload, onNavigateToDocs }) {
  // ── Chat persistence via sessionStorage ───────────────────────────────────
  const [messages, setMessages] = useState(() => {
    try {
      const stored = sessionStorage.getItem('docagent_chat_messages')
      return stored ? JSON.parse(stored) : []
    } catch {
      return []
    }
  })

  const [input, setInput]                   = useState('')
  const [isLoading, setIsLoading]           = useState(!!_pendingAsk)
  const [previewPage, setPreviewPage]       = useState(null)
  const [highlightQuote, setHighlightQuote] = useState(null)
  const [activeCitationId, setActiveCitationId] = useState(null)
  const [mobilePreviewOpen, setMobilePreviewOpen] = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef       = useRef(null)

  // Sync messages to sessionStorage
  useEffect(() => {
    try {
      const toStore = messages.length > 100 ? messages.slice(-100) : messages
      sessionStorage.setItem('docagent_chat_messages', JSON.stringify(toStore))
    } catch {
      sessionStorage.removeItem('docagent_chat_messages')
    }
  }, [messages])

  // Re-subscribe to an in-flight ask request that was started before unmount
  useEffect(() => {
    if (!_pendingAsk) return
    let cancelled = false

    setIsLoading(true)
    _pendingAsk.finally(() => {
      if (cancelled) return
      // The promise handler already wrote the response to sessionStorage.
      // Re-read from there to pick up the latest messages.
      try {
        const stored = JSON.parse(sessionStorage.getItem('docagent_chat_messages') || '[]')
        setMessages(stored)
      } catch { /* best-effort */ }
      setIsLoading(false)
    })

    return () => { cancelled = true }
  }, [])

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // ── Clear chat ────────────────────────────────────────────────────────────
  const handleClearChat = () => {
    setMessages([])
    sessionStorage.removeItem('docagent_chat_messages')
  }

  // ── Send message ──────────────────────────────────────────────────────────
  const handleSend = async () => {
    if (!input.trim() || isLoading || !activeDoc) return

    const question = input.trim()
    setInput('')
    setHighlightQuote(null)
    setActiveCitationId(null)

    const userMsg = { role: 'user', content: question }
    setMessages(prev => [...prev, userMsg])
    setIsLoading(true)

    // Single-doc querying — only the active document
    const docIds = [activeDoc.doc_id]

    const allMsgs = [...messages, userMsg]
    const conversationHistory = allMsgs.slice(-10).map(m => ({
      role: m.role,
      content: m.content
    }))

    const t0 = performance.now()

    // Store the promise at module level so it survives unmount/remount.
    // The chain: API call → build message → persist to sessionStorage → return message.
    _pendingAsk = ask(question, docIds, conversationHistory)
      .then(res => {
        const ttft = ((performance.now() - t0) / 1000).toFixed(2)
        console.log(`⏱ TTFT (client round-trip): ${ttft}s`)
        return { role: 'assistant', content: res.answer, citations: res.citations }
      })
      .catch(() => {
        return { role: 'assistant', content: 'Sorry, something went wrong. Please try again.', citations: [] }
      })
      .then(msg => {
        // Persist to sessionStorage — works even if the component unmounted.
        try {
          const stored = JSON.parse(sessionStorage.getItem('docagent_chat_messages') || '[]')
          stored.push(msg)
          sessionStorage.setItem('docagent_chat_messages', JSON.stringify(stored.slice(-100)))
        } catch { /* best-effort */ }
        return msg
      })

    try {
      const msg = await _pendingAsk
      // Update React state (only effective if component is still mounted)
      setMessages(prev => [...prev, msg])
    } finally {
      _pendingAsk = null
      setIsLoading(false)
    }
  }

  const handleKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }

  // ── Citation click → jump preview + highlight ───────────────────────────────
  const handleCitationClick = (citation) => {
    setActiveCitationId(citation.chunk_id || null)

    // Only set highlight/page if we have the file blob for preview
    if (activeDoc?.file) {
      setHighlightQuote(citation.quote || null)
      if (citation.page) {
        setPreviewPage({ page: citation.page, ts: Date.now() })
      } else {
        setPreviewPage(null)
      }
    } else {
      setHighlightQuote(null)
      setPreviewPage(null)
    }

    // On mobile, auto-open the preview
    if (window.innerWidth <= 768) {
      setMobilePreviewOpen(true)
    }
  }

  const hasFileBlob = activeDoc?.file != null

  // ── Guard: no active document selected ────────────────────────────────────
  if (!activeDoc) {
    return (
      <div className="ask-no-docs">
        <div className="ask-no-docs-content">
          <FolderOpen size={40} strokeWidth={1} color="var(--accent-dim)" />
          <h2 className="ask-no-docs-title">No document selected</h2>
          <p className="ask-no-docs-text">
            Select a document from Your Documents to start asking questions, or upload a new one.
          </p>
          <div className="ask-no-docs-actions">
            <button className="ask-no-docs-btn" onClick={onNavigateToDocs}>
              Your Documents
            </button>
            <button className="ask-no-docs-btn ask-no-docs-btn--secondary" onClick={onNavigateToUpload}>
              Upload New
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="ask-workspace">
      {/* ── Chat area ──────────────────────────────────────────────────────── */}
      <div className="ask-chat-area">
        {/* Doc bar */}
        <div className="ask-doc-bar">
          <FileText size={13} />
          <span className="ask-doc-bar-name" title={activeDoc.doc_name}>
            {activeDoc.doc_name}
          </span>
          {!hasFileBlob && (
            <span className="ask-doc-bar-notice">No preview</span>
          )}
          {messages.length > 0 && (
            <button
              className="ask-clear-chat-btn"
              onClick={handleClearChat}
              title="Clear chat"
            >
              <Trash2 size={12} />
            </button>
          )}
        </div>

        {/* Messages */}
        <div className="ask-messages">
          {messages.length === 0 && (
            <div className="ask-empty">
              <MessageSquare size={40} strokeWidth={1} color="var(--accent-dim)" />
              <h2 className="ask-empty-title">Ask about {activeDoc.doc_name}</h2>
              <p className="ask-empty-text">
                Ask anything about this document. Answers come with exact citations.
              </p>
            </div>
          )}

          {messages.map((msg, i) => (
            <ChatMessage
              key={i}
              msg={msg}
              onCitationClick={handleCitationClick}
              activeCitationId={activeCitationId}
            />
          ))}

          {isLoading && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* Input bar */}
        <div className="ask-input-bar">
          <input
            ref={inputRef}
            className="ask-input"
            type="text"
            placeholder={`Ask a question about ${activeDoc.doc_name}…`}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            disabled={isLoading}
          />
          <button
            className="ask-send-btn"
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            aria-label="Send"
          >
            <Send size={16} />
          </button>
        </div>
      </div>

      {/* ── Preview panel — always visible ─────────────────────────────────── */}
      <div className={`ask-preview-panel${mobilePreviewOpen ? ' ask-preview-panel--open' : ''}`}>
        <div className="ask-preview-handle" />
        <button
          className="ask-preview-close"
          onClick={() => setMobilePreviewOpen(false)}
          aria-label="Close preview"
        >
          <X size={16} />
        </button>
        {hasFileBlob ? (
          <DocumentPreview
            file={activeDoc.file}
            externalPage={previewPage}
            highlightText={highlightQuote}
          />
        ) : (
          <div className="preview-library-notice">
            <FileText size={32} strokeWidth={1} color="var(--accent-dim)" />
            <p className="preview-library-title">{activeDoc.doc_name}</p>
            <p className="preview-library-text">
              Preview and citation highlighting are not available for library documents.
              <br />Re-upload this file on the Upload page to enable these features.
            </p>
          </div>
        )}
      </div>

      {/* ── Mobile FAB to toggle preview ──────────────────────────────────── */}
      <button
        className="ask-preview-fab"
        onClick={() => setMobilePreviewOpen(prev => !prev)}
        aria-label="Toggle document preview"
      >
        {mobilePreviewOpen ? <X size={20} /> : <Eye size={20} />}
      </button>
    </div>
  )
}
