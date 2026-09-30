"""Transactional in-app delivery. No external messaging is performed."""
from sqlalchemy import select
from .models import Notification, User, UserRole


def notify_users(db, user_ids, comparison_id, event_type, message):
    recipients = db.scalars(select(User.id).where(User.id.in_({uid for uid in user_ids if uid}), User.active.is_(True)))
    for user_id in recipients:
        db.add(Notification(user_id=user_id, comparison_id=comparison_id, event_type=event_type, message=message))


def notify_department(db, department_id, roles, comparison_id, event_type, message, exclude=()):
    recipients = db.scalars(select(User.id).join(UserRole).where(User.department_id == department_id,
                    User.active.is_(True), UserRole.role_name.in_(roles), User.id.not_in(set(exclude))).distinct())
    notify_users(db, list(recipients), comparison_id, event_type, message)
