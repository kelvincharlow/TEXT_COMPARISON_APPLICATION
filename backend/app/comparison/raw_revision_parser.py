"""Preserve individual tracked-revision events from the engine redline."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

from .similarity import normalize_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
SUPPORTED_PART = re.compile(
    r"^word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml$"
)
REVISION_XPATH = ".//w:ins | .//w:del | .//w:moveFrom | .//w:moveTo"


def _part_label(name: str) -> str:
    return "document" if name == "word/document.xml" else Path(name).stem


def _location(revision: etree._Element, part_name: str) -> dict[str, object]:
    paragraph = revision.xpath("ancestor-or-self::w:p[1]", namespaces=NS)
    cell = revision.xpath("ancestor::w:tc[1]", namespaces=NS)
    row = revision.xpath("ancestor::w:tr[1]", namespaces=NS)
    table = revision.xpath("ancestor::w:tbl[1]", namespaces=NS)
    location: dict[str, object] = {"part": _part_label(part_name)}
    if paragraph:
        location["paragraph_index"] = len(
            paragraph[0].xpath("preceding::w:p", namespaces=NS)
        ) + 1
    if cell and row and table:
        location.update(
            {
                "container": "table_cell",
                "table_index": len(table[0].xpath("preceding::w:tbl", namespaces=NS)) + 1,
                "row_index": len(row[0].xpath("preceding-sibling::w:tr", namespaces=NS)) + 1,
                "cell_index": len(cell[0].xpath("preceding-sibling::w:tc", namespaces=NS)) + 1,
            }
        )
    else:
        location["container"] = "paragraph"
    return location


def parse_raw_revisions(redline_path: Path) -> list[dict[str, object]]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    events: list[dict[str, object]] = []
    with zipfile.ZipFile(redline_path) as package:
        for part_name in sorted(name for name in package.namelist() if SUPPORTED_PART.match(name)):
            root = etree.fromstring(package.read(part_name), parser=parser)
            for revision in root.xpath(REVISION_XPATH, namespaces=NS):
                name = etree.QName(revision).localname
                text = normalize_text(
                    "".join(
                        revision.xpath(".//w:t/text() | .//w:delText/text()", namespaces=NS)
                    )
                )
                if not text:
                    continue
                revision_type = "insertion" if name in {"ins", "moveTo"} else "deletion"
                events.append(
                    {
                        "id": len(events) + 1,
                        "type": revision_type,
                        "text": text,
                        "location": _location(revision, part_name),
                    }
                )
    return events

