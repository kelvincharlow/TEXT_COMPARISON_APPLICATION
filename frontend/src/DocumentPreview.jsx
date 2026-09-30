import { useEffect, useState } from "react";
import { preparePreview } from "./api.js";

function PageImage({ url, label }) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  return <>
    {!loaded && !error && <p role="status">Loading {label.toLowerCase()}…</p>}
    {error && <p role="alert">Unable to load this page. <button className="secondary-button" onClick={() => { setError(false); setLoaded(false); setRetry(retry + 1); }}>Retry page</button></p>}
    <img src={`${url}?retry=${retry}`} alt={label} hidden={error} onLoad={() => setLoaded(true)} onError={() => setError(true)} />
  </>;
}

export default function DocumentPreview({ comparisonId, autoOpen = false }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [visible, setVisible] = useState(false);
  const [linked, setLinked] = useState(true);
  const [pages, setPages] = useState({ original: 1, redline: 1 });
  const [zoom, setZoom] = useState(100);
  useEffect(() => {
    if (!autoOpen) return;
    let active = true;
    setVisible(true); setBusy(true);
    preparePreview(comparisonId).then((value) => { if (active) { setData(value); setError(""); } }).catch((e) => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [comparisonId, autoOpen]);
  async function open() {
    setVisible(true);
    if (data) return;
    setBusy(true); setError("");
    try { setData(await preparePreview(comparisonId)); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  const maximum = data ? Math.max(data.original.page_count, data.redline.page_count) : 1;
  function selectPage(kind, value) {
    const page = Number(value);
    const limit = linked ? maximum : data[kind].page_count;
    if (!Number.isInteger(page) || page < 1 || page > limit) return;
    setPages((old) => linked ? { original: page, redline: page } : { ...old, [kind]: page });
  }
  function link(checked) {
    setLinked(checked);
    setPages((old) => checked ? { original: old.original, redline: old.original } : {
      original: Math.min(old.original, data.original.page_count), redline: Math.min(old.redline, data.redline.page_count),
    });
  }
  return <section className="document-preview" aria-labelledby="preview-heading">
    <div className="results-heading-row"><h3 id="preview-heading">Original and redline · Page preview</h3>
      <button className="secondary-button" disabled={busy} onClick={() => visible ? setVisible(false) : open()}>{visible ? "Hide preview" : "Open side-by-side preview"}</button></div>
    {visible && <>
      <p>Compare rendered pages side by side. Redline markup can shift page breaks; turn off linked pages to align the sections you need. Rendering may differ from Microsoft Word.</p>
      {busy && <p role="status">Preparing document pages… This may take a moment.</p>}
      {error && <p role="alert">{error} <button className="secondary-button" onClick={open}>Retry preview</button></p>}
      {data && <>
        <div className="preview-controls">
          <label><input type="checkbox" checked={linked} onChange={(e) => link(e.target.checked)} /> Link page navigation</label>
          <label>Preview zoom <select value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>{[100, 125, 150, 200].map((n) => <option key={n} value={n}>{n}%</option>)}</select></label>
          {linked && <div className="preview-pagination">
            <button className="secondary-button" disabled={pages.original <= 1} onClick={() => selectPage("original", pages.original - 1)}>Previous page</button>
            <label>Page <input type="number" min="1" max={maximum} value={pages.original} onChange={(e) => selectPage("original", e.target.value)} /></label><span>of {maximum}</span>
            <button className="secondary-button" disabled={pages.original >= maximum} onClick={() => selectPage("original", pages.original + 1)}>Next page</button>
          </div>}
        </div>
        <div className="preview-columns">{["original", "redline"].map((kind) => {
          const title = kind === "original" ? "Original" : "Redline";
          return <section className="preview-column" key={kind} aria-label={`${title} document preview`}>
            <h4>{title} · {data[kind].page_count} {data[kind].page_count === 1 ? "page" : "pages"}</h4>
            {!linked && <div className="preview-pagination">
              <button className="secondary-button" aria-label={`Previous ${kind} page`} disabled={pages[kind] <= 1} onClick={() => selectPage(kind, pages[kind] - 1)}>Previous</button>
              <label>{title} page <input type="number" min="1" max={data[kind].page_count} value={pages[kind]} onChange={(e) => selectPage(kind, e.target.value)} /></label>
              <button className="secondary-button" aria-label={`Next ${kind} page`} disabled={pages[kind] >= data[kind].page_count} onClick={() => selectPage(kind, pages[kind] + 1)}>Next</button>
            </div>}
            <div className="preview-viewport"><div className="preview-sheet" style={{ width: `${zoom}%` }}>
              {pages[kind] > data[kind].page_count ? <p>No {kind} page {pages[kind]}. This document ends at page {data[kind].page_count}.</p> :
                <PageImage key={`${kind}-${pages[kind]}`} url={`${data[kind].page_url}${pages[kind]}`} label={`${title} page ${pages[kind]}`} />}
            </div></div>
          </section>;
        })}</div>
      </>}
    </>}
  </section>;
}
