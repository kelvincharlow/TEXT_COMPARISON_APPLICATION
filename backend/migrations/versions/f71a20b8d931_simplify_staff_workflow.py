"""Unify staff roles and retire mandatory final approval without approving pending work."""
import uuid
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = 'f71a20b8d931'
down_revision = 'fe15e27dc2fc'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('approval_tasks') as batch:
        batch.drop_constraint('approval_task_status', type_='check')
        batch.create_check_constraint('approval_task_status', "status IN ('available', 'in_progress', 'approved', 'returned', 'superseded')")
    connection = op.get_bind()
    metadata = sa.MetaData()
    tables = {name: sa.Table(name, metadata, autoload_with=connection) for name in
              ('roles', 'user_roles', 'users', 'auth_sessions', 'audit_logs', 'review_tasks',
               'approval_tasks', 'comparisons', 'review_decisions', 'notifications')}
    roles, links, users = tables['roles'], tables['user_roles'], tables['users']
    now = datetime.now(timezone.utc)
    connection.execute(roles.insert().values(name='staff'))
    for user in connection.execute(sa.select(users)).mappings().all():
        old = set(connection.execute(sa.select(links.c.role_name).where(links.c.user_id == user['id'])).scalars())
        new = old - {'comparator', 'reviewer', 'approver'}
        if old & {'comparator', 'reviewer'}:
            new.add('staff')
        if 'approver' in old:
            new.add('manager')
        if 'administrator' in new:
            new = {'administrator'}
        if new != old:
            connection.execute(links.delete().where(links.c.user_id == user['id']))
            connection.execute(links.insert(), [{'user_id': user['id'], 'role_name': name} for name in sorted(new)])
            connection.execute(tables['auth_sessions'].delete().where(tables['auth_sessions'].c.user_id == user['id']))
            connection.execute(tables['audit_logs'].insert().values(id=str(uuid.uuid4()), user_id=user['id'],
                event_type='workflow_roles_migrated', occurred_at=now,
                details={'migration': revision, 'previous_roles': sorted(old), 'roles': sorted(new)}))
    connection.execute(roles.delete().where(roles.c.name.in_(['comparator', 'reviewer', 'approver'])))
    tasks, approvals = tables['review_tasks'], tables['approval_tasks']
    for task in connection.execute(sa.select(tasks).where(tasks.c.status == 'awaiting_final_approval')).mappings().all():
        comparison = connection.execute(sa.select(tables['comparisons']).where(tables['comparisons'].c.id == task['comparison_id'])).mappings().one()
        owner = task['review_completed_by'] or task['claimed_by'] or comparison['created_by']
        eligible = connection.execute(sa.select(users.c.id).join(links).where(
            users.c.id == owner, users.c.active.is_(True), users.c.department_id == task['department_id'], links.c.role_name == 'staff')).scalar()
        status = 'in_review' if eligible else 'available'
        connection.execute(tasks.update().where(tasks.c.id == task['id']).values(status=status,
            claimed_by=owner if eligible else None, claimed_at=now if eligible else None, revision=task['revision'] + 1))
        comment = 'Separate final approval retired. Returned to staff for explicit completion; no version was automatically approved.'
        connection.execute(tables['review_decisions'].insert().values(id=str(uuid.uuid4()), task_id=task['id'],
            user_id=comparison['created_by'], action='workflow_simplified', comment=comment, created_at=now))
        connection.execute(tables['audit_logs'].insert().values(id=str(uuid.uuid4()), user_id=comparison['created_by'],
            comparison_id=task['comparison_id'], event_type='workflow_simplified', occurred_at=now,
            details={'migration': revision, 'previous_status': task['status'], 'status': status, 'claimed_by': owner if eligible else None}))
        recipients = [owner] if eligible else list(connection.execute(sa.select(users.c.id).join(links).where(
            users.c.active.is_(True), users.c.department_id == task['department_id'], links.c.role_name == 'staff')).scalars())
        for recipient in recipients:
            connection.execute(tables['notifications'].insert().values(id=str(uuid.uuid4()), user_id=recipient,
                comparison_id=task['comparison_id'], event_type='workflow_simplified', created_at=now,
                message='This document now needs staff completion. Separate final approval is no longer required.'))
    # Keep all previous approval assignments and decisions as historical records.
    connection.execute(approvals.update().where(approvals.c.status.in_(['available', 'in_progress'])).values(status='superseded'))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT COUNT(*) FROM users')).scalar():
        raise RuntimeError('Role consolidation cannot be safely reversed for populated databases. Restore a pre-migration backup instead.')
    connection.execute(sa.text("DELETE FROM roles WHERE name = 'staff'"))
    for name in ('comparator', 'reviewer', 'approver'):
        connection.execute(sa.text('INSERT INTO roles (name) VALUES (:name)'), {'name': name})
    with op.batch_alter_table('approval_tasks') as batch:
        batch.drop_constraint('approval_task_status', type_='check')
        batch.create_check_constraint('approval_task_status', "status IN ('available', 'in_progress', 'approved', 'returned')")
