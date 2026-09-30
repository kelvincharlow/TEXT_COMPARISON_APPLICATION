"""Add final approvals revision rounds and notifications"""
import uuid
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = 'b8ed3df49c47'
down_revision = 'cf081fc34bd8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('comparison_rounds',
    sa.Column('comparison_id', sa.String(length=36), nullable=False),
    sa.Column('previous_comparison_id', sa.String(length=36), nullable=False),
    sa.Column('round_number', sa.Integer(), nullable=False),
    sa.CheckConstraint('round_number >= 2', name='comparison_round_number'),
    sa.ForeignKeyConstraint(['comparison_id'], ['comparisons.id'], ),
    sa.ForeignKeyConstraint(['previous_comparison_id'], ['comparisons.id'], ),
    sa.PrimaryKeyConstraint('comparison_id')
    )
    op.create_index(op.f('ix_comparison_rounds_previous_comparison_id'), 'comparison_rounds', ['previous_comparison_id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('comparison_id', sa.String(length=36), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('message', sa.String(length=300), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['comparison_id'], ['comparisons.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_comparison_id'), 'notifications', ['comparison_id'], unique=False)
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_table('approval_tasks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('review_task_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='available', nullable=False),
    sa.Column('claimed_by', sa.String(length=36), nullable=True),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_by', sa.String(length=36), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('comment', sa.Text(), server_default='', nullable=False),
    sa.CheckConstraint("status IN ('available', 'in_progress', 'approved', 'returned')", name='approval_task_status'),
    sa.ForeignKeyConstraint(['claimed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['review_task_id'], ['review_tasks.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('review_task_id')
    )

    # Resume Controlled Reviews that reached this gate before approval tasks
    # existed. No past reviewer decisions or version flags are changed.
    connection = op.get_bind()
    approvals = sa.table("approval_tasks", sa.column("id", sa.String()), sa.column("review_task_id", sa.String()),
                         sa.column("created_at", sa.DateTime(timezone=True)))
    notices = sa.table("notifications", sa.column("id", sa.String()), sa.column("user_id", sa.String()),
                       sa.column("comparison_id", sa.String()), sa.column("event_type", sa.String()),
                       sa.column("message", sa.String()), sa.column("created_at", sa.DateTime(timezone=True)))
    pending = connection.execute(sa.text("""SELECT t.id, t.comparison_id, t.department_id, t.review_completed_by
        FROM review_tasks t JOIN comparisons c ON c.id = t.comparison_id
        WHERE t.status = 'awaiting_final_approval' AND c.review_type = 'controlled'""")).mappings().all()
    for task in pending:
        now = datetime.now(timezone.utc)
        connection.execute(approvals.insert().values(id=str(uuid.uuid4()), review_task_id=task["id"], created_at=now))
        recipients = connection.execute(sa.text("""SELECT DISTINCT u.id FROM users u JOIN user_roles r ON r.user_id = u.id
            WHERE u.active = true AND u.department_id = :department AND r.role_name = 'approver'"""),
            {"department": task["department_id"]}).scalars()
        for recipient in recipients:
            if recipient != task["review_completed_by"]:
                connection.execute(notices.insert().values(id=str(uuid.uuid4()), user_id=recipient,
                    comparison_id=task["comparison_id"], event_type="final_approval_requested",
                    message="A Controlled Review awaits final approval.", created_at=now))


def downgrade():
    op.drop_table('approval_tasks')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_comparison_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_comparison_rounds_previous_comparison_id'), table_name='comparison_rounds')
    op.drop_table('comparison_rounds')
