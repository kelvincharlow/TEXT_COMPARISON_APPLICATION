"""Extract UI-friendly changes from a tracked-changes DOCX redline."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

try:
    from .compare_documents import DocumentValidationError, validate_docx
except ImportError:  # Allow direct execution: python poc/extract_changes.py
    from compare_documents import DocumentValidationError, validate_docx

WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NAMESPACES = {"w": WORD_NAMESPACE}
INSERTION_ELEMENTS = {"ins", "moveTo"}
DELETION_ELEMENTS = {"del", "moveFrom"}
SUPPORTED_PART_PATTERNS = (
    re.compile(r"^word/document\.xml$"),
    re.compile(r"^word/header\d+\.xml$"),
    re.compile(r"^word/footer\d+\.xml$"),
    re.compile(r"^word/footnotes\.xml$"),
    re.compile(r"^word/endnotes\.xml$"),
)


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _revision_state(node: etree._Element) -> str:
    current: etree._Element | None = node
    while current is not None:
        name = _local_name(current)
        if name in INSERTION_ELEMENTS:
            return "inserted"
        if name in DELETION_ELEMENTS:
            return "deleted"
        current = current.getparent()
    return "unchanged"


def _normalize_text(value: str) -> str:
    value = re.sub(r"[\t\r\n ]+", " ", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return value.strip()


def _paragraph_text(paragraph: etree._Element) -> dict[str, str]:
    original: list[str] = []
    revised: list[str] = []
    inserted: list[str] = []
    deleted: list[str] = []

    text_nodes = paragraph.xpath(".//w:t | .//w:delText | .//w:tab | .//w:br", namespaces=NAMESPACES)
    for node in text_nodes:
        name = _local_name(node)
        value = " " if name in {"tab", "br"} else (node.text or "")
        state = _revision_state(node)
        if state == "inserted":
            revised.append(value)
            inserted.append(value)
        elif state == "deleted":
            original.append(value)
            deleted.append(value)
        else:
            original.append(value)
            revised.append(value)

    return {
        "original_text": _normalize_text("".join(original)),
        "revised_text": _normalize_text("".join(revised)),
        "inserted_text": _normalize_text("".join(inserted)),
        "deleted_text": _normalize_text("".join(deleted)),
    }


def _part_label(part_name: str) -> str:
    if part_name == "word/document.xml":
        return "document"
    return Path(part_name).stem


def _is_supported_part(part_name: str) -> bool:
    return any(pattern.match(part_name) for pattern in SUPPORTED_PART_PATTERNS)


def _one_ancestor(element: etree._Element, name: str) -> etree._Element | None:
    matches = element.xpath(f"ancestor::w:{name}[1]", namespaces=NAMESPACES)
    return matches[0] if matches else None


def _sibling_index(element: etree._Element, name: str) -> int:
    return len(element.xpath(f"preceding-sibling::w:{name}", namespaces=NAMESPACES)) + 1


def _table_location(paragraph: etree._Element) -> dict[str, object]:
    cell = _one_ancestor(paragraph, "tc")
    row = _one_ancestor(paragraph, "tr")
    table = _one_ancestor(paragraph, "tbl")
    if cell is None or row is None or table is None:
        return {"container": "paragraph"}

    table_index = len(table.xpath("preceding::w:tbl", namespaces=NAMESPACES)) + 1
    return {
        "container": "table_cell",
        "table_index": table_index,
        "row_index": _sibling_index(row, "tr"),
        "cell_index": _sibling_index(cell, "tc"),
    }


def _row_is_fully_inserted(paragraph: etree._Element) -> bool:
    row = _one_ancestor(paragraph, "tr")
    if row is None:
        return False
    row_paragraphs = row.xpath(".//w:p", namespaces=NAMESPACES)
    nonempty = [text for item in row_paragraphs if (text := _paragraph_text(item))["revised_text"]]
    return bool(nonempty) and all(not text["original_text"] and text["inserted_text"] for text in nonempty)


def _group_inserted_table_rows(changes: list[dict[str, object]]) -> list[dict[str, object]]:
    row_groups: dict[tuple[object, object, object], list[dict[str, object]]] = {}
    for change in changes:
        location = change["location"]
        if change.pop("_fully_inserted_row", False):
            key = (location["part"], location["table_index"], location["row_index"])
            row_groups.setdefault(key, []).append(change)

    grouped: list[dict[str, object]] = []
    consumed_ids: set[int] = set()
    for (part, table_index, row_index), items in row_groups.items():
        if len(items) < 2:
            continue
        consumed_ids.update(int(item["id"]) for item in items)
        cell_texts = [str(item["revised_text"]) for item in items if item["revised_text"]]
        combined = " | ".join(cell_texts)
        grouped.append(
            {
                "id": min(int(item["id"]) for item in items),
                "type": "addition",
                "original_text": "",
                "revised_text": combined,
                "inserted_text": combined,
                "deleted_text": "",
                "context": f"Table {table_index}, row {row_index} added: {combined}",
                "location": {
                    "part": part,
                    "container": "table_row",
                    "table_index": table_index,
                    "row_index": row_index,
                },
            }
        )

    result = [change for change in changes if int(change["id"]) not in consumed_ids]
    result.extend(grouped)
    result.sort(key=lambda change: int(change["id"]))
    for new_id, change in enumerate(result, start=1):
        change["id"] = new_id
    return result


def extract_changes(redline_path: Path) -> dict[str, object]:
    validate_docx(redline_path)
    changes: list[dict[str, object]] = []
    parsed_parts: list[str] = []
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)

    with zipfile.ZipFile(redline_path) as package:
        for part_name in sorted(package.namelist()):
            if not _is_supported_part(part_name):
                continue
            try:
                root = etree.fromstring(package.read(part_name), parser=parser)
            except etree.XMLSyntaxError as exc:
                raise DocumentValidationError(f"Invalid XML in DOCX part: {part_name}") from exc

            parsed_parts.append(_part_label(part_name))
            paragraphs = root.xpath(".//w:p", namespaces=NAMESPACES)
            for paragraph_index, paragraph in enumerate(paragraphs, start=1):
                text = _paragraph_text(paragraph)
                if not text["inserted_text"] and not text["deleted_text"]:
                    continue

                if text["inserted_text"] and text["deleted_text"]:
                    change_type = "modification"
                elif text["inserted_text"]:
                    change_type = "addition"
                else:
                    change_type = "deletion"

                table_location = _table_location(paragraph)
                context = text["revised_text"] or text["original_text"]
                changes.append(
                    {
                        "id": len(changes) + 1,
                        "type": change_type,
                        **text,
                        "context": context,
                        "location": {
                            "part": _part_label(part_name),
                            "paragraph_index": paragraph_index,
                            **table_location,
                        },
                        "_fully_inserted_row": _row_is_fully_inserted(paragraph),
                    }
                )

    changes = _group_inserted_table_rows(changes)
    counts = Counter(change["type"] for change in changes)
    return {
        "success": True,
        "engine": "wmlcomparer",
        "summary": {
            "total_changes": len(changes),
            "additions": counts["addition"],
            "deletions": counts["deletion"],
            "modifications": counts["modification"],
        },
        "changes": changes,
        "coverage": {
            "parsed_parts": parsed_parts,
            "supports": ["body paragraphs", "tables", "headers", "footers", "footnotes", "endnotes"],
            "does_not_yet_support": [
                "formatting-only changes in the JSON summary",
                "images and embedded objects",
                "text-box location labels",
                "precise page numbers",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("redline", type=Path, help="Tracked-changes redline DOCX")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = extract_changes(args.redline)
    except (DocumentValidationError, OSError, zipfile.BadZipFile) as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
        print(f"Structured changes written to {args.output.resolve()}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
