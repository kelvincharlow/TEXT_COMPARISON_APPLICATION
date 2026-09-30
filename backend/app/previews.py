"""Private, on-demand page previews of immutable original and redline files."""
import fcntl
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from .auth import current_user, get_db
from .models import DocumentVersion
from .reviews import accessible_comparison

router = APIRouter(prefix="/api/v1/comparisons")
logger = logging.getLogger(__name__)


@contextmanager
def preview_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.lock').open('a') as handle:
        deadline = time.monotonic() + 25
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HTTPException(503, "Preview is being prepared. Please try again shortly.")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_renderer(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=60)


def render_pdf(source, destination):
    # Independent LibreOffice profiles prevent concurrent requests attaching to
    # another renderer process. Only complete output is published to the cache.
    with tempfile.TemporaryDirectory(prefix='postbank-preview-') as scratch:
        root = Path(scratch)
        run_renderer(['libreoffice', '-env:UserInstallation=' + (root / 'profile').as_uri(),
                      '--headless', '--convert-to', 'pdf', '--outdir', str(root), str(source)])
        pdf = root / (source.stem + '.pdf')
        if not pdf.is_file():
            raise RuntimeError('No PDF produced')
        info = run_renderer(['pdfinfo', str(pdf)]).stdout
        match = re.search(r'^Pages:\s+(\d+)', info, re.MULTILINE)
        if not match or int(match.group(1)) < 1:
            raise RuntimeError('No rendered pages')
        destination.write_bytes(pdf.read_bytes())
        return int(match.group(1))


def prepare_preview(folder, sources):
    with preview_lock(folder):
        manifest = folder / 'manifest.json'
        if manifest.is_file():
            return json.loads(manifest.read_text())
        # Stage both PDFs and metadata together; a failed conversion is retryable.
        with tempfile.TemporaryDirectory(dir=folder, prefix='staging-') as staging:
            stage = Path(staging)
            counts = {kind: render_pdf(source, stage / (kind + '.pdf')) for kind, source in sources.items()}
            for kind in sources:
                os.replace(stage / (kind + '.pdf'), folder / (kind + '.pdf'))
            (stage / 'manifest.json').write_text(json.dumps(counts))
            os.replace(stage / 'manifest.json', manifest)
        return counts


def render_page(folder, kind, page):
    with preview_lock(folder):
        manifest = folder / 'manifest.json'
        if not manifest.is_file():
            raise HTTPException(409, 'Open the document preview first.')
        counts = json.loads(manifest.read_text())
        if page < 1 or page > counts[kind]:
            raise HTTPException(404, 'This document has no such page.')
        target = folder / f'{kind}-{page}.png'
        if not target.is_file():
            with tempfile.TemporaryDirectory(dir=folder, prefix='page-') as staging:
                prefix = Path(staging) / 'page'
                run_renderer(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                              '-scale-to', '1800', '-png', str(folder / (kind + '.pdf')), str(prefix)])
                os.replace(prefix.with_suffix('.png'), target)
        return target


def preview_context(db, user, request, comparison_id):
    record = accessible_comparison(db, comparison_id, user)
    if record.processing_status != 'completed' or not record.redline_path:
        raise HTTPException(409, 'No completed redline is available to preview.')
    storage = request.app.state.document_storage
    original = db.get(DocumentVersion, record.original_version_id)
    sources = {'original': storage.path(original.storage_path), 'redline': storage.path(record.redline_path)}
    if not all(path.is_file() for path in sources.values()):
        raise HTTPException(404, 'A source document is unavailable.')
    return storage.path(f'{record.id}/preview-v1'), sources


@router.post('/{comparison_id}/preview')
def prepare(comparison_id: str, request: Request, db=Depends(get_db), user=Depends(current_user)):
    folder, sources = preview_context(db, user, request, comparison_id)
    try:
        counts = prepare_preview(folder, sources)
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.warning('Preview failed for %s (%s)', comparison_id, type(exc).__name__)
        raise HTTPException(503, 'Document preview could not be prepared. Retry or download the Word documents.') from exc
    return {kind: {'page_count': count, 'page_url': f'/api/v1/comparisons/{comparison_id}/preview/{kind}/pages/'}
            for kind, count in counts.items()}


@router.get('/{comparison_id}/preview/{kind}/pages/{page}')
def page_image(comparison_id: str, kind: Literal['original', 'redline'], page: int,
               request: Request, db=Depends(get_db), user=Depends(current_user)):
    folder, _ = preview_context(db, user, request, comparison_id)
    try:
        target = render_page(folder, kind, page)
    except HTTPException:
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.warning('Page rendering failed for %s (%s)', comparison_id, type(exc).__name__)
        raise HTTPException(503, 'This page could not be rendered. Please retry.') from exc
    return FileResponse(target, media_type='image/png', headers={'Cache-Control': 'private, no-store'})
