import { useEffect, useState } from "react";
import { issueRecipients, issueInbox } from "./api.js";

export function IssueInbox({ onOpen, busy, refreshKey }) {
  const [items, setItems] = useState([]), [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0), [offset, setOffset] = useState(0);
  useEffect(() => {
    let active = true;
    const load = () => issueInbox(offset).then((value) => { if (active) { setItems(value); setError(""); } }).catch((e) => { if (active) setError(e.message); });
    load(); const timer = setInterval(load, 30000);
    return () => { active = false; clearInterval(timer); };
  }, [refreshKey, refresh, offset]);
  return <section className="history-panel" aria-labelledby="issue-inbox-heading">
    <div className="results-heading-row"><h2 id="issue-inbox-heading">Clarification and escalation inbox</h2><button className="secondary-button" disabled={busy} onClick={() => setRefresh(refresh + 1)}>Refresh issues</button></div>
    {error && <p role="alert">{error}</p>}
    {!items.length && <p>No requests assigned to you.</p>}
    <ul>{items.map((i) => <li key={i.id}><button className="history-link" disabled={busy} onClick={() => onOpen(i.comparison_id)}>{i.title} · {i.kind} · {i.document_side} page {i.page_number || "not recorded"}</button><span>{i.status} · {i.review_status.replaceAll("_", " ")}</span></li>)}</ul>
    <div className="history-pagination"><button className="secondary-button" disabled={busy || !offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous issues</button><button className="secondary-button" disabled={busy || items.length < 50} onClick={() => setOffset(offset + 50)}>More issues</button></div>
  </section>;
}

export function ReviewIssues({ task, user, onAction, busy }) {
  const [recipients, setRecipients] = useState([]), [error, setError] = useState("");
  const [form, setForm] = useState({ kind: "clarification", document_side: "redline", page_number: 1, reference: "", question: "", assigned_to: "" });
  const owner = task.status === "in_review" && task.claimed_by === user.id && user.roles.includes("staff") && user.department_id === task.department_id;
  useEffect(() => {
    let active = true;
    if (owner) issueRecipients(task.id).then((value) => { if (active) setRecipients(value); }).catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [task.id, owner]);
  async function submit(e) {
    e.preventDefault();
    if (await onAction("issues", { ...form, page_number: Number(form.page_number), assigned_to: form.kind === "clarification" ? form.assigned_to : "" })) {
      setForm((old) => ({ ...old, reference: "", question: "" }));
    }
  }
  const field = (e) => setForm({ ...form, [e.target.name]: e.target.value });
  return <section className="review-panel" aria-labelledby="issues-heading">
    <h3 id="issues-heading">Review issues · {task.open_issue_count} unresolved</h3>
    <p>{owner ? "Continue inspecting all pages and raise as many questions as needed. Open and answered issues block completion until the reviewer confirms their resolution." : user.roles.includes("manager") ? "Inspect the page reference and discussion, then provide guidance or require a document revision. The reviewer must confirm answered issues are resolved before completing the review." : "Respond to requests assigned to you. The reviewer must confirm that each issue is resolved before completing the review."}</p>
    {owner && <details className="review-history"><summary>Raise clarification or escalation</summary>
      <form className="metadata-grid review-response" onSubmit={submit}>
        {error && <p role="alert">{error}</p>}
        <label>Issue type<select name="kind" value={form.kind} onChange={field} disabled={busy}><option value="clarification">Request clarification</option><option value="escalation">Escalate to department manager</option></select></label>
        <label>Document reference<select name="document_side" value={form.document_side} onChange={field} disabled={busy}><option value="original">Original</option><option value="redline">Redline</option></select></label>
        <label>Page number<input name="page_number" type="number" min="1" required value={form.page_number} onChange={field} disabled={busy} /></label>
        <label>Paragraph reference or quoted text<textarea name="reference" required maxLength={2000} value={form.reference} onChange={field} disabled={busy} /></label>
        <label>Question or concern<textarea name="question" required maxLength={4000} value={form.question} onChange={field} disabled={busy} /></label>
        {form.kind === "clarification" ? <label>Responsible person<select name="assigned_to" required value={form.assigned_to} onChange={field} disabled={busy}><option value="">Select a person</option>{recipients.map((r) => <option key={r.id} value={r.id}>{r.name} · {r.department} · {r.email}</option>)}</select></label> : <p>This issue goes to managers in the owning department.</p>}
        <p>The recipient will be able to view this comparison and its documents. Delivery is currently in-app; email is not connected.</p>
        <button className="primary-button" disabled={busy || !form.reference.trim() || !form.question.trim()}>Send review issue</button>
      </form>
    </details>}
    {task.issues.map((issue, index) => <Issue key={issue.id} issue={issue} index={index} task={task} user={user} owner={owner} busy={busy} onAction={onAction} />)}
  </section>;
}

function Issue({ issue, index, task, user, owner, busy, onAction }) {
  const [comment, setComment] = useState(""), [outcome, setOutcome] = useState("answer");
  const active = ["available", "in_review"].includes(task.status);
  const recipient = user.id !== issue.created_by && (issue.kind === "clarification" ? issue.assigned_to === user.id : user.roles.includes("manager") && user.department_id === issue.department_id);
  async function act(action) { if (await onAction(`issues/${issue.id}/${action}`, { comment, outcome })) setComment(""); }
  return <article className="review-issue">
    <h4>Issue {index + 1} · {issue.kind} · {issue.status}</h4>
    <p><strong>{issue.document_side === "original" ? "Original" : "Redline"} page {issue.page_number || "not recorded (earlier review)"}</strong> · {issue.department} · {issue.assigned_name || "Department managers"}</p>
    <blockquote>{issue.reference}</blockquote><p>{issue.question}</p>
    <ol>{issue.messages.map((m) => <li key={m.id}><strong>{m.user_name}</strong> · {m.action} · {new Date(m.created_at).toLocaleString()}<p>{m.comment}</p></li>)}</ol>
    {active && (owner || (recipient && issue.status !== "resolved")) && <>
      <label>Issue {index + 1} response or resolution<textarea maxLength={4000} value={comment} onChange={(e) => setComment(e.target.value)} disabled={busy} /></label>
      {recipient && issue.kind === "escalation" && issue.status !== "resolved" && <label>Manager outcome<select value={outcome} onChange={(e) => setOutcome(e.target.value)} disabled={busy}><option value="answer">Provide decision to reviewer</option><option value="revision_required">Require document revision</option></select></label>}
      <div className="review-actions">
        {recipient && issue.status !== "resolved" && <button className="primary-button" disabled={busy || !comment.trim()} onClick={() => act("respond")}>Send response</button>}
        {owner && issue.status === "answered" && <button className="primary-button" disabled={busy || !comment.trim()} onClick={() => act("resolve")}>Confirm issue resolved</button>}
        {owner && issue.status !== "open" && <button className="secondary-button" disabled={busy || !comment.trim()} onClick={() => act("reopen")}>Request further response</button>}
      </div>
    </>}
  </article>;
}
