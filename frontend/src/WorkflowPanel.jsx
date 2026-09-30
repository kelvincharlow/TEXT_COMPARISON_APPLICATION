import { useState } from "react";
import { reviewLabel } from "./ReviewPanel.jsx";

export function RevisionPanel({ result, onUpload, onOpen, busy }) {
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  function choose(event) {
    const candidate = event.target.files?.[0]; setFile(null); setError("");
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith(".docx") || !candidate.size || candidate.size > 25 * 1024 * 1024) {
      setError("Choose a nonempty DOCX file no larger than 25 MB."); event.target.value = ""; return;
    }
    setFile(candidate);
  }
  return <section className="review-panel" aria-label="Version and comparison history">
    <h3>Document history · Round {result.round_number || 1}</h3>
    <ul className="family-history">{result.family_history?.map((item) => <li key={item.comparison_id}>
      <button className="history-link" disabled={busy || item.comparison_id === result.comparison_id} onClick={() => onOpen(item.comparison_id)}>
        Round {item.round_number} · Version {item.version_number} · {reviewLabel(item.status)}{item.current_approved ? " · Current Approved Version" : ""}
      </button>
    </li>)}</ul>
    {result.previous_comparison_id && <button className="secondary-button" disabled={busy} onClick={() => onOpen(result.previous_comparison_id)}>Open preceding comparison</button>}
    {result.can_upload_revision && <form className="review-response" onSubmit={(event) => { event.preventDefault(); if (file) onUpload(file); }}>
      <p>Upload the corrected document. It will be compared with original version {result.versions?.[0]?.version_number}; previous versions and decisions stay in history.</p>
      <label>Corrected Word document<input type="file" accept=".docx" disabled={busy} onChange={choose} required /></label>
      {error && <p role="alert">{error}</p>}
      <button className="primary-button" disabled={busy || !file}>{busy ? "Processing corrected document…" : "Upload corrected version"}</button>
    </form>}
  </section>;
}
