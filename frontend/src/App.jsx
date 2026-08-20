import { useEffect, useMemo, useRef, useState } from "react";
import { compareDocuments, downloadRedline, releaseComparison } from "./api.js";

const FILTERS = ["all", "addition", "deletion", "modification"];

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function DocumentIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 2.75h6.7L18.25 7.3V21.25H7a2.25 2.25 0 0 1-2.25-2.25V5A2.25 2.25 0 0 1 7 2.75Z" />
      <path d="M13.25 3v4.75H18M8.5 12h6.75M8.5 15.5h6.75" />
    </svg>
  );
}

function UploadCard({ label, helper, file, onFile, disabled }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  function accept(candidate) {
    if (candidate) onFile(candidate);
  }

  return (
    <section className={`upload-card ${file ? "has-file" : ""}`} aria-label={`${label} document`}>
      <div className="upload-heading">
        <span className="step-badge">{label === "Original" ? "1" : "2"}</span>
        <div>
          <h2>{label} document</h2>
          <p>{helper}</p>
        </div>
      </div>
      <button
        type="button"
        className={`drop-zone ${dragging ? "is-dragging" : ""}`}
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          accept(event.dataTransfer.files?.[0]);
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={disabled}
          onChange={(event) => accept(event.target.files?.[0])}
          tabIndex="-1"
          aria-hidden="true"
        />
        <span className="document-icon"><DocumentIcon /></span>
        {file ? (
          <span className="selected-file">
            <strong>{file.name}</strong>
            <span>{formatBytes(file.size)} · Ready to compare</span>
          </span>
        ) : (
          <span className="drop-copy">
            <strong>Choose a Word document</strong>
            <span>or drag and drop a .docx file here</span>
          </span>
        )}
        <span className="browse-label">{file ? "Replace file" : "Browse files"}</span>
      </button>
    </section>
  );
}

function locationLabel(location) {
  if (location.container === "table_row") {
    return `Table ${location.table_index}, row ${location.row_index}`;
  }
  if (location.container === "table_cell") {
    return `Table ${location.table_index}, row ${location.row_index}, cell ${location.cell_index}`;
  }
  const part = location.part === "document"
    ? "Document body"
    : location.part.startsWith("header")
      ? "Header"
      : location.part.startsWith("footer")
        ? "Footer"
        : location.part;
  return `${part}, paragraph ${location.paragraph_index}`;
}

function ChangeCard({ change }) {
  return (
    <article className={`change-card ${change.type}`}>
      <div className="change-card-head">
        <span className={`change-type ${change.type}`}>
          <span aria-hidden="true">{change.type === "addition" ? "+" : change.type === "deletion" ? "−" : "↔"}</span>
          {change.type}
        </span>
        {change.severity === "heavily_revised" && (
          <span className="severity-badge">Heavily revised</span>
        )}
        <span className="change-location">{locationLabel(change.location)}</span>
      </div>

      {change.type === "modification" && (
        <div className="comparison-lines">
          <div className="text-line before">
            <span className="line-label">Before</span>
            <span>{change.original_text || "—"}</span>
          </div>
          <div className="text-line after">
            <span className="line-label">After</span>
            <span>{change.revised_text || "—"}</span>
          </div>
          <div className="changed-fragments">
            {change.deleted_text && <span className="fragment deleted-fragment">Removed: {change.deleted_text}</span>}
            {change.inserted_text && <span className="fragment inserted-fragment">Added: {change.inserted_text}</span>}
          </div>
        </div>
      )}

      {change.type === "addition" && (
        <div className="single-change added-text">{change.revised_text}</div>
      )}

      {change.type === "deletion" && (
        <div className="single-change deleted-text">{change.original_text}</div>
      )}
    </article>
  );
}

function SummaryCard({ label, count, kind }) {
  return (
    <div className={`summary-card ${kind}`}>
      <span className="summary-number">{count}</span>
      <span>{label}</span>
    </div>
  );
}

