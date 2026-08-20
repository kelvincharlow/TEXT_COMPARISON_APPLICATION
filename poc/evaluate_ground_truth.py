"""Evaluate Test Case 001 against its frozen semantic-change manifest."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from backend.app.comparison import build_comparison_result
from poc.compare_documents import compare_documents

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT.parent / "backend" / "tests" / "fixtures"
DEFAULT_MANIFEST = ROOT / "ground_truth" / "test_case_001.json"
DEFAULT_ORIGINAL = FIXTURES / "Original_Postbank_Test_Letter.docx"
DEFAULT_REVISED = FIXTURES / "Revised_Postbank_Test_Letter.docx"


def _identity_matches(change: dict[str, object], expected: dict[str, object]) -> bool:
    location = expected["location"]
    return (
        all(change["location"].get(key) == value for key, value in location.items())
        and expected.get("original_contains", "") in change["original_text"]
        and expected.get("revised_contains", "") in change["revised_text"]
    )


def evaluate(
    manifest_path: Path,
    original_path: Path,
    revised_path: Path,
    redline_path: Path,
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = build_comparison_result(original_path, revised_path, redline_path)
    remaining = list(result["changes"])
    correct: list[dict[str, object]] = []
    missed: list[dict[str, object]] = []
    misclassified: list[dict[str, object]] = []

    for expected in manifest["changes"]:
        identity_matches = [change for change in remaining if _identity_matches(change, expected)]
        if not identity_matches:
            missed.append(expected)
            continue
        actual = identity_matches[0]
        remaining.remove(actual)
        expected_severity = expected.get("severity", "normal")
        if actual["type"] != expected["type"] or actual["severity"] != expected_severity:
            misclassified.append({"expected": expected, "actual": actual})
        else:
            correct.append(actual)

    return {
        "test_case": manifest["id"],
        "passed": not missed and not misclassified and not remaining,
        "expected_summary": manifest["expected_summary"],
        "actual_summary": result["summary"],
        "metrics": {
            "correctly_detected": len(correct),
            "missed": len(missed),
            "misclassified": len(misclassified),
            "false_changes": len(remaining),
        },
        "missed_changes": missed,
        "misclassified_changes": misclassified,
        "false_changes": remaining,
        "coverage": result["coverage"],
        "diagnostics": result["diagnostics"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    parser.add_argument("--revised", type=Path, default=DEFAULT_REVISED)
    parser.add_argument("--redline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.redline:
        report = evaluate(args.manifest, args.original, args.revised, args.redline)
    else:
        with tempfile.TemporaryDirectory() as temporary_directory:
            redline_path = Path(temporary_directory) / "native-redline.docx"
            compare_documents(
                args.original,
                args.revised,
                redline_path,
                engine_name="wmlcomparer",
                highlight_changes=False,
            )
            report = evaluate(args.manifest, args.original, args.revised, redline_path)
    encoded = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"Evaluation report written to {args.output.resolve()}")
    else:
        print(encoded)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
