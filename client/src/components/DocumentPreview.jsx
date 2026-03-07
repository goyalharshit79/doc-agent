import React, { useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  RotateCcw,
} from "lucide-react";

// ── Shared sub-components ──────────────────────────────────────────────────────
function LoadingState({ label }) {
  return (
    <div className="preview-center">
      <div className="preview-spinner" />
      <p className="preview-loading-label">{label}</p>
    </div>
  );
}

function ErrorState({ message }) {
  return (
    <div className="preview-center">
      <p className="preview-error-label">{message}</p>
    </div>
  );
}

// ── Highlight helpers ───────────────────────────────────────────────────────────

/** Collapse whitespace → single space, trim, lowercase. */
function normalize(str) {
  return str.replace(/\s+/g, " ").trim().toLowerCase();
}

/**
 * Strip Markdown / HTML formatting that the parser adds to chunk text,
 * so the search query looks closer to the original document text.
 */
function stripMarkdown(text) {
  return text
    .replace(/<[^>]+>/g, "")                 // HTML tags
    .replace(/^#{1,6}\s+/gm, "")             // Markdown headings
    .replace(/^\s*[-*+]\s+/gm, "")           // List markers
    .replace(/\*\*(.+?)\*\*/g, "$1")         // Bold
    .replace(/\*(.+?)\*/g, "$1")             // Italic
    .replace(/`{1,3}[^`]*`{1,3}/g, "")       // Code blocks / inline code
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // Links [text](url) → text
    .replace(/^>\s?/gm, "")                  // Blockquotes
    .trim();
}

/**
 * Normalize a string and build a character-level map from normalized indices
 * back to original indices, so highlights land on the exact right characters.
 * (Replaces the old proportional-ratio approximation which was inaccurate.)
 */
function normalizeWithMap(str) {
  const map = [];  // map[normalizedIndex] = originalIndex
  let normalized = "";
  let inSpace = false;
  let started = false;

  for (let i = 0; i < str.length; i++) {
    const ch = str[i];
    if (/\s/.test(ch)) {
      if (started && !inSpace) {
        map.push(i);
        normalized += " ";
        inSpace = true;
      }
    } else {
      map.push(i);
      normalized += ch.toLowerCase();
      inSpace = false;
      started = true;
    }
  }

  // Trim trailing space
  if (normalized.endsWith(" ")) {
    normalized = normalized.slice(0, -1);
    map.pop();
  }

  return { normalized, map };
}

/**
 * Remove all highlight elements from a container.
 */
function clearHighlights(container) {
  if (!container) return;
  container.querySelectorAll(".citation-highlight").forEach((mark) => {
    const parent = mark.parentNode;
    mark.replaceWith(document.createTextNode(mark.textContent));
    parent?.normalize();
  });
}

/**
 * Given a DOM container, find the citation text in its text nodes,
 * wrap the matching range in <mark class="citation-highlight">,
 * and return the first <mark> element for scrolling.
 *
 * Improvements over the original:
 *  - Strips Markdown formatting from the query before searching
 *  - Uses a character-level map instead of proportional ratio
 *  - Progressive fallback: tries full text, then shorter prefixes
 */
function highlightInTextNodes(container, query) {
  if (!query || !container) return null;

  // Strip Markdown so "## Heading\n\n- item" becomes "Heading item"
  const cleaned = stripMarkdown(query);
  const searchText = normalize(cleaned).slice(0, 300);
  if (!searchText || searchText.length < 8) return null;

  // Collect text nodes from the DOM
  const walker = document.createTreeWalker(
    container,
    NodeFilter.SHOW_TEXT,
    null,
  );
  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) textNodes.push(node);
  if (!textNodes.length) return null;

  // Build concatenated text from all text nodes
  let fullText = "";
  const entries = [];
  for (const tn of textNodes) {
    entries.push({ node: tn, start: fullText.length });
    fullText += tn.textContent;
  }

  // Normalize with character-level index map
  const { normalized: normalizedFull, map } = normalizeWithMap(fullText);

  // Progressive matching — try full query, then shorter prefixes
  // until we find a match (handles partial page overlaps, minor differences)
  let matchIdx = -1;
  let matchLen = 0;
  const minLen = Math.min(30, searchText.length);

  for (
    let len = searchText.length;
    len >= minLen;
    len = Math.floor(len * 0.7)
  ) {
    const sub = searchText.slice(0, len);
    const idx = normalizedFull.indexOf(sub);
    if (idx !== -1) {
      matchIdx = idx;
      matchLen = sub.length;
      break;
    }
  }

  if (matchIdx === -1) return null;

  // Translate normalized indices → original text indices via the map
  const origStart = map[matchIdx];
  const origEnd =
    matchIdx + matchLen < map.length
      ? map[matchIdx + matchLen]
      : fullText.length;

  let firstMark = null;

  // Walk entries in reverse to avoid index shifts when wrapping
  for (let i = entries.length - 1; i >= 0; i--) {
    const { node: tn, start } = entries[i];
    const nodeEnd = start + tn.textContent.length;

    if (nodeEnd <= origStart || start >= origEnd) continue;

    const overlapStart = Math.max(0, origStart - start);
    const overlapEnd = Math.min(tn.textContent.length, origEnd - start);

    try {
      const range = document.createRange();
      range.setStart(tn, overlapStart);
      range.setEnd(tn, overlapEnd);
      const mark = document.createElement("mark");
      mark.className = "citation-highlight";
      range.surroundContents(mark);
      firstMark = mark;
    } catch (e) {
      // surroundContents can fail if range crosses element boundaries
      console.warn("Highlight range failed:", e);
    }
  }

  return firstMark;
}

// ── PDF Preview ────────────────────────────────────────────────────────────────
function PdfPreview({ file, externalPage, highlightText }) {
  const canvasRef = useRef(null);
  const textLayerRef = useRef(null);
  const [pdf, setPdf] = useState(null);
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [renderKey, setRenderKey] = useState(0); // toggled after text layer renders

  // Jump to page when citation is clicked externally
  useEffect(() => {
    if (
      externalPage?.page != null &&
      externalPage.page >= 1 &&
      externalPage.page <= numPages
    ) {
      setPage(externalPage.page);
    }
  }, [externalPage, numPages]);

  // Load PDF
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPage(1);

    async function loadPdf() {
      try {
        const pdfjsLib = await import("pdfjs-dist");
        pdfjsLib.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.mjs`;
        const buf = await file.arrayBuffer();
        const doc = await pdfjsLib.getDocument({ data: buf }).promise;
        if (cancelled) return;
        setPdf(doc);
        setNumPages(doc.numPages);
        setLoading(false);
      } catch (e) {
        if (!cancelled) {
          setError("Failed to load PDF: " + e.message);
          setLoading(false);
        }
      }
    }
    loadPdf();
    return () => {
      cancelled = true;
    };
  }, [file]);

  // Render page canvas + pdfjs text layer (like Ctrl+F in PDF viewers)
  useEffect(() => {
    if (!pdf || !canvasRef.current) return;
    let cancelled = false;

    async function render() {
      try {
        const pdfjsLib = await import("pdfjs-dist");
        const pdfPage = await pdf.getPage(page);
        if (cancelled) return;
        const viewport = pdfPage.getViewport({ scale });

        // ── Canvas ──
        const canvas = canvasRef.current;
        const ctx = canvas.getContext("2d");
        canvas.height = viewport.height;
        canvas.width = viewport.width;
        await pdfPage.render({ canvasContext: ctx, viewport }).promise;

        // ── Text layer — invisible spans positioned over canvas text ──
        const tlDiv = textLayerRef.current;
        if (tlDiv && !cancelled) {
          tlDiv.innerHTML = "";
          tlDiv.style.width = `${viewport.width}px`;
          tlDiv.style.height = `${viewport.height}px`;

          const textContent = await pdfPage.getTextContent();
          if (cancelled) return;

          // pdfjs v4 TextLayer class
          if (pdfjsLib.TextLayer) {
            const tl = new pdfjsLib.TextLayer({
              textContentSource: textContent,
              container: tlDiv,
              viewport,
            });
            await tl.render();
          } else if (pdfjsLib.renderTextLayer) {
            // pdfjs v3 fallback
            await pdfjsLib.renderTextLayer({
              textContent,
              container: tlDiv,
              viewport,
              textDivs: [],
            }).promise;
          }

          // Signal text layer ready → triggers highlight effect
          setRenderKey((k) => k + 1);
        }
      } catch (e) {
        if (!cancelled) setError("Render error: " + e.message);
      }
    }
    render();
    return () => {
      cancelled = true;
    };
  }, [pdf, page, scale]);

  // ── Highlight: search through text layer spans for the citation quote ──
  useEffect(() => {
    const tlDiv = textLayerRef.current;
    if (!tlDiv) return;

    clearHighlights(tlDiv);
    if (!highlightText) return;

    const firstMark = highlightInTextNodes(tlDiv, highlightText);
    if (firstMark) {
      firstMark.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightText, renderKey]);

  const zoom = (d) =>
    setScale((s) => Math.min(3, Math.max(0.5, +(s + d).toFixed(1))));

  if (loading) return <LoadingState label="Rendering PDF…" />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="pdf-wrap">
      <div className="pdf-toolbar">
        <div className="pdf-tool-group">
          <button
            className="pdf-tool-btn"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            <ChevronLeft size={15} />
          </button>
          <span className="pdf-page-label">
            <span className="pdf-page-current">{page}</span>
            {" / " + numPages}
          </span>
          <button
            className="pdf-tool-btn"
            onClick={() => setPage((p) => Math.min(numPages, p + 1))}
            disabled={page >= numPages}
          >
            <ChevronRight size={15} />
          </button>
        </div>
        <div className="pdf-tool-group">
          <button className="pdf-tool-btn" onClick={() => zoom(-0.2)}>
            <ZoomOut size={14} />
          </button>
          <span className="pdf-zoom-label">{Math.round(scale * 100)}%</span>
          <button className="pdf-tool-btn" onClick={() => zoom(0.2)}>
            <ZoomIn size={14} />
          </button>
          <button
            className="pdf-tool-btn"
            onClick={() => {
              setScale(1.2);
              setPage(1);
            }}
          >
            <RotateCcw size={13} />
          </button>
        </div>
      </div>
      <div className="pdf-canvas-scroll">
        <div className="pdf-page-container">
          <canvas ref={canvasRef} className="pdf-canvas" />
          <div ref={textLayerRef} className="textLayer" />
        </div>
      </div>
    </div>
  );
}

