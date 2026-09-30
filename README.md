# Postbank Document Workspace

Internal DOCX comparison and department review application. Staff upload original
and revised versions, inspect page-by-page redlines, approve and download.
Clarifications and manager escalations are optional and block approval until
resolved. Administrators manage accounts and departments separately.

## Run locally

1. Copy `.env.compose.example` to `.env` and set a unique database password.
2. Run `docker compose up -d --build`.
3. Create the initial administrator using the command in [DEPLOYMENT.md](DEPLOYMENT.md).
4. Open <http://localhost:8080>.

Never commit `.env`, account credentials, uploaded documents or database backups.
No accounts are seeded automatically. Email delivery is intentionally disabled;
in-app notifications are implemented.

## Repository layout

- `backend/app/`: FastAPI, authentication, comparison engine and review workflows.
- `backend/migrations/`: complete Alembic schema and data migration history.
- `backend/tests/`: API, workflow, PostgreSQL, preview and comparison regressions.
- `frontend/`: React UI and Nginx configuration.
- `poc/`: optional developer benchmarks and comparison regression tools; not shipped in the runtime image.
- `scripts/`: authenticated deployment smoke test.
- `compose.yaml`: application services with persistent database and document volumes.
- `compose.test.yaml`: isolated disposable integration environment.

## Verify changes

```sh
npm ci --prefix frontend
npm run build --prefix frontend
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down --volumes
```

The test configuration uses a separate project and disposable PostgreSQL storage.
It does not mount application data. GitHub Actions runs these checks on pushes
and pull requests. The backend test image includes fixtures and tools; Compose
explicitly selects the smaller `runtime` target for application services.

For optional developer commands, run modules from the repository root, e.g.
`python -m poc.compare_documents --help`. To benchmark generated synthetic
samples, run `python -m poc.generate_samples` followed by `python -m poc.benchmark`.

## Deployment status

Prepared for internal acceptance testing; enterprise rollout still needs approved
HTTPS hosting, backup/restore procedures, retention policies and operational
monitoring. Corporate identity and email transport await Postbank IT decisions.
See [DEPLOYMENT.md](DEPLOYMENT.md) for configuration, upgrades and access rules.
