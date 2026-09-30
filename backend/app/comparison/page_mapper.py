"""Map semantic DOCX changes to rendered PDF pages."""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .similarity import normalize_text


def _page_texts(pdf_path: Path) -> list[str]:
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [normalize_text(page) for page in result.stdout.split("\f") if normalize_text(page)]


def _render_pages(docx_path: Path, output_directory: Path) -> list[str]:
    output_directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "libreoffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_directory),
            str(docx_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pdf_path = output_directory / f"{docx_path.stem}.pdf"
    if not pdf_path.is_file():
        raise RuntimeError(f"DOCX renderer did not create a PDF for {docx_path.name}")
    return _page_texts(pdf_path)


def _search_text(change: dict[str, object]) -> str:
    if change["type"] == "deletion":
        return normalize_text(str(change["original_text"]))
    return normalize_text(str(change["revised_text"]))


def _find_page(text: str, pages: list[str]) -> int | None:
    if not text:
        return None
    for page_number, page_text in enumerate(pages, start=1):
        if text.casefold() in page_text.casefold():
            return page_number

    # Long paragraphs can wrap differently after PDF extraction. A distinctive
    # prefix/suffix gives a useful page assignment without pretending it is exact.
    words = re.findall(r"\S+", text)
    if len(words) >= 8:
        fragments = (" ".join(words[:8]), " ".join(words[-8:]))
        for page_number, page_text in enumerate(pages, start=1):
            if any(fragment.casefold() in page_text.casefold() for fragment in fragments):
                return page_number
    return None


def add_page_mapping(
    changes: list[dict[str, object]],
    original_path: Path,
    revised_path: Path,
) -> dict[str, object]:
    """Annotate changes with page numbers and return a compact page summary."""
    with tempfile.TemporaryDirectory(prefix="postbank-pages-") as directory:
        render_directory = Path(directory)
        original_pages = _render_pages(original_path, render_directory / "original")
        revised_pages = _render_pages(revised_path, render_directory / "revised")

    page_counts: Counter[int] = Counter()
    page_types: dict[int, Counter[str]] = {}
    unmapped = 0
    for change in changes:
        pages = revised_pages if change["type"] != "deletion" else original_pages
        page_number = _find_page(_search_text(change), pages)
        change["page"] = page_number
        if page_number is None:
            unmapped += 1
            continue
        page_counts[page_number] += 1
        page_types.setdefault(page_number, Counter())[str(change["type"])] += 1

    page_summary = [
        {
            "page": page_number,
            "changes": page_counts[page_number],
            "additions": page_types[page_number]["addition"],
            "deletions": page_types[page_number]["deletion"],
            "modifications": page_types[page_number]["modification"],
        }
        for page_number in sorted(page_counts)
    ]
    return {
        "page_count": max(len(original_pages), len(revised_pages)),
        "affected_pages": len(page_summary),
        "pages": page_summary,
        "unmapped_changes": unmapped,
    }