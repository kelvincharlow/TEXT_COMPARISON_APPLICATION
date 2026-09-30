"""Document-level issues; questions never pause inspection or other questions."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select, or_, and_
from .auth import current_user, get_db
from .models import Comparison, Document, ReviewIssue, ReviewIssueMessage, ReviewTask, User, Department, utcnow
from .reviews import (RevisionInput, CommentInput, task_for_user, active_reviewer,
                      mutate_task, record_event, commit_view, department_role)
from .notification_service import notify_users, notify_department

router = APIRouter(prefix='/api/v1')


class IssueInput(RevisionInput):
    kind: Literal['clarification', 'escalation']
    document_side: Literal['original', 'redline']
    page_number: int = Field(ge=1)
    reference: str = Field(min_length=1, max_length=2000)
    question: str = Field(min_length=1, max_length=4000)
    assigned_to: str = Field(default='', max_length=36)


class ResponseInput(CommentInput):
    outcome: Literal['answer', 'revision_required'] = 'answer'


def event(db, task, issue, user, action, comment):
    db.add(ReviewIssueMessage(issue_id=issue.id, user_id=user.id, action=action, comment=comment))
    record_event(db, task, user, 'issue_' + action, f'Issue {issue.id} · {comment}')


@router.get('/review-tasks/{task_id}/issue-recipients')
def recipients(task_id: str, db=Depends(get_db), user=Depends(current_user)):
    task = task_for_user(db, task_id, user)
    active_reviewer(task, user)
    return [{'id': u.id, 'name': u.full_name, 'department': u.department.name, 'email': u.email}
            for u in db.scalars(select(User).where(User.active.is_(True), User.id != user.id, ~User.roles.any(name="administrator")).order_by(User.full_name, User.id))]


@router.get('/review-issues')
def inbox(offset: int = Query(0, ge=0), db=Depends(get_db), user=Depends(current_user)):
    manager = 'manager' in {r.name for r in user.roles}
    issues = db.scalars(select(ReviewIssue).where(or_(ReviewIssue.assigned_to == user.id,
        and_(ReviewIssue.kind == 'escalation', ReviewIssue.department_id == user.department_id, manager)))
        .order_by(ReviewIssue.created_at.desc(), ReviewIssue.id).offset(offset).limit(50))
    result = []
    for i in issues:
        task = db.get(ReviewTask, i.task_id)
        c = db.get(Comparison, task.comparison_id)
        result.append({'id': i.id, 'comparison_id': c.id, 'title': db.get(Document, c.document_id).title,
                       'kind': i.kind, 'status': i.status, 'page_number': i.page_number, 'document_side': i.document_side,
                       'review_status': task.status, 'question': i.question})
    return result


@router.post('/review-tasks/{task_id}/issues')
def create(task_id: str, body: IssueInput, db=Depends(get_db), user=Depends(current_user)):
    task = task_for_user(db, task_id, user)
    active_reviewer(task, user)
    if not body.question.strip() or not body.reference.strip():
        raise HTTPException(422, 'Enter the question and a paragraph reference or quoted text.')
    target = None
    if body.kind == 'clarification':
        target = db.get(User, body.assigned_to)
        if not target or not target.active or target.id == user.id or any(r.name == "administrator" for r in target.roles):
            raise HTTPException(422, 'Choose another active account to answer the clarification.')
    elif body.assigned_to:
        raise HTTPException(422, 'Escalations go to the owning department manager queue.')
    c = db.get(Comparison, task.comparison_id)
    mutate_task(db, task, body.revision)
    issue = ReviewIssue(task_id=task.id, kind=body.kind, document_side=body.document_side,
                        version_id=c.original_version_id if body.document_side == 'original' else c.revised_version_id,
                        page_number=body.page_number, reference=body.reference.strip(), question=body.question.strip(),
                        assigned_to=target.id if target else None, department_id=target.department_id if target else task.department_id,
                        created_by=user.id)
    db.add(issue); db.flush()
    event(db, task, issue, user, 'opened', body.question.strip())
    if target:
        notify_users(db, [target.id], c.id, 'clarification_requested', 'A document clarification needs your response.')
    else:
        notify_department(db, task.department_id, ['manager'], c.id, 'escalation_requested', 'A document issue needs a manager decision.')
    return commit_view(db, task)


def context(db, task_id, issue_id, user):
    task = task_for_user(db, task_id, user)
    issue = db.get(ReviewIssue, issue_id)
    if not issue or issue.task_id != task.id:
        raise HTTPException(404, 'Issue was not found in this review.')
    if task.status not in {'available', 'in_review'}:
        raise HTTPException(409, 'This review round is closed to issue changes.')
    return task, issue


@router.post('/review-tasks/{task_id}/issues/{issue_id}/respond')
def respond(task_id: str, issue_id: str, body: ResponseInput, db=Depends(get_db), user=Depends(current_user)):
    task, issue = context(db, task_id, issue_id, user)
    authorized = user.id == issue.assigned_to if issue.kind == 'clarification' else department_role(user, issue.department_id, ('manager',))
    if not authorized or user.id == issue.created_by:
        raise HTTPException(403, 'Only the responsible recipient or escalation manager can respond.')
    if issue.status == 'resolved':
        raise HTTPException(409, 'This issue has already been resolved.')
    if not body.comment.strip():
        raise HTTPException(422, 'Enter a response.')
    if body.outcome == 'revision_required' and issue.kind != 'escalation':
        raise HTTPException(403, 'Only an escalation manager can require revision through this action.')
    mutate_task(db, task, body.revision)
    issue.status = 'answered'
    if body.outcome == 'revision_required':
        task.status = 'revision_required'
        record_event(db, task, user, 'escalation_revision_required', body.comment.strip())
    event(db, task, issue, user, 'answered', body.comment.strip())
    notify_users(db, [task.claimed_by], task.comparison_id, 'issue_answered', 'A review issue has a response. Review it before resolving the issue.')
    return commit_view(db, task)


@router.post('/review-tasks/{task_id}/issues/{issue_id}/resolve')
def resolve(task_id: str, issue_id: str, body: CommentInput, db=Depends(get_db), user=Depends(current_user)):
    task, issue = context(db, task_id, issue_id, user)
    active_reviewer(task, user)
    if issue.status != 'answered':
        raise HTTPException(409, 'A response is required before the reviewer can resolve this issue.')
    if not body.comment.strip():
        raise HTTPException(422, 'Record why the response resolves this issue.')
    mutate_task(db, task, body.revision)
    issue.status = 'resolved'; issue.resolved_by = user.id; issue.resolved_at = utcnow()
    event(db, task, issue, user, 'resolved', body.comment.strip())
    return commit_view(db, task)


@router.post('/review-tasks/{task_id}/issues/{issue_id}/reopen')
def reopen(task_id: str, issue_id: str, body: CommentInput, db=Depends(get_db), user=Depends(current_user)):
    task, issue = context(db, task_id, issue_id, user)
    active_reviewer(task, user)
    if issue.status == 'open' or not body.comment.strip():
        raise HTTPException(422, 'Reopen an answered or resolved issue with a follow-up question.')
    mutate_task(db, task, body.revision)
    issue.status = 'open'; issue.resolved_by = None; issue.resolved_at = None
    event(db, task, issue, user, 'reopened', body.comment.strip())
    if issue.assigned_to:
        notify_users(db, [issue.assigned_to], task.comparison_id, 'issue_reopened', 'A clarification needs a further response.')
    else:
        notify_department(db, issue.department_id, ['manager'], task.comparison_id, 'issue_reopened', 'An escalation needs a further response.')
    return commit_view(db, task)
