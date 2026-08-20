from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from extract_changes import extract_changes


class ExtractChangesTests(unittest.TestCase):
    def test_extracts_addition_deletion_and_modification(self) -> None:
        content_types = b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'''
        document_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Hello </w:t></w:r><w:ins><w:r><w:t>team</w:t></w:r></w:ins></w:p>
    <w:p><w:del><w:r><w:delText>Old paragraph</w:delText></w:r></w:del></w:p>
    <w:p><w:r><w:t>Pay within </w:t></w:r><w:del><w:r><w:delText>14</w:delText></w:r></w:del><w:ins><w:r><w:t>30</w:t></w:r></w:ins><w:r><w:t> days.</w:t></w:r></w:p>
  </w:body>
</w:document>'''

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "redline.docx"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("[Content_Types].xml", content_types)
                package.writestr("word/document.xml", document_xml)

            result = extract_changes(path)

        self.assertEqual(result["summary"], {
            "total_changes": 3,
            "additions": 1,
            "deletions": 1,
            "modifications": 1,
        })
        self.assertEqual(result["changes"][0]["inserted_text"], "team")
        self.assertEqual(result["changes"][1]["deleted_text"], "Old paragraph")
        self.assertEqual(result["changes"][2]["original_text"], "Pay within 14 days.")
        self.assertEqual(result["changes"][2]["revised_text"], "Pay within 30 days.")

    def test_groups_a_fully_inserted_table_row(self) -> None:
        content_types = b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'''
        document_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:tbl>
    <w:tr><w:tc><w:p><w:r><w:t>Existing</w:t></w:r></w:p></w:tc></w:tr>
    <w:tr>
      <w:tc><w:p><w:ins><w:r><w:t>New item</w:t></w:r></w:ins></w:p></w:tc>
      <w:tc><w:p><w:ins><w:r><w:t>REF-300</w:t></w:r></w:ins></w:p></w:tc>
      <w:tc><w:p><w:ins><w:r><w:t>Pending</w:t></w:r></w:ins></w:p></w:tc>
    </w:tr>
  </w:tbl></w:body>
</w:document>'''

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "redline.docx"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("[Content_Types].xml", content_types)
                package.writestr("word/document.xml", document_xml)
            result = extract_changes(path)

        self.assertEqual(result["summary"]["total_changes"], 1)
        self.assertEqual(result["changes"][0]["type"], "addition")
        self.assertEqual(result["changes"][0]["revised_text"], "New item | REF-300 | Pending")
        self.assertEqual(result["changes"][0]["location"]["container"], "table_row")


if __name__ == "__main__":
    unittest.main()
