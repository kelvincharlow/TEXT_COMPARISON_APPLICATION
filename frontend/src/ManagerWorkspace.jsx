import { useEffect, useState } from 'react';
import { issueInbox } from './api.js';
import { DocumentTable, Icon, Status } from './DashboardUI.jsx';
import './manager.css';

const activeReview = (issue) => ['available', 'in_review'].includes(issue.review_status);
const needsDecision = (issue) => issue.status === 'open' && activeReview(issue);
const issueLabel = (issue) => issue.status === 'resolved' ? 'Resolved' : !activeReview(issue) ? 'Review closed' : issue.status === 'answered' ? 'With staff' : 'Needs decision';

export function ManagerEscalations({ onOpen, busy, refreshKey, compact = false, navigate }) {
  const [items, setItems] = useState([]), [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [filter, setFilter] = useState('all'), [search, setSearch] = useState('');
  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const rows = await issueInbox(offset); if (active) { setItems(rows); setError(''); } }
      catch (e) { if (active) setError(e.message); }
      finally { if (active) setLoading(false); }
    };
    setLoading(true); load(); const timer = setInterval(load, 30000);
    return () => { active = false; clearInterval(timer); };
  }, [offset, refresh, refreshKey]);
  const escalations = items.filter((i) => i.kind === 'escalation');
  const matches = escalations.filter((i) => (!compact || needsDecision(i)) && (filter === 'all' || (filter === 'open' ? needsDecision(i) : filter === 'answered' ? i.status === 'answered' && activeReview(i) : i.status === 'resolved')) && `${i.title} ${i.question}`.toLowerCase().includes(search.toLowerCase()));
  const shown = compact ? matches.slice(0, 3) : matches;
  return <section className="ds-card mg-escalations" aria-label="Department escalations">
    <div className="ds-card-heading"><div><h2>{compact ? 'Escalations needing a decision' : 'Department escalation inbox'}</h2><p>{compact ? 'Open questions from your department staff.' : 'Each question stays linked to its document and page reference.'}</p></div>{compact ? <button className="ds-text-button" onClick={() => navigate('escalations')}>View all<Icon name="arrow" size={16} /></button> : <button className="ds-icon-button" aria-label="Refresh escalations" disabled={busy || loading} onClick={() => setRefresh((n) => n + 1)}><Icon name="refresh" size={18} /></button>}</div>
    {!compact && <div className="ds-list-toolbar"><div className="ds-filter-tabs" aria-label="Escalation filters">{[['all','All'],['open','Needs decision'],['answered','With staff'],['resolved','Resolved']].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div><label className="ds-search"><Icon name="search" size={17} /><input aria-label="Search escalations" placeholder="Search this page…" value={search} onChange={(e) => setSearch(e.target.value)} /></label></div>}
    {error && <p className="ds-inline-error" role="alert">{error}</p>}
    {loading ? <p className="ds-loading" role="status">Loading escalations…</p> : shown.length ? <div className="mg-issue-list">{shown.map((issue) => <article className="mg-issue" key={issue.id}><span className="mg-issue-icon"><Icon name="chat" size={21} /></span><div className="mg-issue-body"><div className="mg-issue-heading"><button className="ds-document-title" disabled={busy} onClick={() => onOpen(issue.comparison_id, 'issues')}>{issue.title}</button><span className={`mg-issue-status ${needsDecision(issue) ? 'needs-decision' : ''}`}>{issueLabel(issue)}</span></div><p className="mg-question">{issue.question}</p><div className="mg-issue-meta"><span>{issue.document_side === 'original' ? 'Original' : 'Redline'} · Page {issue.page_number || 'not recorded'}</span><Status value={issue.review_status} /></div><div className="mg-issue-actions"><button className="ds-text-button" disabled={busy} onClick={() => onOpen(issue.comparison_id, 'issues')}>{needsDecision(issue) ? 'Review escalation' : 'View discussion'}<Icon name="arrow" size={15} /></button><button className="ds-text-button" disabled={busy} onClick={() => onOpen(issue.comparison_id, 'preview')}><Icon name="file" size={15} />Document preview</button></div></div></article>)}</div> : <div className="ds-empty"><Icon name="shield" size={30} /><h3>{compact ? 'No decisions waiting in this view' : 'No matching escalations'}</h3><p>{compact ? 'Open escalations from the latest inbox page will appear here.' : 'Try another filter or inbox page. New department escalations appear here automatically.'}</p></div>}
    <div className="ds-list-footer"><span>{compact ? 'Based on the latest 50 inbox requests.' : `${matches.length} escalations on this page · Filters apply to 50 inbox requests per page`}</span>{!compact && <div><button className="ds-secondary" disabled={busy || loading || !offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><button className="ds-secondary" disabled={busy || loading || items.length < 50} onClick={() => setOffset(offset + 50)}>Next</button></div>}</div>
  </section>;
}

export function ManagerOverview({ queue, loading, busy, user, navigate, onOpen, refreshKey }) {
  const metrics = [
    ['Department reviews', queue.length, 'file', 'neutral'],
    ['Available for staff', queue.filter((r) => r.status === 'available').length, 'clock', 'gold'],
    ['Reviews in progress', queue.filter((r) => r.status === 'in_review').length, 'review', 'rose'],
    ['Approved', queue.filter((r) => r.status === 'approved').length, 'check', 'green'],
  ];
  return <>
    <div className="ds-page-heading"><div><p className="ds-eyebrow">{user.department.toUpperCase()} · MANAGER WORKSPACE</p><h1>Welcome back, {user.full_name.split(' ')[0]}.</h1><p>Keep reviews moving. Give your team clarity on the decisions that need you.</p></div><button className="ds-primary" disabled={busy} onClick={() => navigate('escalations')}><Icon name="shield" size={18} />Open escalations</button></div>
    <div className="ds-stats">{metrics.map(([label, count, icon, tone]) => <article className="ds-stat" key={label}><div><span>{label}</span><span className={`ds-stat-icon ${tone}`}><Icon name={icon} size={19} /></span></div><strong>{loading ? '—' : count}</strong><small>Within the latest 50 department reviews</small></article>)}</div>
    <div className="mg-overview-grid"><div className="mg-overview-main"><ManagerEscalations compact navigate={navigate} onOpen={onOpen} busy={busy} refreshKey={refreshKey} /><section className="ds-card"><div className="ds-card-heading"><div><h2>Department activity</h2><p>Current ownership and progress of your latest reviews.</p></div><button className="ds-text-button" onClick={() => navigate('queue')}>View reviews<Icon name="arrow" size={16} /></button></div>{loading ? <p className="ds-loading">Loading department reviews…</p> : <DocumentTable rows={queue.slice(0, 5)} reviewer busy={busy} onOpen={onOpen} />}</section></div>
    </div>
  </>;
}
