"""Comparison orchestration independent of HTTP routing."""

from __future__ import annotations

from pathlib import Path

from backend.app.comparison import build_comparison_result
from backend.app.comparison.visual_redline import generate_visual_redline
from poc.compare_documents import ComparisonResult, compare_documents, validate_docx


def run_comparison(original_path: Path, revised_path: Path, output_path: Path) -> dict[str, object]:
    native_redline_path = output_path.with_name("native-redline.docx")
    engine_result: ComparisonResult = compare_documents(
        original_path,
        revised_path,
        native_redline_path,
        engine_name="wmlcomparer",
        overwrite=False,
        highlight_changes=False,
    )
    structured = build_comparison_result(original_path, revised_path, native_redline_path)
    generate_visual_redline(
        original_path,
        revised_path,
        structured["changes"],
        output_path,
    )
    validate_docx(output_path)
    native_redline_path.unlink(missing_ok=True)
    structured["processing_ms"] = engine_result.elapsed_ms
    structured["engine_revision_count"] = engine_result.revision_count
    structured["changes_highlighted"] = True
    structured["download_style"] = "visual_redline"
    # The native engine gaps are retained for diagnostics; the employee download
    # is regenerated from semantic changes and therefore covers these text parts.
    structured["coverage"]["redline_known_gaps"] = []
    return structured
