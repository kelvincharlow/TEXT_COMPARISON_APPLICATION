"""FastAPI entry point for the Postbank document-comparison MVP."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from poc.compare_documents import DocumentValidationError

from .service import run_comparison
from .storage import ComparisonStore

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_ROOT = Path(__file__).resolve().parents[1] / ".runtime"
MAX_UPLOAD_BYTES = int(os.getenv("POSTBANK_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
DOWNLOAD_TTL_SECONDS = int(os.getenv("POSTBANK_DOWNLOAD_TTL_SECONDS", "900"))
UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _save_upload(upload: UploadFile, destination: Path) -> int:
    size = 0
    try:
        with destination.open("xb") as output:
            while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Document exceeds the permitted size.")
                output.write(chunk)
    finally:
        await upload.close()
    return size


def create_app(storage_root: Path | None = None, ttl_seconds: int | None = None) -> FastAPI:
    store = ComparisonStore(
        storage_root or DEFAULT_STORAGE_ROOT,
        ttl_seconds=ttl_seconds if ttl_seconds is not None else DOWNLOAD_TTL_SECONDS,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.cleanup_expired()
        yield
        store.cleanup_expired()

    app = FastAPI(
        title="Postbank Document Comparison API",
        version="0.1.0",
        description="Local DOCX comparison PoC using wmlcomparer. No database or permanent history.",
        lifespan=lifespan,
    )
    app.state.comparison_store = store

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/compare")
    async def compare(
        original: UploadFile = File(...),
        revised: UploadFile = File(...),
    ) -> dict[str, object]:
        for upload, label in ((original, "Original"), (revised, "Revised")):
            if not upload.filename or not upload.filename.lower().endswith(".docx"):
                raise HTTPException(status_code=415, detail=f"{label} document must be a .docx file.")

        store.cleanup_expired()
        comparison_id, session_path = store.create_session()
        original_path = session_path / "original.docx"
        revised_path = session_path / "revised.docx"
        output_path = session_path / "redline.docx"

        try:
            await _save_upload(original, original_path)
            await _save_upload(revised, revised_path)
            result = await run_in_threadpool(
                run_comparison, original_path, revised_path, output_path
            )
            original_path.unlink(missing_ok=True)
            revised_path.unlink(missing_ok=True)
            store.register(comparison_id, output_path)
        except HTTPException:
            store.delete(comparison_id)
            raise
        except DocumentValidationError as exc:
            store.delete(comparison_id)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            # Keep sensitive document content out of the response and logs, but
            # retain the exception traceback in the local server console so an
            # administrator can diagnose engine, permission and platform errors.
            logger.exception("Comparison %s failed", comparison_id)
            store.delete(comparison_id)
            raise HTTPException(
                status_code=500,
                detail="The comparison could not be completed.",
            ) from exc

        result["comparison_id"] = comparison_id
        result["download"] = {
            "available": True,
            "url": f"/api/v1/comparisons/{comparison_id}/download",
            "expires_in_seconds": store.ttl_seconds,
        }
        return result

    @app.get("/api/v1/comparisons/{comparison_id}/download")
    async def download(comparison_id: str, background_tasks: BackgroundTasks) -> FileResponse:
        record = store.get(comparison_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Comparison has expired or does not exist.")
        background_tasks.add_task(store.delete, comparison_id)
        return FileResponse(
            record.output_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="postbank-comparison-visual-redline.docx",
            background=background_tasks,
            headers={"Cache-Control": "no-store"},
        )

    @app.delete("/api/v1/comparisons/{comparison_id}", status_code=204)
    async def delete_comparison(comparison_id: str) -> None:
        store.delete(comparison_id)

    return app


app = create_app()
