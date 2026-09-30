"""Department review queues and transactional review state transitions."""
from collections import Counter
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from .auth import current_user, get_db, require_role
from .models import (ApprovalTask, AuditLog, Comparison, ComparisonChange, Department, Document,
                     DocumentVersion, ReviewDecision, ReviewTask, ReviewIssue, User, UserRole, utcnow)

from .issue_views import issue_views, has_open_issues
from .notification_service import notify_department, notify_users

router = APIRouter(prefix="/api/v1")
REVIEW_STATES = ("accepted", "rejected", "unresolved", "clarification_requested", "escalated")


def department_role(user, department_id, roles):
    return "administrator" not in {r.name for r in user.roles} and user.department_id == department_id and bool({r.name for r in user.roles} & set(roles))


def accessible_comparison(db, comparison_id, user):
    if "administrator" in {r.name for r in user.roles}:
        raise HTTPException(404, "Comparison does not exist or is not available to your account.")
    record = db.get(Comparison, comparison_id)
    if record:
        task = db.scalar(select(ReviewTask).where(ReviewTask.comparison_id == comparison_id))
        if record.created_by == user.id or (task and db.scalar(select(ReviewIssue.id).where(ReviewIssue.task_id == task.id, ReviewIssue.assigned_to == user.id).limit(1))) or (task and (
            department_role(user, task.department_id, ("staff", "manager"))
        )):
            return record
    raise HTTPException(404, "Comparison does not exist or is not available to your account.")


def task_view(db, task):
    if task is None:
        return None
    states = Counter(db.scalars(select(ComparisonChange.review_state).where(ComparisonChange.comparison_id == task.comparison_id)))
    decisions = list(db.scalars(select(ReviewDecision).where(ReviewDecision.task_id == task.id)
                               .order_by(ReviewDecision.created_at, ReviewDecision.id)))
    approval = db.scalar(select(ApprovalTask).where(ApprovalTask.review_task_id == task.id))
    approval_view = None if approval is None else {
        "id": approval.id, "status": approval.status, "claimed_by": approval.claimed_by,
        "claimed_by_name": db.get(User, approval.claimed_by).full_name if approval.claimed_by else None,
        "decided_by": approval.decided_by, "decided_at": approval.decided_at, "comment": approval.comment,
    }
    issues = issue_views(db, task)
    return {"issues": issues, "open_issue_count": sum(i["status"] != "resolved" for i in issues), "approval_task": approval_view, "id": task.id, "comparison_id": task.comparison_id, "department_id": task.department_id,
            "queue_name": db.get(Department, task.department_id).name + " Review Queue",
            "status": task.status, "revision": task.revision, "claimed_by": task.claimed_by,
            "claimed_by_name": db.get(User, task.claimed_by).full_name if task.claimed_by else None,
            "claimed_at": task.claimed_at, "review_completed_by": task.review_completed_by,
            "review_completed_at": task.review_completed_at, "final_decision_by": task.final_decision_by,
            "final_decision_at": task.final_decision_at,
            "counts": {"total": sum(states.values()), **{state: states[state] for state in REVIEW_STATES}},
            "decisions": [{"id": d.id, "change_id": d.change_id, "action": d.action,
                           "comment": d.comment, "user_id": d.user_id,
                           "user_name": db.get(User, d.user_id).full_name, "created_at": d.created_at,
                           "change_number": db.get(ComparisonChange, d.change_id).position if d.change_id else None} for d in decisions]}


def task_for_user(db, task_id, user):
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(404, "Review task was not found.")
    accessible_comparison(db, task.comparison_id, user)
    return task


def record_event(db, task, user, action, comment="", change=None):
    db.add(ReviewDecision(task_id=task.id, change_id=change.id if change else None,
                          user_id=user.id, action=action, comment=comment))
    db.add(AuditLog(user_id=user.id, comparison_id=task.comparison_id, event_type=action,
                    details={"task_id": task.id, "change_id": change.id if change else None,
                             "comment": comment, "revision": task.revision}))
    creator = db.get(Comparison, task.comparison_id).created_by
    if action in {"document_returned", "change_rejected", "change_clarification_requested", "escalation_revision_required", "final_approval_returned"}:
        message = "A clarification response is needed." if action == "change_clarification_requested" else "A corrected document is required."
        notify_users(db, [creator], task.comparison_id, action, message)
    elif action == "change_escalated":
        notify_department(db, task.department_id, ["manager"], task.comparison_id, action, "A review requires a manager decision.")
    elif action in {"clarification_answered", "escalation_resume_review", "review_reassigned"}:
        notify_users(db, [task.claimed_by], task.comparison_id, action, "A review is ready for your attention.")
    elif action in {"review_approved", "final_approval_granted"}:
        notify_users(db, [creator, task.review_completed_by], task.comparison_id, action, "The revised document has been approved.")
    elif action == "review_released":
        notify_department(db, task.department_id, ["staff"], task.comparison_id, action, "A review is available to claim.")
    if action == "final_approval_returned":
        notify_users(db, [task.review_completed_by] if task.review_completed_by != creator else [],
                     task.comparison_id, action, "Final approval was returned for document revision.")


