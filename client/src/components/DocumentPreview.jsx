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

// ── Highlight helpers ───────────────────────────────────────────────────────────

/**
 * Normalize whitespace for fuzzy text matching:
 *   collapse runs of whitespace → single space, trim, lowercase.
 */
function normalize(str) {
  return str.replace(/\s+/g, ' ').trim().toLowerCase()
}

/**
 * Given an array of DOM text-containing elements (spans or text nodes),
 * find the first occurrence of `query` in their concatenated text and
 * wrap matching portions in <mark class="citation-highlight">.
 *
 * Returns the first <mark> element created (for scroll-into-view), or null.
 */
function highlightInNodes(nodes, getText, query) {
  if (!query) return null

  // Use first ~120 chars of query for matching (quotes can be very long chunks)
  const searchText = normalize(query).slice(0, 120)
  if (!searchText) return null

  // Build concatenated text + offset map
  let fullText = ''
  const entries = []
  for (const node of nodes) {
    const text = getText(node)
    entries.push({ node, start: fullText.length, text })
    fullText += text
  }

  const normalizedFull = normalize(fullText)
  const matchIdx = normalizedFull.indexOf(searchText)
  if (matchIdx === -1) return null

  // Map normalized index back to original positions.
  // Build a mapping: normalized char index → original char index
  const origText = entries.map(e => e.text).join('')
  const normToOrig = []
  let oi = 0
  for (let ni = 0; ni < normalizedFull.length; ni++) {
    // Skip extra whitespace in original
    while (oi < origText.length && origText[oi] !== normalizedFull[ni] &&
           /\s/.test(origText[oi]) && /\s/.test(normalizedFull[ni])) {
      oi++
    }
    if (oi < origText.length && origText[oi].toLowerCase() === normalizedFull[ni]) {
      normToOrig.push(oi)
      oi++
    } else {
      normToOrig.push(oi)
    }
  }

  const origStart = normToOrig[matchIdx] || 0
  const origEnd = (normToOrig[matchIdx + searchText.length - 1] || origStart) + 1

  let firstMark = null

  // Walk entries in reverse so DOM mutations don't shift later indices
  for (let i = entries.length - 1; i >= 0; i--) {
    const { node, start, text } = entries[i]
    const nodeEnd = start + text.length

    // Skip nodes outside the match range
    if (nodeEnd <= origStart || start >= origEnd) continue

    const overlapStart = Math.max(0, origStart - start)
    const overlapEnd = Math.min(text.length, origEnd - start)

    // Create mark element
    const mark = document.createElement('mark')
    mark.className = 'citation-highlight'
    mark.textContent = text.slice(overlapStart, overlapEnd)

    // For text layer spans: replace the span's content by splitting
    if (node.nodeType === Node.TEXT_NODE) {
      // Split text node and insert mark
      const afterNode = node.splitText(overlapStart)
      afterNode.textContent = afterNode.textContent.slice(overlapEnd - overlapStart)
      node.parentNode.insertBefore(mark, afterNode)
    } else {
      // It's an element (like a text layer <span>): manipulate innerHTML
      const before = text.slice(0, overlapStart)
      const after = text.slice(overlapEnd)
      node.textContent = ''
      if (before) node.appendChild(document.createTextNode(before))
      node.appendChild(mark)
      if (after) node.appendChild(document.createTextNode(after))
    }

    firstMark = mark
  }

  return firstMark
}

/**
 * Remove all <mark class="citation-highlight"> from a container,
 * restoring the original text.
 */
function clearHighlights(container) {
  if (!container) return
  container.querySelectorAll('.citation-highlight').forEach(mark => {
    const parent = mark.parentNode
    mark.replaceWith(document.createTextNode(mark.textContent))
    parent?.normalize()
  })
}


