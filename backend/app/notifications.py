from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from .auth import current_user, get_db
from .models import Notification, utcnow

router = APIRouter(prefix="/api/v1/notifications")


@router.get("")
def notifications(offset: int = Query(0, ge=0), db=Depends(get_db), user=Depends(current_user)):
    records = db.scalars(select(Notification).where(Notification.user_id == user.id)
                         .order_by(Notification.created_at.desc(), Notification.id).offset(offset).limit(30))
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)))
    return {"unread_count": unread, "items": [{"id": item.id, "comparison_id": item.comparison_id,
            "event_type": item.event_type, "message": item.message, "created_at": item.created_at,
            "read_at": item.read_at} for item in records]}


@router.post("/{notification_id}/read", status_code=204)
def mark_read(notification_id: str, db=Depends(get_db), user=Depends(current_user)):
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "Notification was not found.")
    if item.read_at is None:
        item.read_at = utcnow()
        db.commit()
