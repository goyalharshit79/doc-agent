import React, {
  useState,
  useRef,
  useCallback,
  useEffect,
  useInsertionEffect,
} from "react";
import {
  Menu,
  X,
  BookOpen,
  FileOutput,
  PanelLeft,
  ChevronLeft,
  FolderOpen,
} from "lucide-react";
import AuthPage from "./components/AuthPage";
import UploadZone from "./components/UploadZone";
import FileList from "./components/FileList";
import DocumentPreview from "./components/DocumentPreview";
import AskPage from "./components/AskPage";
import YourDocuments from "./components/YourDocuments";
import { uploadDocument } from "./api";
import { get, set, del } from "idb-keyval";

// ── Placeholder pages for upcoming features ──────────────────────────────────
const PAGE_ICONS = { study: BookOpen, extract: FileOutput };

function PlaceholderPage({ page }) {
  const Icon = PAGE_ICONS[page];
  return (
    <div className="placeholder-page">
      <div className="placeholder-content">
        {Icon && <Icon size={48} strokeWidth={1} color="var(--accent-dim)" />}
        <h2 className="placeholder-title">
          {page.charAt(0).toUpperCase() + page.slice(1)}
        </h2>
        <p className="placeholder-subtitle">Coming soon</p>
      </div>
    </div>
  );
}

// ── Nav pages ────────────────────────────────────────────────────────────────
const PAGES = ["upload", "documents", "ask", "study", "extract"];

