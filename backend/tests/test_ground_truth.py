from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.comparison import build_comparison_result
from poc.compare_documents import compare_documents

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "backend" / "tests" / "fixtures"
MANIFEST = ROOT / "poc" / "ground_truth" / "test_case_001.json"


def location_matches(actual: dict[str, object], expected: dict[str, object]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


class GroundTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
        native_redline = Path(cls.temporary_directory.name) / "native-redline.docx"
        compare_documents(
            SAMPLES / "Original_Postbank_Test_Letter.docx",
            SAMPLES / "Revised_Postbank_Test_Letter.docx",
            native_redline,
            engine_name="wmlcomparer",
            highlight_changes=False,
        )
        cls.result = build_comparison_result(
            SAMPLES / "Original_Postbank_Test_Letter.docx",
            SAMPLES / "Revised_Postbank_Test_Letter.docx",
            native_redline,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_summary_matches_frozen_policy(self) -> None:
        self.assertEqual(self.result["summary"], self.expected["expected_summary"])

    def test_all_29_expected_change_identities_are_present(self) -> None:
        unmatched = list(self.result["changes"])
        for expected in self.expected["changes"]:
            matches = [
                change
                for change in unmatched
                if change["type"] == expected["type"]
                and location_matches(change["location"], expected["location"])
                and expected.get("original_contains", "") in change["original_text"]
                and expected.get("revised_contains", "") in change["revised_text"]
                and change["severity"] == expected.get("severity", "normal")
            ]
            self.assertEqual(len(matches), 1, f"Expected change not uniquely detected: {expected}")
            unmatched.remove(matches[0])
        self.assertEqual(unmatched, [], f"Unexpected semantic changes: {unmatched}")

    def test_raw_revisions_are_preserved_separately(self) -> None:
        self.assertGreater(len(self.result["raw_revisions"]), 0)
        self.assertEqual(
            self.result["diagnostics"]["raw_revision_events"],
            len(self.result["raw_revisions"]),
        )

    def test_engine_row_misalignment_is_not_exposed_as_business_meaning(self) -> None:
        false_mapping = [
            change
            for change in self.result["changes"]
            if change["original_text"] == "Pilot close and review"
            and change["revised_text"] == "Mid-pilot review"
        ]
        self.assertEqual(false_mapping, [])


if __name__ == "__main__":
    unittest.main()
