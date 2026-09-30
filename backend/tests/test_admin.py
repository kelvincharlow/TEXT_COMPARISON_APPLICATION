"""Administrative permissions, identity lifecycle and session revocation."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from sqlalchemy import select
from backend.app.models import AuditLog, User
from backend.tests.test_reviews import ReviewFixture
from backend.tests.support import login_client
from backend.app.email_delivery import build_notification_email, DisabledEmailTransport
from types import SimpleNamespace


class AdminTests(ReviewFixture):
    def row(self, email):
        return next(u for u in self.admin.get('/api/v1/admin/users').json() if u['email'] == email)

    def create(self, **changes):
        return self.admin.post('/api/v1/admin/users', json={
            'full_name': 'New Employee', 'employee_number': 'NEW-1', 'email': 'new@example.com',
            'department_id': self.department_id, 'roles': ['staff'], 'password': 'new-test-password-123', **changes})

    def test_administrator_is_exclusive_and_not_a_clarification_recipient(self):
        self.assertEqual(self.create(roles=['administrator','staff']).status_code, 422)
        p = self.comparison(); self.accept_all(p)
        recipients = self.reviewer.get(f"/api/v1/review-tasks/{p['review_task']['id']}/issue-recipients").json()
        self.assertNotIn('admin@example.com', [r['email'] for r in recipients])
        admin = self.row('admin@example.com')
        self.assertEqual(self.action(self.reviewer, p, 'issues', kind='clarification', document_side='redline', page_number=1, reference='Terms', question='Confirm?', assigned_to=admin['id']).status_code, 422)
        self.assertEqual(self.admin.get(f"/api/v1/comparisons/{p['comparison_id']}").status_code, 404)

    def test_non_admin_cannot_manage_accounts_or_departments(self):
        for client in (self.creator, self.reviewer, self.manager, self.outsider):
            for path in ('users', 'settings'):
                self.assertEqual(client.get('/api/v1/admin/' + path).status_code, 403)
            self.assertEqual(client.post('/api/v1/admin/departments', json={'name': 'Hidden'}).status_code, 403)
        settings = self.admin.get('/api/v1/admin/settings').json()
        self.assertEqual(len(settings['roles']), 3)
        self.assertFalse(settings['email']['delivery_enabled'])

    def test_create_update_deactivate_reactivate_and_duplicate_validation(self):
        response = self.create(); self.assertEqual(response.status_code, 201, response.text)
        account = response.json()
        self.assertNotIn('password', response.text)
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.create(email='other@example.com', employee_number='NEW-2', roles=['owner']).status_code, 422)
        login_client(self.creator, 'new@example.com', 'new-test-password-123')
        self.assertEqual(self.creator.get('/api/v1/auth/me').status_code, 200)
        result = self.admin.put('/api/v1/admin/users/' + account['id'], json={**account, 'active': False})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.creator.get('/api/v1/auth/me').status_code, 401)
        self.assertEqual(self.creator.post('/api/v1/auth/login', json={'email':'new@example.com','password':'new-test-password-123'}).status_code, 401)
        account = result.json()
        result = self.admin.put('/api/v1/admin/users/' + account['id'], json={**account, 'active': True, 'roles': ['staff']})
        self.assertEqual(result.status_code, 200, result.text)
        login_client(self.creator, 'new@example.com', 'new-test-password-123')
        self.assertEqual(self.creator.get('/api/v1/review-tasks').status_code, 200)
        self.assertEqual(self.creator.get('/api/v1/admin/users').status_code, 403)

    def test_retired_roles_cannot_be_assigned(self):
        for role in ('comparator', 'reviewer', 'approver'):
            self.assertEqual(self.create(roles=[role]).status_code, 422)

    def test_password_reset_revokes_sessions_and_never_enters_audit(self):
        row = self.row('reviewer@example.com')
        password = 'reset-test-password-456'
        self.assertEqual(self.admin.post('/api/v1/admin/users/' + row['id'] + '/password', json={'password': password}).status_code, 204)
        self.assertEqual(self.reviewer.get('/api/v1/auth/me').status_code, 401)
        login_client(self.reviewer, 'reviewer@example.com', password)
        with self.app.state.sessions() as db:
            logs = [a.details for a in db.scalars(select(AuditLog))]
        self.assertNotIn(password, json.dumps(logs))
        self.assertNotIn('password_hash', self.admin.get('/api/v1/admin/users').text)

    def test_self_lockout_and_stale_updates_are_blocked(self):
        row = self.row('admin@example.com')
        for changes in ({'active': False}, {'roles': ['staff']}):
            self.assertEqual(self.admin.put('/api/v1/admin/users/' + row['id'], json={**row, **changes}).status_code, 422)
        row = self.row('reviewer@example.com')
        self.assertEqual(self.admin.put('/api/v1/admin/users/' + row['id'], json={**row, 'full_name': 'Updated Reviewer'}).status_code, 200)
        self.assertEqual(self.admin.put('/api/v1/admin/users/' + row['id'], json={**row, 'full_name': 'Stale Reviewer'}).status_code, 409)

    def test_department_rename_preserves_membership_and_document_history(self):
        p = self.comparison()
        department = self.admin.post('/api/v1/admin/departments', json={'name': 'Operations'}).json()
        self.assertEqual(self.admin.post('/api/v1/admin/departments', json={'name': 'operations'}).status_code, 409)
        self.assertEqual(self.admin.put('/api/v1/admin/departments/' + department['id'], json={'name':'Operations Support', 'previous_name':'Operations'}).status_code, 200)
        self.assertEqual(self.admin.put('/api/v1/admin/departments/' + self.department_id, json={'name':'ICT Services','previous_name':'ICT'}).status_code, 200)
        self.assertEqual(self.row('reviewer@example.com')['department'], 'ICT Services')
        self.assertEqual(self.detail(p)['review_task']['queue_name'], 'ICT Services Review Queue')
        self.assertEqual(self.creator.get(p['versions'][0]['download_url']).status_code, 200)

    def test_assignments_visible_and_deactivation_preserves_review(self):
        p = self.comparison(); self.accept_all(p)
        row = self.row('reviewer@example.com')
        self.assertEqual(row['assignments']['reviews'], 1)
        self.assertEqual(self.admin.put('/api/v1/admin/users/' + row['id'], json={**row, 'active':False}).status_code, 200)
        self.assertEqual(self.detail(p)['review_task']['claimed_by'], self.reviewer_id)
        self.assertEqual(self.action(self.manager,p,'reassign',reviewer_id=self.second_id,comment='Former reviewer deactivated').status_code,200)

    def test_parallel_admin_demotion_preserves_an_active_administrator(self):
        if self.app.state.engine.dialect.name != 'postgresql': self.skipTest('Concurrency is verified on PostgreSQL')
        other, _, _ = self.account('otheradmin', ['administrator'])
        first = self.row('admin@example.com'); second = self.row('otheradmin@example.com'); barrier = Barrier(2)
        def demote(pair):
            client, target = pair; barrier.wait(timeout=10)
            return client.put('/api/v1/admin/users/' + target['id'], json={**target, 'roles':['staff']}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(demote, [(self.admin,second),(other,first)]))
        self.assertEqual(codes.count(200), 1)
        self.assertTrue(all(c in (200,401,403) for c in codes))
        with self.app.state.sessions() as db:
            self.assertEqual(sum(u.active and any(r.name=='administrator' for r in u.roles) for u in db.scalars(select(User))), 1)

    def test_email_skeleton_does_not_send_and_in_app_notifications_continue(self):
        from unittest.mock import patch
        notification = SimpleNamespace(id='notice-id',comparison_id='comparison-id',message='A clarification needs your response.')
        with patch('socket.create_connection') as network:
            message = build_notification_email(notification,'recipient@example.com','https://review.example.com')
            self.assertIn('comparison-id',message.text)
            self.assertFalse(DisabledEmailTransport().send(message))
            network.assert_not_called()
        p = self.comparison(); self.action(self.creator, p, 'release')
        self.assertEqual(self.reviewer.get('/api/v1/notifications').json()['unread_count'],1)
