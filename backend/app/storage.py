"""Permanent file storage. Database records hold references to these files."""
from __future__ import annotations
import hashlib
import shutil
import uuid
from pathlib import Path
from fastapi import HTTPException


class DocumentStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_session(self):
        comparison_id = str(uuid.uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        folder = self.root / comparison_id
        folder.mkdir(mode=0o700)
        return comparison_id, folder

    def path(self, relative_path):
        resolved = (self.root / relative_path).resolve()
        if self.root not in resolved.parents:
            raise ValueError("Invalid storage path")
        return resolved

    def discard_uncommitted(self, comparison_id):
        # Only used when the database transaction has not committed.
        folder = self.root / str(uuid.UUID(comparison_id))
        shutil.rmtree(folder, ignore_errors=True)


async def save_upload(upload, destination, max_bytes):
    size = 0
    digest = hashlib.sha256()
    try:
        with destination.open("xb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, "Document exceeds the permitted size.")
                output.write(chunk)
                digest.update(chunk)
    finally:
        await upload.close()
    return digest.hexdigest()
