"""Opt-in PostgreSQL integration tests. Every test gets a disposable database.

Set POSTBANK_TEST_POSTGRES=1 and the normal database connection settings.
The database account must be able to CREATE DATABASE. Existing data is untouched.
"""
import os
import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from backend.app.database import database_url
from backend.tests import test_foundation, test_reviews, test_workflow, test_issues, test_admin, test_staff_migration


class PostgreSQLDatabaseMixin:
    def make_test_database_url(self):
        self.test_database_name = "postbank_test_" + uuid.uuid4().hex
        url = make_url(database_url())
        self.admin_engine = create_engine(url, isolation_level="AUTOCOMMIT")
        with self.admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{self.test_database_name}"')
        self.addCleanup(self.drop_test_database)
        return url.set(database=self.test_database_name)

    def drop_test_database(self):
        with self.admin_engine.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{self.test_database_name}" WITH (FORCE)')
        self.admin_engine.dispose()


@unittest.skipUnless(os.getenv("POSTBANK_TEST_POSTGRES") == "1", "Set POSTBANK_TEST_POSTGRES=1 to test PostgreSQL")
class PostgreSQLFoundationTests(PostgreSQLDatabaseMixin, test_foundation.FoundationTests):
    pass


@unittest.skipUnless(os.getenv("POSTBANK_TEST_POSTGRES") == "1", "Set POSTBANK_TEST_POSTGRES=1 to test PostgreSQL")
class PostgreSQLReviewTests(PostgreSQLDatabaseMixin, test_reviews.ReviewTests):
    pass


@unittest.skipUnless(os.getenv("POSTBANK_TEST_POSTGRES") == "1", "Set POSTBANK_TEST_POSTGRES=1 to test PostgreSQL")
class PostgreSQLWorkflowTests(PostgreSQLDatabaseMixin, test_workflow.WorkflowTests):
    pass


@unittest.skipUnless(os.getenv("POSTBANK_TEST_POSTGRES") == "1", "Set POSTBANK_TEST_POSTGRES=1 to test PostgreSQL")
class PostgreSQLIssueTests(PostgreSQLDatabaseMixin, test_issues.IssueTests):
    pass


@unittest.skipUnless(os.getenv("POSTBANK_TEST_POSTGRES") == "1", "Set POSTBANK_TEST_POSTGRES=1 to test PostgreSQL")
class PostgreSQLAdminTests(PostgreSQLDatabaseMixin, test_admin.AdminTests):
    pass


@unittest.skipUnless(os.getenv("POSTBANK_TEST_POSTGRES") == "1", "Set POSTBANK_TEST_POSTGRES=1 to test PostgreSQL")
class PostgreSQLStaffMigrationTests(PostgreSQLDatabaseMixin, test_staff_migration.StaffMigrationTests):
    pass
