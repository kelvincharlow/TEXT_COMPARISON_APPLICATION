import { useEffect, useState } from "react";
import { compareDocuments, downloadRedline, departments, comparisonHistory, getComparison, reviewAction, uploadRevision, reviewQueue } from "./api.js";
import { DashboardShell, Icon, Status, DocumentTable, dateLabel } from "./DashboardUI.jsx";
import { UploadCard, ChangeCard } from "./ComparisonPieces.jsx";
import DocumentPreview from "./DocumentPreview.jsx";
import { ReviewPanel } from "./ReviewPanel.jsx";
import { ReviewIssues, IssueInbox } from "./ReviewIssues.jsx";
import { RevisionPanel } from "./WorkflowPanel.jsx";
import { ManagerOverview, ManagerEscalations } from "./ManagerWorkspace.jsx";
import "./dashboard.css";

export default function Dashboard({ user, onSignOut }) {
  const [page, setPage] = useState('overview'), [detailTab, setDetailTab] = useState('preview');
  const [queue, setQueue] = useState([]), [queueOffset, setQueueOffset] = useState(0), [loading, setLoading] = useState(true);
  const [search, setSearch] = useState(''), [filter, setFilter] = useState('all');
  const canCompare = user.roles.includes('staff'), isReviewer = user.roles.includes('staff'), isManager = user.roles.includes('manager');
  const hasQueue = isReviewer || isManager;

  const [original, setOriginal] = useState(null), [revised, setRevised] = useState(null);
  const [result, setResult] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [history, setHistory] = useState([]), [offset, setOffset] = useState(0), [refreshKey, setRefreshKey] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [departmentList, setDepartmentList] = useState([]);
  const [metadata, setMetadata] = useState({ title: "", owning_department_id: user.department_id, document_type: "",
    responsible_officer: user.full_name, work_email: user.email, revision_source: "", revision_contact: "", review_type: "standard" });
  useEffect(() => {
    let active = true;
    Promise.all([departments(), comparisonHistory()]).then(([d, h]) => { if (active) { setDepartmentList(d); setHistory(h); } }).catch((e) => { if (active) setError(e.message); }).finally(() => { if (active) setHistoryLoading(false); });
    return () => { active = false; };
  }, []);
  async function refreshHistory(next = offset) {
    setHistoryLoading(true);
    try { setHistory(await comparisonHistory(next)); setOffset(next); setRefreshKey((n) => n + 1); }
    finally { setHistoryLoading(false); }
  }
  async function openSaved(id, tab) {
    setBusy(true); setError("");
    try { setResult(await getComparison(id)); setOriginal(null); setRevised(null); setPage("detail"); if (tab || result?.comparison_id !== id) setDetailTab(tab || "preview"); window.scrollTo({ top: 0, behavior: 'instant' }); return true; }
    catch (e) { setError(e.message); return false; }
    finally { setBusy(false); }
  }
  async function action(route, body = {}) {
    if (!result?.review_task) return false;
    setBusy(true); setError("");
    try {
      await reviewAction(result.review_task.id, route, { revision: result.review_task.revision, ...body });
      setResult(await getComparison(result.comparison_id)); await refreshHistory(); return true;
    } catch (e) {
      setError(e.message);
      if (e.status === 409) { try { setResult(await getComparison(result.comparison_id)); } catch { /* Preserve conflict. */ } }
      return false;
    } finally { setBusy(false); }
  }
  function chooseFile(setter) {
    return (file) => {
      if (!file.name.toLowerCase().endsWith('.docx') || !file.size || file.size > 25 * 1024 * 1024) return { ok: false, message: 'Choose a nonempty DOCX file no larger than 25 MB.' };
      setter(file); setError(""); return { ok: true };
    };
  }
  async function compare(e) {
    e.preventDefault(); setBusy(true); setError("");
    try { setResult(await compareDocuments(original, revised, metadata)); setPage("detail"); setDetailTab("preview"); await refreshHistory(0); }
    catch (e) { setError(e.message); try { await refreshHistory(0); } catch { /* Preserve comparison error. */ } }
    finally { setBusy(false); }
  }
  async function corrected(file) {
    setBusy(true); setError("");
    try { setResult(await uploadRevision(result.comparison_id, result.review_task.revision, file)); setDetailTab("preview"); await refreshHistory(0); }
    catch (e) { setError(e.message); try { setResult(await getComparison(result.comparison_id)); await refreshHistory(0); } catch { /* Preserve upload error. */ } }
    finally { setBusy(false); }
  }
  async function download() {
    setBusy(true); setError("");
    try {
      const blob = await downloadRedline(result.download.url); const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'postbank-comparison-visual-redline.docx'; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const field = (e) => setMetadata({ ...metadata, [e.target.name]: e.target.value });

  useEffect(() => {
    let active = true;
    if (!hasQueue) { setLoading(false); return; }
    setLoading(true);
    reviewQueue(queueOffset).then((rows) => { if (active) setQueue(rows); }).catch((e) => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [queueOffset, refreshKey, hasQueue]);
  function navigate(next) {
    setPage(next); setSearch(''); setFilter('all'); setError('');
    if (next === 'overview') { setQueueOffset(0); refreshHistory(0).catch((e) => setError(e.message)); }
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  const scopedRows = isReviewer ? queue : history;
  const overviewLoading = isReviewer ? loading : historyLoading;
  function tabKeyDown(event, index) {
    const next = { ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault(); setDetailTab(tabs[next][0]); document.getElementById(`ds-tab-${tabs[next][0]}`)?.focus();
  }
  const status = (r) => r.status || r.review_status || r.processing_status;
  const metrics = [
    { label: isReviewer ? 'Recent department reviews' : 'Recent comparisons', value: scopedRows.length, icon: 'file', tone: 'neutral' },
    { label: isReviewer ? 'Available to claim' : 'Awaiting review', value: scopedRows.filter((r) => status(r) === 'available').length, icon: 'clock', tone: 'gold' },
    { label: isReviewer ? 'My active reviews' : 'Returned for revision', value: scopedRows.filter((r) => isReviewer ? r.claimed_by === user.id && status(r) === 'in_review' : status(r) === 'revision_required').length, icon: isReviewer ? 'review' : 'chat', tone: 'rose' },
    { label: 'Approved', value: scopedRows.filter((r) => status(r) === 'approved').length, icon: 'check', tone: 'green' },
  ];
  const listRows = page === 'queue' ? queue : history;
  const filtered = listRows.filter((r) => r.title.toLowerCase().includes(search.toLowerCase()) && (filter === 'all' || (filter === 'mine' ? r.claimed_by === user.id : status(r) === filter)));
  const tabs = [['preview', 'Document preview', 'file'], ['decisions', isManager ? 'Review & handover' : 'Review & decisions', 'review'], ['issues', `Issues${result?.review_task ? ` · ${result.review_task.open_issue_count}` : ''}`, 'chat'], ['versions', 'Versions & history', 'clock'], ['changes', 'Change reference', 'search']];
  return <DashboardShell user={user} page={page} navigate={navigate} busy={busy} onOpen={openSaved} refreshKey={refreshKey} onSignOut={onSignOut}>
    {error && <div className="ds-inline-error" role="alert">{error}<button className="ds-icon-button" aria-label="Dismiss error" onClick={() => setError('')}><Icon name="close" size={16} /></button></div>}
    {page === 'overview' && isManager && <ManagerOverview queue={queue} loading={loading} busy={busy} user={user} navigate={navigate} onOpen={openSaved} refreshKey={refreshKey} />}
    {page === 'escalations' && isManager && <><div className="ds-page-heading"><div><p className="ds-eyebrow">{user.department.toUpperCase()} MANAGEMENT</p><h1>Escalations</h1><p>Inspect the document, consider the concern, and send a decision to the reviewer.</p></div></div><ManagerEscalations onOpen={openSaved} busy={busy} refreshKey={refreshKey} /></>}
    {page === 'overview' && !isManager && <>
      <div className="ds-page-heading"><div><p className="ds-eyebrow">YOUR WORKSPACE, AT A GLANCE</p><h1>Welcome back, {user.full_name.split(' ')[0]}.</h1><p>{isReviewer ? 'Upload, inspect and approve your department’s documents in one place.' : 'Every document, version and decision. All in one place.'}</p></div><button className="ds-primary" disabled={busy} onClick={() => navigate('new')}><Icon name="plus" size={18} />New comparison</button></div>
      <div className="ds-stats">{metrics.map((m) => <article className="ds-stat" key={m.label}><div><span>{m.label}</span><span className={`ds-stat-icon ${m.tone}`}><Icon name={m.icon} size={19} /></span></div><strong>{overviewLoading ? '—' : m.value}</strong><small>{m.label === 'My active reviews' ? 'Claimed by you, in this view' : 'In your recent document activity'}</small></article>)}</div>
      <div className="ds-overview-grid"><section className="ds-card ds-recent"><div className="ds-card-heading"><div><h2>{isReviewer ? 'Department activity' : 'Recent documents'}</h2><p>Your latest comparisons and their progress.</p></div><button className="ds-text-button" onClick={() => navigate(hasQueue ? 'queue' : 'documents')}>View all <Icon name="arrow" size={15} /></button></div><DocumentTable rows={scopedRows.slice(0, 5)} busy={busy} reviewer={isReviewer} onOpen={openSaved} emptyAction={!isReviewer && <button className="ds-primary" onClick={() => navigate('new')}><Icon name="plus" size={16} />Start a comparison</button>} /><div className="ds-card-footnote">Overview counts reflect the latest 50 {isReviewer ? 'department reviews' : 'comparisons'}.</div></section>

      </div>
    </>}
    {['documents', 'queue'].includes(page) && <>
      <div className="ds-page-heading"><div><p className="ds-eyebrow">{user.department.toUpperCase()} WORKSPACE</p><h1>{page === 'queue' ? (isManager ? 'Department reviews' : 'Department documents') : 'My documents'}</h1><p>{page === 'queue' ? (isManager ? 'Monitor department progress and arrange reviewer handovers.' : 'Find your next review, or pick up where you left off.') : 'A complete trail of your comparisons and document versions.'}</p></div>{canCompare && <button className="ds-primary" onClick={() => navigate('new')}><Icon name="plus" size={18} />New comparison</button>}</div>
      <section className="ds-card"><div className="ds-list-toolbar"><div className="ds-filter-tabs" aria-label="Document status filters">{[['all','All documents'],...(page === 'queue' ? [['available','Available'], isManager ? ['in_review','In review'] : ['mine','Assigned to me']] : [['revision_required','Needs revision']]),['approved','Approved']].map(([id,title]) => <button key={id} aria-pressed={filter === id} onClick={() => setFilter(id)}>{title}</button>)}</div><div className="ds-list-tools"><label className="ds-search"><Icon name="search" size={17} /><input aria-label="Search document titles" placeholder="Search this page…" value={search} onChange={(e) => setSearch(e.target.value)} /></label><button className="ds-icon-button" aria-label={page === 'queue' ? 'Refresh queue' : 'Refresh documents'} disabled={busy} onClick={() => refreshHistory().catch((e) => setError(e.message))}><Icon name="refresh" size={18} /></button></div></div>
        {(page === 'queue' ? loading : historyLoading) && <p className="ds-loading" role="status">Loading documents…</p>}
        <DocumentTable rows={filtered} query={search || (filter !== 'all' ? filter : '')} reviewer={page === 'queue'} onOpen={openSaved} busy={busy} />
        <div className="ds-list-footer"><span>{filtered.length} of {listRows.length} documents on this page · Filters apply to this page</span><div><button className="ds-secondary" disabled={busy || (page === 'queue' ? loading || !queueOffset : historyLoading || !offset)} onClick={() => page === 'queue' ? setQueueOffset(Math.max(0, queueOffset - 50)) : refreshHistory(Math.max(0, offset - 50)).catch((e) => setError(e.message))}>Previous</button><button className="ds-secondary" disabled={busy || (page === 'queue' ? loading : historyLoading) || listRows.length < 50} onClick={() => page === 'queue' ? setQueueOffset(queueOffset + 50) : refreshHistory(offset + 50).catch((e) => setError(e.message))}>Next</button></div></div>
      </section>
    </>}
    {page === 'new' && canCompare && <>
      <div className="ds-page-heading"><div><p className="ds-eyebrow">START SOMETHING CLEAR</p><h1>New comparison</h1><p>Add the document details, then choose the two versions to compare.</p></div><span className="ds-format-badge"><Icon name="file" size={17} />Word documents · Up to 25 MB each</span></div>
      <form className="ds-card ds-compare-form" onSubmit={compare}>
        <div className="ds-form-section"><div className="ds-section-intro"><span>01</span><div><h2>Document details</h2><p>Record who is responsible for this document.</p></div></div><fieldset className="metadata-grid" disabled={busy}>
          <label>Document title<input name="title" required maxLength={255} value={metadata.title} onChange={field} placeholder="e.g. Procurement policy — September revision" /></label>
          <label>Owning department<select name="owning_department_id" required value={metadata.owning_department_id} onChange={field}>{departmentList.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}</select></label>
          <label>Document type<input name="document_type" required maxLength={120} value={metadata.document_type} onChange={field} placeholder="Policy, contract, letter…" /></label>
          <label>Responsible officer<input name="responsible_officer" required maxLength={200} value={metadata.responsible_officer} onChange={field} /></label>
          <label>Work email<input name="work_email" required type="email" maxLength={254} value={metadata.work_email} onChange={field} /></label>
          <label>Revision source<input name="revision_source" required maxLength={200} value={metadata.revision_source} onChange={field} placeholder="Department or source of the revision" /></label>
          <label>Revision contact <small>Optional</small><input name="revision_contact" maxLength={200} value={metadata.revision_contact} onChange={field} placeholder="Name of the revision contact" /></label>
        </fieldset></div>
        <div className="ds-form-section"><div className="ds-section-intro"><span>02</span><div><h2>Choose document versions</h2><p>Keep the earlier version on the left and the revised version on the right.</p></div></div><div className="upload-grid"><UploadCard label="Original" helper="The earlier version" file={original} onFile={chooseFile(setOriginal)} disabled={busy} /><button className="ds-icon-button ds-swap" type="button" disabled={busy} aria-label="Swap original and revised documents" onClick={() => { setOriginal(revised); setRevised(original); }}><Icon name="refresh" size={18} /></button><UploadCard label="Revised" helper="The newer version" file={revised} onFile={chooseFile(setRevised)} disabled={busy} /></div></div>
        <div className="ds-form-footer"><p><Icon name="shield" size={17} />Versions and decisions stay in your document history.</p><button className="ds-primary" disabled={busy || !original || !revised}>{busy ? 'Comparing documents…' : 'Compare documents'}<Icon name="arrow" size={18} /></button></div>
      </form>
    </>}
    {page === 'requests' && <><div className="ds-page-heading"><div><p className="ds-eyebrow">KEEP THE CONVERSATION MOVING</p><h1>Requests & responses</h1><p>Clarifications and escalations that need your attention.</p></div></div><IssueInbox onOpen={(id) => openSaved(id, 'issues')} busy={busy} refreshKey={refreshKey} /></>}

    {page === 'detail' && result && <section id="results" className="ds-document-workspace" aria-labelledby="results-heading">
      <button className="ds-text-button ds-back" disabled={busy} onClick={() => navigate(hasQueue ? 'queue' : 'documents')}><Icon name="back" size={16} />{isManager ? 'Back to department reviews' : isReviewer ? 'Back to department documents' : 'Back to my documents'}</button>
      <div className="ds-page-heading"><div><div className="ds-document-kicker"><span>Staff review</span><span>Round {result.round_number || 1}</span></div><h1 id="results-heading">{result.metadata.title}</h1><p>{result.metadata.document_type} <span>·</span> {result.metadata.responsible_officer} <span>·</span> {dateLabel(result.created_at)}</p></div><div className="ds-detail-actions"><button className="ds-icon-button" aria-label="Refresh document review" disabled={busy} onClick={() => openSaved(result.comparison_id)}><Icon name="refresh" /></button><button className="ds-secondary" disabled={busy || !result.download?.available} onClick={download}><Icon name="download" size={17} />Download redline</button></div></div>
      <div className="ds-document-summary"><Status value={result.review_task?.status || result.processing_status} /><span>{result.summary?.total_changes || 0} detected changes</span><span>{result.review_task?.open_issue_count || 0} unresolved issues</span><span>{result.review_task?.claimed_by_name ? `Staff: ${result.review_task.claimed_by_name}` : 'Not yet claimed'}</span></div>
      {result.processing_status === 'failed' && <p className="ds-inline-error">Comparison processing failed. Documents remain saved in version history; retry a corrected upload from the preceding comparison.</p>}
      {detailTab === 'preview' && isReviewer && result.review_task?.status === 'available' && result.review_task.department_id === user.department_id && <div className="ds-claim-banner"><div><strong>This document is ready for review</strong><p>Claim it to record decisions and raise clarification requests.</p></div><button className="ds-primary" disabled={busy} onClick={() => action('claim')}><Icon name="review" size={18} />Start review</button></div>}
      <div className="ds-detail-tabs" role="tablist" aria-label="Document sections">{tabs.map(([id,title,icon], index) => <button key={id} id={`ds-tab-${id}`} role="tab" tabIndex={detailTab === id ? 0 : -1} onKeyDown={(event) => tabKeyDown(event, index)} aria-selected={detailTab === id} aria-controls={`ds-panel-${id}`} onClick={() => setDetailTab(id)}><Icon name={icon} size={17} />{title}</button>)}</div>
      <div className="ds-tab-panel" id="ds-panel-preview" role="tabpanel" aria-labelledby="ds-tab-preview" hidden={detailTab !== 'preview'}>{result.download?.available ? <DocumentPreview key={`preview-${result.comparison_id}`} comparisonId={result.comparison_id} autoOpen /> : <div className="ds-empty"><Icon name="file" size={32} /><h3>Preview unavailable</h3><p>Download the saved documents from Versions & history.</p></div>}<div className="ds-preview-next"><p>{isManager ? 'Use Issues to respond to escalations, or arrange a reviewer handover.' : 'Finished inspecting? Record your decision or raise a question.'}</p><button className="ds-secondary" onClick={() => setDetailTab('issues')}>{isManager ? 'Respond to issues' : 'Raise or view issues'}<Icon name="chat" size={17} /></button><button className="ds-primary" onClick={() => setDetailTab('decisions')}>{isManager ? 'Review & handover' : 'Review & decisions'}<Icon name="arrow" size={17} /></button></div></div>
      <div className="ds-tab-panel" id="ds-panel-decisions" role="tabpanel" aria-labelledby="ds-tab-decisions" hidden={detailTab !== 'decisions'}>{result.review_task ? <><ReviewPanel key={result.review_task.id} task={result.review_task} user={user} onAction={action} busy={busy} /></> : <p>No review task is available for this comparison.</p>}</div>
      <div className="ds-tab-panel" id="ds-panel-issues" role="tabpanel" aria-labelledby="ds-tab-issues" hidden={detailTab !== 'issues'}>{result.review_task ? <ReviewIssues key={`issues-${result.review_task.id}`} task={result.review_task} user={user} onAction={action} busy={busy} /> : <p>No review issues are available.</p>}</div>
      <div className="ds-tab-panel" id="ds-panel-versions" role="tabpanel" aria-labelledby="ds-tab-versions" hidden={detailTab !== 'versions'}><div className="ds-version-downloads">{result.versions.map((v) => <a key={v.id} href={v.download_url}><span className="ds-file-tile"><Icon name="file" /></span><span><strong>Version {v.version_number}{v.current_approved ? ' · Current Approved Version' : ''}</strong><small>{v.file_name}</small></span><Icon name="download" size={18} /></a>)}</div><RevisionPanel key={result.comparison_id} result={result} onUpload={corrected} onOpen={openSaved} busy={busy} /><p className="ds-reference-id">Comparison ID: {result.comparison_id}</p></div>
      <div className="ds-tab-panel" id="ds-panel-changes" role="tabpanel" aria-labelledby="ds-tab-changes" hidden={detailTab !== 'changes'}><div className="ds-card-heading"><div><h2>Detected changes</h2><p>Reference only. Review and approve the whole document.</p></div><span className="ds-format-badge">{result.changes.length} changes</span></div>{result.changes.map((c) => <ChangeCard key={c.id} change={c} />)}{!result.changes.length && <p>No text changes were detected.</p>}{result.coverage?.does_not_yet_support?.length > 0 && <details className="coverage-note"><summary>Comparison coverage</summary><p>Formatting-only changes, images, embedded objects and exact text-box locations may not appear in the list. Inspect the redline for material changes.</p></details>}</div>
    </section>}
  </DashboardShell>;
}
