"""Document review issues and response history"""
import uuid
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = 'fe15e27dc2fc'
down_revision = 'b8ed3df49c47'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('review_issues',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
    sa.Column('document_side', sa.String(length=20), nullable=False),
    sa.Column('version_id', sa.String(length=36), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('reference', sa.Text(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('assigned_to', sa.String(length=36), nullable=True),
    sa.Column('department_id', sa.String(length=36), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_by', sa.String(length=36), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("document_side IN ('original', 'redline')", name='review_issue_side'),
    sa.CheckConstraint("kind IN ('clarification', 'escalation')", name='review_issue_kind'),
    sa.CheckConstraint("status IN ('open', 'answered', 'resolved')", name='review_issue_status'),
    sa.CheckConstraint('page_number IS NULL OR page_number > 0', name='review_issue_page'),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['review_tasks.id'], ),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_review_issues_assigned_to'), 'review_issues', ['assigned_to'], unique=False)
    op.create_index(op.f('ix_review_issues_task_id'), 'review_issues', ['task_id'], unique=False)
    op.create_table('review_issue_messages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('issue_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['issue_id'], ['review_issues.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_review_issue_messages_issue_id'), 'review_issue_messages', ['issue_id'], unique=False)

    connection = op.get_bind()
    metadata = sa.MetaData()
    tasks = sa.Table('review_tasks', metadata, autoload_with=connection)
    comparisons = sa.Table('comparisons', metadata, autoload_with=connection)
    changes = sa.Table('comparison_changes', metadata, autoload_with=connection)
    decisions = sa.Table('review_decisions', metadata, autoload_with=connection)
    issues = sa.Table('review_issues', metadata, autoload_with=connection)
    audits = sa.Table('audit_logs', metadata, autoload_with=connection)
    users = sa.Table('users', metadata, autoload_with=connection)
    pending = connection.execute(sa.select(tasks).where(tasks.c.status.in_(['clarification_requested', 'escalated']))).mappings().all()
    for task in pending:
        comparison = connection.execute(sa.select(comparisons).where(comparisons.c.id == task['comparison_id'])).mappings().one()
        old_changes = connection.execute(sa.select(changes).where(changes.c.comparison_id == comparison['id'], changes.c.review_state.in_(['clarification_requested', 'escalated']))).mappings().all()
        # Keep a blocking issue even for an inconsistent older paused task.
        for change in old_changes or [None]:
            kind = 'clarification' if (change['review_state'] if change else task['status']) == 'clarification_requested' else 'escalation'
            query = sa.select(decisions).where(decisions.c.task_id == task['id'])
            if change: query = query.where(decisions.c.change_id == change['id'], decisions.c.action == 'change_' + change['review_state'])
            latest = connection.execute(query.order_by(decisions.c.created_at.desc(), decisions.c.id.desc())).mappings().first()
            recipient = comparison['created_by'] if kind == 'clarification' else None
            department = connection.execute(sa.select(users.c.department_id).where(users.c.id == recipient)).scalar_one() if recipient else task['department_id']
            reference = ('Legacy change ' + str(change['position']) + ': ' + str(change['finding'].get('revised_text') or change['finding'].get('original_text') or 'See review history')) if change else 'See previous review history'
            connection.execute(issues.insert().values(id=str(uuid.uuid4()), task_id=task['id'], kind=kind,
                status='open', document_side='redline', version_id=comparison['revised_version_id'],
                page_number=None, reference=reference, question=latest['comment'] if latest and latest['comment'] else 'Please address the outstanding review request.',
                assigned_to=recipient, department_id=department, created_by=task['claimed_by'] or comparison['created_by'], created_at=datetime.now(timezone.utc)))
        connection.execute(tasks.update().where(tasks.c.id == task['id']).values(status='in_review' if task['claimed_by'] else 'available', revision=task['revision'] + 1))
        connection.execute(audits.insert().values(id=str(uuid.uuid4()), user_id=task['claimed_by'] or comparison['created_by'], comparison_id=comparison['id'],
            event_type='document_review_migrated', occurred_at=datetime.now(timezone.utc), details={'previous_status': task['status'], 'outstanding_requests_preserved': True}))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM review_issues')).scalar():
        raise RuntimeError('Cannot downgrade while review issues exist; retain their audit history.')
    op.drop_index(op.f('ix_review_issue_messages_issue_id'), table_name='review_issue_messages')
    op.drop_table('review_issue_messages')
    op.drop_index(op.f('ix_review_issues_task_id'), table_name='review_issues')
    op.drop_index(op.f('ix_review_issues_assigned_to'), table_name='review_issues')
    op.drop_table('review_issues')
