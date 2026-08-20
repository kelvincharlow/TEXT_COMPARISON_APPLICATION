"""Build the stable API representation from raw and semantic comparison data."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .raw_revision_parser import parse_raw_revisions
from .semantic_comparator import compare_semantic_changes


def build_comparison_result(
    original_path: Path,
    revised_path: Path,
    redline_path: Path,
) -> dict[str, object]:
    raw_revisions = parse_raw_revisions(redline_path)
    changes = compare_semantic_changes(original_path, revised_path)
    counts = Counter(change["type"] for change in changes)
    semantic_parts = {str(change["location"]["part"]) for change in changes}
    raw_parts = {str(event["location"]["part"]) for event in raw_revisions}
    redline_known_gaps = sorted(semantic_parts - raw_parts)
    return {
        "success": True,
        "engine": "wmlcomparer",
        "summary": {
            "total_changes": len(changes),
            "additions": counts["addition"],
            "deletions": counts["deletion"],
            "modifications": counts["modification"],
            "heavily_revised": sum(
                change["severity"] == "heavily_revised" for change in changes
            ),
        },
        "changes": changes,
        "raw_revisions": raw_revisions,
        "diagnostics": {
            "raw_revision_events": len(raw_revisions),
            "semantic_changes": len(changes),
        },
        "coverage": {
            "body": True,
            "tables": True,
            "headers": True,
            "footers": True,
            "redline_known_gaps": redline_known_gaps,
            "engine_redline_known_gaps": redline_known_gaps,
            "does_not_yet_support": [
                "formatting-only changes in the on-screen summary",
                "images and embedded objects",
                "text-box location labels",
                "precise page numbers",
            ],
        },
    }
