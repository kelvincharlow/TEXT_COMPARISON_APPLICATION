"""Account and department administration, without business review authority."""
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, delete, func, or_
from sqlalchemy.exc import IntegrityError
from .auth import current_user, get_db, require_role, user_view, hash_password, ROLES
from .models import User, Role, Department, AuthSession, AuditLog, ReviewTask, ApprovalTask, ReviewIssue

router = APIRouter(prefix='/api/v1/admin')


def administrator(user=Depends(current_user)):
    require_role(user, 'administrator')
    return user


def lock_administration(db, user):
    # Serialize role/account administration to avoid concurrent privilege changes
    # using an administrator session that has just been revoked.
    uid = user.id
    db.scalar(select(Role).where(Role.name == 'administrator').with_for_update())
    db.expire_all()
    actor = db.get(User, uid)
    if not actor.active:
        raise HTTPException(401, 'Please sign in again.')
    require_role(actor, 'administrator')
    return actor


def account_view(user):
    result = {**user_view(user), 'active': user.active}
    result['roles'] = sorted(result['roles'])
    result['revision'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def assignments(db, uid):
    return {
        'reviews': db.scalar(select(func.count()).select_from(ReviewTask).where(ReviewTask.claimed_by == uid, ReviewTask.status.in_(['in_review', 'clarification_requested', 'escalated']))),
        'approvals': db.scalar(select(func.count()).select_from(ApprovalTask).where(ApprovalTask.claimed_by == uid, ApprovalTask.status == 'in_progress')),
        'clarifications': db.scalar(select(func.count()).select_from(ReviewIssue).join(ReviewTask, ReviewIssue.task_id == ReviewTask.id).where(ReviewIssue.assigned_to == uid, ReviewIssue.status != 'resolved', ReviewTask.status.in_(['available', 'in_review']))),
    }


class UserInput(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    employee_number: str = Field(min_length=1, max_length=80)
    email: EmailStr
    department_id: str = Field(min_length=1, max_length=36)
    roles: list[str] = Field(min_length=1, max_length=5)


class CreateUserInput(UserInput):
    password: str = Field(min_length=12, max_length=128)


class UpdateUserInput(UserInput):
    active: bool
    revision: str = Field(min_length=64, max_length=64)


class PasswordInput(BaseModel):
    password: str = Field(min_length=12, max_length=128)


class DepartmentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RenameDepartmentInput(DepartmentInput):
    previous_name: str


def validate_user(db, body):
    if "administrator" in body.roles and len(body.roles) != 1:
        raise HTTPException(422, "Administrator accounts are administration-only. Use a separate account for document work.")
    if not body.full_name.strip() or not body.employee_number.strip():
        raise HTTPException(422, 'Name and employee number must not be blank.')
    if len(str(body.email)) > 254 or set(body.roles) - set(ROLES) or len(body.roles) != len(set(body.roles)):
        raise HTTPException(422, 'Choose valid, distinct roles and a valid work email.')
    if not db.get(Department, body.department_id):
        raise HTTPException(422, 'Choose an existing department.')


def audit(db, actor, event, details):
    db.add(AuditLog(user_id=actor.id, event_type=event, details=details))


def commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'That email, employee number, or department name already exists. Refresh and try again.') from exc


@router.get('/users')
def users(q: str = Query('', max_length=200), offset: int = Query(0, ge=0), db=Depends(get_db), user=Depends(administrator)):
    query = select(User)
    if q.strip():
        pattern = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.where(or_(User.full_name.ilike(pattern, escape='\\'), User.email.ilike(pattern, escape='\\'), User.employee_number.ilike(pattern, escape='\\')))
    rows = db.scalars(query.order_by(User.full_name, User.id).offset(offset).limit(50))
    return [{**account_view(u), 'assignments': assignments(db, u.id)} for u in rows]


@router.get('/settings')
def settings(db=Depends(get_db), user=Depends(administrator)):
    return {'roles': list(ROLES), 'departments': [{'id': d.id, 'name': d.name} for d in db.scalars(select(Department).order_by(Department.name))],
            'email': {'delivery_enabled': False, 'status': 'Not connected; in-app notifications remain active.'}}


@router.post('/users', status_code=201)
def create_user(body: CreateUserInput, db=Depends(get_db), user=Depends(administrator)):
    actor = lock_administration(db, user)
    validate_user(db, body)
    target = User(full_name=body.full_name.strip(), employee_number=body.employee_number.strip(), email=str(body.email).lower(),
                  department_id=body.department_id, password_hash=hash_password(body.password),
                  roles=list(db.scalars(select(Role).where(Role.name.in_(body.roles)))))
    db.add(target)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'Email or employee number already exists.') from exc
    audit(db, actor, 'admin_user_created', {'target_user_id': target.id, 'roles': sorted(body.roles), 'department_id': target.department_id})
    commit(db)
    return account_view(target)


