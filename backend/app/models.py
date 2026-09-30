"""Persistent identity and comparison foundation for the internal workflow."""
from __future__ import annotations

import uuid
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, CheckConstraint, Index, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Role(Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_name: Mapped[str] = mapped_column(ForeignKey("roles.name"), primary_key=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    full_name: Mapped[str] = mapped_column(String(200))
    employee_number: Mapped[str] = mapped_column(String(80), unique=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin")
    department: Mapped[Department] = relationship(lazy="joined")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Document(Base):
    """A document family. Responsibility metadata never grants access."""
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    owning_department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    document_type: Mapped[str] = mapped_column(String(120))
    responsible_officer: Mapped[str] = mapped_column(String(200))
    work_email: Mapped[str] = mapped_column(String(254))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number"), CheckConstraint("version_number > 0"),
        Index("uq_current_approved_version", "document_id", unique=True,
              postgresql_where=text("current_approved = true"), sqlite_where=text("current_approved = 1")),
    )
    current_approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    previous_version_id: Mapped[Optional[str]] = mapped_column(ForeignKey("document_versions.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    file_hash: Mapped[str] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revision_source: Mapped[str] = mapped_column(String(200))
    revision_contact: Mapped[str] = mapped_column(String(200))


class Comparison(Base):
    __tablename__ = "comparisons"
    __table_args__ = (
        CheckConstraint("review_type IN ('standard', 'controlled')"),
        CheckConstraint("processing_status IN ('completed', 'failed')"),
        CheckConstraint("original_version_id <> revised_version_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    original_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"))
    revised_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    review_type: Mapped[str] = mapped_column(String(20))
    processing_status: Mapped[str] = mapped_column(String(20), default="completed")
    result: Mapped[dict] = mapped_column(JSON)
    redline_path: Mapped[Optional[str]] = mapped_column(String(255))


class ComparisonChange(Base):
    __tablename__ = "comparison_changes"
    __table_args__ = (UniqueConstraint("comparison_id", "position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("comparisons.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    finding: Mapped[dict] = mapped_column(JSON)
    review_state: Mapped[str] = mapped_column(String(30), default="unresolved", server_default="unresolved")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    comparison_id: Mapped[Optional[str]] = mapped_column(ForeignKey("comparisons.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('available', 'in_review', 'clarification_requested', 'escalated', 'revision_required', 'awaiting_final_approval', 'approved')", name="review_task_status"),
        CheckConstraint("revision > 0", name="review_task_revision_positive"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("comparisons.id"), unique=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="available", server_default="available")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    claimed_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    review_completed_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    review_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    final_decision_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    final_decision_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReviewDecision(Base):
    """Append-only review history; current change state is stored separately."""
    __tablename__ = "review_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    change_id: Mapped[Optional[str]] = mapped_column(ForeignKey("comparison_changes.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalTask(Base):
    __tablename__ = "approval_tasks"
    __table_args__ = (CheckConstraint("status IN ('available', 'in_progress', 'approved', 'returned', 'superseded')", name="approval_task_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_task_id: Mapped[str] = mapped_column(ForeignKey("review_tasks.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="available", server_default="available")
    claimed_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")


class ComparisonRound(Base):
    """A corrected upload's link to its preceding comparison, including failures."""
    __tablename__ = "comparison_rounds"
    __table_args__ = (CheckConstraint("round_number >= 2", name="comparison_round_number"),)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("comparisons.id"), primary_key=True)
    previous_comparison_id: Mapped[str] = mapped_column(ForeignKey("comparisons.id"), index=True)
    round_number: Mapped[int] = mapped_column(Integer)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("comparisons.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReviewIssue(Base):
    __tablename__ = "review_issues"
    __table_args__ = (
        CheckConstraint("kind IN ('clarification', 'escalation')", name="review_issue_kind"),
        CheckConstraint("status IN ('open', 'answered', 'resolved')", name="review_issue_status"),
        CheckConstraint("document_side IN ('original', 'redline')", name="review_issue_side"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="review_issue_page"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    document_side: Mapped[str] = mapped_column(String(20))
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"))
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    reference: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    assigned_to: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReviewIssueMessage(Base):
    __tablename__ = "review_issue_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    issue_id: Mapped[str] = mapped_column(ForeignKey("review_issues.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
