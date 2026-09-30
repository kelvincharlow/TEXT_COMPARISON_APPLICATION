"""Authenticated, persistent document comparison API."""
from __future__ import annotations
from .reviews import start_staff_review

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select, text

from backend.app.comparison.engine import DocumentValidationError
from .auth import (COOKIE_NAME, DUMMY_HASH, SESSION_SECONDS, aware, current_user, get_db,
                   hasher, require_role, token_hash, user_view, verify_password)
from .database import make_engine, session_factory
from .models import (AuditLog, AuthSession, Comparison, ComparisonChange, Department,
                     Document, DocumentVersion, ReviewTask, User, new_id, utcnow)
from .service import run_comparison
from .storage import DocumentStorage, save_upload
from .views import comparison_view
from .approvals import router as approval_router
from .notifications import router as notification_router
from .revisions import router as revision_router
from .previews import router as preview_router
from .issues import router as issue_router
from .admin import router as admin_router
from .notification_service import notify_department
from .reviews import accessible_comparison, router as review_router

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = int(os.getenv("POSTBANK_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
DEFAULT_STORAGE_ROOT = Path(os.getenv("POSTBANK_STORAGE_ROOT", str(Path(__file__).resolve().parents[1] / ".runtime")))


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


def create_app(storage_root=None, database_url=None):
    storage = DocumentStorage(storage_root or DEFAULT_STORAGE_ROOT)
    engine = make_engine(database_url)
    @asynccontextmanager
    async def lifespan(_app):
        yield
        engine.dispose()

    app = FastAPI(title="Postbank Document Comparison API", version="0.4.0", lifespan=lifespan,
                  description="Staff document comparison and approval, optional escalation, and version history.")
    app.include_router(review_router)
    app.include_router(approval_router)
    app.include_router(notification_router)
    app.include_router(revision_router)
    app.include_router(preview_router)
    app.include_router(issue_router)
    app.include_router(admin_router)
    app.state.engine = engine
    app.state.sessions = session_factory(engine)
    app.state.document_storage = storage

    @app.middleware("http")
    async def request_guard(request: Request, call_next):
        # Browsers cannot submit this header across origins without a successful
        # CORS preflight. This API intentionally does not enable cross-origin CORS.
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("X-Postbank-Request") != "1":
            return JSONResponse({"detail": "Missing application request header."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/health")
    def health(db=Depends(get_db)):
        try:
            db.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
        except Exception:
            raise HTTPException(503, "Database is unavailable or migrations have not run.")
        return {"status": "ok"}

    @app.post("/api/v1/auth/login")
    def login(body: LoginInput, response: Response, db=Depends(get_db)):
        user = db.scalar(select(User).where(User.email == str(body.email).lower()).with_for_update(of=User))
        valid = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
        if user is None:
            raise HTTPException(401, "Email or password is incorrect.")
        if user.locked_until and aware(user.locked_until) > utcnow():
            raise HTTPException(429, "Too many sign-in attempts. Try again later.")
        if not valid or not user.active:
            user.failed_logins += 1
            if user.failed_logins >= 5:
                user.locked_until = utcnow() + timedelta(minutes=15)
                user.failed_logins = 0
            db.add(AuditLog(user_id=user.id, event_type="login_failed"))
            db.commit()
            raise HTTPException(401, "Email or password is incorrect.")
        user.failed_logins = 0
        user.locked_until = None
        if hasher.check_needs_rehash(user.password_hash):
            user.password_hash = hasher.hash(body.password)
        db.execute(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
        token = secrets.token_urlsafe(32)
        db.add(AuthSession(token_hash=token_hash(token), user_id=user.id,
                           expires_at=utcnow() + timedelta(seconds=SESSION_SECONDS)))
        db.add(AuditLog(user_id=user.id, event_type="logged_in"))
        db.commit()
        response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict", path="/api",
                            secure=os.getenv("POSTBANK_COOKIE_SECURE", "false").lower() == "true",
                            max_age=SESSION_SECONDS)
        return user_view(user)

    @app.get("/api/v1/auth/me")
    def me(user=Depends(current_user)):
        return user_view(user)

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request, response: Response, db=Depends(get_db), user=Depends(current_user)):
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(request.cookies[COOKIE_NAME])))
        db.add(AuditLog(user_id=user.id, event_type="logged_out"))
        db.commit()
        response.delete_cookie(COOKIE_NAME, path="/api")

    @app.get("/api/v1/departments")
    def departments(db=Depends(get_db), user=Depends(current_user)):
        return [{"id": item.id, "name": item.name} for item in db.scalars(select(Department).order_by(Department.name))]

    @app.post("/api/v1/compare")
    async def compare(
        original: UploadFile = File(...), revised: UploadFile = File(...),
        title: str = Form(..., min_length=1, max_length=255),
        owning_department_id: str = Form(..., max_length=36),
        document_type: str = Form(..., min_length=1, max_length=120),
        responsible_officer: str = Form(..., min_length=1, max_length=200),
        work_email: EmailStr = Form(...),
        revision_source: str = Form(..., min_length=1, max_length=200),
        revision_contact: str = Form("", max_length=200),
        review_type: Literal["standard"] = Form("standard"),
        db=Depends(get_db), user=Depends(current_user),
    ):
        require_role(user, "staff")
        if db.get(Department, owning_department_id) is None:
            raise HTTPException(422, "Choose an existing owning department.")
        for value in (title, document_type, responsible_officer, revision_source):
            if not value.strip():
                raise HTTPException(422, "Document metadata cannot be blank.")
        for upload, label in ((original, "Original"), (revised, "Revised")):
            if not upload.filename or not upload.filename.lower().endswith(".docx"):
                raise HTTPException(415, f"{label} document must be a .docx file.")
        submitted_at = utcnow()
        comparison_id, folder = storage.create_session()
        try:
            hashes = [await save_upload(original, folder / "original.docx", MAX_UPLOAD_BYTES),
                      await save_upload(revised, folder / "revised.docx", MAX_UPLOAD_BYTES)]
            error_status = None
            try:
                result = await run_in_threadpool(run_comparison, folder / "original.docx", folder / "revised.docx", folder / "redline.docx")
            except DocumentValidationError as exc:
                raise HTTPException(422, str(exc)) from exc
            except Exception:
                # Preserve valid uploads and the failed comparison for traceability.
                logger.error("Comparison engine failed for %s", comparison_id)
                result = {"success": False, "changes": [], "error": "Comparison processing failed."}
                error_status = 500
            document = Document(id=new_id(), title=title.strip(), owning_department_id=owning_department_id,
                                document_type=document_type.strip(), responsible_officer=responsible_officer.strip(),
                                work_email=str(work_email).lower(), created_by=user.id, created_at=submitted_at)
            db.add(document)
            db.flush()
            versions = []
            for index, (upload, kind) in enumerate(((original, "original"), (revised, "revised"))):
                version = DocumentVersion(id=new_id(), document_id=document.id, version_number=index + 1,
                    previous_version_id=versions[0].id if index else None,
                    file_name=Path(upload.filename.replace("\\", "/")).name[:255],
                    storage_path=f"{comparison_id}/{kind}.docx", file_hash=hashes[index], uploaded_by=user.id, uploaded_at=submitted_at,
                    revision_source=revision_source.strip() if index else user.department.name,
                    revision_contact=revision_contact.strip() if index else user.full_name)
                db.add(version)
                db.flush()
                versions.append(version)
            for change in result["changes"]:
                change["id"] = new_id()
            record = Comparison(id=comparison_id, document_id=document.id, original_version_id=versions[0].id,
                revised_version_id=versions[1].id, created_by=user.id, created_at=submitted_at, review_type=review_type,
                result=result, redline_path=f"{comparison_id}/redline.docx" if not error_status else None,
                processing_status="failed" if error_status else "completed")
            db.add(record)
            db.flush()
            for position, change in enumerate(result["changes"], 1):
                db.add(ComparisonChange(id=change["id"], comparison_id=comparison_id, position=position, finding=change))
            for event in ("documents_uploaded", "comparison_failed" if error_status else "comparison_completed"):
                db.add(AuditLog(user_id=user.id, comparison_id=comparison_id, event_type=event,
                               details={"document_id": document.id, "review_type": review_type}))
            if not error_status:
                start_staff_review(db, comparison_id, owning_department_id, user)
                db.add(AuditLog(user_id=user.id, comparison_id=comparison_id, event_type="review_task_created",
                               details={"department_id": owning_department_id}))

            db.flush()
            payload = comparison_view(db, record, user)
            db.commit()
        except BaseException:
            db.rollback()
            storage.discard_uncommitted(comparison_id)
            raise
        if error_status:
            return JSONResponse({"detail": "Comparison failed. The uploaded versions are saved in your history.",
                                 "comparison_id": comparison_id}, status_code=error_status)
        return payload

    @app.get("/api/v1/comparisons")
    def history(offset: int = 0, db=Depends(get_db), user=Depends(current_user)):
        records = db.scalars(select(Comparison).where(Comparison.created_by == user.id)
                             .order_by(Comparison.created_at.desc(), Comparison.id).offset(max(offset, 0)).limit(50))
        return [{"comparison_id": item.id, "title": db.get(Document, item.document_id).title,
                 "created_at": item.created_at.isoformat(), "review_type": item.review_type,
                 "processing_status": item.processing_status,
                 "review_status": db.scalar(select(ReviewTask.status).where(ReviewTask.comparison_id == item.id)),
                 "total_changes": item.result.get("summary", {}).get("total_changes", 0)} for item in records]

    @app.get("/api/v1/comparisons/{comparison_id}")
    def detail(comparison_id: str, db=Depends(get_db), user=Depends(current_user)):
        return comparison_view(db, accessible_comparison(db, comparison_id, user), user)

    def file_response(db, user, record, kind):
        if kind == "redline":
            relative = record.redline_path
            filename = "postbank-comparison-visual-redline.docx"
        else:
            version = db.get(DocumentVersion, record.original_version_id if kind == "original" else record.revised_version_id)
            relative, filename = version.storage_path, version.file_name
        if not relative or not storage.path(relative).is_file():
            raise HTTPException(404, "The requested file is unavailable.")
        db.add(AuditLog(user_id=user.id, comparison_id=record.id, event_type="document_downloaded", details={"kind": kind}))
        db.commit()
        return FileResponse(storage.path(relative), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=filename)

    @app.get("/api/v1/comparisons/{comparison_id}/download")
    def download(comparison_id: str, db=Depends(get_db), user=Depends(current_user)):
        return file_response(db, user, accessible_comparison(db, comparison_id, user), "redline")

    @app.get("/api/v1/comparisons/{comparison_id}/files/{kind}")
    def version_download(comparison_id: str, kind: Literal["original", "revised"], db=Depends(get_db), user=Depends(current_user)):
        return file_response(db, user, accessible_comparison(db, comparison_id, user), kind)

    @app.get("/api/v1/comparisons/{comparison_id}/audit")
    def audit(comparison_id: str, db=Depends(get_db), user=Depends(current_user)):
        accessible_comparison(db, comparison_id, user)
        return [{"id": item.id, "event_type": item.event_type, "user_id": item.user_id,
                 "occurred_at": item.occurred_at.isoformat(), "details": item.details}
                for item in db.scalars(select(AuditLog).where(AuditLog.comparison_id == comparison_id).order_by(AuditLog.occurred_at))]

    return app


app = create_app()
