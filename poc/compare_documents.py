"""Compatibility entry point for local comparison/benchmark tools.

Run from the repository root with ``python -m poc.compare_documents``.
The production implementation lives in the backend.
"""
from backend.app.comparison.engine import (
    ENGINES, ComparisonResult, DocumentValidationError, compare_documents,
    highlight_tracked_changes, main, validate_docx,
)

if __name__ == "__main__":
    raise SystemExit(main())
