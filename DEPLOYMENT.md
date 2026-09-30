# Setup and deployment

The application now uses PostgreSQL for accounts and comparison history, and a
separate Docker volume for uploaded documents and redlines. Login is required.
The React interface is served by Nginx, which proxies requests to FastAPI.

## Start the application

Requirements: Docker Desktop or Docker Engine with Compose v2. Local Python is
not required when running the application through Docker.

1. Copy `.env.compose.example` to `.env` if you do not already have one.
2. Set `POSTGRES_PASSWORD` to a unique local password. Keep `.env` out of Git.
3. Run:

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

PostgreSQL starts first. The `migrate` service runs `alembic upgrade head` and must
finish successfully before the backend starts. On a fresh installation the
migration creates the tables and three roles; it does not create default users.

4. Create your first account (substitute your own details):

   ```bash
   docker compose exec backend python -m backend.app.manage create-user \
     --name "Your Name" \
     --employee-number "YOUR-EMPLOYEE-NUMBER" \
     --email "your.name@your-work-domain.example" \
     --department "ICT" \
     --roles administrator
   ```

The command prompts for a password and confirmation without displaying it.
Passwords must contain 12–128 characters. Departments are created if needed.
After creating the first administrator, use the **Administration** tab to
manage accounts and departments. There is no public registration. Available role codes are
`staff`, `manager`, and `administrator`.
Administrator accounts are administration-only; create separate accounts for document workflows.

