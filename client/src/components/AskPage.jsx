import React, { useState, useRef, useEffect } from 'react'
import { MessageSquare, Send, FileText, Eye, X, Upload } from 'lucide-react'
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
export default function AskPage({ files, processedFiles, onNavigateToUpload }) {
  const [messages, setMessages]             = useState([])
  const [input, setInput]                   = useState('')
  const [isLoading, setIsLoading]           = useState(false)
  const [previewDocId, setPreviewDocId]     = useState(null)
  const [previewPage, setPreviewPage]       = useState(null)
  const [highlightQuote, setHighlightQuote] = useState(null)
  const [activeCitationId, setActiveCitationId] = useState(null)
  const [mobilePreviewOpen, setMobilePreviewOpen] = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef       = useRef(null)

  // Default preview to first processed file
  useEffect(() => {
    if (!previewDocId && processedFiles.length > 0) {
      setPreviewDocId(processedFiles[0].docId)
    }
  }, [processedFiles, previewDocId])

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // ── Send message ──────────────────────────────────────────────────────────
  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const question = input.trim()
    setInput('')
    setHighlightQuote(null)
    setActiveCitationId(null)

    const userMsg = { role: 'user', content: question }
    setMessages(prev => [...prev, userMsg])
    setIsLoading(true)

    const docIds = processedFiles.map(f => f.docId)

    try {
      // Build conversation history from last 10 messages
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
    const fileEntry = files.find(f => f.docId === citation.doc_id)
    if (!fileEntry) return

    setPreviewDocId(citation.doc_id)
    setHighlightQuote(citation.quote || null)
    setActiveCitationId(citation.chunk_id || null)

    if (citation.page) {
      setPreviewPage({ page: citation.page, ts: Date.now() })
    } else {
      setPreviewPage(null)
    }

    // On mobile, auto-open the preview
    if (window.innerWidth <= 768) {
      setMobilePreviewOpen(true)
    }
  }

  // Find the File object for the current preview
  const previewFile = files.find(f => f.docId === previewDocId)

  // ── Guard: no processed docs ──────────────────────────────────────────────
  if (processedFiles.length === 0) {
    return (
      <div className="ask-no-docs">
        <div className="ask-no-docs-content">
          <Upload size={40} strokeWidth={1} color="var(--accent-dim)" />
          <h2 className="ask-no-docs-title">No documents processed</h2>
          <p className="ask-no-docs-text">
            Upload and process your documents first, then come back to ask questions.
          </p>
          <button className="ask-no-docs-btn" onClick={onNavigateToUpload}>
            Go to Upload
          </button>
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
          <span>Querying {processedFiles.length} document{processedFiles.length !== 1 ? 's' : ''}</span>
        </div>

        {/* Messages */}
        <div className="ask-messages">
          {messages.length === 0 && (
            <div className="ask-empty">
              <MessageSquare size={40} strokeWidth={1} color="var(--accent-dim)" />
              <h2 className="ask-empty-title">Ask your documents</h2>
              <p className="ask-empty-text">
                Ask anything about your {processedFiles.length} processed document{processedFiles.length !== 1 ? 's' : ''}.
                Answers come with exact citations.
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
            placeholder="Ask a question about your documents…"
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
        {previewFile ? (
          <DocumentPreview
            file={previewFile.file}
            externalPage={previewPage}
            highlightText={highlightQuote}
          />
        ) : (
          <div className="ask-preview-empty">
            <FileText size={32} strokeWidth={1} color="var(--accent-dim)" />
            <p>Document preview</p>
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
