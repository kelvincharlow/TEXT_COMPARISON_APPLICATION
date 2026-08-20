"""Run each PoC document pair through both comparison algorithms."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from compare_documents import ENGINES, compare_documents

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "test_cases.json"
OUTPUTS = ROOT / "outputs"


def main() -> int:
    if not MANIFEST.exists():
        print("Missing test_cases.json. Run: python poc/generate_samples.py", file=sys.stderr)
        return 1

    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    failures = 0

    for case in cases:
        for engine in ENGINES:
            output = OUTPUTS / f"{case['id']}_{engine}_highlighted.docx"
            print(f"Comparing {case['id']} with {engine}...")
            try:
                result = compare_documents(
                    ROOT / case["original"],
                    ROOT / case["revised"],
                    output,
                    engine,
                    overwrite=True,
                )
                row = {
                    "test_id": case["id"],
                    "engine": engine,
                    "expected_change_count": len(case["expected_changes"]),
                    "engine_revision_count": result.revision_count,
                    "processing_ms": result.elapsed_ms,
                    "output_opens_in_word": "REVIEW_REQUIRED",
                    "expected_changes_detected": "REVIEW_REQUIRED",
                    "material_changes_missed": "REVIEW_REQUIRED",
                    "false_changes": "REVIEW_REQUIRED",
                    "layout_usable": "REVIEW_REQUIRED",
                    "reviewer_notes": "",
                    "output_file": output.name,
                    "error": "",
                }
            except Exception as exc:  # Continue so one bad document does not end the experiment.
                failures += 1
                row = {
                    "test_id": case["id"],
                    "engine": engine,
                    "expected_change_count": len(case["expected_changes"]),
                    "engine_revision_count": "",
                    "processing_ms": "",
                    "output_opens_in_word": "NO",
                    "expected_changes_detected": "",
                    "material_changes_missed": "",
                    "false_changes": "",
                    "layout_usable": "",
                    "reviewer_notes": "",
                    "output_file": output.name,
                    "error": str(exc),
                }
                print(f"  Failed: {exc}", file=sys.stderr)
            rows.append(row)

    report = OUTPUTS / "benchmark_highlighted_results.csv"
    with report.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Benchmark finished. Manual review sheet: {report}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
