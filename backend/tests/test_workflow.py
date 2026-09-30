"""Final approval, immutable revision rounds and private notifications."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from alembic import command
from sqlalchemy import select
from backend.app.models import ApprovalTask, Comparison, DocumentVersion, User, Role
from backend.tests.test_reviews import ReviewFixture, synthetic_comparison


class WorkflowTests(ReviewFixture):
    def reject(self, p):
        self.accept_all(p)
        self.assertEqual(self.action(self.reviewer, p, "return", comment="Correct the payment term.").status_code, 200)

    def upload(self, p, engine=synthetic_comparison, client=None, revision=None):
        task = self.detail(p)["review_task"]
        with patch("backend.app.revisions.run_comparison", side_effect=engine):
            return (client or self.creator).post(f"/api/v1/comparisons/{p['comparison_id']}/revisions",
                data={"review_revision": revision or task["revision"]}, files={"revised": ("corrected.docx", b"corrected")})

    def test_return_and_corrected_round_preserve_history_then_staff_approval(self):
        p = self.comparison(); self.reject(p)
        def engine(original, revised, output):
            self.assertEqual(original.read_bytes(), b"original")
            return synthetic_comparison(original, revised, output)
        q = self.upload(p, engine).json()
        self.assertEqual(q['review_type'], 'standard')
        self.assertEqual(q['round_number'], 2)
        self.assertEqual(q['previous_comparison_id'], p['comparison_id'])
        self.assertEqual([v['version_number'] for v in q['versions']], [1, 3])
        self.assertEqual(q['review_task']['claimed_by'], self.creator_id)
        self.assertFalse(self.detail(p)['can_upload_revision'])
        self.assertEqual(self.upload(p).status_code, 409)
        self.assertEqual(self.action(self.creator, q, 'complete', accept_revised_version=True).json()['status'], 'approved')
        self.assertTrue(self.detail(q)['versions'][1]['current_approved'])
        self.assertEqual(self.creator.get(p['versions'][1]['download_url']).content, b'revised')

    def test_department_colleague_can_upload_corrected_version(self):
        p = self.comparison(); self.reject(p)
        self.assertTrue(self.reviewer.get(f"/api/v1/comparisons/{p['comparison_id']}").json()['can_upload_revision'])
        response = self.upload(p, client=self.reviewer)
        self.assertEqual(response.status_code, 200, response.text)
        q = response.json()
        self.assertEqual(q['review_task']['claimed_by'], self.reviewer_id)
        self.assertEqual(self.action(self.reviewer, q, 'complete', accept_revised_version=True).json()['status'], 'approved')

    def test_revision_permissions_stale_version_and_repeated_rounds(self):
        p = self.comparison()
        self.assertEqual(self.upload(p).status_code, 409)
        self.reject(p)
        for client in (self.manager, self.admin, self.outsider):
            self.assertIn(self.upload(p, client=client).status_code, (403, 404))
        self.assertEqual(self.upload(p, revision=1).status_code, 409)
        q = self.upload(p).json()
        self.reject(q)
        r = self.upload(q).json()
        self.assertEqual(r["round_number"], 3)
        self.assertEqual([v["version_number"] for v in r["versions"]], [1, 4])
        self.assertEqual(len(r["family_history"]), 3)

    def test_failed_corrected_upload_is_preserved_and_retry_allowed(self):
        p = self.comparison(); self.reject(p)
        response = self.upload(p, engine=RuntimeError("engine unavailable"))
        self.assertEqual(response.status_code, 500, response.text)
        failed = self.creator.get('/api/v1/comparisons/' + response.json()['comparison_id']).json()
        self.assertEqual(failed["processing_status"], "failed")
        self.assertIsNone(failed["review_task"])
        self.assertEqual(self.creator.get(failed["versions"][1]["download_url"]).content, b"corrected")
        self.assertTrue(self.detail(p)["can_upload_revision"])
        q = self.upload(p).json()
        self.assertEqual(q["versions"][1]["version_number"], 4)
        self.assertEqual(len(q["family_history"]), 3)

    def test_notifications_are_private_and_mark_read_idempotently(self):
        p = self.comparison()
        self.assertEqual(self.reviewer.get('/api/v1/notifications').json()['unread_count'], 0)
        self.action(self.creator, p, 'release')
        notice = self.reviewer.get('/api/v1/notifications').json()['items'][0]
        self.assertEqual(self.outsider.post(f"/api/v1/notifications/{notice['id']}/read").status_code, 404)
        for _ in range(2):
            self.assertEqual(self.reviewer.post(f"/api/v1/notifications/{notice['id']}/read").status_code, 204)
        self.assertEqual(self.reviewer.get('/api/v1/notifications').json()['unread_count'], 0)

    def test_parallel_corrected_uploads_create_only_one_successor(self):
        if self.app.state.engine.dialect.name != "postgresql": self.skipTest("Concurrency is verified on PostgreSQL")
        p = self.comparison(); self.reject(p)
        task = self.detail(p)["review_task"]; barrier = Barrier(2)
        def engine(original, revised, output):
            barrier.wait(timeout=10)
            return synthetic_comparison(original, revised, output)
        def submit(index):
            return self.creator.post(f"/api/v1/comparisons/{p['comparison_id']}/revisions",
                data={"review_revision": task["revision"]}, files={"revised": ("corrected.docx", b"corrected")}).status_code
        with patch("backend.app.revisions.run_comparison", side_effect=engine):
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(submit, (0, 1))), [200, 409])
        self.assertEqual(len(self.detail(p)["family_history"]), 2)
        self.assertEqual(len(list((self.root / "files").iterdir())), 2)
