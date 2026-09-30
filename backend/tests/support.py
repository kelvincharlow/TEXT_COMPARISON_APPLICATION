from pathlib import Path
from alembic import command
from alembic.config import Config
from backend.app.manage import create_user

TEST_PASSWORD = "synthetic-test-password-123"


def initialize_database(url):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    return config


def provision_user(app, email="test@example.com", roles=None, employee="TEST-1", department="ICT"):
    with app.state.sessions() as db:
        user = create_user(db, full_name="Test User", employee_number=employee, email=email,
                           department=department, roles=roles or ["staff"], password=TEST_PASSWORD)
        db.commit()
        return user.id, user.department_id


def login_client(client, email="test@example.com", password=TEST_PASSWORD):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response