@router.put('/users/{user_id}')
def update_user(user_id: str, body: UpdateUserInput, db=Depends(get_db), user=Depends(administrator)):
    actor = lock_administration(db, user)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, 'Account not found.')
    before = account_view(target)
    if body.revision != before['revision']:
        raise HTTPException(409, 'This account changed. Refresh and reopen it before saving.')
    validate_user(db, body)
    if target.id == actor.id and (not body.active or 'administrator' not in body.roles):
        raise HTTPException(422, 'You cannot deactivate your own account or remove your own Administrator role.')
    target.full_name = body.full_name.strip(); target.employee_number = body.employee_number.strip()
    target.email = str(body.email).lower(); target.department_id = body.department_id; target.active = body.active
    target.roles = list(db.scalars(select(Role).where(Role.name.in_(body.roles))))
    target.failed_logins = 0; target.locked_until = None
    db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
    audit(db, actor, 'admin_user_updated', {'target_user_id': target.id, 'before': before,
          'after': {'full_name': target.full_name, 'email': target.email, 'employee_number': target.employee_number, 'roles': sorted(body.roles), 'department_id': body.department_id, 'active': body.active}})
    commit(db)
    db.refresh(target)
    return account_view(target)


@router.post('/users/{user_id}/password', status_code=204)
def reset_password(user_id: str, body: PasswordInput, db=Depends(get_db), user=Depends(administrator)):
    actor = lock_administration(db, user)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, 'Account not found.')
    target.password_hash = hash_password(body.password); target.failed_logins = 0; target.locked_until = None
    db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
    audit(db, actor, 'admin_password_reset', {'target_user_id': target.id})
    commit(db)


@router.post('/departments', status_code=201)
def create_department(body: DepartmentInput, db=Depends(get_db), user=Depends(administrator)):
    actor = lock_administration(db, user)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, 'Enter a department name.')
    if db.scalar(select(Department.id).where(func.lower(Department.name) == name.lower())):
        raise HTTPException(409, 'That department already exists.')
    department = Department(name=name); db.add(department); db.flush()
    audit(db, actor, 'admin_department_created', {'department_id': department.id, 'name': name})
    commit(db)
    return {'id': department.id, 'name': department.name}


@router.put('/departments/{department_id}')
def rename_department(department_id: str, body: RenameDepartmentInput, db=Depends(get_db), user=Depends(administrator)):
    actor = lock_administration(db, user)
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(404, 'Department not found.')
    if department.name != body.previous_name:
        raise HTTPException(409, 'Department changed. Refresh before renaming.')
    name = body.name.strip()
    if not name:
        raise HTTPException(422, 'Enter a department name.')
    if db.scalar(select(Department.id).where(func.lower(Department.name) == name.lower(), Department.id != department.id)):
        raise HTTPException(409, 'That department already exists.')
    audit(db, actor, 'admin_department_renamed', {'department_id': department.id, 'before': department.name, 'after': name})
    department.name = name
    commit(db)
    return {'id': department.id, 'name': department.name}
