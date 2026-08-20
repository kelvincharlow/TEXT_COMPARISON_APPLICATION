"""Short-lived, local comparison-session storage."""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredComparison:
    comparison_id: str
    output_path: Path
    expires_at: float


class ComparisonStore:
    def __init__(self, root: Path, ttl_seconds: int = 900) -> None:
        self.root = root.resolve()
        self.ttl_seconds = ttl_seconds
        self._records: dict[str, StoredComparison] = {}
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> tuple[str, Path]:
        # The runtime directory may be removed by maintenance while the API is
        # still running. Recreate it for every new session instead of relying
        # only on application-startup initialization.
        self.root.mkdir(parents=True, exist_ok=True)
        comparison_id = str(uuid.uuid4())
        session_path = self.root / comparison_id
        session_path.mkdir(mode=0o700)
        return comparison_id, session_path

    def register(self, comparison_id: str, output_path: Path) -> StoredComparison:
        record = StoredComparison(
            comparison_id=comparison_id,
            output_path=output_path,
            expires_at=time.time() + self.ttl_seconds,
        )
        with self._lock:
            self._records[comparison_id] = record
        return record

    def get(self, comparison_id: str) -> StoredComparison | None:
        try:
            uuid.UUID(comparison_id)
        except ValueError:
            return None
        with self._lock:
            record = self._records.get(comparison_id)
        if record is None or record.expires_at <= time.time() or not record.output_path.is_file():
            self.delete(comparison_id)
            return None
        return record

    def delete(self, comparison_id: str) -> None:
        with self._lock:
            self._records.pop(comparison_id, None)
        try:
            session_path = (self.root / str(uuid.UUID(comparison_id))).resolve()
        except ValueError:
            return
        if session_path.parent == self.root and session_path.is_dir():
            shutil.rmtree(session_path, ignore_errors=True)

    def cleanup_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [key for key, record in self._records.items() if record.expires_at <= now]
        for comparison_id in expired:
            self.delete(comparison_id)

        # After a process restart, remove only expired UUID-named children.
        for candidate in self.root.iterdir():
            if not candidate.is_dir():
                continue
            try:
                uuid.UUID(candidate.name)
            except ValueError:
                continue
            if candidate.stat().st_mtime + self.ttl_seconds <= now:
                shutil.rmtree(candidate, ignore_errors=True)
