"""Database-backed opaque sessions and application-account authentication."""
from __future__ import annotations

import hashlib
from datetime import timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request
from .models import AuthSession, User, utcnow

ROLES = ("staff", "manager", "administrator")
COOKIE_NAME = "postbank_session"
SESSION_SECONDS = 8 * 60 * 60
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("not-an-account-password")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def hash_password(password):
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain between 12 and 128 characters.")
    return hasher.hash(password)


def verify_password(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def get_db(request: Request):
    with request.app.state.sessions() as session:
        yield session


def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    record = db.get(AuthSession, token_hash(token)) if token else None
    if record is None or aware(record.expires_at) <= utcnow():
        raise HTTPException(401, "Please sign in to continue.")
    user = db.get(User, record.user_id)
    if user is None or not user.active:
        raise HTTPException(401, "Please sign in to continue.")
    return user


def require_role(user, role):
    if role != "administrator" and "administrator" in {item.name for item in user.roles}:
        raise HTTPException(403, "Administrator accounts are administration-only.")
    if role not in {item.name for item in user.roles}:
        raise HTTPException(403, "Your account does not have permission for this action.")


def user_view(user):
    return {"id": user.id, "full_name": user.full_name, "email": user.email,
            "employee_number": user.employee_number, "department_id": user.department_id,
            "department": user.department.name, "roles": [role.name for role in user.roles]}
