"""Create a flattened visual redline from semantic changes.

The revised document is used as the structural base. Deleted tokens are inserted
as normal red strikethrough text, inserted tokens receive green highlighting, and
unchanged tokens remain normal. This intentionally does not use native Word Track
Changes, so its appearance does not depend on a reviewer's markup-view settings.
"""

from __future__ import annotations

import copy
import io
import re
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# Restrained report palette: familiar red/green changes with a professional,
# print-friendly institutional header and legend.
NAVY = "17365D"
SLATE = "44546A"
MUTED = "667085"
LIGHT_BORDER = "D0D5DD"
NEUTRAL_FILL = "F2F4F7"
DELETION_FILL = "FDECEC"
INSERTION_FILL = "E7F4EA"
INSERTION_TEXT = "000000"
DELETION_TEXT = "FF0000"

RPR_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
            "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
            "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
            "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
            "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
            "eastAsianLayout", "specVanish", "oMath",
        )
    )
}
PPR_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
            "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd",
            "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
            "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
            "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
            "suppressOverlap", "jc", "textDirection", "textAlignment", "textboxTightWrap",
            "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange",
        )
    )
}


def _normalize_run_property_order(properties: etree._Element) -> None:
    children = list(properties)
    children.sort(key=lambda child: RPR_ORDER.get(etree.QName(child).localname, 1000))
    properties[:] = children


def _normalize_paragraph_property_order(properties: etree._Element) -> None:
    children = list(properties)
    children.sort(key=lambda child: PPR_ORDER.get(etree.QName(child).localname, 1000))
    properties[:] = children
TOKEN_PATTERN = re.compile(r"\s+|[^\W_]+(?:[’'\-][^\W_]+)*|[^\w\s]", re.UNICODE)


def _element_text(element: etree._Element) -> str:
    return "".join(element.xpath(".//w:t/text() | .//w:delText/text()", namespaces=NS)).strip()


def _container(root: etree._Element) -> etree._Element:
    if etree.QName(root).localname == "document":
        body = root.find(f"{{{W}}}body")
        if body is None:
            raise ValueError("DOCX document part has no body")
        return body
    return root


def _direct_paragraphs(container: etree._Element) -> list[etree._Element]:
    return [
        child
        for child in container
        if etree.QName(child).localname == "p" and _element_text(child)
    ]


def _direct_tables(container: etree._Element) -> list[etree._Element]:
    return [child for child in container if etree.QName(child).localname == "tbl"]


