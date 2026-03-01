import React, { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react'

// ── Shared sub-components ──────────────────────────────────────────────────────
function LoadingState({ label }) {
  return (
    <div className="preview-center">
      <div className="preview-spinner" />
      <p className="preview-loading-label">{label}</p>
    </div>
  )
}

function ErrorState({ message }) {
  return (
    <div className="preview-center">
      <p className="preview-error-label">{message}</p>
    </div>
  )
}

// ── PDF Preview ────────────────────────────────────────────────────────────────
function PdfPreview({ file, externalPage }) {
  const canvasRef  = useRef(null)
  const [pdf, setPdf]           = useState(null)
  const [page, setPage]         = useState(1)
  const [numPages, setNumPages] = useState(0)
  const [scale, setScale]       = useState(1.2)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  // Jump to page when citation is clicked externally
  useEffect(() => {
    if (externalPage?.page != null && externalPage.page >= 1 && externalPage.page <= numPages) {
      setPage(externalPage.page)
    }
  }, [externalPage, numPages])

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null); setPage(1)

    async function loadPdf() {
      try {
        const pdfjsLib = await import('pdfjs-dist')
        pdfjsLib.GlobalWorkerOptions.workerSrc =
          `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.mjs`
        const buf = await file.arrayBuffer()
        const doc = await pdfjsLib.getDocument({ data: buf }).promise
        if (cancelled) return
        setPdf(doc); setNumPages(doc.numPages); setLoading(false)
      } catch (e) {
        if (!cancelled) { setError('Failed to load PDF: ' + e.message); setLoading(false) }
      }
    }
    loadPdf()
    return () => { cancelled = true }
  }, [file])

  useEffect(() => {
    if (!pdf || !canvasRef.current) return
    let cancelled = false

    async function renderPage() {
      try {
        const pdfPage  = await pdf.getPage(page)
        if (cancelled) return
        const viewport = pdfPage.getViewport({ scale })
        const canvas   = canvasRef.current
        const ctx      = canvas.getContext('2d')
        canvas.height  = viewport.height
        canvas.width   = viewport.width
        await pdfPage.render({ canvasContext: ctx, viewport }).promise
      } catch (e) {
        if (!cancelled) setError('Render error: ' + e.message)
      }
    }
    renderPage()
    return () => { cancelled = true }
  }, [pdf, page, scale])

  const zoom = (d) => setScale(s => Math.min(3, Math.max(0.5, +(s + d).toFixed(1))))

  if (loading) return <LoadingState label="Rendering PDF…" />
  if (error)   return <ErrorState  message={error} />

  return (
    <div className="pdf-wrap">
      <div className="pdf-toolbar">
        <div className="pdf-tool-group">
          <button className="pdf-tool-btn" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>
            <ChevronLeft size={15} />
          </button>
          <span className="pdf-page-label">
            <span className="pdf-page-current">{page}</span>
            {' / ' + numPages}
          </span>
          <button className="pdf-tool-btn" onClick={() => setPage(p => Math.min(numPages, p + 1))} disabled={page >= numPages}>
            <ChevronRight size={15} />
          </button>
        </div>
        <div className="pdf-tool-group">
          <button className="pdf-tool-btn" onClick={() => zoom(-0.2)}><ZoomOut size={14} /></button>
          <span className="pdf-zoom-label">{Math.round(scale * 100)}%</span>
          <button className="pdf-tool-btn" onClick={() => zoom(0.2)}><ZoomIn size={14} /></button>
          <button className="pdf-tool-btn" onClick={() => { setScale(1.2); setPage(1) }}><RotateCcw size={13} /></button>
        </div>
      </div>
      <div className="pdf-canvas-scroll">
        <canvas ref={canvasRef} className="pdf-canvas" />
      </div>
    </div>
  )
}

// ── DOCX Preview ───────────────────────────────────────────────────────────────
function DocxPreview({ file }) {
  const [html, setHtml]       = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    let cancelled = false
    async function convert() {
      try {
        const mammoth  = await import('mammoth')
        const buf      = await file.arrayBuffer()
        const result   = await mammoth.convertToHtml({ arrayBuffer: buf })
        if (!cancelled) { setHtml(result.value); setLoading(false) }
      } catch (e) {
        if (!cancelled) { setError('Failed to parse DOCX: ' + e.message); setLoading(false) }
      }
    }
    convert()
    return () => { cancelled = true }
  }, [file])

  if (loading) return <LoadingState label="Parsing document…" />
  if (error)   return <ErrorState  message={error} />

  return (
    <div className="docx-scroll">
      <div className="docx-body" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  )
}

// ── TXT / MD Preview ───────────────────────────────────────────────────────────
function TextPreview({ file }) {
  const [text, setText]       = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const reader = new FileReader()
    reader.onload = e => { setText(e.target.result); setLoading(false) }
    reader.readAsText(file)
  }, [file])

  if (loading) return <LoadingState label="Reading file…" />

  return (
    <div className="text-scroll">
      <pre className="text-body">{text}</pre>
    </div>
  )
}

// ── Main export ────────────────────────────────────────────────────────────────
export default function DocumentPreview({ file, externalPage }) {
  if (!file) return null
  const ext = file.name.split('.').pop().toLowerCase()

  return (
    <div className="preview-wrap">
      <div className="preview-header">
        <span className="preview-title">{file.name}</span>
        <span className="preview-ext-badge">{ext.toUpperCase()}</span>
      </div>
      <div className="preview-content">
        {ext === 'pdf'                    && <PdfPreview  file={file} externalPage={externalPage} />}
        {ext === 'docx'                   && <DocxPreview file={file} />}
        {(ext === 'txt' || ext === 'md')  && <TextPreview file={file} />}
      </div>
    </div>
  )
}
