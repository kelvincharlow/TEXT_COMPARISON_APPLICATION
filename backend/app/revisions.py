"""Corrected uploads keep their original baseline and document family."""
import logging
import os
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from backend.app.comparison.engine import DocumentValidationError
from .auth import current_user, get_db, require_role
from .models import (AuditLog, Comparison, ComparisonChange, ComparisonRound, Document,
                     DocumentVersion, ReviewTask, new_id, utcnow)
from .notification_service import notify_department, notify_users
from .reviews import accessible_comparison, mutate_task, start_staff_review, department_role
from .service import run_comparison
from .storage import save_upload
from .views import comparison_view

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = int(os.getenv("POSTBANK_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))


@router.post("/comparisons/{comparison_id}/revisions")
async def upload_revision(comparison_id: str, request: Request, revised: UploadFile = File(...),
                          review_revision: int = Form(..., ge=1),
                          db=Depends(get_db), user=Depends(current_user)):
    parent = accessible_comparison(db, comparison_id, user)
    require_role(user, "staff")
    if parent.created_by != user.id and not department_role(user, db.get(Document, parent.document_id).owning_department_id, ("staff",)):
        raise HTTPException(403, "Only the uploader or staff in the owning department may upload a corrected version.")
    task = db.scalar(select(ReviewTask).where(ReviewTask.comparison_id == parent.id))
    if task is None or task.status != "revision_required" or task.revision != review_revision:
        raise HTTPException(409, "Refresh the comparison. A corrected upload must follow a current revision request.")
    if db.scalar(select(ComparisonRound.comparison_id).join(Comparison, Comparison.id == ComparisonRound.comparison_id)
                 .where(ComparisonRound.previous_comparison_id == parent.id, Comparison.processing_status == "completed").limit(1)):
        raise HTTPException(409, "This revision request already has a new comparison round.")
    if not revised.filename or not revised.filename.lower().endswith(".docx"):
        raise HTTPException(415, "The corrected document must be a .docx file.")
    storage = request.app.state.document_storage
    baseline = db.get(DocumentVersion, parent.original_version_id)
    prior_version = db.get(DocumentVersion, parent.revised_version_id)
    baseline_path = storage.path(baseline.storage_path)
    if not baseline_path.is_file():
        raise HTTPException(409, "The original baseline file is unavailable.")
    new_comparison_id, folder = storage.create_session()
    submitted_at = utcnow()
    try:
        digest = await save_upload(revised, folder / "revised.docx", MAX_UPLOAD_BYTES)
        failed = False
        try:
            result = await run_in_threadpool(run_comparison, baseline_path, folder / "revised.docx", folder / "redline.docx")
        except DocumentValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            logger.error("Corrected comparison %s failed (%s)", new_comparison_id, type(exc).__name__)
            failed = True
            result = {"success": False, "changes": [], "error": "Comparison processing failed."}
        # Processing happens before locking. On return, recheck the persisted
        # parent revision and serialize numbering within this document family.
        locked_task = db.scalar(select(ReviewTask).where(ReviewTask.id == task.id).with_for_update()
                                .execution_options(populate_existing=True))
        if locked_task.status != "revision_required" or locked_task.revision != review_revision:
            raise HTTPException(409, "Another upload or decision changed this case. Refresh its history.")
        successor = db.scalar(select(ComparisonRound.comparison_id).join(Comparison, Comparison.id == ComparisonRound.comparison_id)
                              .where(ComparisonRound.previous_comparison_id == parent.id, Comparison.processing_status == "completed").limit(1))
        if successor:
            raise HTTPException(409, "This revision request already has a new comparison round.")
        document = db.scalar(select(Document).where(Document.id == parent.document_id).with_for_update())
        next_number = db.scalar(select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document.id)) + 1
        version = DocumentVersion(id=new_id(), document_id=document.id, version_number=next_number,
                                  previous_version_id=prior_version.id, file_name=Path(revised.filename.replace("\\", "/")).name[:255],
                                  storage_path=f"{new_comparison_id}/revised.docx", file_hash=digest, uploaded_by=user.id,
                                  uploaded_at=submitted_at, revision_source=prior_version.revision_source, revision_contact=prior_version.revision_contact)
        db.add(version); db.flush()
        for change in result["changes"]: change["id"] = new_id()
        record = Comparison(id=new_comparison_id, document_id=document.id, original_version_id=baseline.id,
                            revised_version_id=version.id, created_by=user.id, created_at=submitted_at,
                            review_type="standard", processing_status="failed" if failed else "completed", result=result,
                            redline_path=None if failed else f"{new_comparison_id}/redline.docx")
        db.add(record); db.flush()
        previous_link = db.get(ComparisonRound, parent.id)
        db.add(ComparisonRound(comparison_id=record.id, previous_comparison_id=parent.id,
                               round_number=(previous_link.round_number if previous_link else 1) + 1))
        for position, change in enumerate(result["changes"], 1):
            db.add(ComparisonChange(id=change["id"], comparison_id=record.id, position=position, finding=change))
        if not failed:
            mutate_task(db, locked_task, review_revision)
            start_staff_review(db, record.id, document.owning_department_id, user)

            db.add(AuditLog(user_id=user.id, comparison_id=record.id, event_type="review_task_created",
                            details={"previous_comparison_id": parent.id}))
        else:
            notify_users(db, [user.id], record.id, "comparison_failed", "The corrected upload was saved, but comparison processing failed.")
        for target in (parent.id, record.id):
            db.add(AuditLog(user_id=user.id, comparison_id=target,
                            event_type="revision_processing_failed" if failed else "revision_uploaded",
                            details={"previous_comparison_id": parent.id, "new_comparison_id": record.id,
                                     "version_id": version.id, "baseline_version_id": baseline.id}))
        db.flush()
        payload = comparison_view(db, record, user)
        db.commit()
    except BaseException:
        db.rollback()
        storage.discard_uncommitted(new_comparison_id)
        raise
    if failed:
        return JSONResponse({"detail": "Processing failed. The corrected version is saved in history; retry from the preceding revision request.",
                             "comparison_id": new_comparison_id}, status_code=500)
    return payload
