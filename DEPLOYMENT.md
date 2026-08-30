# Container Deployment

This deployment runs the compiled React interface behind Nginx and proxies API requests to a single FastAPI backend container. Authentication is intentionally outside the application scope; access must be restricted to the approved Postbank internal network.

## Prerequisites

- A Linux x64 server approved for container workloads
- Docker Engine with Docker Compose v2
- An internal DNS name and HTTPS certificate or an existing internal reverse proxy
- Access to an approved internal container registry for production promotion

## Local or UAT start

1. Copy `.env.compose.example` to `.env`.
2. Keep `POSTBANK_BIND_ADDRESS=127.0.0.1` for local testing. For UAT, replace it with the server's approved internal IP.
3. Build and start the application:

   ```bash
   docker compose build --pull
   docker compose up -d
   ```

4. Verify container health:

   ```bash
   docker compose ps
   curl --fail http://127.0.0.1:8080/healthz
   ```

5. Run the end-to-end smoke test. It compares the synthetic fixtures through Nginx, checks the API response, downloads the redline, and verifies that it is a DOCX package:

   ```bash
   python scripts/container_smoke_test.py
   ```

6. Open `http://127.0.0.1:8080` or the approved internal address.

The first comparison may take longer while the platform-specific Docxodus binary is extracted into the `engine-cache` volume.

## Operations

View recent logs without exposing document content:

```bash
docker compose logs --tail=200 backend frontend
docker compose logs --follow backend
```

Restart the application:

```bash
docker compose restart
```

Stop the application while retaining the engine cache:

```bash
docker compose down
```

Uploaded documents and generated redlines are written under the backend's memory-backed `/tmp` filesystem. They disappear when the backend container stops and are also deleted by the application after download or expiry. The named `engine-cache` volume contains only the extracted comparison executable.

## Production promotion

1. Build the images in the controlled CI environment.
2. Scan the images and dependency inventory using Postbank-approved security tooling.
3. Push versioned images to the internal registry. Do not build production directly from a public Git repository.
4. Deploy the exact images tested in UAT.
5. Terminate HTTPS at the approved reverse proxy and expose only the frontend container.
6. Restrict inbound access to the internal network and keep the backend port unpublished.
7. Forward Docker logs to the approved central logging platform.
8. Keep the previous image versions available for rollback.

## Current scaling boundary

Run exactly one backend worker and one backend container. Download records are held in process memory and redline files are local to that container. Horizontal scaling requires a shared record store and shared temporary object storage before additional backend replicas are introduced.

## Health endpoints

- Public through Nginx: `/healthz`
- Backend-only: `/api/v1/health`

Neither endpoint processes or returns document content.
