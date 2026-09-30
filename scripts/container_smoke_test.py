"""Exercise health, comparison, and redline download through the public container endpoint."""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import mimetypes
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORIGINAL = ROOT / "backend/tests/fixtures/Original_Postbank_Test_Letter.docx"
DEFAULT_REVISED = ROOT / "backend/tests/fixtures/Revised_Postbank_Test_Letter.docx"


def request_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def multipart_body(files: list[tuple[str, Path]], fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"postbank-smoke-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for field_name, path in files:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{path.name}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def run(base_url: str, original: Path, revised: Path, email: str, password: str) -> None:
    health = request_json(f"{base_url}/healthz")
    if health.get("status") != "ok":
        raise RuntimeError(f"Unexpected health response: {health}")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [("X-Postbank-Request", "1")]
    login = urllib.request.Request(f"{base_url}/api/v1/auth/login", data=json.dumps({"email": email, "password": password}).encode(), headers={"Content-Type": "application/json"})
    with opener.open(login, timeout=30) as response:
        user = json.load(response)
    body, boundary = multipart_body([("original", original), ("revised", revised)], {
        "title": "Synthetic smoke test", "owning_department_id": user["department_id"],
        "document_type": "Test letter", "responsible_officer": user["full_name"],
        "work_email": user["email"], "revision_source": "Synthetic Finance", "review_type": "standard",
    })
    compare_request = urllib.request.Request(
        f"{base_url}/api/v1/compare",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with opener.open(compare_request, timeout=300) as response:
        result = json.load(response)

    changes = result.get("changes")
    if not isinstance(changes, list):
        raise RuntimeError("Comparison response did not contain a change list")

    download = result.get("download")
    if not isinstance(download, dict) or not download.get("url"):
        raise RuntimeError("Comparison response did not contain a download URL")

    with opener.open(f"{base_url}{download['url']}", timeout=60) as response:
        redline = response.read()
    if not zipfile.is_zipfile(BytesIO(redline)):
        raise RuntimeError("Downloaded redline is not a valid DOCX package")

    with opener.open(f"{base_url}{download['url']}", timeout=60) as response:
        if response.read() != redline:
            raise RuntimeError("Repeat download did not preserve the saved redline")
    with opener.open(urllib.request.Request(f"{base_url}/api/v1/auth/logout", method="POST"), timeout=10):
        pass
    print(
        json.dumps(
            {
                "health": "ok",
                "comparison": "ok",
                "changes_returned": len(changes),
                "redline_download": "ok",
                "redline_bytes": len(redline),
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    parser.add_argument("--revised", type=Path, default=DEFAULT_REVISED)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    try:
        run(args.base_url.rstrip("/"), args.original.resolve(), args.revised.resolve(), args.email, getpass.getpass("Application password: "))
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"Container smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
