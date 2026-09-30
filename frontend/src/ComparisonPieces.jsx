import { useRef, useState } from "react";
function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function DocumentIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 2.75h6.7L18.25 7.3V21.25H7a2.25 2.25 0 0 1-2.25-2.25V5A2.25 2.25 0 0 1 7 2.75Z" />
      <path d="M13.25 3v4.75H18M8.5 12h6.75M8.5 15.5h6.75" />
    </svg>
  );
}

export function UploadCard({ label, helper, file, onFile, disabled }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [validationError, setValidationError] = useState("");

  function accept(candidate) {
    if (disabled || !candidate) return;
    const validation = onFile(candidate);
    if (validation?.ok === false) {
      setValidationError(validation.message);
      return;
    }
    setValidationError("");
  }

  return (
    <section
      className={`upload-card ${file ? "has-file" : ""} ${validationError ? "is-invalid" : ""}`}
      aria-label={`${label} document`}
    >
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
          const droppedFiles = event.dataTransfer.files;
          if (droppedFiles?.length > 1) {
            setValidationError("Please drag and drop one DOCX document at a time.");
            return;
          }
          accept(droppedFiles?.[0]);
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={disabled}
          onChange={(event) => {
            accept(event.target.files?.[0]);
            event.target.value = "";
          }}
          tabIndex="-1"
          aria-hidden="true"
        />
        <span className="document-icon"><DocumentIcon /></span>
        {file ? (
          <span className="selected-file">
            <strong>{file.name}</strong>
            <span>{formatBytes(file.size)}</span>
            <span className="upload-success"><span aria-hidden="true">✓</span> Document selected successfully</span>
          </span>
        ) : (
          <span className="drop-copy">
            <strong>Choose a Word document</strong>
            <span>or drag and drop a .docx file here</span>
          </span>
        )}
        <span className="browse-label">{file ? "Replace file" : "Browse files"}</span>
      </button>
      {validationError && (
        <p className="upload-validation" role="alert">
          <span aria-hidden="true">!</span> {validationError}
        </p>
      )}
    </section>
  );
}

function locationLabel(location = {}) {
  if (location.container === "table_row") {
    return `Table ${location.table_index}, row ${location.row_index}`;
  }
  if (location.container === "table_cell") {
    return `Table ${location.table_index}, row ${location.row_index}, cell ${location.cell_index}`;
  }
  const part = location.part === "document"
    ? "Document body"
    : (location.part || "").startsWith("header")
      ? "Header"
      : (location.part || "").startsWith("footer")
        ? "Footer"
        : location.part;
  return `${part}, paragraph ${location.paragraph_index}`;
}

export function ChangeCard({ change }) {
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
