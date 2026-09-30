"""Migration preserves legacy records while removing compulsory handoffs."""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from backend.app.database import make_engine, session_factory
from backend.app.models import (Role, User, Department, AuthSession, Document, DocumentVersion,
    Comparison, ReviewTask, ApprovalTask, ReviewIssue, ReviewDecision, AuditLog, Notification, utcnow)


class StaffMigrationTests(unittest.TestCase):
    def make_test_database_url(self):
        return f"sqlite:///{self.root / 'legacy.db'}"

    def test_consolidation_preserves_history_and_never_auto_approves(self):
        with tempfile.TemporaryDirectory() as folder:
            self.root = Path(folder)
            url = self.make_test_database_url()
            config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
            config.attributes['database_url'] = url
            command.upgrade(config, 'fe15e27dc2fc')
            engine = make_engine(url)
            try:
                sessions = session_factory(engine)
                with sessions() as db:
                    department = Department(name='ICT'); db.add(department); db.flush()
                    accounts = []
                    for i, roles in enumerate([['comparator','reviewer'], ['approver'], ['administrator'], ['reviewer']]):
                        user = User(full_name=f'Legacy {i}', employee_number=f'L{i}', email=f'legacy{i}@example.com',
                            department_id=department.id, password_hash='retained-password-hash', active=i != 3,
                            roles=[db.get(Role, role) for role in roles])
                        db.add(user); db.flush(); accounts.append(user)
                        db.add(AuthSession(token_hash=str(i)*64, user_id=user.id, expires_at=utcnow()+timedelta(hours=1)))
                    account_ids = [u.id for u in accounts]
                    document = Document(title='Legacy policy', owning_department_id=department.id, document_type='Policy',
                        responsible_officer='Officer', work_email=accounts[0].email, created_by=accounts[0].id)
                    db.add(document); db.flush()
                    versions = []
                    for i in range(1,5):
                        v = DocumentVersion(document_id=document.id, version_number=i, file_name=f'{i}.docx',
                            storage_path=f'legacy/{i}.docx', file_hash=str(i)*64, uploaded_by=accounts[0].id,
                            revision_source='Finance', revision_contact='Officer', current_approved=i == 2)
                        db.add(v); db.flush(); versions.append(v)
                    task_ids = []
                    for i, status in enumerate(['approved','awaiting_final_approval','awaiting_final_approval']):
                        c = Comparison(document_id=document.id, original_version_id=versions[0].id,
                            revised_version_id=versions[i+1].id, created_by=accounts[0].id,
                            review_type='controlled', processing_status='completed', result={'changes':[]})
                        db.add(c); db.flush()
                        owner = accounts[3] if i == 2 else accounts[0]
                        t = ReviewTask(comparison_id=c.id, department_id=department.id, status=status,
                            claimed_by=owner.id, review_completed_by=owner.id, review_completed_at=utcnow())
                        db.add(t); db.flush(); task_ids.append(t.id)
                        db.add(ApprovalTask(review_task_id=t.id, status='approved' if i == 0 else 'in_progress',
                            claimed_by=accounts[1].id, comment='Historical approval note',
                            decided_by=accounts[1].id if i == 0 else None))
                        db.add(ReviewDecision(task_id=t.id, user_id=owner.id, action='final_approval_requested', comment='Historical decision'))
                        if i == 1:
                            db.add(ReviewIssue(task_id=t.id, kind='escalation', status='open', document_side='redline',
                                version_id=versions[i+1].id, page_number=1, reference='Terms', question='Outstanding question',
                                department_id=department.id, created_by=owner.id))
                    db.commit()
                command.upgrade(config, 'head')
                command.check(config)
                with sessions() as db:
                    self.assertEqual(set(db.scalars(select(Role.name))), {'staff','manager','administrator'})
                    self.assertEqual([[r.name for r in db.get(User, uid).roles] for uid in account_ids],
                                     [['staff'],['manager'],['administrator'],['staff']])
                    self.assertEqual(db.get(User, account_ids[0]).password_hash, 'retained-password-hash')
                    self.assertFalse(db.get(User, account_ids[3]).active)
                    self.assertEqual(len(list(db.scalars(select(AuthSession)))), 1)  # administrator retained
                    tasks = [db.get(ReviewTask, tid) for tid in task_ids]
                    self.assertEqual([t.status for t in tasks], ['approved','in_review','available'])
                    self.assertEqual(tasks[1].claimed_by, account_ids[0]); self.assertIsNone(tasks[2].claimed_by)
                    self.assertEqual([t.revision for t in tasks], [1,2,2])
                    self.assertEqual([db.scalar(select(ApprovalTask).where(ApprovalTask.review_task_id == tid)).status for tid in task_ids], ['approved','superseded','superseded'])
                    self.assertEqual(len(list(db.scalars(select(ReviewIssue)))), 1)
                    self.assertEqual(len(list(db.scalars(select(ReviewDecision)))), 5)
                    self.assertEqual(len(list(db.scalars(select(DocumentVersion).where(DocumentVersion.current_approved.is_(True))))), 1)
                    self.assertEqual(len(list(db.scalars(select(AuditLog)))), 5)
                    self.assertTrue(list(db.scalars(select(Notification))))
            finally:
                engine.dispose()