def _tokens(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(value)


def _set_run_style(run: etree._Element, style: str) -> None:
    properties = run.find(f"{{{W}}}rPr")
    if properties is None:
        properties = etree.Element(f"{{{W}}}rPr")
        run.insert(0, properties)

    for name in ("color", "highlight", "strike"):
        existing = properties.find(f"{{{W}}}{name}")
        if existing is not None:
            properties.remove(existing)

    if style == "insertion":
        color = etree.SubElement(properties, f"{{{W}}}color")
        color.set(f"{{{W}}}val", INSERTION_TEXT)
        highlight = etree.SubElement(properties, f"{{{W}}}highlight")
        highlight.set(f"{{{W}}}val", "green")
    elif style == "deletion":
        color = etree.SubElement(properties, f"{{{W}}}color")
        color.set(f"{{{W}}}val", DELETION_TEXT)
        etree.SubElement(properties, f"{{{W}}}strike")
    _normalize_run_property_order(properties)


def _set_on_off(properties: etree._Element, name: str, enabled: bool = True) -> None:
    existing = properties.find(f"{{{W}}}{name}")
    if existing is not None:
        properties.remove(existing)
    if enabled:
        etree.SubElement(properties, f"{{{W}}}{name}")


def _new_text_run(
    text: str,
    *,
    color: str,
    size: int,
    bold: bool = False,
    strike: bool = False,
    highlight: str | None = None,
) -> etree._Element:
    run = etree.Element(f"{{{W}}}r")
    properties = etree.SubElement(run, f"{{{W}}}rPr")
    fonts = etree.SubElement(properties, f"{{{W}}}rFonts")
    for attribute in ("ascii", "hAnsi", "cs"):
        fonts.set(f"{{{W}}}{attribute}", "Arial")
    _set_on_off(properties, "b", bold)
    _set_on_off(properties, "strike", strike)
    color_element = etree.SubElement(properties, f"{{{W}}}color")
    color_element.set(f"{{{W}}}val", color)
    for name in ("sz", "szCs"):
        size_element = etree.SubElement(properties, f"{{{W}}}{name}")
        size_element.set(f"{{{W}}}val", str(size))
    if highlight:
        highlight_element = etree.SubElement(properties, f"{{{W}}}highlight")
        highlight_element.set(f"{{{W}}}val", highlight)
    _normalize_run_property_order(properties)
    text_element = etree.SubElement(run, f"{{{W}}}t")
    if text[:1].isspace() or text[-1:].isspace():
        text_element.set(XML_SPACE, "preserve")
    text_element.text = text
    return run


def _new_paragraph(*, alignment: str = "left", before: int = 0, after: int = 0) -> etree._Element:
    paragraph = etree.Element(f"{{{W}}}p")
    properties = etree.SubElement(paragraph, f"{{{W}}}pPr")
    spacing = etree.SubElement(properties, f"{{{W}}}spacing")
    spacing.set(f"{{{W}}}before", str(before))
    spacing.set(f"{{{W}}}after", str(after))
    spacing.set(f"{{{W}}}line", "240")
    spacing.set(f"{{{W}}}lineRule", "auto")
    justification = etree.SubElement(properties, f"{{{W}}}jc")
    justification.set(f"{{{W}}}val", alignment)
    return paragraph


def _set_cell_shading(cell: etree._Element, fill: str) -> None:
    properties = etree.SubElement(cell, f"{{{W}}}tcPr")
    width = etree.SubElement(properties, f"{{{W}}}tcW")
    width.set(f"{{{W}}}w", "3264")
    width.set(f"{{{W}}}type", "dxa")
    shading = etree.SubElement(properties, f"{{{W}}}shd")
    shading.set(f"{{{W}}}val", "clear")
    shading.set(f"{{{W}}}color", "auto")
    shading.set(f"{{{W}}}fill", fill)
    margins = etree.SubElement(properties, f"{{{W}}}tcMar")
    for side in ("top", "left", "bottom", "right"):
        margin = etree.SubElement(margins, f"{{{W}}}{side}")
        margin.set(f"{{{W}}}w", "110" if side in ("top", "bottom") else "140")
        margin.set(f"{{{W}}}type", "dxa")


def _legend_cell(label: str, description: str, style: str) -> etree._Element:
    cell = etree.Element(f"{{{W}}}tc")
    _set_cell_shading(cell, "C9C9C9")
    paragraph = _new_paragraph(after=0)
    paragraph.append(
        _new_text_run(
            label + ":",
            color=DELETION_TEXT if style == "deletion" else "000000",
            size=20,
            bold=True,
            strike=style == "deletion",
            highlight="green" if style == "insertion" else None,
        )
    )
    paragraph.append(_new_text_run(" ", color="000000", size=19))
    paragraph.append(_new_text_run(description, color="000000", size=19))
    cell.append(paragraph)
    return cell


def _add_report_header(root: etree._Element) -> None:
    """Add a polished comparison title and an immediately readable key."""
    body = _container(root)
    is_test_document = "TEST / SYNTHETIC DOCUMENT" in _element_text(body)
    report_title = (
        "POSTBANK TEST DOCUMENT — VISUAL REDLINE COMPARISON"
        if is_test_document
        else "POSTBANK DOCUMENT — VISUAL REDLINE COMPARISON"
    )
    report_subtitle = (
        "Reference output for comparison-engine validation. This is a visual redline, not native Word Track Changes."
        if is_test_document
        else "This visual redline shows changes from the original document to the revised document."
    )

    title = _new_paragraph(alignment="center", before=100, after=180)
    title.append(
        _new_text_run(
            report_title,
            color="000000",
            size=36,
            bold=True,
        )
    )

    subtitle = _new_paragraph(alignment="center", after=180)
    subtitle.append(
        _new_text_run(
            report_subtitle,
            color="595959",
            size=21,
        )
    )

    table = etree.Element(f"{{{W}}}tbl")
    properties = etree.SubElement(table, f"{{{W}}}tblPr")
    width = etree.SubElement(properties, f"{{{W}}}tblW")
    width.set(f"{{{W}}}w", "5000")
    width.set(f"{{{W}}}type", "pct")
    alignment = etree.SubElement(properties, f"{{{W}}}jc")
    alignment.set(f"{{{W}}}val", "center")
    borders = etree.SubElement(properties, f"{{{W}}}tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = etree.SubElement(borders, f"{{{W}}}{side}")
        border.set(f"{{{W}}}val", "single")
        border.set(f"{{{W}}}sz", "8")
        border.set(f"{{{W}}}color", "000000")
    grid = etree.SubElement(table, f"{{{W}}}tblGrid")
    for _ in range(3):
        column = etree.SubElement(grid, f"{{{W}}}gridCol")
        column.set(f"{{{W}}}w", "3264")
    row = etree.SubElement(table, f"{{{W}}}tr")
    row_properties = etree.SubElement(row, f"{{{W}}}trPr")
    no_split = etree.SubElement(row_properties, f"{{{W}}}cantSplit")
    row_height = etree.SubElement(row_properties, f"{{{W}}}trHeight")
    row_height.set(f"{{{W}}}val", "420")
    row_height.set(f"{{{W}}}hRule", "atLeast")
    row.append(_legend_cell("UNCHANGED", "Normal text", "unchanged"))
    row.append(_legend_cell("DELETED", "Red strikethrough", "deletion"))
    row.append(_legend_cell("INSERTED", "Green highlight", "insertion"))

    spacer = _new_paragraph(after=150)
    body.insert(0, spacer)
    body.insert(0, table)
    body.insert(0, subtitle)
    body.insert(0, title)


def _improve_body_spacing(root: etree._Element) -> None:
    """Apply consistent paragraph rhythm without flattening document structure."""
    body = _container(root)
    for paragraph in body.xpath("./w:p", namespaces=NS):
        properties = paragraph.find(f"{{{W}}}pPr")
        if properties is None:
            properties = etree.Element(f"{{{W}}}pPr")
            paragraph.insert(0, properties)
        spacing = properties.find(f"{{{W}}}spacing")
        if spacing is None:
            spacing = etree.SubElement(properties, f"{{{W}}}spacing")
        if _element_text(paragraph):
            spacing.set(f"{{{W}}}after", "110")
            spacing.set(f"{{{W}}}line", "276")
            spacing.set(f"{{{W}}}lineRule", "auto")
        else:
            spacing.set(f"{{{W}}}before", "0")
            spacing.set(f"{{{W}}}after", "0")
            spacing.set(f"{{{W}}}line", "80")
            spacing.set(f"{{{W}}}lineRule", "exact")
        _normalize_paragraph_property_order(properties)


def _append_run(paragraph: etree._Element, text: str, style: str = "unchanged") -> None:
    if not text:
        return
    run = etree.SubElement(paragraph, f"{{{W}}}r")
    if style != "unchanged":
        _set_run_style(run, style)
    text_element = etree.SubElement(run, f"{{{W}}}t")
    if text[:1].isspace() or text[-1:].isspace():
        text_element.set(XML_SPACE, "preserve")
    text_element.text = text


def _clear_paragraph_content(paragraph: etree._Element) -> None:
    for child in list(paragraph):
        if etree.QName(child).localname != "pPr":
            paragraph.remove(child)


def _render_modification(paragraph: etree._Element, original: str, revised: str) -> None:
    _clear_paragraph_content(paragraph)
    original_tokens = _tokens(original)
    revised_tokens = _tokens(revised)
    matcher = SequenceMatcher(None, original_tokens, revised_tokens, autojunk=False)
    for operation, i1, i2, j1, j2 in matcher.get_opcodes():
        if operation == "equal":
            _append_run(paragraph, "".join(revised_tokens[j1:j2]))
        elif operation == "delete":
            _append_run(paragraph, "".join(original_tokens[i1:i2]), "deletion")
        elif operation == "insert":
            _append_run(paragraph, "".join(revised_tokens[j1:j2]), "insertion")
        else:
            _append_run(paragraph, "".join(original_tokens[i1:i2]), "deletion")
            _append_run(paragraph, "".join(revised_tokens[j1:j2]), "insertion")


def _style_all_runs(element: etree._Element, style: str) -> None:
    for run in element.xpath(".//w:r", namespaces=NS):
        _set_run_style(run, style)


def _cell_paragraph(cell: etree._Element) -> etree._Element:
    paragraphs = cell.xpath(".//w:p", namespaces=NS)
    if paragraphs:
        target = paragraphs[0]
        for extra in paragraphs[1:]:
            _clear_paragraph_content(extra)
        return target
    return etree.SubElement(cell, f"{{{W}}}p")


def _part_filename(part: str) -> str:
    return "word/document.xml" if part == "document" else f"word/{part}.xml"


def _copy_deleted_paragraph(
    revised_container: etree._Element,
    original_container: etree._Element,
    paragraph_index: int,
) -> None:
    original_paragraphs = _direct_paragraphs(original_container)
    if paragraph_index < 1 or paragraph_index > len(original_paragraphs):
        return
    deleted = copy.deepcopy(original_paragraphs[paragraph_index - 1])
    _style_all_runs(deleted, "deletion")
    revised_paragraphs = _direct_paragraphs(revised_container)
    if paragraph_index <= len(revised_paragraphs):
        revised_container.insert(revised_container.index(revised_paragraphs[paragraph_index - 1]), deleted)
    else:
        revised_container.append(deleted)


def _apply_part_changes(
    revised_root: etree._Element,
    original_root: etree._Element | None,
    changes: list[dict[str, object]],
) -> None:
    revised_container = _container(revised_root)
    original_container = _container(original_root) if original_root is not None else None

    # First style units that already exist in the revised document. Removed
    # paragraphs/rows are reinserted afterward so they cannot shift these indices.
    for change in changes:
        location = change["location"]
        container_type = location["container"]
        change_type = change["type"]

        if container_type == "paragraph":
            if change_type == "deletion":
                continue
            paragraphs = _direct_paragraphs(revised_container)
            index = int(location["paragraph_index"]) - 1
            if not 0 <= index < len(paragraphs):
                continue
            paragraph = paragraphs[index]
            if change_type == "addition":
                _style_all_runs(paragraph, "insertion")
            else:
                _render_modification(
                    paragraph, str(change["original_text"]), str(change["revised_text"])
                )
            continue

        tables = _direct_tables(revised_container)
        table_index = int(location["table_index"]) - 1
        if not 0 <= table_index < len(tables):
            continue
        table = tables[table_index]
        rows = table.xpath("./w:tr", namespaces=NS)
        row_index = int(location["row_index"]) - 1

        if container_type == "table_row":
            if change_type == "addition" and 0 <= row_index < len(rows):
                _style_all_runs(rows[row_index], "insertion")
            continue

        if not 0 <= row_index < len(rows):
            continue
        cells = rows[row_index].xpath("./w:tc", namespaces=NS)
        cell_index = int(location["cell_index"]) - 1
        if not 0 <= cell_index < len(cells):
            continue
        paragraph = _cell_paragraph(cells[cell_index])
        if change_type == "addition":
            _style_all_runs(cells[cell_index], "insertion")
        elif change_type == "deletion":
            _render_modification(paragraph, str(change["original_text"]), "")
        else:
            _render_modification(
                paragraph, str(change["original_text"]), str(change["revised_text"])
            )

    if original_container is None:
        return

    paragraph_deletions = [
        change
        for change in changes
        if change["type"] == "deletion" and change["location"]["container"] == "paragraph"
    ]
    for change in sorted(
        paragraph_deletions,
        key=lambda item: int(item["location"]["paragraph_index"]),
        reverse=True,
    ):
        _copy_deleted_paragraph(
            revised_container,
            original_container,
            int(change["location"]["paragraph_index"]),
        )

    row_deletions = [
        change
        for change in changes
        if change["type"] == "deletion" and change["location"]["container"] == "table_row"
    ]
    for change in sorted(
        row_deletions,
        key=lambda item: (
            int(item["location"]["table_index"]),
            int(item["location"]["row_index"]),
        ),
        reverse=True,
    ):
        table_index = int(change["location"]["table_index"]) - 1
        row_index = int(change["location"]["row_index"]) - 1
        revised_tables = _direct_tables(revised_container)
        original_tables = _direct_tables(original_container)
        if table_index >= len(revised_tables) or table_index >= len(original_tables):
            continue
        revised_table = revised_tables[table_index]
        original_rows = original_tables[table_index].xpath("./w:tr", namespaces=NS)
        revised_rows = revised_table.xpath("./w:tr", namespaces=NS)
        if not 0 <= row_index < len(original_rows):
            continue
        deleted_row = copy.deepcopy(original_rows[row_index])
        _style_all_runs(deleted_row, "deletion")
        revised_table.insert(min(row_index, len(revised_rows)), deleted_row)


def generate_visual_redline(
    original_path: Path,
    revised_path: Path,
    changes: list[dict[str, object]],
    output_path: Path,
) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    changes_by_part: dict[str, list[dict[str, object]]] = {}
    for change in changes:
        changes_by_part.setdefault(str(change["location"]["part"]), []).append(change)

    with zipfile.ZipFile(original_path) as original_package, zipfile.ZipFile(
        revised_path
    ) as revised_package:
        original_names = set(original_package.namelist())
        destination = io.BytesIO()
        with zipfile.ZipFile(destination, "w") as output_package:
            for entry in revised_package.infolist():
                content = revised_package.read(entry.filename)
                part = None
                if entry.filename == "word/document.xml":
                    part = "document"
                elif re.match(r"^word/(header|footer)\d+\.xml$", entry.filename):
                    part = Path(entry.filename).stem

                if part in changes_by_part:
                    revised_root = etree.fromstring(content, parser=parser)
                    original_root = (
                        etree.fromstring(original_package.read(entry.filename), parser=parser)
                        if entry.filename in original_names
                        else None
                    )
                    _apply_part_changes(revised_root, original_root, changes_by_part[part])
                    if part == "document":
                        _improve_body_spacing(revised_root)
                        _add_report_header(revised_root)
                    content = etree.tostring(
                        revised_root, encoding="UTF-8", xml_declaration=True, standalone=True
                    )
                output_package.writestr(entry, content)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(destination.getvalue())
