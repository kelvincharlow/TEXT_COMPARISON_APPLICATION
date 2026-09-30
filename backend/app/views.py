from fastapi import HTTPException
from sqlalchemy import select
from .models import Comparison, ComparisonRound, ComparisonChange, Document, DocumentVersion, ReviewTask
from .reviews import accessible_comparison, task_view


def comparison_view(db, record, user):
    document = db.get(Document, record.document_id)
    versions = [db.get(DocumentVersion, key) for key in (record.original_version_id, record.revised_version_id)]
    task = db.scalar(select(ReviewTask).where(ReviewTask.comparison_id == record.id))
    changes = [{**change.finding, "review_state": change.review_state} for change in db.scalars(
        select(ComparisonChange).where(ComparisonChange.comparison_id == record.id).order_by(ComparisonChange.position))]
    link = db.get(ComparisonRound, record.id)
    family = []
    has_successor = False
    for other in db.scalars(select(Comparison).where(Comparison.document_id == record.document_id).order_by(Comparison.created_at, Comparison.id)):
        other_link = db.get(ComparisonRound, other.id)
        if other_link and other_link.previous_comparison_id == record.id and other.processing_status == "completed":
            has_successor = True
        try:
            accessible_comparison(db, other.id, user)
        except HTTPException:
            continue
        other_task = db.scalar(select(ReviewTask).where(ReviewTask.comparison_id == other.id))
        revised = db.get(DocumentVersion, other.revised_version_id)
        family.append({"comparison_id": other.id, "round_number": other_link.round_number if other_link else 1,
                       "version_number": revised.version_number, "status": other_task.status if other_task else other.processing_status,
                       "created_at": other.created_at, "current_approved": revised.current_approved})
    return {"round_number": link.round_number if link else 1,
            "previous_comparison_id": link.previous_comparison_id if link else None,
            "family_history": family,
            "can_upload_revision": bool(task and task.status == "revision_required" and not has_successor and
                                        (record.created_by == user.id or document.owning_department_id == user.department_id) and "staff" in {r.name for r in user.roles}),
            **record.result, "changes": changes, "review_task": task_view(db, task), "comparison_id": record.id, "created_at": record.created_at.isoformat(),
            "created_by": record.created_by, "review_type": record.review_type,
            "processing_status": record.processing_status,
            "metadata": {"document_id": document.id, "title": document.title,
                         "owning_department_id": document.owning_department_id,
                         "document_type": document.document_type,
                         "responsible_officer": document.responsible_officer,
                         "work_email": document.work_email,
                         "revision_source": versions[1].revision_source,
                         "revision_contact": versions[1].revision_contact},
            "versions": [{"id": v.id, "version_number": v.version_number, "file_name": v.file_name,
                          "file_hash": v.file_hash, "uploaded_at": v.uploaded_at.isoformat(), "current_approved": v.current_approved,
                          "download_url": f"/api/v1/comparisons/{record.id}/files/{kind}"}
                         for v, kind in zip(versions, ("original", "revised"))],
            "download": {"available": bool(record.redline_path),
                         "url": f"/api/v1/comparisons/{record.id}/download" if record.redline_path else None}}
