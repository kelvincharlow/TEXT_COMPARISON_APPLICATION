from __future__ import annotations

import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "backend" / "tests" / "fixtures"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temporary_directory.name), ttl_seconds=60)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temporary_directory.cleanup()

    def test_health(self) -> None:
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_rejects_non_docx_extension(self) -> None:
        response = self.client.post(
            "/api/v1/compare",
            files={
                "original": ("original.txt", b"text", "text/plain"),
                "revised": ("revised.docx", b"text", DOCX_TYPE),
            },
        )
        self.assertEqual(response.status_code, 415)

    def test_rejects_fake_docx_content(self) -> None:
        response = self.client.post(
            "/api/v1/compare",
            files={
                "original": ("original.docx", b"not a docx", DOCX_TYPE),
                "revised": ("revised.docx", b"not a docx", DOCX_TYPE),
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_compare_and_one_time_download(self) -> None:
        with (SAMPLES / "simple_original.docx").open("rb") as original, (
            SAMPLES / "simple_revised.docx"
        ).open("rb") as revised:
            response = self.client.post(
                "/api/v1/compare",
                files={
                    "original": ("original.docx", original, DOCX_TYPE),
                    "revised": ("revised.docx", revised, DOCX_TYPE),
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["engine"], "wmlcomparer")
        self.assertEqual(payload["summary"]["total_changes"], 3)
        self.assertTrue(payload["changes_highlighted"])

        download_url = payload["download"]["url"]
        download = self.client.get(download_url)
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.content.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(download.content)) as package:
            document_xml = package.read("word/document.xml")
        self.assertIn(b'w:val="green"', document_xml)
        self.assertIn(b'w:val="FF0000"', document_xml)
        self.assertIn(b"VISUAL REDLINE COMPARISON", document_xml)
        self.assertIn(b"<w:strike", document_xml)
        self.assertNotRegex(document_xml, br"<w:(?:ins|del)(?:\s|>)")
        self.assertEqual(self.client.get(download_url).status_code, 404)

    def test_table_row_is_one_employee_facing_change(self) -> None:
        with (SAMPLES / "table_original.docx").open("rb") as original, (
            SAMPLES / "table_revised.docx"
        ).open("rb") as revised:
            response = self.client.post(
                "/api/v1/compare",
                files={
                    "original": ("original.docx", original, DOCX_TYPE),
                    "revised": ("revised.docx", revised, DOCX_TYPE),
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["summary"], {
            "total_changes": 3,
            "additions": 1,
            "deletions": 0,
            "modifications": 2,
            "heavily_revised": 0,
        })
        row_change = payload["changes"][2]
        self.assertEqual(row_change["location"]["container"], "table_row")
        self.assertEqual(row_change["revised_text"], "Signature check | REF-300 | Pending")
        self.client.delete(f"/api/v1/comparisons/{payload['comparison_id']}")

    def test_postbank_case_returns_correct_semantic_result(self) -> None:
        with (SAMPLES / "Original_Postbank_Test_Letter.docx").open("rb") as original, (
            SAMPLES / "Revised_Postbank_Test_Letter.docx"
        ).open("rb") as revised:
            response = self.client.post(
                "/api/v1/compare",
                files={
                    "original": ("Original_Postbank_Test_Letter.docx", original, DOCX_TYPE),
                    "revised": ("Revised_Postbank_Test_Letter.docx", revised, DOCX_TYPE),
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["summary"], {
            "total_changes": 29,
            "additions": 3,
            "deletions": 0,
            "modifications": 26,
            "heavily_revised": 1,
        })
        self.assertEqual(payload["coverage"]["redline_known_gaps"], [])
        self.assertEqual(
            payload["coverage"]["engine_redline_known_gaps"], ["footer1", "header1"]
        )
        self.assertEqual(payload["diagnostics"]["semantic_changes"], 29)
        self.assertGreater(payload["diagnostics"]["raw_revision_events"], 29)
        self.assertEqual(payload["download_style"], "visual_redline")

        download = self.client.get(payload["download"]["url"])
        self.assertEqual(download.status_code, 200)
        with zipfile.ZipFile(BytesIO(download.content)) as package:
            document_xml = package.read("word/document.xml")
            header_xml = package.read("word/header1.xml")
            footer_xml = package.read("word/footer1.xml")
        for part_xml in (document_xml, header_xml, footer_xml):
            self.assertIn(b'w:val="green"', part_xml)
        for part_xml in (document_xml, footer_xml):
            self.assertIn(b'w:val="FF0000"', part_xml)
            self.assertIn(b"<w:strike", part_xml)


if __name__ == "__main__":
    unittest.main()