// ── DOCX Preview ───────────────────────────────────────────────────────────────
function DocxPreview({ file, highlightText }) {
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const bodyRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    async function convert() {
      try {
        const mammoth = await import("mammoth");
        const buf = await file.arrayBuffer();
        const result = await mammoth.convertToHtml({ arrayBuffer: buf });
        if (!cancelled) {
          setHtml(result.value);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError("Failed to parse DOCX: " + e.message);
          setLoading(false);
        }
      }
    }
    convert();
    return () => {
      cancelled = true;
    };
  }, [file]);

  // Highlight quote in DOCX HTML
  useEffect(() => {
    if (!bodyRef.current || loading) return;

    clearHighlights(bodyRef.current);
    if (!highlightText) return;

    const firstMark = highlightInTextNodes(bodyRef.current, highlightText);
    if (firstMark) {
      firstMark.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightText, html, loading]);

  if (loading) return <LoadingState label="Parsing document…" />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="docx-scroll">
      <div
        className="docx-body"
        ref={bodyRef}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

// ── TXT / MD Preview ───────────────────────────────────────────────────────────
function TextPreview({ file, highlightText }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const highlightRef = useRef(null);

  useEffect(() => {
    const reader = new FileReader();
    reader.onload = (e) => {
      setText(e.target.result);
      setLoading(false);
    };
    reader.readAsText(file);
  }, [file]);

  // Scroll to highlight after render
  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
  }, [highlightText, text]);

  if (loading) return <LoadingState label="Reading file…" />;

  // Build highlighted content
  const renderContent = () => {
    if (!highlightText || !text) return text;

    // Strip Markdown formatting and normalize
    const cleaned = stripMarkdown(highlightText);
    const searchText = normalize(cleaned).slice(0, 300);
    if (!searchText || searchText.length < 8) return text;

    // Normalize with character-level map for accurate positioning
    const { normalized: normalizedFull, map } = normalizeWithMap(text);

    // Progressive matching — try full text, then shorter prefixes
    let matchIdx = -1;
    let matchLen = 0;
    const minLen = Math.min(30, searchText.length);

    for (
      let len = searchText.length;
      len >= minLen;
      len = Math.floor(len * 0.7)
    ) {
      const sub = searchText.slice(0, len);
      const idx = normalizedFull.indexOf(sub);
      if (idx !== -1) {
        matchIdx = idx;
        matchLen = sub.length;
        break;
      }
    }

    if (matchIdx === -1) return text;

    const origStart = map[matchIdx];
    const origEnd =
      matchIdx + matchLen < map.length
        ? map[matchIdx + matchLen]
        : text.length;

    return (
      <>
        {text.slice(0, origStart)}
        <mark ref={highlightRef} className="citation-highlight">
          {text.slice(origStart, origEnd)}
        </mark>
        {text.slice(origEnd)}
      </>
    );
  };

  return (
    <div className="text-scroll">
      <pre className="text-body">{renderContent()}</pre>
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────────
export default function DocumentPreview({ file, externalPage, highlightText }) {
  if (!file) return null;
  const ext = file.name.split(".").pop().toLowerCase();

  return (
    <div className="preview-wrap">
      <div className="preview-header">
        <span className="preview-title">{file.name}</span>
        <span className="preview-ext-badge">{ext.toUpperCase()}</span>
      </div>
      <div className="preview-content">
        {ext === "pdf" && (
          <PdfPreview
            file={file}
            externalPage={externalPage}
            highlightText={highlightText}
          />
        )}
        {ext === "docx" && (
          <DocxPreview file={file} highlightText={highlightText} />
        )}
        {(ext === "txt" || ext === "md") && (
          <TextPreview file={file} highlightText={highlightText} />
        )}
      </div>
    </div>
  );
}