5. Open [the local application](http://localhost:8080) and sign in.
6. Enter document metadata, upload two DOCX files, and compare them. Results,
   original/revised versions, file hashes, and audit events are saved. You can
   reopen results from My documents and download files repeatedly.

The first comparison may take longer while the native engine is extracted.

## DBeaver connection

Install DBeaver separately if desired. Create a **PostgreSQL** connection:

| Setting | Local default |
| --- | --- |
| Host | `localhost` |
| Port | `5432` (or `POSTBANK_DB_PORT` from `.env`) |
| Database | `postbank` (or `POSTGRES_DB`) |
| Username | `postbank` (or `POSTGRES_USER`) |
| Password | `POSTGRES_PASSWORD` from your local `.env` |

Use **Test Connection**, then browse the `public` schema. Tables include
`departments`, `roles`, `users`, `user_roles`, `auth_sessions`, `documents`,
`document_versions`, `comparisons`, `comparison_changes`, `review_tasks`,
`review_decisions`, and `audit_logs`.
`alembic_version` records the applied migration. Document binary files live in
`document-data`, while the database stores their relative paths and hashes.

DBeaver is for inspecting local data. Keep schema changes in Alembic migrations.
The database port is bound to loopback only. These database credentials are
separate from application login credentials.

## Data and operations

- `postgres-data`: persistent database tables and data.
- `document-data`: original/revised documents and redlines.
- `engine-cache`: extracted native comparison engine.

```bash
docker compose logs --tail=100 backend migrate postgres
docker compose restart backend
docker compose down
```

`docker compose down` preserves named volumes. Do not use `down --volumes` when
you need to retain history. Back up both database and document volumes together.
Previously expired or deleted PoC uploads cannot be recovered by this migration.

## Staff workflow

Staff can upload, compare, inspect, approve and download their department's
versions, including documents they prepared. Successful uploads for the staff
member's own department start in review, assigned to that uploader. Uploads for
another department enter that department's queue for an eligible staff member.
Failed comparisons retain their documents and never create a review task.

1. Upload original and revised Word documents. Inspect the page preview.
2. Approve after explicitly confirming the whole document was read and the
   revised version is accepted. There is no separate reviewer or final approver.
3. Ask for clarification only when needed, assigning an active application user.
   Cross-department recipients get access to that comparison, not the department.
4. Escalate a question to the owning department's manager only when higher
   authority is needed. The manager supplies guidance or requires a correction.
5. Continue inspection and raise other questions while waiting. Open and answered
   issues block approval until the responsible staff member records resolution.
6. Release the review for another department staff member to claim, or ask a
   manager to arrange a handover. Exclusive ownership and stale-write checks
   prevent simultaneous decisions. History remains attached to the document.
7. For revision requests, the uploader or owning-department staff can upload a
   corrected version. The original baseline and prior versions are retained.
   A successful new round starts a fresh staff review; failed uploads remain in
   history and may be retried from the preceding request.

Use `--roles staff` for routine users, `--roles manager` for escalation handling,
and `--roles administrator` for account and department management. Staff and
Manager can coexist on an account. Administrator remains exclusive.

### Upgrading existing installations

Back up the database and document volume before `alembic upgrade head`.
Migration `f71a20b8d931` maps Comparator/Reviewer accounts to Staff and Approver
accounts to Manager, preserving account IDs, credentials and departments. Role
changes are audited and affected sessions revoked; users must sign in again.
Existing managers and administrators keep their access.

Pending final approvals return to staff review (or the department queue if the
previous staff member is unavailable). Nothing is automatically approved.
Historical approval tasks are retained; unfinished ones are marked superseded.
Approved versions, previous decisions, open issues and original review-type
metadata remain in history. All future completions use the single staff flow.
Old final-approval endpoints return HTTP 410, and new controlled-review submissions
are rejected. Corrected rounds always use the staff workflow.

This role consolidation cannot be automatically downgraded on populated databases;
restore the pre-upgrade database backup and previous application image to roll back.

## Current access rules and remaining scope

Creators retain access to their uploads. Staff and managers have department-scoped
read access. Only the current staff owner records review decisions and resolves
issues. Managers respond to escalations and arrange handovers; the issue author
cannot answer their own escalation. Staff may review and approve their own uploads.
Approval here records acceptance of the compared version; formal departmental
signing authority is outside the application.

Administrator alone grants no document permissions. Document ownership/contact
metadata grants no access. Work email remains a contact field and automatic email
delivery is disabled. In-app notifications cover requests, responses, handovers
and outcomes. Approval requires all issues resolved. One current approved version
is permitted per document family.

Documents, version pairs, comparisons, decisions and audit events are retained.
A new original/revised pair starts a family with versions 1 and 2; corrected
uploads add versions 3, 4 and so on to that family. Earlier documents, rejected
comparisons and decisions remain accessible. Accepted decisions are not carried
forward into a new round. The comparison engine itself grants no approval.

The workflow tables include `approval_tasks`, `comparison_rounds` and
`notifications`, alongside `review_tasks`, `review_decisions`, `review_issues`,
and `review_issue_messages`. The `approval_tasks` table remains for historical
records; the current workflow has no separate final approval stage. Corporate
identity, Outlook delivery and additional department memberships remain future
work. Staff can release review tasks; managers can reassign them.

Sessions use HttpOnly, SameSite=Strict cookies, expire after eight hours, and are
revoked by logout. Five failed attempts lock the account for 15 minutes. Set
`POSTBANK_COOKIE_SECURE=true` when serving over HTTPS. Mutating API calls require
`X-Postbank-Request: 1`; browser requests are same-origin through Nginx/Vite.

## Tests and migrations

Use Python 3.12 for the pinned application dependencies:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s backend/tests -t . -v
cd frontend
npm ci
npm run build
```

The automated unit/API tests create disposable SQLite databases through the same
Alembic migration; PostgreSQL must also be checked during deployment:

```bash
docker compose exec backend python -m alembic current
docker compose exec backend python -m alembic check
```

For the opt-in PostgreSQL integration suite, set `POSTBANK_TEST_POSTGRES=1`
and run `python -m unittest backend.tests.test_postgres -v` in a development
environment with these sources and dependencies. It creates and drops randomly
named disposable databases; the database user needs CREATE DATABASE permission.
The normal application database is not modified by this suite.

For local commands outside Docker, export the database settings from
`backend/.env.example` with your actual local credentials (the file is not
automatically loaded). `DATABASE_URL` can alternatively supply a full SQLAlchemy
URL. Never commit real credentials or include them in terminal logs.

The authenticated smoke test prompts for application credentials and saves a
synthetic comparison in that user's history:

```bash
python3 scripts/container_smoke_test.py --email "your-work-email"
```

## Deployment boundary

Keep this prototype local or on the approved internal network. Before enterprise
deployment, configure HTTPS and approved identity, retention, backup, and workflow
policies. Corporate SSO and Outlook notifications are not integrated yet.

Use one backend container for now. Multiple containers would also need shared
file storage. Public health: `/healthz`; backend health: `/api/v1/health`.
Health checks verify database connectivity and the migration table.

## Page-by-page review preview

Open a saved comparison and choose the **Preview** tab to see the
original and visual redline as rendered pages. Linked navigation moves both
panes by page number. Turn it off to navigate each document independently when
redline markup shifts page breaks. Zoom is available in both panes; narrow
screens stack the panes vertically.

Previews are generated on demand for existing and new comparisons using the
container's LibreOffice and Poppler tools. PDFs and requested page images are
cached under the comparison's `preview-v1` directory in the document volume.
Each request enforces the same account/department access as document downloads.
Rendering does not claim a review, modify a source document, or record a review
decision. Preview page numbers describe rendered documents and are not exact
semantic alignment or Microsoft Word pagination. Downloads remain available
if rendering fails; the preview can be retried.

The document-review migration converts earlier paused clarification/escalation
requests into blocking issues and resumes inspection. Historical per-change
votes and comments remain unchanged. Earlier requests without a reliable page
reference display “page not recorded”. The old change-decision and single
clarification/escalation endpoints return HTTP 410 to prevent outdated clients
from reintroducing the paused workflow. Downgrade is refused while issue records
exist to prevent loss of their history. Mail delivery is still not configured;
application inboxes and notifications are the current delivery mechanism.

## Administration screens

Administrators can search users, create accounts with initial passwords, change
names, work email, employee number, roles and department membership, and
activate/deactivate accounts. Password resets clear login lockouts and revoke
all sessions. Saving an account also revokes its sessions, so changed roles and
membership take effect on a fresh sign-in. Saving your own account signs you out.
You cannot deactivate yourself or remove your own Administrator role.
Concurrent administration writes are serialized on PostgreSQL; stale account
forms are rejected. Administrative events are audited without passwords or hashes.

Departments can be created and renamed. Users and departments are not deleted,
so document, decision and audit references remain intact. Outstanding review,
approval and clarification assignments are shown when editing an account.
Changing access does not automatically transfer that work. Arrange handover;
managers can reassign detailed reviews. Clarification reassignment remains future work, and an account can be reactivated if needed.
The three roles are fixed; Document Owner is metadata, not an access role.

## Disabled email integration skeleton

`backend/app/email_delivery.py` defines a provider-neutral message, a message
builder for notification text and application/reference links, and a transport
interface. The supplied disabled transport returns false and performs no network
operation. No worker, SMTP/Graph credentials, activation toggle or sending call
is installed. Existing in-app notification delivery is unchanged. No email is
sent and no backlog of emails is queued. Once Postbank IT approves an integration,
a provider and durable delivery/retry policy can be added explicitly without
coupling mail delivery to the review database transaction. Initial passwords
must currently be shared directly with the account holder.

Administrators now land directly on Administration and have no document-review
navigation. Administrator cannot be combined with another role, including via
account provisioning or the administration API. Use separate business accounts
for uploads, reviews, approvals, or clarification responses. Administrators are
excluded from clarification recipient selection and comparison access.

## Release preparation

1. Run the isolated checks documented in README.md. Do not run tests against the
   application database. `compose.test.yaml` uses disposable storage and its own project.
2. Back up PostgreSQL and the `document-data` volume together and verify restoration
   in a separate environment before upgrading. Keep backups outside the repository.
3. Configure the approved TLS reverse proxy and set `POSTBANK_COOKIE_SECURE=true`.
   Keep the backend private and bind the frontend to the approved interface.
4. Build and start with `docker compose up -d --build`. Application services select
   the backend `runtime` target; the `test` target is for verification only.
5. Check `docker compose ps`, migration completion, `/healthz` and a staff comparison.
   Record the deployed commit and retain the preceding images and matching backup.
6. Confirm retention, backup scheduling, monitoring, support ownership and native
   comparison engine licensing with the deployment owner before production rollout.

The native engine now lives in `backend/app/comparison/engine.py`. Its extracted
binaries use `POSTBANK_ENGINE_CACHE` (Docker: `/app/engine-cache`). The existing
`engine-cache` named volume is retained. `poc` tools and presentations are not part
of the runtime image. Historical migrations must not be removed or squashed on
an existing installation.
