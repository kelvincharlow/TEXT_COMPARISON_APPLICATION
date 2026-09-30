"""Add department review tasks and decisions"""
import uuid
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = 'cf081fc34bd8'
down_revision = '94a10f4f5c10'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('review_tasks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('comparison_id', sa.String(length=36), nullable=False),
    sa.Column('department_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=30), server_default='available', nullable=False),
    sa.Column('revision', sa.Integer(), server_default='1', nullable=False),
    sa.Column('claimed_by', sa.String(length=36), nullable=True),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('review_completed_by', sa.String(length=36), nullable=True),
    sa.Column('review_completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('final_decision_by', sa.String(length=36), nullable=True),
    sa.Column('final_decision_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('available', 'in_review', 'clarification_requested', 'escalated', 'revision_required', 'awaiting_final_approval', 'approved')", name='review_task_status'),
    sa.CheckConstraint('revision > 0', name='review_task_revision_positive'),
    sa.ForeignKeyConstraint(['claimed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['comparison_id'], ['comparisons.id'], ),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['final_decision_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['review_completed_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('comparison_id')
    )
    op.create_index(op.f('ix_review_tasks_department_id'), 'review_tasks', ['department_id'], unique=False)
    op.create_table('review_decisions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('change_id', sa.String(length=36), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['change_id'], ['comparison_changes.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['review_tasks.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_review_decisions_task_id'), 'review_decisions', ['task_id'], unique=False)
    op.add_column('comparison_changes', sa.Column('review_state', sa.String(length=30), server_default='unresolved', nullable=False))
    op.add_column('document_versions', sa.Column('current_approved', sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_index('uq_current_approved_version', 'document_versions', ['document_id'], unique=True, postgresql_where=sa.text('current_approved = true'), sqlite_where=sa.text('current_approved = 1'))


    # Existing successful comparisons become available for review. Failed
    # processing attempts remain in history without a review task.
    connection = op.get_bind()
    tasks = sa.table("review_tasks", sa.column("id", sa.String()), sa.column("comparison_id", sa.String()),
                     sa.column("department_id", sa.String()), sa.column("created_at", sa.DateTime(timezone=True)))
    rows = connection.execute(sa.text("""
        SELECT c.id, c.created_by, d.owning_department_id FROM comparisons c
        JOIN documents d ON d.id = c.document_id WHERE c.processing_status = 'completed'
    """)).mappings()
    audits = sa.table("audit_logs", sa.column("id", sa.String()), sa.column("user_id", sa.String()),
                      sa.column("comparison_id", sa.String()), sa.column("event_type", sa.String()),
                      sa.column("occurred_at", sa.DateTime(timezone=True)), sa.column("details", sa.JSON()))
    for row in rows:
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        connection.execute(tasks.insert().values(id=task_id, comparison_id=row["id"],
                           department_id=row["owning_department_id"], created_at=now))
        connection.execute(audits.insert().values(id=str(uuid.uuid4()), user_id=row["created_by"],
                           comparison_id=row["id"], event_type="review_task_created", occurred_at=now,
                           details={"source": "workflow_migration", "task_id": task_id}))


def downgrade():
    op.drop_index('uq_current_approved_version', table_name='document_versions', postgresql_where=sa.text('current_approved = true'), sqlite_where=sa.text('current_approved = 1'))
    op.drop_column('document_versions', 'current_approved')
    op.drop_column('comparison_changes', 'review_state')
    op.drop_index(op.f('ix_review_decisions_task_id'), table_name='review_decisions')
    op.drop_table('review_decisions')
    op.drop_index(op.f('ix_review_tasks_department_id'), table_name='review_tasks')
    op.drop_table('review_tasks')
