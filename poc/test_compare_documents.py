from __future__ import annotations

import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from compare_documents import (
    DocumentValidationError,
    highlight_tracked_changes,
    validate_docx,
)


class ValidateDocxTests(unittest.TestCase):
    def test_rejects_wrong_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "letter.txt"
            path.write_text("not a document", encoding="utf-8")
            with self.assertRaises(DocumentValidationError):
                validate_docx(path)

    def test_rejects_fake_docx(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "letter.docx"
            path.write_text("not a zip", encoding="utf-8")
            with self.assertRaises(DocumentValidationError):
                validate_docx(path)

    def test_accepts_minimal_required_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "letter.docx"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("[Content_Types].xml", "<Types />")
                package.writestr("word/document.xml", "<document />")
            validate_docx(path)


class HighlightTrackedChangesTests(unittest.TestCase):
    def test_adds_highlight_without_removing_revision_markup(self) -> None:
        document_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:ins><w:r><w:t>new</w:t></w:r></w:ins></w:p></w:body>
</w:document>'''
        package_bytes = BytesIO()
        with zipfile.ZipFile(package_bytes, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("[Content_Types].xml", "<Types />")
            package.writestr("word/document.xml", document_xml)

        highlighted = highlight_tracked_changes(package_bytes.getvalue())

        with zipfile.ZipFile(BytesIO(highlighted)) as package:
            output_xml = package.read("word/document.xml")
        self.assertIn(b"<w:ins>", output_xml)
        self.assertIn(b"<w:highlight w:val=\"yellow\"/>", output_xml)


if __name__ == "__main__":
    unittest.main()
