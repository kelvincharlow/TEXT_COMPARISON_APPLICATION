"""Compatibility responses for the retired separate final-approval workflow."""
from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .reviews import task_for_user
from .auth import get_db

router = APIRouter(prefix="/api/v1")


@router.get("/approval-tasks")
def queue(user=Depends(current_user)):
    raise HTTPException(410, "Separate final approval has been retired. Use the staff document workspace.")


@router.post("/review-tasks/{task_id}/approval/claim")
@router.post("/review-tasks/{task_id}/approval/release")
@router.post("/review-tasks/{task_id}/approval/decision")
def retired_approval(task_id: str, db=Depends(get_db), user=Depends(current_user)):
    task_for_user(db, task_id, user)
    raise HTTPException(410, "Separate final approval has been retired. Complete the staff review instead.")
