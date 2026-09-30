import { useEffect, useRef, useState } from "react";
import { notifications, markNotificationRead } from "./api.js";
import { reviewLabel } from "./ReviewPanel.jsx";
import logo from "./logo.jpg";

export function Icon({ name, size = 20 }) {
  const paths = {
    users: <><circle cx="9" cy="8" r="3" /><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 4v2" /></>,
    building: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h1m6 0h1M8 11h1m6 0h1M10 21v-6h4v6" /></>,
    settings: <><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="3" fill="white" /><circle cx="15" cy="17" r="3" fill="white" /></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    file: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M8 13h8M8 17h5" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    review: <><rect x="4" y="4" width="16" height="17" rx="2" /><path d="M9 3h6v3H9zM8 13l3 3 5-6" /></>,
    chat: <><path d="M21 12a9 9 0 0 1-9 9H3l2-5a9 9 0 1 1 16-4Z" /><path d="M8 10h8M8 14h5" /></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    back: <path d="M19 12H5m5-5-5 5 5 5" />,
    logout: <><path d="M9 4H4v16h5M10 12h11m-4-4 4 4-4 4" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    shield: <><path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6z" /><path d="m8 12 3 3 5-6" /></>,
    download: <><path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.15" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.file}</svg>;
}

export function Status({ value }) { return <span className={`ds-status ds-status-${value || 'unknown'}`}><i />{reviewLabel(value) || 'Processing'}</span>; }
export const dateLabel = (date) => date ? new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(date)) : '—';

function NotificationBell({ onOpen, busy, refreshKey }) {
  const [data, setData] = useState({ items: [], unread_count: 0 }), [open, setOpen] = useState(false), [error, setError] = useState('');
  const [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0), [reading, setReading] = useState(false);
  const [alertCount, setAlertCount] = useState(0), [alertPaused, setAlertPaused] = useState(false);
  const first = useRef(true), root = useRef(null), button = useRef(null);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const value = await notifications(offset); if (!active) return; setData(value); setError(''); if (first.current) { first.current = false; if (value.unread_count) setAlertCount(value.unread_count); } }
      catch (e) { if (active) setError(e.message); }
    };
    load(); const timer = setInterval(load, 30000); return () => { active = false; clearInterval(timer); };
  }, [offset, refresh, refreshKey]);
  useEffect(() => {
    if (!open) return;
    const outside = (e) => { if (!root.current?.contains(e.target)) setOpen(false); };
    const escape = (e) => { if (e.key === 'Escape') { setOpen(false); button.current?.focus(); } };
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);
  useEffect(() => {
    if (!alertCount || alertPaused) return;
    const timer = setTimeout(() => setAlertCount(0), 8000);
    return () => clearTimeout(timer);
  }, [alertCount, alertPaused]);
  async function read(item, navigate) {
    setReading(true);
    try { if (navigate && !(await onOpen(item.comparison_id))) return; await markNotificationRead(item.id); setRefresh((n) => n + 1); if (navigate) setOpen(false); }
    catch (e) { setError(e.message); } finally { setReading(false); }
  }
  return <div className="ds-notification-root" ref={root}>
    <button className="ds-icon-button ds-bell" ref={button} aria-label={`Notifications, ${data.unread_count} unread`} aria-expanded={open} aria-controls="ds-notifications" onClick={() => { setAlertCount(0); setOpen(!open); }}><Icon name="bell" />{data.unread_count > 0 && <span>{data.unread_count > 99 ? '99+' : data.unread_count}</span>}</button>
    {alertCount > 0 && <div className="ds-login-notice" onMouseEnter={() => setAlertPaused(true)} onMouseLeave={() => setAlertPaused(false)} onFocus={() => setAlertPaused(true)} onBlur={() => setAlertPaused(false)}>
      <span className="ds-login-notice-icon"><Icon name="bell" size={20} /></span><div role="status" aria-live="polite" aria-atomic="true"><strong>{alertCount} unread {alertCount === 1 ? 'notification' : 'notifications'}</strong><p>Open the bell to see your updates.</p></div><button className="ds-icon-button" aria-label="Dismiss notification alert" onClick={() => setAlertCount(0)}><Icon name="close" size={16} /></button>
    </div>}
    {open && <section className="ds-notifications" id="ds-notifications" aria-label="Notifications">
      <div className="ds-notification-heading"><div><h2>Notifications</h2><p>{data.unread_count ? `${data.unread_count} unread updates for you` : 'You’re all caught up'}</p></div><button className="ds-icon-button" aria-label="Close notifications" onClick={() => { setOpen(false); button.current?.focus(); }}><Icon name="close" size={18} /></button></div>
      {error && <p role="alert" className="ds-inline-error">{error}</p>}
      <div className="ds-notification-list">{!data.items.length && <div className="ds-empty"><Icon name="bell" size={30} /><h3>No updates yet</h3><p>Review requests and responses will appear here.</p></div>}{data.items.map((n) => <article key={n.id} className={!n.read_at ? 'is-unread' : ''}><span className="ds-notice-icon"><Icon name={n.event_type.includes('approv') ? 'check' : 'chat'} size={18} /></span><div><button className="ds-notification-link" disabled={busy || reading} onClick={() => read(n, true)}>{n.message}</button><small>{dateLabel(n.created_at)}</small>{!n.read_at && <button className="ds-text-button" disabled={reading} onClick={() => read(n, false)}>Mark as read</button>}</div>{!n.read_at && <i className="ds-unread-dot" />}</article>)}</div>
      <div className="ds-notification-footer"><button className="ds-text-button" onClick={() => setRefresh(refresh + 1)}>Refresh</button><div><button className="ds-icon-button" aria-label="Previous notifications" disabled={!offset || reading} onClick={() => setOffset(Math.max(0, offset - 30))}><Icon name="back" size={16} /></button><button className="ds-icon-button" aria-label="More notifications" disabled={data.items.length < 30 || reading} onClick={() => setOffset(offset + 30)}><Icon name="arrow" size={16} /></button></div></div>
    </section>}
  </div>;
}

