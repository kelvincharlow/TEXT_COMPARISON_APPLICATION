"""Local account provisioning: python -m backend.app.manage create-user --help."""
from __future__ import annotations
import argparse
import getpass
from email_validator import validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .auth import ROLES, hash_password
from .database import make_engine, session_factory
from .models import AuditLog, Department, Role, User


def create_user(db, *, full_name, employee_number, email, department, roles, password):
    if "administrator" in roles and len(set(roles)) != 1:
        raise ValueError("Administrator accounts cannot also have document workflow roles.")
    email = validate_email(email, check_deliverability=False).normalized.lower()
    if not roles or set(roles) - set(ROLES):
        raise ValueError("Choose at least one valid role.")
    values = ((full_name, 200), (employee_number, 80), (department, 120))
    if any(not value.strip() or len(value) > limit for value, limit in values):
        raise ValueError("Name, employee number and department must be nonblank and within field limits.")
    password_hash = hash_password(password)
    dept = db.scalar(select(Department).where(Department.name == department.strip()))
    if dept is None:
        dept = Department(name=department.strip())
        db.add(dept)
        db.flush()
    role_rows = list(db.scalars(select(Role).where(Role.name.in_(roles))))
    if len(role_rows) != len(set(roles)):
        raise ValueError("Run Alembic migrations before provisioning accounts.")
    user = User(full_name=full_name.strip(), employee_number=employee_number.strip(), email=email,
                department_id=dept.id, password_hash=password_hash, roles=role_rows)
    db.add(user)
    db.flush()
    db.add(AuditLog(user_id=user.id, event_type="account_provisioned",
                    details={"source": "local_admin_cli", "roles": sorted(set(roles))}))
    return user


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--name", required=True)
    create.add_argument("--employee-number", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--department", required=True)
    create.add_argument("--roles", nargs="+", choices=ROLES, default=["staff"])
    args = parser.parse_args()
    password = getpass.getpass("Password (12–128 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match.")
    try:
        with session_factory(make_engine())() as db:
            user = create_user(db, full_name=args.name, employee_number=args.employee_number,
                               email=args.email, department=args.department, roles=args.roles, password=password)
            db.commit()
            print(f"Account created for {user.email}.")
    except (ValueError, IntegrityError) as exc:
        parser.error("Email or employee number already exists." if isinstance(exc, IntegrityError) else str(exc))


if __name__ == "__main__":
    main()
