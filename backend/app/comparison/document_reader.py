"""Read logical text units directly from original and revised DOCX packages."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .similarity import normalize_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
HEADER_FOOTER_PATTERN = re.compile(r"^word/(header|footer)\d+\.xml$")


@dataclass(frozen=True)
class ParagraphUnit:
    text: str
    paragraph_index: int
    block_order: int
    style: str = ""


@dataclass(frozen=True)
class TableRowUnit:
    cells: list[str]
    table_index: int
    row_index: int
    block_order: int


@dataclass
class PartContent:
    paragraphs: list[ParagraphUnit] = field(default_factory=list)
    rows: list[TableRowUnit] = field(default_factory=list)


@dataclass
class DocumentContent:
    parts: dict[str, PartContent] = field(default_factory=dict)


def _text(element: etree._Element) -> str:
    values: list[str] = []
    for node in element.xpath(".//w:t | .//w:delText | .//w:tab | .//w:br", namespaces=NS):
        name = etree.QName(node).localname
        values.append(" " if name in {"tab", "br"} else (node.text or ""))
    return normalize_text("".join(values))


def _paragraph_style(paragraph: etree._Element) -> str:
    values = paragraph.xpath("./w:pPr/w:pStyle/@w:val", namespaces=NS)
    return str(values[0]) if values else ""


def _read_part(root: etree._Element) -> PartContent:
    container = root.find(f"{{{W}}}body") if etree.QName(root).localname == "document" else root
    if container is None:
        return PartContent()

    content = PartContent()
    paragraph_index = 0
    table_index = 0
    for block_order, child in enumerate(container, start=1):
        name = etree.QName(child).localname
        if name == "p":
            text = _text(child)
            if text:
                paragraph_index += 1
                content.paragraphs.append(
                    ParagraphUnit(text, paragraph_index, block_order, _paragraph_style(child))
                )
        elif name == "tbl":
            table_index += 1
            for row_index, row in enumerate(child.xpath("./w:tr", namespaces=NS), start=1):
                cells = [_text(cell) for cell in row.xpath("./w:tc", namespaces=NS)]
                content.rows.append(TableRowUnit(cells, table_index, row_index, block_order))
    return content


def read_document(path: Path) -> DocumentContent:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    result = DocumentContent()
    with zipfile.ZipFile(path) as package:
        names = ["word/document.xml"]
        names.extend(sorted(name for name in package.namelist() if HEADER_FOOTER_PATTERN.match(name)))
        for name in names:
            if name not in package.namelist():
                continue
            root = etree.fromstring(package.read(name), parser=parser)
            part_name = "document" if name == "word/document.xml" else Path(name).stem
            result.parts[part_name] = _read_part(root)
    return result

