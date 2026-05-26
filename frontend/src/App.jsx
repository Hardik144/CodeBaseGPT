import { useState, useRef, useEffect, useCallback } from "react";

// When using nginx proxy (production Docker), API calls go to same origin
// When using Vite dev server, VITE_API_URL points to localhost:8001
const API_BASE = import.meta.env.VITE_API_URL || "";

const EXAMPLE_REPOS = [
  { label: "fastapi/fastapi",    url: "https://github.com/fastapi/fastapi" },
  { label: "pallets/flask",      url: "https://github.com/pallets/flask" },
  { label: "psf/requests",       url: "https://github.com/psf/requests" },
  { label: "expressjs/express",  url: "https://github.com/expressjs/express" },
];

const EXAMPLE_QUESTIONS = [
  "How does authentication work?",
  "Explain the request lifecycle",
  "Where is database connection handled?",
  "How are errors handled globally?",
  "What middleware is used and why?",
];

// ── Markdown renderer — handles headings, lists, code, bold, citations ───────

function escapeHtml(str) {
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function applyInline(text) {
  return text
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+\.\w+[:\d][^\]]{0,30})\]/g, '<span class="citation">[$1]</span>');
}

function parseMarkdown(raw) {
  if (!raw) return "";

  let text = raw.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  text = text.replace(/([^\n])\s+-\s+(?=[A-Z`\[\*])/g, "$1\n- ");

  const codeBlocks = [];
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, function(_, lang, code) {
    var idx = codeBlocks.length;
    codeBlocks.push(
      '<pre class="code-block"><code class="lang-' + (lang||"text") + '">' + escapeHtml(code.trim()) + "</code></pre>"
    );
    return "@@CODE" + idx + "@@";
  });

  var lines = text.split("\n");
  var html = [];
  var inList = null;

  function closelist() {
    if (inList) { html.push("</" + inList + ">"); inList = null; }
  }

  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trimEnd();

    var codeMatch = line.trim().match(/^@@CODE(\d+)@@$/);
    if (codeMatch) { closelist(); html.push(codeBlocks[parseInt(codeMatch[1])]); continue; }

    var m;
    if ((m = line.match(/^### (.+)/))) { closelist(); html.push("<h3 class='md-h3'>" + applyInline(m[1]) + "</h3>"); continue; }
    if ((m = line.match(/^## (.+)/)))  { closelist(); html.push("<h2 class='md-h2'>" + applyInline(m[1]) + "</h2>"); continue; }
    if ((m = line.match(/^# (.+)/)))   { closelist(); html.push("<h1 class='md-h1'>" + applyInline(m[1]) + "</h1>"); continue; }

    if ((m = line.match(/^[-*+] (.*)/))) {
      if (inList !== "ul") { closelist(); html.push('<ul class="md-list">'); inList = "ul"; }
      html.push("<li class='md-li'>" + applyInline(m[1]) + "</li>");
      continue;
    }

    if ((m = line.match(/^\d+\. (.*)/))) {
      if (inList !== "ol") { closelist(); html.push('<ol class="md-list">'); inList = "ol"; }
      html.push("<li class='md-li'>" + applyInline(m[1]) + "</li>");
      continue;
    }

    var emojiUL = line.match(/^([\uD83D\uDD34\uD83D\uDFE1\uD83D\uDFE2\uD83D\uDFE3\uD83D\uDFE4\uD83D\uDFE5])\s+(.*)/);
    if (emojiUL) {
      if (inList !== "ul") { closelist(); html.push('<ul class="md-list md-emoji-list">'); inList = "ul"; }
      html.push("<li class='md-li'>" + emojiUL[1] + " " + applyInline(emojiUL[2]) + "</li>");
      continue;
    }

    if (line.trim() === "") { closelist(); html.push('<div class="md-gap"></div>'); continue; }
    if (/^[-*_]{3,}$/.test(line.trim())) { closelist(); html.push('<hr class="md-hr"/>'); continue; }

    closelist();
    html.push("<p class='md-p'>" + applyInline(line) + "</p>");
  }

  closelist();
  return html.join("");
}

// ── Utility ──────────────────────────────────────────────────────────────────

function getRepoName(url) {
  return url.replace(/\.git$/, "").split("/").slice(-2).join("/") || url;
}

// ── Components ───────────────────────────────────────────────────────────────

function SourceBadge({ source }) {
  const filename = source.file.split("/").pop();
  return (
    <span className="source-badge" title={`${source.type}: ${source.name}\n${source.file}`}>
      <span className="source-type">{source.type}</span>
      <span className="source-name">{source.name}</span>
      <span className="source-loc">{filename}:{source.start}</span>
    </span>
  );
}

function Message({ msg }) {
  const [showSources, setShowSources] = useState(false);

  if (msg.role === "user") {
    return (
      <div className="msg msg-user">
        <div className="msg-bubble">{msg.content}</div>
      </div>
    );
  }

  const hasSources = msg.sources?.length > 0;

  return (
    <div className="msg msg-assistant">
      <div className="msg-avatar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
        </svg>
      </div>
      <div className="msg-body">
        {msg.content ? (
          <div
            className="msg-text"
            dangerouslySetInnerHTML={{ __html: parseMarkdown(msg.content) }}
          />
        ) : (
          <div className="msg-thinking">
            <span className="dot" /><span className="dot" /><span className="dot" />
          </div>
        )}
        {hasSources && (
          <div className="sources-section">
            <button className="sources-toggle" onClick={() => setShowSources(s => !s)}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
              {msg.sources.length} source{msg.sources.length !== 1 ? "s" : ""}
              <span className={`chevron ${showSources ? "open" : ""}`}>›</span>
            </button>
            {showSources && (
              <div className="sources-list">
                {msg.sources.map((s, i) => <SourceBadge key={i} source={s} />)}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function IngestProgress({ job }) {
  if (!job) return null;
  const labels = {
    pending:  "Queued — loading embedding model…",
    cloning:  "Cloning repository…",
    chunking: "Parsing — extracting functions & classes…",
    indexing: `Embedding & indexing… ${job.indexed_chunks}/${job.total_chunks} chunks`,
    done:     `Ready — ${job.total_chunks} chunks indexed`,
    error:    job.error,
  };
  const isActive = ["pending","cloning","chunking","indexing"].includes(job.status);
  return (
    <div className={`ingest-progress status-${job.status}`}>
      <div className="ingest-status-row">
        <span className={`ingest-dot dot-${job.status}`} />
        <span className="ingest-label">{labels[job.status]}</span>
        {isActive && <span className="ingest-pct">{job.progress}%</span>}
      </div>
      {isActive && (
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${job.progress}%` }} />
        </div>
      )}
    </div>
  );
}

// ── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [repoUrl,        setRepoUrl]        = useState("");
  const [ingestJob,      setIngestJob]      = useState(null);
  const [activeRepoId,   setActiveRepoId]   = useState(null);
  const [activeRepoName, setActiveRepoName] = useState("");
  const [messages,       setMessages]       = useState([]);
  const [input,          setInput]          = useState("");
  const [isStreaming,    setIsStreaming]     = useState(false);
  const [sidebarOpen,    setSidebarOpen]    = useState(true);

  const bottomRef = useRef(null);
  const inputRef  = useRef(null);
  const pollRef   = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const startPolling = useCallback((jobId, currentRepoUrl) => {
    if (pollRef.current) clearInterval(pollRef.current);
    let streak = 0;
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const job = await res.json();
        streak = 0;
        setIngestJob(job);
        if (job.status === "done") {
          clearInterval(pollRef.current);
          setActiveRepoId(job.repo_id);
          setMessages([{
            id: "welcome", role: "assistant", sources: [],
            content: `Repository indexed! I've analyzed **${job.total_chunks} code chunks** from \`${getRepoName(currentRepoUrl)}\`.\n\nAsk me anything — how something works, where to find a function, architecture questions.`,
          }]);
        } else if (job.status === "error") {
          clearInterval(pollRef.current);
        }
      } catch {
        if (++streak >= 5) {
          clearInterval(pollRef.current);
          setIngestJob({ status: "error", error: "Lost connection to backend." });
        }
      }
    }, 800);
  }, []);

  const handleIngest = async (url) => {
    const target = (url || repoUrl).trim();
    if (!target) return;
    setRepoUrl(target);
    setActiveRepoId(null);
    setMessages([]);
    setActiveRepoName(getRepoName(target));
    setIngestJob({ status: "pending", progress: 0, total_chunks: 0, indexed_chunks: 0 });

    try {
      const res = await fetch(`${API_BASE}/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: target }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const job = await res.json();
      setIngestJob(job);
      if (job.status === "done") {
        setActiveRepoId(job.repo_id);
        setMessages([{
          id: "welcome", role: "assistant", sources: [],
          content: `Repository already indexed! I have **${job.total_chunks} code chunks** from \`${getRepoName(target)}\` ready.\n\nWhat would you like to know?`,
        }]);
      } else {
        startPolling(job.job_id, target);
      }
    } catch (e) {
      setIngestJob({ status: "error", error: e.message || "Could not connect to backend." });
    }
  };

  const handleSend = async (override) => {
    const question = (override || input).trim();
    if (!question || !activeRepoId || isStreaming) return;

    setInput("");
    const uid = Date.now();
    const aid = uid + 1;
    setMessages(prev => [
      ...prev,
      { id: uid, role: "user",      content: question, sources: [] },
      { id: aid, role: "assistant", content: "",        sources: [] },
    ]);
    setIsStreaming(true);

    const history = messages
      .filter(m => m.id !== "welcome")
      .slice(-6)
      .map(m => ({ role: m.role, content: m.content }));

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_id: activeRepoId, question, history }),
      });

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "", full = "", sources = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const chunk = line.slice(6);

          // Parse SOURCES marker
          const srcMatch = chunk.match(/\[SOURCES\]([\s\S]*?)\[\/SOURCES\]/);
          if (srcMatch) {
            try { sources = JSON.parse(srcMatch[1]); } catch {}
            full = full.replace(/\[SOURCES\][\s\S]*?\[\/SOURCES\]/, "").trim();
          } else if (chunk.includes("[ERROR]")) {
            full += "\n⚠️ " + chunk.replace(/\[ERROR\]|\[\/ERROR\]/g, "");
          } else {
            full += chunk.replace(/\\n/g, "\n");
          }

          const displayText = full.replace(/\[SOURCES\][\s\S]*?\[\/SOURCES\]/, "").trim();
          setMessages(prev => prev.map(m =>
            m.id === aid ? { ...m, content: displayText, sources } : m
          ));
        }
      }
    } catch {
      setMessages(prev => prev.map(m =>
        m.id === aid ? { ...m, content: "Connection error. Make sure the backend is running." } : m
      ));
    } finally {
      setIsStreaming(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <>
      <style>{CSS}</style>
      <div className="app">

        {/* Sidebar */}
        <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
          <div className="sidebar-header">
            <div className="logo">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
              </svg>
              <span>CodebaseGPT</span>
            </div>
            <button className="icon-btn" onClick={() => setSidebarOpen(s => !s)} title="Toggle sidebar">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
              </svg>
            </button>
          </div>

          <div className="sidebar-section">
            <label className="section-label">GitHub Repository</label>
            <div className="input-row">
              <input
                className="repo-input"
                placeholder="https://github.com/owner/repo"
                value={repoUrl}
                onChange={e => setRepoUrl(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleIngest()}
              />
              <button
                className="ingest-btn"
                onClick={() => handleIngest()}
                disabled={!repoUrl.trim() || ["pending","cloning","chunking","indexing"].includes(ingestJob?.status)}
              >
                Index
              </button>
            </div>
            <IngestProgress job={ingestJob} />
          </div>

          <div className="sidebar-section">
            <label className="section-label">Examples</label>
            {EXAMPLE_REPOS.map(r => (
              <button
                key={r.url}
                className={`row-btn ${repoUrl === r.url ? "active" : ""}`}
                onClick={() => handleIngest(r.url)}
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>
                </svg>
                {r.label}
              </button>
            ))}
          </div>

          {activeRepoId && (
            <div className="sidebar-section">
              <label className="section-label">Suggested questions</label>
              {EXAMPLE_QUESTIONS.map(q => (
                <button
                  key={q} className="row-btn"
                  onClick={() => handleSend(q)}
                  disabled={isStreaming}
                >{q}</button>
              ))}
            </div>
          )}

          <div className="sidebar-footer">
            <span className="footer-tag">Tree-sitter AST</span>
            <span className="footer-tag">Hybrid RAG</span>
            <span className="footer-tag">BM25 + Dense</span>
          </div>
        </aside>

        {/* Main area */}
        <main className="main">
          {!activeRepoId ? (
            <div className="empty-state">
              <div className="empty-icon">
                <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
                  <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
                </svg>
              </div>
              <h1>CodebaseGPT</h1>
              <p>Index any GitHub repository and ask questions about the code in plain English.</p>
              <div className="features">
                <div className="feature"><span className="fi">⟨/⟩</span><span>AST-aware chunking — never splits a function in half</span></div>
                <div className="feature"><span className="fi">⌖</span><span>Hybrid BM25 + vector search for best retrieval</span></div>
                <div className="feature"><span className="fi">↗</span><span>Every answer cites exact file paths and line numbers</span></div>
              </div>
              {ingestJob && ingestJob.status !== "done" && (
                <div style={{ width: "100%", maxWidth: 360 }}>
                  <IngestProgress job={ingestJob} />
                </div>
              )}
            </div>
          ) : (
            <div className="chat-area">
              <div className="chat-header">
                <div className="chat-repo">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>
                  </svg>
                  {activeRepoName}
                </div>
                {ingestJob && <span className="chunk-pill">{ingestJob.total_chunks} chunks indexed</span>}
              </div>

              <div className="messages">
                {messages.map(m => <Message key={m.id} msg={m} />)}
                <div ref={bottomRef} />
              </div>

              <div className="input-area">
                <div className="input-wrap">
                  <textarea
                    ref={inputRef}
                    className="chat-input"
                    placeholder="Ask about the codebase…"
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={handleKey}
                    rows={1}
                    disabled={isStreaming}
                  />
                  <button
                    className={`send-btn ${isStreaming ? "busy" : ""}`}
                    onClick={() => handleSend()}
                    disabled={!input.trim() || isStreaming}
                  >
                    {isStreaming
                      ? <span className="spinner" />
                      : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                    }
                  </button>
                </div>
                <p className="hint">Enter to send · Shift+Enter for newline</p>
              </div>
            </div>
          )}
        </main>
      </div>
    </>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500&family=DM+Mono:wght@400;500&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:      #0e0e10;
    --bg2:     #141416;
    --bg3:     #1c1c20;
    --border:  rgba(255,255,255,0.07);
    --border2: rgba(255,255,255,0.13);
    --text:    #e4e4e0;
    --text2:   #888882;
    --text3:   #50504a;
    --accent:  #6ee7b7;
    --accent2: #34d399;
    --purple:  #a78bfa;
    --amber:   #fbbf24;
    --danger:  #f87171;
    --sans:    'DM Sans', system-ui, sans-serif;
    --mono:    'DM Mono', 'Fira Code', monospace;
    --r:       8px;
    --sidebar: 256px;
  }

  html, body, #root { height: 100%; background: var(--bg); color: var(--text); font-family: var(--sans); font-size: 14px; line-height: 1.6; }

  .app { display: flex; height: 100vh; overflow: hidden; }

  /* Sidebar */
  .sidebar { width: var(--sidebar); min-width: var(--sidebar); background: var(--bg2); border-right: 0.5px solid var(--border); display: flex; flex-direction: column; overflow-y: auto; transition: width 0.2s, min-width 0.2s; overflow-x: hidden; }
  .sidebar.closed { width: 48px; min-width: 48px; }
  .sidebar.closed .sidebar-section, .sidebar.closed .sidebar-footer { display: none; }

  .sidebar-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 12px; border-bottom: 0.5px solid var(--border); }
  .logo { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; color: var(--text); white-space: nowrap; overflow: hidden; }
  .logo svg { color: var(--accent); flex-shrink: 0; }
  .icon-btn { background: none; border: none; color: var(--text3); cursor: pointer; padding: 4px; border-radius: 4px; line-height: 0; }
  .icon-btn:hover { background: var(--bg3); color: var(--text2); }

  .sidebar-section { padding: 14px 12px; border-bottom: 0.5px solid var(--border); }
  .section-label { display: block; font-size: 10px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text3); margin-bottom: 8px; }

  .input-row { display: flex; gap: 6px; }
  .repo-input { flex: 1; background: var(--bg3); border: 0.5px solid var(--border); border-radius: var(--r); color: var(--text); padding: 6px 9px; font-size: 11.5px; font-family: var(--mono); outline: none; min-width: 0; }
  .repo-input:focus { border-color: var(--accent); }
  .repo-input::placeholder { color: var(--text3); }

  .ingest-btn { background: var(--accent); color: #0a0a0c; border: none; border-radius: var(--r); padding: 6px 11px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; transition: background 0.15s, opacity 0.15s; }
  .ingest-btn:hover { background: var(--accent2); }
  .ingest-btn:disabled { opacity: 0.35; cursor: not-allowed; }

  /* Progress */
  .ingest-progress { margin-top: 9px; }
  .ingest-status-row { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text2); }
  .ingest-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
  .dot-pending, .dot-cloning, .dot-chunking, .dot-indexing { background: var(--amber); animation: pulse 1.2s ease-in-out infinite; }
  .dot-done { background: var(--accent); }
  .dot-error { background: var(--danger); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
  .ingest-pct { margin-left: auto; font-family: var(--mono); font-size: 10px; color: var(--text3); }
  .progress-bar { height: 2px; background: var(--border); border-radius: 1px; margin-top: 7px; overflow: hidden; }
  .progress-fill { height: 100%; background: var(--accent); border-radius: 1px; transition: width 0.3s ease; }

  .row-btn { display: flex; align-items: center; gap: 7px; width: 100%; background: none; border: 0.5px solid transparent; border-radius: var(--r); color: var(--text2); padding: 6px 7px; font-size: 12px; font-family: var(--sans); cursor: pointer; text-align: left; transition: all 0.1s; margin-bottom: 2px; }
  .row-btn:hover { background: var(--bg3); border-color: var(--border); color: var(--text); }
  .row-btn.active { background: rgba(110,231,183,0.07); border-color: rgba(110,231,183,0.18); color: var(--accent); }
  .row-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .row-btn svg { flex-shrink: 0; }

  .sidebar-footer { margin-top: auto; padding: 12px; display: flex; flex-wrap: wrap; gap: 5px; }
  .footer-tag { font-size: 10px; font-family: var(--mono); background: var(--bg3); border: 0.5px solid var(--border); border-radius: 20px; padding: 2px 7px; color: var(--text3); }

  /* Main */
  .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

  /* Empty state */
  .empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 40px 24px; gap: 0; }
  .empty-icon { color: var(--text3); margin-bottom: 18px; }
  .empty-state h1 { font-size: 26px; font-weight: 300; letter-spacing: -0.5px; color: var(--text); margin-bottom: 10px; }
  .empty-state > p { font-size: 14px; color: var(--text2); max-width: 420px; line-height: 1.65; margin-bottom: 28px; }
  .features { display: flex; flex-direction: column; gap: 10px; max-width: 340px; width: 100%; margin-bottom: 24px; }
  .feature { display: flex; align-items: flex-start; gap: 12px; text-align: left; font-size: 13px; color: var(--text2); }
  .fi { font-family: var(--mono); color: var(--accent); font-size: 14px; width: 22px; flex-shrink: 0; }

  /* Chat */
  .chat-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .chat-header { display: flex; align-items: center; justify-content: space-between; padding: 11px 18px; border-bottom: 0.5px solid var(--border); background: var(--bg2); }
  .chat-repo { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text2); }
  .chat-repo svg { color: var(--text3); flex-shrink: 0; }
  .chunk-pill { font-size: 11px; font-family: var(--mono); color: var(--accent); background: rgba(110,231,183,0.08); padding: 2px 8px; border-radius: 20px; }

  .messages { flex: 1; overflow-y: auto; padding: 24px 20px; display: flex; flex-direction: column; gap: 22px; }
  .messages::-webkit-scrollbar { width: 3px; }
  .messages::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

  /* Message bubbles */
  .msg { display: flex; gap: 11px; }
  .msg-user { flex-direction: row-reverse; margin-left: auto; max-width: 75%; }
  .msg-user .msg-bubble { background: rgba(110,231,183,0.09); border: 0.5px solid rgba(110,231,183,0.18); border-radius: 14px 14px 2px 14px; padding: 10px 14px; font-size: 14px; line-height: 1.6; color: var(--text); }

  .msg-assistant { align-items: flex-start; max-width: 100%; }
  .msg-avatar { width: 26px; height: 26px; background: rgba(110,231,183,0.08); border: 0.5px solid rgba(110,231,183,0.18); border-radius: 7px; display: flex; align-items: center; justify-content: center; color: var(--accent); flex-shrink: 0; margin-top: 3px; }
  .msg-body { flex: 1; min-width: 0; }

  /* Rendered markdown */
  /* Message text container */
  .msg-text { font-size: 14px; line-height: 1.75; color: var(--text); }

  /* Block elements — each on its own line with spacing */
  .msg-text .md-p { display: block; margin: 0 0 10px; line-height: 1.75; }
  .msg-text .md-p:last-child { margin-bottom: 0; }
  .msg-text .md-gap { height: 6px; }
  .msg-text .md-hr { border: none; border-top: 0.5px solid var(--border); margin: 12px 0; }

  /* Headings */
  .msg-text .md-h1 { font-size: 16px; font-weight: 600; color: var(--text); margin: 16px 0 8px; }
  .msg-text .md-h2 { font-size: 14px; font-weight: 600; color: var(--text); margin: 14px 0 6px; padding-bottom: 4px; border-bottom: 0.5px solid var(--border); }
  .msg-text .md-h3 { font-size: 13px; font-weight: 600; color: var(--accent); margin: 12px 0 4px; }

  /* Lists — always block, items spaced */
  .msg-text .md-list { display: block; padding-left: 20px; margin: 8px 0 10px; }
  .msg-text ul.md-list { list-style: disc; }
  .msg-text ol.md-list { list-style: decimal; }
  .msg-text .md-li { display: list-item; margin-bottom: 8px; line-height: 1.7; }
  .msg-text .md-li:last-child { margin-bottom: 0; }
  .msg-text .md-li strong { color: var(--text); }

  /* Inline */
  .msg-text strong { font-weight: 600; color: var(--text); }
  .msg-text em { font-style: italic; color: var(--text2); }

  .citation { font-family: var(--mono); font-size: 11px; color: var(--accent); background: rgba(110,231,183,0.08); border-radius: 4px; padding: 1px 6px; white-space: nowrap; display: inline-block; }

  .code-block { background: var(--bg2); border: 0.5px solid var(--border); border-radius: var(--r); padding: 13px 15px; margin: 10px 0; overflow-x: auto; font-family: var(--mono); font-size: 12.5px; line-height: 1.65; color: #9dd6aa; }
  .inline-code { font-family: var(--mono); font-size: 12px; background: var(--bg3); border: 0.5px solid var(--border); border-radius: 4px; padding: 1px 5px; color: var(--purple); }

  /* Thinking indicator */
  .msg-thinking { display: flex; gap: 5px; padding: 8px 0; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text3); animation: bounce 1.1s ease-in-out infinite; }
  .dot:nth-child(2) { animation-delay: 0.18s; }
  .dot:nth-child(3) { animation-delay: 0.36s; }
  @keyframes bounce { 0%,80%,100%{transform:translateY(0)} 40%{transform:translateY(-6px)} }

  /* Sources */
  .sources-section { margin-top: 10px; }
  .sources-toggle { display: inline-flex; align-items: center; gap: 5px; background: none; border: 0.5px solid var(--border); border-radius: 20px; color: var(--text2); font-size: 11px; padding: 3px 10px; cursor: pointer; font-family: var(--sans); transition: all 0.12s; }
  .sources-toggle:hover { border-color: var(--border2); color: var(--text); }
  .chevron { transition: transform 0.15s; display: inline-block; font-size: 13px; }
  .chevron.open { transform: rotate(90deg); }
  .sources-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .source-badge { display: inline-flex; align-items: center; gap: 5px; background: var(--bg3); border: 0.5px solid var(--border); border-radius: 5px; padding: 3px 9px; font-size: 11px; cursor: default; max-width: 320px; }
  .source-type { font-family: var(--mono); color: var(--text3); font-size: 10px; text-transform: uppercase; }
  .source-name { font-family: var(--mono); color: var(--text); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
  .source-loc { font-family: var(--mono); color: var(--accent); font-size: 10px; white-space: nowrap; }

  /* Input */
  .input-area { padding: 14px 18px 10px; border-top: 0.5px solid var(--border); background: var(--bg2); }
  .input-wrap { display: flex; gap: 10px; align-items: flex-end; }
  .chat-input { flex: 1; background: var(--bg3); border: 0.5px solid var(--border); border-radius: 12px; color: var(--text); padding: 10px 14px; font-size: 14px; font-family: var(--sans); outline: none; resize: none; min-height: 42px; max-height: 120px; line-height: 1.5; transition: border-color 0.15s; }
  .chat-input:focus { border-color: var(--border2); }
  .chat-input::placeholder { color: var(--text3); }
  .chat-input:disabled { opacity: 0.45; }
  .send-btn { width: 38px; height: 38px; background: var(--accent); border: none; border-radius: 10px; color: #0a0a0c; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: background 0.15s, transform 0.1s; }
  .send-btn:hover:not(:disabled) { background: var(--accent2); transform: translateY(-1px); }
  .send-btn:disabled { opacity: 0.28; cursor: not-allowed; transform: none; }
  .spinner { width: 13px; height: 13px; border: 2px solid rgba(10,10,12,0.25); border-top-color: #0a0a0c; border-radius: 50%; animation: spin 0.65s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .hint { font-size: 10px; color: var(--text3); margin-top: 5px; text-align: center; }

  * { scrollbar-width: thin; scrollbar-color: var(--border2) transparent; }
`;
# frontend: init src directory with App and router
# frontend: init src directory with App and router
# frontend: init src directory with App and router
# frontend: init src directory with App and router