export default function App() {
  const [original, setOriginal] = useState(null);
  const [revised, setRevised] = useState(null);
  const [result, setResult] = useState(null);
  const [filter, setFilter] = useState("all");
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [downloaded, setDownloaded] = useState(false);

  useEffect(() => {
    if (!result || downloaded || secondsLeft <= 0) return undefined;
    const timer = window.setInterval(() => {
      setSecondsLeft((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [result, downloaded, secondsLeft]);

  const filteredChanges = useMemo(() => {
    if (!result) return [];
    return filter === "all"
      ? result.changes
      : result.changes.filter((change) => change.type === filter);
  }, [filter, result]);

  function chooseFile(setter) {
    return (file) => {
      setError("");
      if (!file.name.toLowerCase().endsWith(".docx")) {
        setError("Please choose a Word document ending in .docx.");
        return;
      }
      setter(file);
    };
  }

  function swapFiles() {
    setOriginal(revised);
    setRevised(original);
    setError("");
  }

  async function handleCompare() {
    if (!original || !revised) return;
    if (original === revised) {
      setError("The original and revised documents appear to be the same file.");
      return;
    }
    setStatus("comparing");
    setError("");
    setResult(null);
    setDownloaded(false);
    try {
      const data = await compareDocuments(original, revised);
      setResult(data);
      setSecondsLeft(data.download?.expires_in_seconds || 0);
      setFilter("all");
      setStatus("complete");
      window.requestAnimationFrame(() => {
        document.getElementById("results")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (requestError) {
      setError(requestError.message);
      setStatus("idle");
    }
  }

  async function handleDownload() {
    if (!result?.download?.url || downloaded || secondsLeft <= 0) return;
    setStatus("downloading");
    setError("");
    try {
      const blob = await downloadRedline(result.download.url);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = "postbank-comparison-visual-redline.docx";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setDownloaded(true);
      setStatus("complete");
    } catch (downloadError) {
      setError(downloadError.message);
      setStatus("complete");
    }
  }

  async function startAgain() {
    if (result?.comparison_id && !downloaded) {
      try {
        await releaseComparison(result.comparison_id);
      } catch {
        // Expiry cleanup remains the fallback if explicit release is unavailable.
      }
    }
    setOriginal(null);
    setRevised(null);
    setResult(null);
    setError("");
    setFilter("all");
    setStatus("idle");
    setDownloaded(false);
    setSecondsLeft(0);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const summary = result?.summary;
  const isBusy = status === "comparing";
  const canDownload = result && !downloaded && secondsLeft > 0;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark" aria-label="Postbank Document Compare">
          <span className="brand-symbol">P</span>
          <span className="brand-copy">
            <strong>Postbank</strong>
            <small>Document Compare</small>
          </span>
        </div>
        <div className="privacy-pill"><span className="privacy-dot" /> Internal processing</div>
      </header>

      <main>
        <section className="hero">
          <p className="eyebrow">DOCUMENT REVIEW TOOL</p>
          <h1>See exactly what changed.</h1>
          <p className="hero-copy">
            Compare an original letter with its revised version. Your documents are processed locally
            and are not kept as permanent history.
          </p>
        </section>

        <section className="workspace" aria-labelledby="compare-heading">
          <div className="section-title-row">
            <div>
              <p className="section-kicker">NEW COMPARISON</p>
              <h2 id="compare-heading">Choose two Word documents</h2>
            </div>
            <span className="format-note">DOCX only · Maximum 25 MB each</span>
          </div>

          <div className="upload-grid">
            <UploadCard
              label="Original"
              helper="The earlier version"
              file={original}
              onFile={chooseFile(setOriginal)}
              disabled={isBusy}
            />

            <button
              className="swap-button"
              type="button"
              onClick={swapFiles}
              disabled={isBusy || (!original && !revised)}
              aria-label="Swap original and revised documents"
            >
              <span aria-hidden="true">⇄</span>
              Swap
            </button>

            <UploadCard
              label="Revised"
              helper="The newer version"
              file={revised}
              onFile={chooseFile(setRevised)}
              disabled={isBusy}
            />
          </div>

          {error && <div className="error-banner" role="alert"><strong>Unable to continue.</strong> {error}</div>}

          <div className="action-row">
            <div className="security-note">
              <span className="lock-icon" aria-hidden="true">◆</span>
              <span><strong>Private by design</strong><small>Files remain in the internal comparison environment.</small></span>
            </div>
            <button
              className="primary-button"
              type="button"
              disabled={!original || !revised || isBusy}
              onClick={handleCompare}
            >
              {isBusy ? <><span className="spinner" /> Comparing documents…</> : <>Compare documents <span aria-hidden="true">→</span></>}
            </button>
          </div>
        </section>

        {result && (
          <section className="results" id="results" aria-labelledby="results-heading">
            <div className="results-heading-row">
              <div>
                <p className="section-kicker">COMPARISON COMPLETE</p>
                <h2 id="results-heading">Document changes</h2>
                <p>{original?.name} <span aria-hidden="true">→</span> {revised?.name}</p>
              </div>
              <button className="secondary-button" type="button" onClick={startAgain}>Start another</button>
            </div>

            <div className="summary-grid">
              <SummaryCard label="Total changes" count={summary.total_changes} kind="total" />
              <SummaryCard label="Additions" count={summary.additions} kind="addition" />
              <SummaryCard label="Deletions" count={summary.deletions} kind="deletion" />
              <SummaryCard label="Modifications" count={summary.modifications} kind="modification" />
            </div>

            <div className="results-toolbar">
              <div className="filter-group" aria-label="Filter changes">
                {FILTERS.map((item) => {
                  const count = item === "all" ? summary.total_changes : summary[`${item}s`];
                  return (
                    <button
                      type="button"
                      key={item}
                      className={filter === item ? "active" : ""}
                      onClick={() => setFilter(item)}
                      aria-pressed={filter === item}
                    >
                      {item === "all" ? "All" : `${item[0].toUpperCase()}${item.slice(1)}s`} <span>{count}</span>
                    </button>
                  );
                })}
              </div>
              <span className="processing-time">Processed in {(result.processing_ms / 1000).toFixed(1)} seconds</span>
            </div>

            <div className="change-list">
              {filteredChanges.length ? filteredChanges.map((change) => (
                <ChangeCard key={change.id} change={change} />
              )) : (
                <div className="empty-filter">No {filter}s were found.</div>
              )}
            </div>

            <div className="download-panel">
              <div>
                <span className="download-icon"><DocumentIcon /></span>
                <span>
                  <strong>Visual Word redline</strong>
                  <small>
                    {downloaded
                      ? "Downloaded and removed from temporary storage."
                      : secondsLeft > 0
                        ? `One-time download · Expires in ${formatTime(secondsLeft)}`
                        : "This download has expired. Run the comparison again."}
                  </small>
                </span>
              </div>
              <button
                type="button"
                className="download-button"
                onClick={handleDownload}
                disabled={!canDownload || status === "downloading"}
              >
                {status === "downloading" ? "Preparing…" : downloaded ? "Downloaded" : "Download redline"}
              </button>
            </div>

            {result.coverage?.does_not_yet_support?.length > 0 && (
              <details className="coverage-note">
                <summary>Current comparison coverage</summary>
                <p>The on-screen summary does not yet report formatting-only changes, images, embedded objects, exact text-box locations, or page numbers. Review the Word redline before acting on material correspondence.</p>
                {result.coverage?.redline_known_gaps?.length > 0 && (
                  <p className="coverage-warning">
                    The on-screen comparison found changes in {result.coverage.redline_known_gaps.join(" and ")},
                    but the comparison engine did not include those parts in the downloadable redline.
                  </p>
                )}
              </details>
            )}
          </section>
        )}
      </main>

      <footer>
        <span>Postbank Document Comparison · Internal proof of concept</span>
        <span>Comparison engine: wmlcomparer</span>
      </footer>
      <div className="sr-only" aria-live="polite">
        {status === "comparing" ? "Comparison in progress" : status === "complete" ? "Comparison complete" : ""}
      </div>
    </div>
  );
}
