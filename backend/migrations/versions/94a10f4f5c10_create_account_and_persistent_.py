"""Create account and persistent comparison foundation"""
from alembic import op
import sqlalchemy as sa

revision = '94a10f4f5c10'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('departments',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('roles',
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('employee_number', sa.String(length=80), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('department_id', sa.String(length=36), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('failed_logins', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('employee_number')
    )
    op.create_table('auth_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index(op.f('ix_auth_sessions_user_id'), 'auth_sessions', ['user_id'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('owning_department_id', sa.String(length=36), nullable=False),
    sa.Column('document_type', sa.String(length=120), nullable=False),
    sa.Column('responsible_officer', sa.String(length=200), nullable=False),
    sa.Column('work_email', sa.String(length=254), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['owning_department_id'], ['departments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user_roles',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role_name', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['role_name'], ['roles.name'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'role_name')
    )
    op.create_table('document_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('previous_version_id', sa.String(length=36), nullable=True),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('storage_path', sa.String(length=255), nullable=False),
    sa.Column('file_hash', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by', sa.String(length=36), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revision_source', sa.String(length=200), nullable=False),
    sa.Column('revision_contact', sa.String(length=200), nullable=False),
    sa.CheckConstraint('version_number > 0'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['previous_version_id'], ['document_versions.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'version_number'),
    sa.UniqueConstraint('storage_path')
    )
    op.create_index(op.f('ix_document_versions_document_id'), 'document_versions', ['document_id'], unique=False)
    op.create_table('comparisons',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('original_version_id', sa.String(length=36), nullable=False),
    sa.Column('revised_version_id', sa.String(length=36), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('review_type', sa.String(length=20), nullable=False),
    sa.Column('processing_status', sa.String(length=20), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('redline_path', sa.String(length=255), nullable=True),
    sa.CheckConstraint("processing_status IN ('completed', 'failed')"),
    sa.CheckConstraint("review_type IN ('standard', 'controlled')"),
    sa.CheckConstraint('original_version_id <> revised_version_id'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['original_version_id'], ['document_versions.id'], ),
    sa.ForeignKeyConstraint(['revised_version_id'], ['document_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_comparisons_created_by'), 'comparisons', ['created_by'], unique=False)
    op.create_index(op.f('ix_comparisons_document_id'), 'comparisons', ['document_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('comparison_id', sa.String(length=36), nullable=True),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['comparison_id'], ['comparisons.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_comparison_id'), 'audit_logs', ['comparison_id'], unique=False)
    op.create_table('comparison_changes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('comparison_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('finding', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['comparison_id'], ['comparisons.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('comparison_id', 'position')
    )
    op.create_index(op.f('ix_comparison_changes_comparison_id'), 'comparison_changes', ['comparison_id'], unique=False)
    op.bulk_insert(sa.table("roles", sa.column("name", sa.String())), [
        {"name": name} for name in ("comparator", "reviewer", "approver", "manager", "administrator")
    ])


def downgrade():
    op.drop_index(op.f('ix_comparison_changes_comparison_id'), table_name='comparison_changes')
    op.drop_table('comparison_changes')
    op.drop_index(op.f('ix_audit_logs_comparison_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_comparisons_document_id'), table_name='comparisons')
    op.drop_index(op.f('ix_comparisons_created_by'), table_name='comparisons')
    op.drop_table('comparisons')
    op.drop_index(op.f('ix_document_versions_document_id'), table_name='document_versions')
    op.drop_table('document_versions')
    op.drop_table('user_roles')
    op.drop_table('documents')
    op.drop_index(op.f('ix_auth_sessions_user_id'), table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('departments')
