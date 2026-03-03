import React, { useState, useRef, useEffect } from 'react'
import { MessageSquare, Send, FileText, Eye, X, Upload, Trash2, FolderOpen } from 'lucide-react'
import { ask } from '../api'
import DocumentPreview from './DocumentPreview'

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
        <p className="chat-msg-text">{msg.content}</p>
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
  const [isLoading, setIsLoading]           = useState(false)
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

    try {
      const allMsgs = [...messages, userMsg]
      const conversationHistory = allMsgs.slice(-10).map(m => ({
        role: m.role,
        content: m.content
      }))

      const res = await ask(question, docIds, conversationHistory)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: res.answer,
        citations: res.citations
      }])
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Sorry, something went wrong: ${err.message}`,
        citations: []
      }])
    } finally {
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
