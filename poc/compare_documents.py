"""Generate a local DOCX redline with Python-Redlines/Docxodus."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from lxml import etree

MAX_COMPRESSED_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 150 * 1024 * 1024
MAX_ZIP_ENTRIES = 5_000
MAX_COMPRESSION_RATIO = 100.0
REQUIRED_DOCX_PARTS = {"[Content_Types].xml", "word/document.xml"}
ENGINES = ("wmlcomparer", "docxdiff")
ENGINE_CACHE = Path(__file__).resolve().parent / ".engine-cache"
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_NAMESPACES = {"w": WORD_NAMESPACE}


class DocumentValidationError(ValueError):
    """Raised when an input is not an acceptable DOCX package."""


@dataclass(frozen=True)
class ComparisonResult:
    engine: str
    elapsed_ms: int
    revision_count: int | None
    output_path: str
    output_size_bytes: int
    changes_highlighted: bool


def validate_docx(path: Path) -> None:
    """Apply conservative checks before handing a document to the engine."""
    if not path.is_file():
        raise DocumentValidationError(f"File does not exist: {path}")
    if path.suffix.lower() != ".docx":
        raise DocumentValidationError(f"Only .docx files are accepted: {path.name}")

    compressed_size = path.stat().st_size
    if compressed_size == 0:
        raise DocumentValidationError(f"File is empty: {path.name}")
    if compressed_size > MAX_COMPRESSED_BYTES:
        raise DocumentValidationError(
            f"File exceeds the {MAX_COMPRESSED_BYTES // (1024 * 1024)} MB PoC limit: {path.name}"
        )
    if not zipfile.is_zipfile(path):
        raise DocumentValidationError(f"File is not a valid DOCX/ZIP package: {path.name}")

    with zipfile.ZipFile(path) as package:
        entries = package.infolist()
        names = {entry.filename for entry in entries}
        missing = REQUIRED_DOCX_PARTS - names
        if missing:
            raise DocumentValidationError(
                f"DOCX package is missing required parts: {', '.join(sorted(missing))}"
            )
        if len(entries) > MAX_ZIP_ENTRIES:
            raise DocumentValidationError("DOCX package contains too many ZIP entries")

        expanded_size = 0
        for entry in entries:
            if entry.flag_bits & 0x1:
                raise DocumentValidationError("Encrypted DOCX packages are not supported")
            expanded_size += entry.file_size
            if expanded_size > MAX_EXPANDED_BYTES:
                raise DocumentValidationError("Expanded DOCX package is too large")
            if entry.file_size and entry.compress_size == 0:
                raise DocumentValidationError("DOCX package has an unsafe compression ratio")
            if entry.compress_size:
                ratio = entry.file_size / entry.compress_size
                if ratio > MAX_COMPRESSION_RATIO:
                    raise DocumentValidationError("DOCX package has an unsafe compression ratio")


def _revision_count(engine_stdout: str) -> int | None:
    match = re.search(r"(\d+)\s+revision(?:\(s\))?", engine_stdout, re.IGNORECASE)
    return int(match.group(1)) if match else None


def highlight_tracked_changes(docx_bytes: bytes, color: str = "yellow") -> bytes:
    """Add Word highlighting to text runs contained in tracked revisions.

    Tracked-change markup is retained, so reviewers can still accept or reject
    revisions. Word may also show revision bars depending on its local markup view.
    """
    source = io.BytesIO(docx_bytes)
    destination = io.BytesIO()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)

    with zipfile.ZipFile(source, "r") as input_package, zipfile.ZipFile(
        destination, "w"
    ) as output_package:
        for entry in input_package.infolist():
            content = input_package.read(entry.filename)
            if entry.filename.startswith("word/") and entry.filename.endswith(".xml"):
                try:
                    root = etree.fromstring(content, parser=parser)
                except etree.XMLSyntaxError:
                    output_package.writestr(entry, content)
                    continue

                changed = False
                revisions = root.xpath(".//w:ins | .//w:del | .//w:moveFrom | .//w:moveTo", namespaces=WORD_NAMESPACES)
                for revision in revisions:
                    for run in revision.xpath(".//w:r", namespaces=WORD_NAMESPACES):
                        run_properties = run.find(f"{{{WORD_NAMESPACE}}}rPr")
                        if run_properties is None:
                            run_properties = etree.Element(f"{{{WORD_NAMESPACE}}}rPr")
                            run.insert(0, run_properties)
                        highlight = run_properties.find(f"{{{WORD_NAMESPACE}}}highlight")
                        if highlight is None:
                            highlight = etree.SubElement(
                                run_properties, f"{{{WORD_NAMESPACE}}}highlight"
                            )
                        highlight.set(f"{{{WORD_NAMESPACE}}}val", color)
                        changed = True

                if changed:
                    content = etree.tostring(
                        root, encoding="UTF-8", xml_declaration=True, standalone=True
                    )
            output_package.writestr(entry, content)

    return destination.getvalue()


def compare_documents(
    original_path: Path,
    revised_path: Path,
    output_path: Path,
    engine_name: str = "wmlcomparer",
    *,
    overwrite: bool = False,
    highlight_changes: bool = True,
) -> ComparisonResult:
    if engine_name not in ENGINES:
        raise ValueError(f"Unknown engine: {engine_name}")
    validate_docx(original_path)
    validate_docx(revised_path)

    if output_path.suffix.lower() != ".docx":
        raise ValueError("Output path must end in .docx")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_path}")

    try:
        from python_redlines import DocxodusEngine
    except ImportError as exc:
        raise RuntimeError(
            "Python-Redlines is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    original_bytes = original_path.read_bytes()
    revised_bytes = revised_path.read_bytes()
    kwargs = {} if engine_name == "wmlcomparer" else {"engine": "docxdiff"}

    started = time.perf_counter()
    # The package ships a platform binary and extracts it once. Keeping that
    # cache inside the PoC avoids depending on a writable global user profile.
    redline_bytes, engine_stdout, _engine_stderr = DocxodusEngine(
        target_path=str(ENGINE_CACHE)
    ).run_redline(
        "Postbank Comparison PoC",
        original_bytes,
        revised_bytes,
        **kwargs,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    if not redline_bytes:
        raise RuntimeError("The comparison engine returned an empty document")
    if highlight_changes:
        redline_bytes = highlight_tracked_changes(redline_bytes)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".docx", prefix="redline-", dir=output_path.parent, delete=False
        ) as temporary:
            temporary.write(redline_bytes)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, output_path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)

    validate_docx(output_path)
    return ComparisonResult(
        engine=engine_name,
        elapsed_ms=elapsed_ms,
        revision_count=_revision_count(engine_stdout),
        output_path=str(output_path.resolve()),
        output_size_bytes=output_path.stat().st_size,
        changes_highlighted=highlight_changes,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path, help="Original/older DOCX")
    parser.add_argument("revised", type=Path, help="Revised/newer DOCX")
    parser.add_argument("--output", required=True, type=Path, help="Generated redline DOCX")
    parser.add_argument("--engine", choices=ENGINES, default="wmlcomparer")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--no-highlight",
        action="store_true",
        help="Keep native tracked changes without adding yellow text highlighting",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = compare_documents(
            args.original,
            args.revised,
            args.output,
            args.engine,
            overwrite=args.overwrite,
            highlight_changes=not args.no_highlight,
        )
    except (DocumentValidationError, FileExistsError, RuntimeError, ValueError) as exc:
        print(f"Comparison failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        count = result.revision_count if result.revision_count is not None else "unknown"
        print(f"Comparison completed with {result.engine}.")
        print(f"Revisions reported: {count}")
        print(f"Processing time: {result.elapsed_ms} ms")
        print(f"Output: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