// ── PDF Preview ────────────────────────────────────────────────────────────────
function PdfPreview({ file, externalPage, highlightText }) {
  const canvasRef     = useRef(null)
  const textLayerRef  = useRef(null)
  const scrollRef     = useRef(null)
  const [pdf, setPdf]               = useState(null)
  const [page, setPage]             = useState(1)
  const [numPages, setNumPages]     = useState(0)
  const [scale, setScale]           = useState(1.2)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [textLayerReady, setTextLayerReady] = useState(0)

  // Jump to page when citation is clicked externally
  useEffect(() => {
    if (externalPage?.page != null && externalPage.page >= 1 && externalPage.page <= numPages) {
      setPage(externalPage.page)
    }
  }, [externalPage, numPages])

  // Load PDF
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

  // Render page canvas + text layer
  useEffect(() => {
    if (!pdf || !canvasRef.current) return
    let cancelled = false

    async function renderPage() {
      try {
        const pdfPage  = await pdf.getPage(page)
        if (cancelled) return
        const viewport = pdfPage.getViewport({ scale })

        // ── Canvas ──
        const canvas = canvasRef.current
        const ctx    = canvas.getContext('2d')
        canvas.height = viewport.height
        canvas.width  = viewport.width
        await pdfPage.render({ canvasContext: ctx, viewport }).promise

        // ── Text layer ──
        if (textLayerRef.current) {
          const pdfjsLib = await import('pdfjs-dist')
          const textContent = await pdfPage.getTextContent()
          if (cancelled) return

          const tlDiv = textLayerRef.current
          tlDiv.innerHTML = ''
          tlDiv.style.width  = viewport.width + 'px'
          tlDiv.style.height = viewport.height + 'px'

          const tl = new pdfjsLib.TextLayer({
            textContentSource: textContent,
            container: tlDiv,
            viewport,
          })
          await tl.render()
          if (!cancelled) setTextLayerReady(prev => prev + 1)
        }
      } catch (e) {
        if (!cancelled) setError('Render error: ' + e.message)
      }
    }
    renderPage()
    return () => { cancelled = true }
  }, [pdf, page, scale])

  // Highlight text in text layer
  useEffect(() => {
    const tlDiv = textLayerRef.current
    if (!tlDiv) return

    clearHighlights(tlDiv)
    if (!highlightText) return

    const spans = Array.from(tlDiv.querySelectorAll('span'))
    if (!spans.length) return

    const firstMark = highlightInNodes(spans, s => s.textContent, highlightText)
    if (firstMark) {
      firstMark.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [highlightText, textLayerReady])

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
      <div className="pdf-canvas-scroll" ref={scrollRef}>
        <div className="pdf-page-container">
          <canvas ref={canvasRef} className="pdf-canvas" />
          <div ref={textLayerRef} className="textLayer" />
        </div>
      </div>
    </div>
  )
}

// ── DOCX Preview ───────────────────────────────────────────────────────────────
function DocxPreview({ file, highlightText }) {
  const [html, setHtml]       = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const bodyRef = useRef(null)

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

  // Highlight quote in DOCX HTML
  useEffect(() => {
    if (!bodyRef.current || loading) return

    clearHighlights(bodyRef.current)
    if (!highlightText) return

    // Collect all text nodes via TreeWalker
    const walker = document.createTreeWalker(bodyRef.current, NodeFilter.SHOW_TEXT, null)
    const textNodes = []
    let node
    while ((node = walker.nextNode())) {
      textNodes.push(node)
    }
    if (!textNodes.length) return

    const firstMark = highlightInNodes(textNodes, n => n.textContent, highlightText)
    if (firstMark) {
      firstMark.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [highlightText, html, loading])

  if (loading) return <LoadingState label="Parsing document…" />
  if (error)   return <ErrorState  message={error} />

  return (
    <div className="docx-scroll">
      <div className="docx-body" ref={bodyRef} dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  )
}

// ── TXT / MD Preview ───────────────────────────────────────────────────────────
function TextPreview({ file, highlightText }) {
  const [text, setText]       = useState('')
  const [loading, setLoading] = useState(true)
  const highlightRef = useRef(null)

  useEffect(() => {
    const reader = new FileReader()
    reader.onload = e => { setText(e.target.result); setLoading(false) }
    reader.readAsText(file)
  }, [file])

  // Scroll to highlight after render
  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [highlightText, text])

  if (loading) return <LoadingState label="Reading file…" />

  // Build highlighted content
  const renderContent = () => {
    if (!highlightText || !text) return text

    const searchText = normalize(highlightText).slice(0, 120)
    if (!searchText) return text

    const normalizedFull = normalize(text)
    const idx = normalizedFull.indexOf(searchText)
    if (idx === -1) return text

    // Map normalized index back to original text position
    const normToOrig = []
    let oi = 0
    for (let ni = 0; ni < normalizedFull.length; ni++) {
      while (oi < text.length && text[oi] !== normalizedFull[ni] &&
             /\s/.test(text[oi]) && /\s/.test(normalizedFull[ni])) {
        oi++
      }
      if (oi < text.length && text[oi].toLowerCase() === normalizedFull[ni]) {
        normToOrig.push(oi)
        oi++
      } else {
        normToOrig.push(oi)
      }
    }

    const origStart = normToOrig[idx] || 0
    const origEnd = (normToOrig[idx + searchText.length - 1] || origStart) + 1

    return (
      <>
        {text.slice(0, origStart)}
        <mark ref={highlightRef} className="citation-highlight">
          {text.slice(origStart, origEnd)}
        </mark>
        {text.slice(origEnd)}
      </>
    )
  }

  return (
    <div className="text-scroll">
      <pre className="text-body">{renderContent()}</pre>
    </div>
  )
}

// ── Main export ────────────────────────────────────────────────────────────────
export default function DocumentPreview({ file, externalPage, highlightText }) {
  if (!file) return null
  const ext = file.name.split('.').pop().toLowerCase()

  return (
    <div className="preview-wrap">
      <div className="preview-header">
        <span className="preview-title">{file.name}</span>
        <span className="preview-ext-badge">{ext.toUpperCase()}</span>
      </div>
      <div className="preview-content">
        {ext === 'pdf'                    && <PdfPreview  file={file} externalPage={externalPage} highlightText={highlightText} />}
        {ext === 'docx'                   && <DocxPreview file={file} highlightText={highlightText} />}
        {(ext === 'txt' || ext === 'md')  && <TextPreview file={file} highlightText={highlightText} />}
      </div>
    </div>
  )
}
