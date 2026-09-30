"""Non-blocking inspection, blocking approval, cross-department responses and migration."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from alembic import command
from sqlalchemy import select
from backend.tests.test_reviews import ReviewFixture
from backend.app.models import ReviewTask, ComparisonChange, ReviewDecision, ReviewIssue, new_id


class IssueTests(ReviewFixture):
    def issue(self, p, kind='clarification', recipient=None):
        response = self.action(self.reviewer, p, 'issues', kind=kind, document_side='redline', page_number=2,
            reference='Paragraph 3: Payment within 14 days', question='Please confirm this term.',
            assigned_to=(recipient or self.creator_id) if kind == 'clarification' else '')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['issues'][-1]

    def test_multiple_questions_do_not_pause_but_all_block_completion(self):
        p = self.comparison(); self.accept_all(p)
        a = self.issue(p); b = self.issue(p, 'escalation')
        self.assertEqual(self.detail(p)['review_task']['status'], 'in_review')
        self.assertEqual(self.detail(p)['review_task']['open_issue_count'], 2)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 409)
        self.assertEqual(self.action(self.reviewer, p, f"issues/{a['id']}/resolve", comment='No response yet').status_code, 409)
        self.assertEqual(self.action(self.creator, p, f"issues/{a['id']}/respond", comment='Confirmed.').status_code, 200)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 409)
        self.assertEqual(self.action(self.reviewer, p, f"issues/{a['id']}/resolve", comment='Response is satisfactory.').status_code, 200)
        self.assertEqual(self.action(self.manager, p, f"issues/{b['id']}/respond", comment='Proceed under the agreed conditions.').status_code, 200)
        self.assertEqual(self.action(self.reviewer, p, f"issues/{b['id']}/resolve", comment='Manager decision reviewed.').status_code, 200)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 200)
        self.assertEqual(self.action(self.creator, p, f"issues/{a['id']}/respond", comment='Too late').status_code, 409)

    def test_cross_department_recipient_gets_case_access_but_no_decision_authority(self):
        p = self.comparison(); other = self.comparison(); self.accept_all(p)
        with self.app.state.sessions() as db:
            from backend.app.models import User
            target = db.scalar(select(User).where(User.email == 'outsider@example.com')).id
        issue = self.issue(p, recipient=target)
        self.assertEqual(self.outsider.get(f"/api/v1/comparisons/{p['comparison_id']}").status_code, 200)
        self.assertEqual(self.outsider.get(p['versions'][0]['download_url']).status_code, 200)
        self.assertEqual(self.outsider.get(f"/api/v1/comparisons/{other['comparison_id']}").status_code, 404)
        self.assertEqual(len(self.outsider.get('/api/v1/review-issues').json()), 1)
        self.assertEqual(self.action(self.outsider, p, 'complete', accept_revised_version=True).status_code, 403)
        self.assertEqual(self.action(self.creator, p, f"issues/{issue['id']}/respond", comment='Not assigned').status_code, 403)
        self.assertEqual(self.action(self.outsider, p, f"issues/{issue['id']}/respond", comment='Confirmed by Finance.').status_code, 200)
        self.assertEqual(self.action(self.outsider, p, f"issues/{issue['id']}/resolve", comment='Cannot self resolve').status_code, 403)
        self.assertEqual(self.detail(p)['review_task']['open_issue_count'], 1)
        self.assertEqual(self.outsider.get('/api/v1/notifications').json()['unread_count'], 1)

    def test_reopen_reassignment_and_return_preserve_issue_history(self):
        p = self.comparison(); self.accept_all(p); a = self.issue(p)
        self.action(self.creator, p, f"issues/{a['id']}/respond", comment='Answer')
        self.action(self.reviewer, p, f"issues/{a['id']}/resolve", comment='Reviewed')
        self.assertEqual(self.action(self.reviewer, p, f"issues/{a['id']}/reopen", comment='A further question').status_code, 200)
        self.action(self.manager, p, 'reassign', reviewer_id=self.second_id, comment='Reallocate')
        self.action(self.creator, p, f"issues/{a['id']}/respond", comment='Further response')
        self.assertEqual(self.action(self.reviewer, p, f"issues/{a['id']}/resolve", comment='Old owner').status_code, 403)
        self.assertEqual(self.action(self.second, p, f"issues/{a['id']}/resolve", comment='Reviewed again').status_code, 200)
        self.assertEqual(len(self.detail(p)['review_task']['issues'][0]['messages']), 6)
        self.assertEqual(self.action(self.second, p, 'return', comment='Other corrections required').status_code, 200)

    def test_manager_can_require_revision_and_invalid_issue_inputs_fail(self):
        p = self.comparison(); self.accept_all(p)
        a = self.issue(p, 'escalation')
        self.assertEqual(self.action(self.creator, p, f"issues/{a['id']}/respond", comment='No manager role').status_code, 403)
        self.assertEqual(self.action(self.manager, p, f"issues/{a['id']}/respond", comment='Must correct the term', outcome='revision_required').json()['status'], 'revision_required')
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 409)

    def test_retired_final_approval_cannot_bypass_open_issue(self):
        p = self.comparison(); self.accept_all(p); self.issue(p)
        self.assertEqual(self.action(self.manager, p, 'approval/claim').status_code, 410)
        self.assertEqual(self.action(self.manager, p, 'approval/decision', decision='approve', confirm_version=True).status_code, 410)
        self.assertEqual(self.action(self.reviewer, p, 'complete', accept_revised_version=True).status_code, 409)
        self.assertFalse(self.detail(p)['versions'][1]['current_approved'])

    def test_issue_validation_and_stale_writes(self):
        p = self.comparison(); self.accept_all(p)
        base = dict(kind='clarification', document_side='redline', page_number=1, reference='Terms', question='Explain?', assigned_to=self.creator_id)
        for changes in ({'page_number': 0}, {'reference': ' '}, {'question': ' '}, {'assigned_to': self.reviewer_id}, {'assigned_to': 'missing'}, {'document_side': 'revised'}):
            self.assertEqual(self.action(self.reviewer, p, 'issues', **{**base, **changes}).status_code, 422)
        task = self.detail(p)['review_task']
        a = self.issue(p)
        response = self.reviewer.post(f"/api/v1/review-tasks/{task['id']}/issues", json={**base, 'revision': task['revision']})
        self.assertEqual(response.status_code, 409)
        other = self.comparison(); self.accept_all(other)
        self.assertEqual(self.action(self.reviewer, other, f"issues/{a['id']}/resolve", comment='Wrong review').status_code, 404)

    def test_parallel_question_and_completion_cannot_both_succeed(self):
        if self.app.state.engine.dialect.name != 'postgresql': self.skipTest('Concurrency is verified on PostgreSQL')
        p = self.comparison(); self.accept_all(p)
        task = self.detail(p)['review_task']; barrier = Barrier(2)
        def submit(kind):
            barrier.wait(timeout=10)
            body = {'revision': task['revision']}
            if kind == 'complete': body.update(accept_revised_version=True, confirm_document_read=True)
            else: body.update(kind='clarification', document_side='redline', page_number=1, reference='Terms', question='Confirm?', assigned_to=self.creator_id)
            return self.reviewer.post(f"/api/v1/review-tasks/{task['id']}/{kind}", json=body).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(submit, ('issues', 'complete'))), [200, 409])
        task = self.detail(p)['review_task']
        self.assertFalse(task['status'] == 'approved' and task['open_issue_count'])