def mutate_task(db, task, revision, **values):
    # A conditional UPDATE serializes every task mutation. A competing request
    # waits for the row lock, then fails its revision predicate after commit.
    if task.revision != revision:
        raise HTTPException(409, "This review changed. Refresh it before continuing.")
    changed = db.execute(update(ReviewTask).where(ReviewTask.id == task.id, ReviewTask.revision == revision)
                         .values(revision=ReviewTask.revision + 1, **values)
                         .execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        raise HTTPException(409, "This review changed. Refresh it before continuing.")
    db.refresh(task)


def active_reviewer(task, user):
    require_role(user, "staff")
    if task.department_id != user.department_id or task.claimed_by != user.id:
        raise HTTPException(403, "Only the staff member responsible for this review may change it.")
    if task.status != "in_review":
        raise HTTPException(409, "This review is not currently open for decisions.")


def commit_view(db, task):
    db.flush()
    result = task_view(db, task)
    db.commit()
    return result


class RevisionInput(BaseModel):
    revision: int = Field(ge=1)


class DecisionInput(RevisionInput):
    action: Literal["accepted", "rejected", "clarification_requested", "escalated"]
    comment: str = Field(default="", max_length=4000)


class CommentInput(RevisionInput):
    comment: str = Field(min_length=1, max_length=4000)


class CompletionInput(RevisionInput):
    accept_revised_version: bool
    confirm_document_read: bool = False


class EscalationInput(CommentInput):
    outcome: Literal["resume_review", "revision_required"]


@router.get("/review-tasks")
def queue(offset: int = Query(0, ge=0), db=Depends(get_db), user=Depends(current_user)):
    if not {r.name for r in user.roles} & {"staff", "manager"}:
        raise HTTPException(403, "A staff or manager role is required to view this queue.")
    tasks = db.scalars(select(ReviewTask).where(ReviewTask.department_id == user.department_id)
                      .order_by(ReviewTask.created_at.desc(), ReviewTask.id).offset(offset).limit(50))
    return [{"id": t.id, "comparison_id": t.comparison_id, "status": t.status,
             "claimed_by": t.claimed_by, "claimed_by_name": db.get(User, t.claimed_by).full_name if t.claimed_by else None,
             "title": db.get(Document, db.get(Comparison, t.comparison_id).document_id).title,
             "review_type": db.get(Comparison, t.comparison_id).review_type, "created_at": t.created_at} for t in tasks]


@router.post("/review-tasks/{task_id}/claim")
def claim(task_id: str, db=Depends(get_db), user=Depends(current_user)):
    task = task_for_user(db, task_id, user)
    require_role(user, "staff")
    if task.department_id != user.department_id:
        raise HTTPException(403, "You cannot claim another department's task.")
    changed = db.execute(update(ReviewTask).where(ReviewTask.id == task.id, ReviewTask.status == "available",
                          ReviewTask.claimed_by.is_(None)).values(status="in_review", claimed_by=user.id,
                          claimed_at=utcnow(), revision=ReviewTask.revision + 1)
                         .execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        raise HTTPException(409, "This task is already claimed or is no longer available.")
    db.refresh(task)
    record_event(db, task, user, "review_claimed")
    return commit_view(db, task)


@router.post("/review-tasks/{task_id}/release")
def release(task_id: str, body: RevisionInput, db=Depends(get_db), user=Depends(current_user)):
    task = task_for_user(db, task_id, user)
    active_reviewer(task, user)
    mutate_task(db, task, body.revision, status="available", claimed_by=None, claimed_at=None)
    record_event(db, task, user, "review_released")
    return commit_view(db, task)


@router.post("/review-tasks/{task_id}/changes/{change_id}/decision")
@router.post("/review-tasks/{task_id}/clarification-response")
@router.post("/review-tasks/{task_id}/escalation-resolution")
def retired_change_workflow(task_id: str, db=Depends(get_db), user=Depends(current_user)):
    task_for_user(db, task_id, user)
    raise HTTPException(410, "Review the whole document and use review issues for clarification or escalation. Refresh the application.")


@router.post("/review-tasks/{task_id}/return")
def return_document(task_id: str, body: CommentInput, db=Depends(get_db), user=Depends(current_user)):
    task = task_for_user(db, task_id, user)
    active_reviewer(task, user)
    if not body.comment.strip():
        raise HTTPException(422, "Enter the reason for returning the document.")
    mutate_task(db, task, body.revision, status="revision_required")
    record_event(db, task, user, "document_returned", body.comment.strip())
    return commit_view(db, task)


@router.post("/review-tasks/{task_id}/complete")
def complete(task_id: str, body: CompletionInput, db=Depends(get_db), user=Depends(current_user)):
    task = task_for_user(db, task_id, user)
    active_reviewer(task, user)
    if not body.accept_revised_version or not body.confirm_document_read:
        raise HTTPException(422, "Confirm that you have read the whole document and accept the revised version.")
    mutate_task(db, task, body.revision)
    if has_open_issues(db, task):
        raise HTTPException(409, "Resolve all clarification and escalation issues before completing this review.")
    comparison = db.get(Comparison, task.comparison_id)
    task.review_completed_by = user.id
    task.review_completed_at = utcnow()
    mark_version_approved(db, comparison)
    task.status = "approved"
    task.final_decision_by = user.id
    task.final_decision_at = utcnow()
    event = "review_approved"
    record_event(db, task, user, event)
    return commit_view(db, task)


def mark_version_approved(db, comparison):
    # Every approval of a document family locks this row before updating flags.
    db.scalar(select(Document).where(Document.id == comparison.document_id).with_for_update())
    db.execute(update(DocumentVersion).where(DocumentVersion.document_id == comparison.document_id)
               .values(current_approved=False))
    db.get(DocumentVersion, comparison.revised_version_id).current_approved = True


class ReassignmentInput(CommentInput):
    reviewer_id: str = Field(min_length=1, max_length=36)


def require_manager(task, user):
    if not department_role(user, task.department_id, ("manager",)):
        raise HTTPException(403, "A manager in the owning department is required.")


@router.get("/review-tasks/{task_id}/eligible-reviewers")
def eligible_reviewers(task_id: str, db=Depends(get_db), user=Depends(current_user)):
    task = task_for_user(db, task_id, user)
    require_manager(task, user)
    reviewers = db.scalars(select(User).join(UserRole).where(User.department_id == task.department_id,
                          User.active.is_(True), UserRole.role_name == "staff").order_by(User.full_name, User.id))
    return [{"id": reviewer.id, "name": reviewer.full_name, "email": reviewer.email} for reviewer in reviewers]


@router.post("/review-tasks/{task_id}/reassign")
def reassign(task_id: str, body: ReassignmentInput, db=Depends(get_db), user=Depends(current_user)):
    task = task_for_user(db, task_id, user)
    require_manager(task, user)
    if task.status not in {"in_review", "clarification_requested", "escalated"}:
        raise HTTPException(409, "Only an active or paused review can be reassigned.")
    target = db.get(User, body.reviewer_id)
    if not target or not target.active or not department_role(target, task.department_id, ("staff",)):
        raise HTTPException(422, "Choose an active staff member in the owning department.")
    if not body.comment.strip():
        raise HTTPException(422, "Enter a reason for reassignment.")
    previous_owner = task.claimed_by
    mutate_task(db, task, body.revision, claimed_by=target.id, claimed_at=utcnow())
    record_event(db, task, user, "review_reassigned", body.comment.strip())
    db.add(AuditLog(user_id=user.id, comparison_id=task.comparison_id, event_type="review_owner_changed",
                    details={"previous_owner": previous_owner, "new_owner": target.id}))
    return commit_view(db, task)


def start_staff_review(db, comparison_id, department_id, user):
    """Own-department uploads stay with their uploader; other departments use the queue."""
    own_department = department_role(user, department_id, ("staff",))
    task = ReviewTask(comparison_id=comparison_id, department_id=department_id,
                      status="in_review" if own_department else "available",
                      claimed_by=user.id if own_department else None,
                      claimed_at=utcnow() if own_department else None)
    db.add(task)
    db.flush()
    if own_department:
        record_event(db, task, user, "review_started", "Uploader started the staff review.")
    else:
        notify_department(db, department_id, ["staff"], comparison_id, "review_task_created",
                          "A comparison is available in your department workspace.")
    return task
