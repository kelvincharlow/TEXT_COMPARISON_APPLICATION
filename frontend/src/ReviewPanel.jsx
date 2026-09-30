import { useEffect, useState } from "react";
import { eligibleReviewers } from "./api.js";

export function reviewLabel(value) {
  return { available: "Available", in_review: "In Review", clarification_requested: "Awaiting Clarification",
    escalated: "Escalated", revision_required: "Revision Required", awaiting_final_approval: "Awaiting Final Approval",
    approved: "Approved", accepted: "Accepted", rejected: "Rejected", unresolved: "Unresolved" }[value] || value;
}

export function ReviewPanel({ task, user, onAction, busy }) {
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  useEffect(() => { setConfirmed(false); }, [task?.revision]);
  if (!task) return null;
  const reviewer = user.roles.includes("staff") && user.department_id === task.department_id;
  const owner = reviewer && task.claimed_by === user.id;
  const canComplete = task.open_issue_count === 0;
  return <section className="review-panel" aria-labelledby="review-heading">
    <h3 id="review-heading">{task.queue_name}</h3>
    <p className="review-status" role="status">{reviewLabel(task.status)}{task.claimed_by_name ? ` · Staff: ${task.claimed_by_name}` : ""}</p>
    <p>{task.open_issue_count} unresolved review issues</p>
    {task.status === "available" && reviewer && <button className="primary-button" disabled={busy} onClick={() => onAction("claim")}>Start review</button>}
    {task.status === "in_review" && owner && <>
      <p>Review the original and redline pages. Resolve outstanding questions before completing the whole document review.</p>
      <label className="review-confirm"><input type="checkbox" checked={confirmed} disabled={busy || !canComplete} onChange={(e) => setConfirmed(e.target.checked)} />I have read the whole document and accept the revised version.</label>
      <div className="review-actions">
        <button className="primary-button" disabled={busy || !canComplete || !confirmed}
          onClick={() => onAction("complete", { accept_revised_version: confirmed, confirm_document_read: confirmed })}>Approve document</button>
        <button className="secondary-button" disabled={busy} onClick={() => onAction("release")}>Release review</button>
      </div>
      <label>Reason for returning the document<textarea value={reason} maxLength={4000} disabled={busy} onChange={(e) => setReason(e.target.value)} /></label>
      <button className="secondary-button" disabled={busy || !reason.trim()} onClick={() => onAction("return", { comment: reason })}>Return document for revision</button>
      {!canComplete && <p>Outstanding clarification and escalation issues prevent completion and approval.</p>}
    </>}
    {task.status === "in_review" && !owner && <p>Only the staff member responsible for this review can record decisions.</p>}
    {task.status === "revision_required" && <p>The revised document has not been approved. The reason is recorded in the review history.</p>}

    {task.status === "approved" && <p>The revised document is the Current Approved Version.</p>}
    {user.roles.includes("manager") && user.department_id === task.department_id && ["in_review", "clarification_requested", "escalated"].includes(task.status) &&
      <ReassignReview task={task} busy={busy} onAction={onAction} />}
    {task.approval_task && <details className="review-history"><summary>Earlier final-approval record</summary><p>Status: {task.approval_task.status}. {task.approval_task.comment}</p></details>}
    <details className="review-history"><summary>Review history ({task.decisions.length})</summary>
      <ol>{task.decisions.map((decision) => <li key={decision.id}>
        <strong>{decision.user_name}</strong> · {decision.action.replaceAll("_", " ")} · {new Date(decision.created_at).toLocaleString()}
        {decision.change_number && <small>Change {decision.change_number}</small>}
        {decision.comment && <p>{decision.comment}</p>}
      </li>)}</ol>
    </details>
  </section>;
}

function ReassignReview({ task, busy, onAction }) {
  const [reviewers, setReviewers] = useState([]);
  const [reviewerId, setReviewerId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    eligibleReviewers(task.id).then((items) => { if (active) setReviewers(items); })
      .catch((err) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [task.id]);
  async function submit(event) {
    event.preventDefault();
    if (await onAction("reassign", { reviewer_id: reviewerId, comment: reason })) { setReason(""); setReviewerId(""); }
  }
  return <details className="review-history"><summary>Reassign review</summary>
    <form className="review-response" onSubmit={submit}>
      {error && <p role="alert">{error}</p>}
      <label>New staff member<select required disabled={busy} value={reviewerId} onChange={(e) => setReviewerId(e.target.value)}>
        <option value="">Select a staff member</option>
        {reviewers.filter((item) => item.id !== task.claimed_by).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.email}</option>)}
      </select></label>
      <label>Reason for reassignment<textarea required disabled={busy} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      <button className="secondary-button" disabled={busy || !reviewerId || !reason.trim()}>Reassign review</button>
    </form>
  </details>;
}
