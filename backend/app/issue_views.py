from sqlalchemy import select
from .models import ReviewIssue, ReviewIssueMessage, User, Department


def issue_views(db, task):
    items = []
    for issue in db.scalars(select(ReviewIssue).where(ReviewIssue.task_id == task.id).order_by(ReviewIssue.created_at, ReviewIssue.id)):
        items.append({key: getattr(issue, key) for key in ('id', 'kind', 'status', 'document_side', 'version_id', 'page_number', 'reference', 'question', 'assigned_to', 'department_id', 'created_by', 'created_at', 'resolved_by', 'resolved_at')})
        items[-1].update(department=db.get(Department, issue.department_id).name,
                         assigned_name=db.get(User, issue.assigned_to).full_name if issue.assigned_to else None,
                         messages=[{'id': m.id, 'user_name': db.get(User, m.user_id).full_name, 'action': m.action, 'comment': m.comment, 'created_at': m.created_at}
                                   for m in db.scalars(select(ReviewIssueMessage).where(ReviewIssueMessage.issue_id == issue.id).order_by(ReviewIssueMessage.created_at, ReviewIssueMessage.id))])
    return items


def has_open_issues(db, task):
    return db.scalar(select(ReviewIssue.id).where(ReviewIssue.task_id == task.id, ReviewIssue.status != 'resolved').limit(1)) is not None