export function DashboardShell({ user, page, navigate, busy, onOpen, refreshKey, onSignOut, children }) {
  const [menu, setMenu] = useState(false);
  const admin = user.roles.includes('administrator'), manager = user.roles.includes('manager');
  const staff = user.roles.includes('staff');
  const entries = admin ? [['overview', 'grid', 'Overview'], ['users', 'users', 'Users'], ['departments', 'building', 'Departments'], ['roles', 'shield', 'Access roles'], ['settings', 'settings', 'Settings']] : [['overview', 'grid', 'Overview'], ...(staff ? [['new', 'plus', 'New comparison'], ['documents', 'file', 'My documents']] : []), ...(manager ? [['queue', 'review', 'Department reviews'], ['escalations', 'shield', 'Escalations']] : staff ? [['queue', 'review', 'Department documents']] : []), ['requests', 'chat', 'Requests & responses']];
  const initials = user.full_name.split(' ').filter(Boolean).slice(0, 2).map((v) => v[0]).join('').toUpperCase();
  const label = entries.find(([id]) => id === page)?.[2] || (admin ? 'Account details' : 'Document workspace');
  useEffect(() => { if (!menu) return; const escape = (e) => { if (e.key === 'Escape') setMenu(false); }; document.addEventListener('keydown', escape); return () => document.removeEventListener('keydown', escape); }, [menu]);
  return <div className="ds-app">
    {menu && <button className="ds-mobile-overlay" aria-label="Close navigation" onClick={() => setMenu(false)} />}
    <aside className={`ds-sidebar ${menu ? 'is-open' : ''}`}>
      <a className="ds-brand" href="#" onClick={(e) => { e.preventDefault(); if (!busy) { navigate('overview'); setMenu(false); } }} aria-label="Postbank workspace home"><img src={logo} alt="Postbank" /><span>DOCUMENT WORKSPACE</span></a>
      <div className="ds-department"><span className="ds-department-icon"><Icon name="shield" size={18} /></span><div><strong>{user.department}</strong><small>Internal workspace</small></div></div>
      <p className="ds-nav-label">WORKSPACE</p><nav aria-label="Workspace navigation">{entries.map(([id, icon, title]) => <button key={id} disabled={busy} className={page === id ? 'is-active' : ''} aria-current={page === id ? 'page' : undefined} onClick={() => { navigate(id); setMenu(false); }}><Icon name={icon} /><span>{title}</span>{page === id && <i />}</button>)}</nav>
      <div className="ds-sidebar-bottom"><div className="ds-support"><Icon name="shield" size={18} /><p>{admin ? 'People, teams and access.' : 'Your documents.'}<br /><strong>{admin ? 'One managed workspace.' : 'One accountable workflow.'}</strong></p></div><div className="ds-profile"><span className="ds-avatar">{initials}</span><div><strong>{user.full_name}</strong><small>{admin ? 'Administrator' : manager ? (staff ? 'Manager · Staff' : 'Manager') : 'Staff'}</small></div><button className="ds-icon-button" aria-label="Sign out" title="Sign out" disabled={busy} onClick={onSignOut}><Icon name="logout" size={18} /></button></div></div>
    </aside>
    <div className="ds-main"><header className="ds-topbar"><div className="ds-breadcrumb"><button className="ds-icon-button ds-menu" aria-label="Open navigation" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="menu" /></button><span>Workspace</span><span>/</span><strong>{label}</strong></div><div className="ds-topbar-right"><span className="ds-date">{new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date())}</span>{!admin && <NotificationBell onOpen={onOpen} busy={busy} refreshKey={refreshKey} />}<span className="ds-avatar ds-avatar-small" title={user.full_name}>{initials}</span></div></header>
      <main className="ds-content" id="dashboard-content">{children}</main><footer className="ds-footer"><span>Postbank · Document Review</span><span>Internal use only</span></footer>
    </div>
  </div>;
}

export function DocumentTable({ rows, busy, onOpen, reviewer = false, emptyAction, query = '' }) {
  return <div className="ds-table-scroll"><table className="ds-table"><thead><tr><th>Document</th><th>Status</th><th>{reviewer ? 'Staff member' : 'Changes'}</th><th>Created</th><th><span className="sr-only">Open document</span></th></tr></thead><tbody>{rows.map((r) => <tr key={r.comparison_id}><td><div className="ds-document-cell"><span className="ds-file-tile"><Icon name="file" /></span><div><button className="ds-document-title" disabled={busy} onClick={() => onOpen(r.comparison_id)}>{r.title}</button><small>Staff review</small></div></div></td><td><Status value={r.status || r.review_status || r.processing_status} /></td><td>{reviewer ? r.claimed_by_name || 'Unclaimed' : r.total_changes ?? '—'}</td><td>{dateLabel(r.created_at)}</td><td><button className="ds-icon-button" aria-label={`Open ${r.title}`} disabled={busy} onClick={() => onOpen(r.comparison_id)}><Icon name="arrow" size={18} /></button></td></tr>)}</tbody></table>{!rows.length && <div className="ds-empty"><span className="ds-empty-icon"><Icon name="file" size={28} /></span><h3>{query ? 'No matching documents' : reviewer ? 'Your queue is clear' : 'Your documents will appear here'}</h3><p>{query ? 'Try another title or status filter.' : reviewer ? 'Comparisons assigned to your department will appear here for review.' : 'Start a comparison to keep versions, questions and decisions together.'}</p>{emptyAction}</div>}</div>;
}
