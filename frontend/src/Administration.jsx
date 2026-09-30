import { useEffect, useState } from "react";
import { DashboardShell, Icon } from "./DashboardUI.jsx";
import "./dashboard.css";
import "./administration.css";
import { adminSettings, adminUsers, adminWrite } from "./api.js";

const labels = { staff: "Staff", manager: "Manager", administrator: "Administrator" };
const empty = { full_name: "", employee_number: "", email: "", department_id: "", roles: ["staff"], password: "", active: true };

export default function Administration({ user, onSignOut }) {
  const [page, setPage] = useState("overview"), [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState({ roles: [], departments: [] });
  const [users, setUsers] = useState([]), [query, setQuery] = useState(""), [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [editing, setEditing] = useState(null), [form, setForm] = useState(empty);
  const [resetPassword, setResetPassword] = useState("");
  const [department, setDepartment] = useState({ id: "", name: "", previous_name: "" });
  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([adminSettings(), adminUsers(query, offset)]).then(([s, u]) => { if (active) { setSettings(s); setUsers(u); } }).catch((e) => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [query, offset, refresh]);
  async function perform(action, success) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); setNotice(success); setRefresh((n) => n + 1); return true; }
    catch (e) { setError(e.message); return false; }
    finally { setBusy(false); }
  }
  function edit(account) {
    setPage("account"); window.scrollTo({ top: 0, behavior: "instant" });
    setEditing(account); setForm(account ? { ...account, password: "" } : { ...empty, department_id: settings.departments[0]?.id || "" });
    setResetPassword(""); setError(""); setNotice("");
  }
  function field(e) { setForm({ ...form, [e.target.name]: e.target.value }); }
  async function save(e) {
    e.preventDefault();
    const body = { full_name: form.full_name, employee_number: form.employee_number, email: form.email, department_id: form.department_id, roles: form.roles };
    const okay = await perform(() => adminWrite(editing ? `users/${editing.id}` : 'users', editing ? { ...body, active: form.active, revision: editing.revision } : { ...body, password: form.password }, editing ? 'PUT' : 'POST'), editing ? 'Account updated. The user must sign in again.' : 'Account created. Share the initial password directly with the user.');
    if (okay) { setPage("users"); setEditing(null); setForm(empty); setResetPassword(""); }
  }
  async function reset(e) {
    e.preventDefault();
    if (await perform(() => adminWrite(`users/${editing.id}/password`, { password: resetPassword }), 'Password reset. Existing sessions have been revoked.')) setResetPassword("");
  }
  async function saveDepartment(e) {
    e.preventDefault();
    if (await perform(() => adminWrite(department.id ? `departments/${department.id}` : 'departments', { name: department.name, previous_name: department.previous_name }, department.id ? 'PUT' : 'POST'), 'Department saved.')) setDepartment({ id: "", name: "", previous_name: "" });
  }
  const outstanding = editing ? Object.values(editing.assignments).reduce((sum, n) => sum + n, 0) : 0;
  function navigate(next) {
    setPage(next); setError(""); setNotice("");
    if (next === 'overview') { setQuery(''); setOffset(0); }
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  const descriptions = {
    staff: 'Upload, compare, review, approve and download department documents. Ask for clarification or escalate when needed.',
    manager: 'Respond to escalations and manage review handovers within the department.',
    administrator: 'Manage accounts, departments and access. Document review requires a separate account.',
  };
  const heading = { overview: ['Administration', 'A clear view of your people, departments and application access.'], users: ['Users', 'Manage accounts, department membership and access in one place.'], account: [editing ? 'Edit account' : 'Create account', editing ? editing.email : 'Set up a colleague with the access they need.'], departments: ['Departments', 'Keep department membership and review queues organised.'], roles: ['Access roles', 'Three defined roles, with clear responsibilities.'], settings: ['Settings', 'Application integrations and delivery status.'] }[page];
  return <DashboardShell user={user} page={page} navigate={navigate} busy={busy} onSignOut={onSignOut}>
    <div className="ad-workspace">
    <div className="ds-page-heading"><div><p className="ds-eyebrow">ADMINISTRATOR WORKSPACE</p><h1>{heading[0]}</h1><p>{heading[1]}</p></div>{['overview', 'users'].includes(page) && <button className="ds-primary" disabled={busy || loading} onClick={() => edit(null)}><Icon name="plus" size={18} />New user</button>}{page === 'account' && <button className="ds-secondary" disabled={busy} onClick={() => navigate('users')}><Icon name="back" size={17} />Back to users</button>}</div>
    {error && <p className="ds-inline-error" role="alert">{error}</p>}
    {notice && <p className="ad-notice" role="status"><Icon name="check" size={18} />{notice}</p>}
    {page === 'overview' && <>
      <div className="ds-stats">{[
        ['Accounts in view', users.length, 'users', 'First 50 accounts, sorted by name'],
        ['Active accounts', users.filter((u) => u.active).length, 'check', 'Within the first 50 accounts'],
        ['Departments', settings.departments.length, 'building', 'Across the application'],
        ['Access roles', settings.roles.length, 'shield', 'Defined application roles'],
      ].map(([label, count, icon, note]) => <article className="ds-stat" key={label}><div><span>{label}</span><span className="ds-stat-icon gold"><Icon name={icon} size={19} /></span></div><strong>{loading ? '—' : count}</strong><small>{note}</small></article>)}</div>
      <div className="ad-overview-grid"><section className="ds-card"><div className="ds-card-heading"><div><h2>Account directory</h2><p>An alphabetical snapshot of accounts and their access status.</p></div><button className="ds-text-button" onClick={() => navigate('users')}>View all users<Icon name="arrow" size={16} /></button></div><div className="ad-directory">{loading ? <p role="status">Loading accounts…</p> : users.slice(0, 5).map((u) => <button className="ad-directory-row" key={u.id} onClick={() => edit(u)}><span className="ds-avatar">{u.full_name.split(' ').slice(0,2).map((n) => n[0]).join('')}</span><span className="ad-person"><strong>{u.full_name}</strong><small>{u.email}</small></span><span className="ad-department-label">{u.department}</span><span className={`ad-state ${u.active ? 'active' : ''}`}>{u.active ? 'Active' : 'Inactive'}</span><Icon name="arrow" size={16} /></button>)}{!loading && !users.length && <p>No accounts found.</p>}</div></section>
      </div>
    </>}
    {page === 'users' && <section className="ds-card ad-users">

      <div className="ds-list-toolbar"><label className="ds-search"><Icon name="search" size={18} /><input aria-label="Search users" value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0); }} maxLength={200} placeholder="Name, email or employee number" /></label><button className="ds-secondary" disabled={busy || loading} onClick={() => setRefresh(refresh + 1)}><Icon name="refresh" size={16} />Refresh users</button></div>
      {loading && <p className="ds-loading" role="status">Loading users…</p>}
      <div className="admin-table"><table className="ad-user-table"><thead><tr><th>Name / work email</th><th>Department</th><th>Roles</th><th>Status</th><th>Actions</th></tr></thead><tbody>
        {users.map((u) => <tr key={u.id}><td>{u.full_name}<small>{u.email}</small><small>{u.employee_number}</small></td><td data-label="Department">{u.department}</td><td data-label="Roles"><div className="ad-role-tags">{u.roles.map((r) => <span key={r}>{labels[r]}</span>)}</div></td><td data-label="Status"><span className={`ad-state ${u.active ? 'active' : ''}`}>{u.active ? 'Active' : 'Inactive'}</span></td><td><button className="secondary-button" disabled={busy} aria-label={`Edit ${u.email}`} onClick={() => edit(u)}>Edit</button></td></tr>)}
      </tbody></table></div>
      {!loading && !users.length && <div className="ds-empty"><Icon name="users" size={30} /><h3>No matching accounts</h3><p>Try a different name, email or employee number.</p></div>}
      <div className="ds-list-footer"><span>Showing {users.length} accounts · Up to 50 per page</span><div className="history-pagination"><button className="secondary-button" disabled={busy || loading || !offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous users</button><button className="secondary-button" disabled={busy || loading || users.length < 50} onClick={() => setOffset(offset + 50)}>More users</button></div></div>
    </section>}
    {page === 'account' && <section className="review-panel ad-account"><h2>{editing ? `Edit account: ${editing.email}` : 'Create account'}</h2>
      {outstanding > 0 && <p role="note">Current assignments: {editing.assignments.reviews} reviews, {editing.assignments.approvals} final approvals, {editing.assignments.clarifications} clarification requests. Changing this person's access does not reassign their work. Arrange handover before deactivation or a department/role change.</p>}
      <form className="metadata-grid" onSubmit={save}>
        <label>Full name<input name="full_name" required maxLength={200} value={form.full_name} onChange={field} disabled={busy} /></label>
        <label>Employee number<input name="employee_number" required maxLength={80} value={form.employee_number} onChange={field} disabled={busy} /></label>
        <label>Account work email<input name="email" type="email" required maxLength={254} value={form.email} onChange={field} disabled={busy} /></label>
        <label>Account department<select name="department_id" required value={form.department_id} onChange={field} disabled={busy}><option value="">Select a department</option>{settings.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <fieldset className="admin-roles" disabled={busy}><legend>Access roles</legend>{settings.roles.map((r) => <label key={r}><input type="checkbox" checked={form.roles.includes(r)} disabled={editing?.id === user.id} onChange={(e) => setForm({ ...form, roles: e.target.checked ? (r === "administrator" ? [r] : [...form.roles.filter((v) => v !== "administrator"), r]) : form.roles.filter((v) => v !== r) })} />{labels[r]}</label>)}</fieldset>
        {editing ? <label><input type="checkbox" checked={form.active} disabled={busy || editing.id === user.id} onChange={(e) => setForm({ ...form, active: e.target.checked })} />Account active</label> : <label>Initial password<input name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={form.password} onChange={field} disabled={busy} /><small>12–128 characters. Email delivery is disabled.</small></label>}
        {editing?.id === user.id && <p>Saving changes to your account signs you out. You cannot deactivate yourself or remove your own Administrator role.</p>}
        <div className="review-actions"><button className="primary-button" disabled={busy || !form.roles.length}>{editing ? 'Save account' : 'Create user'}</button>{editing && <button type="button" className="secondary-button" disabled={busy} onClick={() => navigate('users')}>Cancel editing</button>}</div>
      </form>
      {editing && <details className="review-history"><summary>Reset password</summary><form className="review-response" onSubmit={reset}><label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} disabled={busy} /></label><p>Resets the login lock and signs this user out of all sessions.</p><button className="secondary-button" disabled={busy}>Reset password</button></form></details>}
    </section>}
    {page === 'departments' && <div className="ad-departments-grid"><section className="ds-card"><div className="ds-card-heading"><div><h2>Department directory</h2><p>{settings.departments.length} departments in the application</p></div><Icon name="building" /></div><ul className="ad-department-list">{settings.departments.map((d) => <li key={d.id}><span className="ad-department-name"><Icon name="building" size={18} />{d.name}</span> <button className="secondary-button" disabled={busy} aria-label={`Rename ${d.name}`} onClick={() => (setDepartment({ ...d, previous_name: d.name }), document.getElementById('department-name')?.focus())}>Rename</button></li>)}</ul>
      </section><section className="review-panel"><h2>{department.id ? 'Rename department' : 'New department'}</h2><p>Departments connect people to their review queues.</p><form className="review-response" onSubmit={saveDepartment}><label>Department name<input id="department-name" required maxLength={120} value={department.name} disabled={busy} onChange={(e) => setDepartment({ ...department, name: e.target.value })} /></label><div className="review-actions"><button className="primary-button" disabled={busy}>{department.id ? 'Save department name' : 'Create department'}</button>{department.id && <button type="button" className="secondary-button" onClick={() => setDepartment({ id: '', name: '', previous_name: '' })}>Cancel rename</button>}</div></form>
      <p>Renaming preserves existing documents, memberships and review history.</p>
    </section></div>}
    {page === 'roles' && <><div className="ad-role-grid">{settings.roles.map((role) => <article className="ds-card ad-role-card" key={role}><span className="ds-stat-icon gold"><Icon name={role === 'administrator' ? 'settings' : role === 'staff' ? 'file' : role === 'manager' ? 'users' : 'shield'} size={22} /></span><h2>{labels[role]}</h2><p>{descriptions[role]}</p><span className="ad-role-type">{role === 'administrator' ? 'Administration access' : 'Document workflow access'}</span></article>)}</div><p className="ad-role-note">Assign roles when creating or editing a user. Document ownership is recorded as document metadata, not an access role.</p></>}
    {page === 'settings' && <section className="ds-card ad-settings"><span className="ds-stat-icon gold"><Icon name="settings" size={24} /></span><h2>Notifications & email</h2><div className="ad-setting-row"><div><strong>In-app notifications</strong><p>Review requests and responses appear inside the document workspace.</p></div><span className="ad-state active">Enabled</span></div><div className="ad-setting-row"><div><strong>Email integration</strong><p>{settings.email?.status || 'Delivery disabled.'}</p><p>Work emails are stored as contact details. Email delivery can be connected after Postbank IT confirms the integration method.</p></div><span className="ad-state">Not connected</span></div></section>}
    </div>
  </DashboardShell>;
}