export default function App() {
  // ── Auth state ─────────────────────────────────────────────────────────────
  const storedToken = localStorage.getItem("docagent_token");

  const [user, setUser] = useState(storedToken ? { token: storedToken } : null);

  const handleAuth = (userData) => setUser(userData);

  // ── Navigation state ───────────────────────────────────────────────────────
  // const pageOn = localStorage.getItem("activePage");
  const [activePage, setActivePage] = useState(
    localStorage.activePage ? JSON.parse(localStorage.activePage) : "upload",
  );
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Sync state back to localStorage to keep page navigation persistent even on reload
  useEffect(() => {
    localStorage.setItem("activePage", JSON.stringify(activePage));
  }, [activePage]);


  // ── File state (session files only — uploaded in this session) ─────────────
  const [files, setFiles] = useState(() => {
    const saved = localStorage.getItem("docagent_file_meta");
    return saved ? JSON.parse(saved) : [];
  });
  const [activeIndex, setActiveIndex] = useState(0);
  const [docType, setDocType] = useState("general");
  const [isProcessing, setIsProcessing] = useState(false);
  const addInputRef = useRef(null);
  const filesRef = useRef(files);
  filesRef.current = files;

  //document persistence through refreshes
  // 2. Save lightweight metadata to localStorage on ANY state change (Instant/Safe)
  useEffect(() => {
    const metadataOnly = files.map(({ file, ...rest }) => rest);
    localStorage.setItem("docagent_file_meta", JSON.stringify(metadataOnly));
  }, [files]);

  // 3. ASYNC REHYDRATION: Fetch the heavy binary files from IndexedDB ONCE on mount
  useEffect(() => {
    async function attachBinaryFiles() {
      // If we have files in state, but the first one is missing its binary 'file' object
      if (files.length > 0 && !files[0].file) {
        const rehydrated = await Promise.all(
          files.map(async (meta) => {
            try {
              // Fetch individually by filename
              const binaryFile = await get(`docagent_file_${meta.fileName}`);
              return { ...meta, file: binaryFile || null };
            } catch {
              return meta;
            }
          }),
        );
        setFiles(rehydrated);
      }
    }
    attachBinaryFiles();
  }, []); // Run on mount

  // ── Active document for Ask page (single-doc querying) ────────────────────
  // { doc_id, doc_name, doc_type, num_chunks, file?: File }
  const [activeDoc, setActiveDoc] = useState(
    //if meta data there in localstorage put in the activeDoc
    localStorage.activeDoc ? JSON.parse(localStorage.activeDoc) : null,
  );

  //when activeDoc changes, put the new activeDoc Meta data into the localstorage
  useEffect(() => {
    activeDoc &&
      localStorage.setItem(
        "activeDoc",
        JSON.stringify({
          doc_id: activeDoc.doc_id,
          doc_name: activeDoc.doc_name,
          doc_type: activeDoc.doc_type,
          num_chunks: activeDoc.num_chunks,
          file: null,
        }),
      );
  }, [activeDoc]);

  //on mount/reload, check if the filebinary is available in the files useState, which checks with the IndexDb and then when the files state changes, this useEffect is called
  useEffect(() => {
    if (localStorage.activeDoc) {
      const from_local = JSON.parse(localStorage.activeDoc);
      const sessionFile = files.find(
        (f) => f.docId === from_local.doc_id && f.file,
      );
      console.log(sessionFile);
      setActiveDoc({
        doc_id: from_local.doc_id,
        doc_name: from_local.doc_name,

        doc_type: from_local.doc_type,
        num_chunks: from_local.num_chunks,
        file: sessionFile?.file || null,
      });
    } else {
      null;
    }
  }, [files]);

     //handling the logout
  const handleLogout = useCallback(() => {
    localStorage.removeItem("docagent_token");
    localStorage.removeItem("docagent_refresh_token");
    sessionStorage.removeItem("docagent_chat_messages");
    setUser(null);
    setFiles([]);
    setActiveIndex(0);
    setActivePage("upload");
    setMobileMenuOpen(false);
    setActiveDoc(null);
  }, [setUser, setActivePage, setActiveDoc, setActiveIndex, setFiles, setMobileMenuOpen]);

  useEffect(() => {
    window.addEventListener('docagent:session_expired', handleLogout);
    return () => window.removeEventListener('docagent:session_expired', handleLogout);
  }, [handleLogout]);

  // Derived state
  const pendingCount = files.filter((f) => f.status === "pending").length;
  const processedFiles = files.filter((f) => f.status === "processed");
  const hasFiles = files.length > 0;

  // ── Mobile detection helper ───────────────────────────────────────────────
  const isMobile = () => window.innerWidth <= 768;

  // ── Add files (deferred — no backend call) ─────────────────────────────────
  const handleFilesAdded = useCallback((newFiles) => {
    setFiles((prev) => {
      const existingNames = new Set(prev.map((f) => f.file?.name));
      const unique = newFiles.filter((f) => !existingNames.has(f.name));
      if (!unique.length) return prev;

      // Immediately save ONLY the new heavy binary files to IndexedDB
      unique.forEach((f) => {
        set(`docagent_file_${f.name}`, f).catch((err) =>
          console.error("Failed to save binary to IDB:", err),
        );
      });

      const newEntries = unique.map((f) => ({
        file: f,
        fileName: f.name, // Keep explicit track of the name for IDB retrieval
        docId: null,
        status: "pending",
        error: null,
      }));
      const finalList = [...prev, ...newEntries];
      setActiveIndex(finalList.length - 1);
      return finalList;
    });
  }, []);

  // ── Process pending files (sends to backend) ──────────────────────────────
  const handleProcessDocuments = useCallback(async () => {
    // Snapshot pending entries from ref (avoids side-effects in state updaters)
    const currentFiles = filesRef.current;
    const pendingEntries = currentFiles
      .map((e, i) => ({ index: i, file: e.file, status: e.status }))
      .filter((e) => e.status === "pending" && e.file);

    if (!pendingEntries.length) return;

    setIsProcessing(true);

    // Mark all pending as uploading
    setFiles((prev) =>
      prev.map((e) =>
        e.status === "pending" ? { ...e, status: "uploading" } : e,
      ),
    );

    let processedCount = 0;
    let lastProcessedDoc = null;

    for (const { index, file } of pendingEntries) {
      try {
        const res = await uploadDocument(file, docType);
        setFiles((prev) =>
          prev.map((e, i) =>
            i === index
              ? { ...e, docId: res.doc_id, status: "processed", error: null }
              : e,
          ),
        );
        lastProcessedDoc = {
          doc_id: res.doc_id,
          doc_name: res.doc_name,
          doc_type: res.doc_type,
          num_chunks: res.num_chunks,
          file: file,
        };
        processedCount++;
      } catch (err) {
        setFiles((prev) =>
          prev.map((e, i) =>
            i === index ? { ...e, status: "error", error: "Upload failed. Please try again." } : e,
          ),
        );
      }
    }

    setIsProcessing(false);

    // Auto-navigate to Ask page only if no document is already active
    if (processedCount > 0 && lastProcessedDoc) {
      if (!activeDoc) {
        sessionStorage.removeItem("docagent_chat_messages");
        setActiveDoc(lastProcessedDoc);
        setActivePage("ask");
      }
    }
  }, [docType]);

  const handleRemove = useCallback((index) => {
    setFiles((prev) => {
      //added to remove from indexdb
      const fileToRemove = prev[index];
      console.log(fileToRemove);

      // Delete the heavy binary from IndexedDB
      if (fileToRemove?.fileName) {
        del(`docagent_file_${fileToRemove.fileName}`).catch(console.error);
      }

      const updated = prev.filter((_, i) => i !== index);
      setActiveIndex((i) => Math.min(i, Math.max(0, updated.length - 1)));
      return updated;
    });
  }, []);

  const handleAddMore = () => addInputRef.current?.click();
  const handleAddInput = (e) => {
    const newFiles = Array.from(e.target.files);
    if (newFiles.length) handleFilesAdded(newFiles);
    e.target.value = "";
  };

  // ── Select doc from YourDocuments page → go to Ask ────────────────────────
  const handleSelectDoc = (doc) => {
    // doc comes from the API: { doc_id, doc_name, doc_type, num_chunks, created_at }
    // Check if we have a session file with matching name (for preview)
    const sessionFile = files.find((f) => f.docId === doc.doc_id && f.file);
    setActiveDoc({
      doc_id: doc.doc_id,
      doc_name: doc.doc_name,
      doc_type: doc.doc_type,
      num_chunks: doc.num_chunks,
      file: sessionFile?.file || null,
    });
    sessionStorage.removeItem("docagent_chat_messages");
    setActivePage("ask");
  };

  // ── Auth gate ──────────────────────────────────────────────────────────────
  if (!user) return <AuthPage onAuth={handleAuth} />;

  return (
    <div className="app-root">
      <input
        ref={addInputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.txt,.md"
        onChange={handleAddInput}
        style={{ display: "none" }}
      />

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <header className="app-header">
        <div className="logo">
          <span className="logo-mark">D</span>
          <span className="logo-text">
            oc<em>Agent</em>
          </span>
        </div>

        <button
          className="mobile-menu-btn"
          onClick={() => setMobileMenuOpen((prev) => !prev)}
          aria-label="Toggle menu"
        >
          {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        <nav className={`app-nav${mobileMenuOpen ? " app-nav--open" : ""}`}>
          {PAGES.map((page) => (
            <span
              key={page}
              className={`nav-item${activePage === page ? " nav-item--active" : ""}`}
              onClick={() => {
                setActivePage(page);
                setMobileMenuOpen(false);
              }}
            >
              {page === "documents"
                ? "Documents"
                : page.charAt(0).toUpperCase() + page.slice(1)}
            </span>
          ))}
        </nav>

        <div className="header-right">
          <div className="status-pill">
            <span className="status-dot" />
            <span className="status-text">
              {activeDoc
                ? `Querying: ${activeDoc.doc_name}`
                : hasFiles
                  ? `${processedFiles.length}/${files.length} processed`
                  : "No documents"}
            </span>
          </div>
          <button
            className="auth-logout-btn"
            onClick={handleLogout}
            title="Sign out"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* ── Main content ────────────────────────────────────────────────────── */}
      <main
        className="app-main"
        onClick={() => mobileMenuOpen && setMobileMenuOpen(false)}
      >
        {activePage === "upload" && (
          <>
            {!hasFiles ? (
              <div className="empty-state">
                <div className="empty-top">
                  <h1 className="empty-headline">
                    Your documents,
                    <br />
                    <em>intelligently indexed.</em>
                  </h1>
                  <p className="empty-subheadline">
                    Upload PDFs, Word docs, or text files. Ask questions, study,
                    extract — all with exact citations.
                  </p>
                </div>
                <UploadZone
                  onFilesAdded={handleFilesAdded}
                  docType={docType}
                  onDocTypeChange={setDocType}
                />
              </div>
            ) : (
              <div
                className={`workspace${!sidebarOpen ? " workspace--sidebar-hidden" : ""}`}
              >
                <FileList
                  files={files}
                  activeIndex={activeIndex}
                  onSelect={(i) => {
                    setActiveIndex(i);
                    setSidebarOpen(false);
                  }}
                  onRemove={handleRemove}
                  onAddMore={handleAddMore}
                  onProcess={handleProcessDocuments}
                  pendingCount={pendingCount}
                  isProcessing={isProcessing}
                />
                <div className="preview-area">
                  {/* Desktop: panel toggle */}
                  <button
                    className="sidebar-toggle-btn desktop-only"
                    onClick={() => setSidebarOpen((prev) => !prev)}
                    aria-label="Toggle file list"
                  >
                    <PanelLeft size={16} />
                    <span>{sidebarOpen ? "Hide files" : "Show files"}</span>
                  </button>
                  {/* Mobile: always-visible back button when sidebar is hidden */}
                  <button
                    className="mobile-back-btn"
                    onClick={() => setSidebarOpen(true)}
                    aria-label="Back to file list"
                  >
                    <ChevronLeft size={16} />
                    <span>Files</span>
                  </button>
                  {files[activeIndex]?.file ? (
                    <DocumentPreview file={files[activeIndex].file} />
                  ) : null}
                </div>
              </div>
            )}
          </>
        )}

        {activePage === "documents" && (
          <YourDocuments onSelectDoc={handleSelectDoc} user={user} />
        )}

        {activePage === "ask" && (
          <AskPage
            activeDoc={activeDoc}
            onNavigateToUpload={() => setActivePage("upload")}
            onNavigateToDocs={() => setActivePage("documents")}
          />
        )}

        {activePage !== "upload" &&
          activePage !== "ask" &&
          activePage !== "documents" && <PlaceholderPage page={activePage} />}
      </main>
    </div>
  );
}
