from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document

from backend.app.comparison.semantic_comparator import compare_semantic_changes


def write_document(path: Path, paragraphs: list[str]) -> None:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(path)


class SemanticComparatorTests(unittest.TestCase):
    def test_insert_only_edit_inside_existing_paragraph_is_modification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.docx"
            revised = Path(directory) / "revised.docx"
            write_document(original, ["Government Services Unit"])
            write_document(revised, ["Government Services Coordination Unit"])
            changes = compare_semantic_changes(original, revised)

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["type"], "modification")

    def test_inserted_and_removed_paragraphs_remain_addition_and_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.docx"
            revised = Path(directory) / "revised.docx"
            write_document(original, ["Stable opening", "Remove this paragraph", "Stable closing"])
            write_document(revised, ["Stable opening", "New paragraph", "Stable closing"])
            changes = compare_semantic_changes(original, revised)

        # At the same logical position, a replacement is deliberately one modification.
        self.assertEqual([change["type"] for change in changes], ["modification"])

        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.docx"
            revised = Path(directory) / "revised.docx"
            write_document(original, ["Stable opening", "Stable closing"])
            write_document(revised, ["Stable opening", "Inserted paragraph", "Stable closing"])
            additions = compare_semantic_changes(original, revised)
            write_document(original, ["Stable opening", "Removed paragraph", "Stable closing"])
            write_document(revised, ["Stable opening", "Stable closing"])
            deletions = compare_semantic_changes(original, revised)

        self.assertEqual([change["type"] for change in additions], ["addition"])
        self.assertEqual([change["type"] for change in deletions], ["deletion"])


if __name__ == "__main__":
    unittest.main()

