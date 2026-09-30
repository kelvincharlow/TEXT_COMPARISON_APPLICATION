"""Identity, migrations and durability tests independent of the native engine."""
from __future__ import annotations
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from backend.app.auth import COOKIE_NAME, token_hash
from backend.app.main import create_app
from backend.app.models import AuditLog, AuthSession, Comparison, ComparisonChange, DocumentVersion, User, utcnow
from backend.tests.support import initialize_database, provision_user, login_client


def synthetic_comparison(original, revised, output):
    output.write_bytes(b"synthetic-redline")
    return {"success": True, "summary": {"total_changes": 1}, "changes": [{"type": "modification", "original_text": "30", "revised_text": "14"}]}


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.url = self.make_test_database_url()
        self.config = initialize_database(self.url)
        self.app = create_app(self.root / "files", database_url=self.url)
        self.user_id, self.department_id = provision_user(self.app)
        self.client = TestClient(self.app, headers={"X-Postbank-Request": "1"})
        self.metadata = {"title": "Payment terms", "owning_department_id": self.department_id,
                         "document_type": "Letter", "responsible_officer": "Finance Officer",
                         "work_email": "finance@example.com", "revision_source": "Finance"}

    def make_test_database_url(self):
        return f"sqlite:///{self.root / 'test.db'}"

    def tearDown(self):
        self.client.close()
        self.app.state.engine.dispose()
        self.temp.cleanup()

    def compare(self, **metadata):
        with patch("backend.app.main.run_comparison", side_effect=synthetic_comparison):
            return self.client.post("/api/v1/compare", data={**self.metadata, **metadata}, files={
                "original": ("original.docx", b"original document"),
                "revised": ("revised.docx", b"revised document")})

    def test_migration_matches_models_and_has_roles(self):
        command.check(self.config)
        tables = inspect(self.app.state.engine).get_table_names()
        self.assertIn("document_versions", tables)
        self.assertIn("comparison_changes", tables)
        # Downgrade is only exercised against this disposable database.
        with self.assertRaisesRegex(RuntimeError, "cannot be safely reversed"):
            command.downgrade(self.config, "base")
        command.check(self.config)

    def test_authentication_logout_and_session_expiry(self):
        self.assertEqual(self.client.get("/api/v1/comparisons").status_code, 401)
        response = login_client(self.client)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        self.assertNotIn("password", response.text)
        token = self.client.cookies.get(COOKIE_NAME)
        with self.app.state.sessions() as db:
            self.assertIsNone(db.get(AuthSession, token))
            record = db.get(AuthSession, token_hash(token))
            record.expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
        login_client(self.client)
        self.assertEqual(self.client.post("/api/v1/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_login_failures_lock_account_temporarily(self):
        for _ in range(5):
            response = self.client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "incorrect"})
            self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "synthetic-test-password-123"})
        self.assertEqual(response.status_code, 429)

    def test_request_header_and_role_enforcement(self):
        with TestClient(self.app) as unguarded:
            self.assertEqual(unguarded.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "anything"}).status_code, 403)
        provision_user(self.app, "admin@example.com", ["administrator"], "ADMIN-1")
        login_client(self.client, "admin@example.com")
        self.assertEqual(self.compare().status_code, 403)

    def test_deactivated_account_cannot_use_existing_session(self):
        login_client(self.client)
        with self.app.state.sessions() as db:
            db.get(User, self.user_id).active = False
            db.commit()
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_persists_documents_results_and_audit_across_restart(self):
        login_client(self.client)
        response = self.compare()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        key = payload["comparison_id"]
        for _ in range(2):
            self.assertEqual(self.client.get(payload["download"]["url"]).content, b"synthetic-redline")
        for version in payload["versions"]:
            self.assertEqual(self.client.get(version["download_url"]).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v1/comparisons/{key}").status_code, 405)
        restarted = create_app(self.root / "files", database_url=self.url)
        with TestClient(restarted, headers={"X-Postbank-Request": "1"}) as client:
            login_client(client)
            detail = client.get(f"/api/v1/comparisons/{key}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["changes"], payload["changes"])
            self.assertEqual(len(client.get("/api/v1/comparisons").json()), 1)
            events = client.get(f"/api/v1/comparisons/{key}/audit").json()
            self.assertIn("comparison_completed", [event["event_type"] for event in events])
        restarted.state.engine.dispose()
        with self.app.state.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(DocumentVersion)), 2)
            change = db.scalar(select(ComparisonChange))
            self.assertEqual(change.id, payload["changes"][0]["id"])
            versions = list(db.scalars(select(DocumentVersion).order_by(DocumentVersion.version_number)))
            self.assertEqual(versions[1].previous_version_id, versions[0].id)

    def test_other_users_cannot_access_comparison_or_files(self):
        login_client(self.client)
        payload = self.compare().json()
        provision_user(self.app, "another@example.com", employee="TEST-2", department="Finance")
        login_client(self.client, "another@example.com")
        self.assertEqual(self.client.get("/api/v1/comparisons").json(), [])
        key = payload["comparison_id"]
        for path in (f"/api/v1/comparisons/{key}", payload["download"]["url"],
                     payload["versions"][0]["download_url"], f"/api/v1/comparisons/{key}/audit"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_controlled_review_input_is_retired(self):
        login_client(self.client)
        self.assertEqual(self.compare(review_type='controlled').status_code, 422)

    def test_failed_engine_preserves_input_versions(self):
        login_client(self.client)
        with patch("backend.app.main.run_comparison", side_effect=RuntimeError("synthetic failure")):
            response = self.client.post("/api/v1/compare", data=self.metadata, files={
                "original": ("original.docx", b"original"), "revised": ("revised.docx", b"revised")})
        self.assertEqual(response.status_code, 500)
        payload = self.client.get(f"/api/v1/comparisons/{response.json()['comparison_id']}").json()
        self.assertEqual(payload["processing_status"], "failed")
        self.assertFalse(payload["download"]["available"])
        self.assertEqual(self.client.get(payload["versions"][0]["download_url"]).content, b"original")

    def test_invalid_metadata_does_not_create_files(self):
        login_client(self.client)
        self.assertEqual(self.compare(owning_department_id="missing").status_code, 422)
        self.assertEqual(self.compare(review_type="unknown").status_code, 422)
        self.assertEqual(self.compare(title="  ").status_code, 422)
        self.assertEqual(list((self.root / "files").iterdir()), [])

    def test_database_failure_removes_only_uncommitted_files(self):
        login_client(self.client)
        from sqlalchemy.orm import Session
        with patch.object(Session, "commit", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(Exception):
                self.compare()
        self.assertEqual(list((self.root / "files").iterdir()), [])
        with self.app.state.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Comparison)), 0)
