"""Review permissions, state transitions and PostgreSQL concurrency checks."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from alembic import command
from sqlalchemy import select
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.models import ReviewTask, ReviewDecision, DocumentVersion
from backend.tests.support import initialize_database, provision_user, login_client


def synthetic_comparison(original, revised, output):
    output.write_bytes(b"synthetic redline")
    return {"success": True, "summary": {"total_changes": 2}, "changes": [
        {"type": "modification", "original_text": "30 days", "revised_text": "14 days", "location": {"part": "document", "container": "paragraph", "paragraph_index": 1}},
        {"type": "addition", "original_text": "", "revised_text": "New condition", "location": {"part": "document", "container": "paragraph", "paragraph_index": 2}},
    ]}


class ReviewFixture(unittest.TestCase):
    def make_test_database_url(self):
        return f"sqlite:///{self.root / 'test.db'}"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.url = self.make_test_database_url()
        self.config = initialize_database(self.url)
        self.app = create_app(self.root / "files", database_url=self.url)
        self.clients = []
        self.creator, self.creator_id, self.department_id = self.account("creator", ["staff"])
        self.reviewer, self.reviewer_id, _ = self.account("reviewer", ["staff"])
        self.second, self.second_id, _ = self.account("second", ["staff"])
        self.manager, _, _ = self.account("manager", ["manager"])
        self.outsider, _, _ = self.account("outsider", ["staff", "manager"], "Finance")
        self.admin, _, _ = self.account("admin", ["administrator"])

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.app.state.engine.dispose()
        self.temp.cleanup()

    def account(self, name, roles, department="ICT"):
        uid, dept = provision_user(self.app, email=name + "@example.com", employee=name, roles=roles, department=department)
        client = TestClient(self.app, headers={"X-Postbank-Request": "1"})
        self.clients.append(client)
        login_client(client, name + "@example.com")
        return client, uid, dept

    def comparison(self, review_type="standard", engine=synthetic_comparison):
        with patch("backend.app.main.run_comparison", side_effect=engine):
            response = self.creator.post("/api/v1/compare", data={"title": "Payment terms",
                "owning_department_id": self.department_id, "document_type": "Letter",
                "responsible_officer": "Officer", "work_email": "creator@example.com",
                "revision_source": "Finance", "review_type": review_type}, files={
                "original": ("original.docx", b"original"), "revised": ("revised.docx", b"revised")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def detail(self, payload):
        return self.creator.get(f"/api/v1/comparisons/{payload['comparison_id']}").json()

    def action(self, client, payload, route, **body):
        task = self.detail(payload)["review_task"]
        if route == "complete" and "confirm_document_read" not in body:
            body["confirm_document_read"] = True
        return client.post(f"/api/v1/review-tasks/{task['id']}/{route}", json={"revision": task["revision"], **body})

    def decision(self, client, payload, index, action="accepted", **body):
        return self.action(client, payload, f"changes/{payload['changes'][index]['id']}/decision", action=action, **body)

    def accept_all(self, payload):
        self.assertEqual(self.action(self.creator, payload, "release").status_code, 200)
        self.assertEqual(self.action(self.reviewer, payload, "claim").status_code, 200)


class ReviewTests(ReviewFixture):
    def test_department_permissions_and_exclusive_claim(self):
        p = self.comparison()
        self.assertEqual(len(self.reviewer.get('/api/v1/review-tasks').json()), 1)
        self.assertEqual(self.outsider.get('/api/v1/review-tasks').json(), [])
        self.assertEqual(self.action(self.admin, p, 'claim').status_code, 404)
        self.assertEqual(self.action(self.creator, p, 'release').status_code, 200)
        self.assertEqual(self.action(self.reviewer, p, 'claim').status_code, 200)
        self.assertEqual(self.action(self.second, p, 'claim').status_code, 409)
        self.assertEqual(self.action(self.reviewer, p, 'release').status_code, 200)
        self.assertEqual(self.action(self.second, p, 'claim').status_code, 200)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 403)

    def test_document_completion_requires_read_attestation_not_change_votes(self):
        p = self.comparison(); self.accept_all(p)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True, confirm_document_read=False).status_code, 422)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=False).status_code, 422)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 200)
        self.assertEqual(self.detail(p)['review_task']['status'], 'approved')
        self.assertTrue(self.detail(p)['versions'][1]['current_approved'])
        self.assertEqual(self.detail(p)['review_task']['counts']['accepted'], 0)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 409)

    def test_uploader_can_approve_without_handoff(self):
        p = self.comparison()
        self.assertEqual(p['review_task']['claimed_by'], self.creator_id)
        self.assertEqual(p['review_task']['status'], 'in_review')
        self.assertEqual(self.action(self.creator, p, 'complete', accept_revised_version=True).json()['status'], 'approved')
        task = self.detail(p)['review_task']
        self.assertEqual(task['review_completed_by'], self.creator_id)
        self.assertEqual(task['final_decision_by'], self.creator_id)
        self.assertIsNone(task['approval_task'])
        self.assertTrue(self.detail(p)['versions'][1]['current_approved'])

    def test_legacy_controlled_record_uses_staff_completion(self):
        from backend.app.models import Comparison
        p = self.comparison()
        with self.app.state.sessions() as db:
            db.get(Comparison, p['comparison_id']).review_type = 'controlled'
            db.commit()
        self.assertEqual(self.action(self.creator, p, 'complete', accept_revised_version=True).json()['status'], 'approved')

    def test_other_department_upload_waits_for_department_staff(self):
        from backend.app.models import User
        with self.app.state.sessions() as db:
            target_department = db.scalar(select(User).where(User.email == 'outsider@example.com')).department_id
        previous = self.department_id
        self.department_id = target_department
        p = self.comparison()
        self.department_id = previous
        self.assertEqual(p['review_task']['status'], 'available')
        self.assertIsNone(p['review_task']['claimed_by'])
        self.assertEqual(self.action(self.creator, p, 'complete', accept_revised_version=True).status_code, 403)
        self.assertEqual(self.action(self.outsider, p, 'claim').status_code, 200)
        self.assertEqual(self.action(self.outsider, p, 'complete', accept_revised_version=True).json()['status'], 'approved')

    def test_return_requires_reason_and_preserves_documents(self):
        p = self.comparison(); self.accept_all(p)
        self.assertEqual(self.action(self.reviewer, p, 'return', comment=' ').status_code, 422)
        self.assertEqual(self.action(self.reviewer, p, 'return', comment='Correct the document.').json()['status'], 'revision_required')
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 409)
        self.assertEqual(self.creator.get(p['download']['url']).status_code, 200)

    def test_retired_change_endpoints_cannot_pause_review(self):
        p = self.comparison(); self.accept_all(p)
        self.assertEqual(self.decision(self.reviewer, p, 0, 'clarification_requested', comment='Old client').status_code, 410)
        self.assertEqual(self.detail(p)['review_task']['status'], 'in_review')

    def test_manager_reassigns_review_and_revokes_previous_claimant(self):
        p = self.comparison(); self.accept_all(p)
        self.assertEqual(self.action(self.manager, p, 'reassign', reviewer_id=self.second_id, comment='Reviewer unavailable').status_code, 200)
        self.assertEqual(self.action(self.reviewer, p, 'return', comment='Not owner').status_code, 403)
        self.assertEqual(self.action(self.second, p, 'complete', accept_revised_version=True).status_code, 200)

    def test_parallel_claims_have_exactly_one_winner(self):
        if self.app.state.engine.dialect.name != 'postgresql': self.skipTest('Concurrency is verified on PostgreSQL')
        p = self.comparison(); self.action(self.creator, p, 'release'); barrier = Barrier(2)
        def claim(client):
            barrier.wait(timeout=10)
            return client.post(f"/api/v1/review-tasks/{p['review_task']['id']}/claim").status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(claim, (self.reviewer, self.second))), [200, 409])
