"""Compare logical document units independently of engine revision segmentation."""

from __future__ import annotations

from pathlib import Path

from .alignment import align_sequences
from .document_reader import DocumentContent, ParagraphUnit, TableRowUnit, read_document
from .similarity import row_similarity, severity, text_similarity


def _base_change(change_type: str, original: str, revised: str, location: dict[str, object]) -> dict[str, object]:
    if change_type == "modification":
        change_severity = severity(original, revised)
    else:
        change_severity = "normal"
    return {
        "type": change_type,
        "severity": change_severity,
        "original_text": original,
        "revised_text": revised,
        "deleted_text": original if change_type in {"deletion", "modification"} else "",
        "inserted_text": revised if change_type in {"addition", "modification"} else "",
        "context": revised or original,
        "location": location,
    }


def _paragraph_changes(
    part: str,
    original: list[ParagraphUnit],
    revised: list[ParagraphUnit],
) -> list[dict[str, object]]:
    operations = align_sequences(original, revised, lambda left, right: text_similarity(left.text, right.text))
    changes: list[dict[str, object]] = []
    for operation, original_index, revised_index in operations:
        left = original[original_index] if original_index is not None else None
        right = revised[revised_index] if revised_index is not None else None
        if left and right and left.text == right.text:
            continue
        if operation == "insert":
            location = {
                "part": part,
                "container": "paragraph",
                "paragraph_index": right.paragraph_index,
            }
            change = _base_change("addition", "", right.text, location)
            change["_sort"] = (right.block_order, 0, right.paragraph_index)
        elif operation == "delete":
            location = {
                "part": part,
                "container": "paragraph",
                "paragraph_index": left.paragraph_index,
            }
            change = _base_change("deletion", left.text, "", location)
            change["_sort"] = (left.block_order, 0, left.paragraph_index)
        else:
            location = {
                "part": part,
                "container": "paragraph",
                "paragraph_index": right.paragraph_index,
            }
            change = _base_change("modification", left.text, right.text, location)
            change["_sort"] = (right.block_order, 0, right.paragraph_index)
        changes.append(change)
    return changes


def _table_changes(
    part: str,
    original: list[TableRowUnit],
    revised: list[TableRowUnit],
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    table_numbers = sorted({row.table_index for row in original} | {row.table_index for row in revised})
    for table_index in table_numbers:
        original_rows = [row for row in original if row.table_index == table_index]
        revised_rows = [row for row in revised if row.table_index == table_index]
        operations = align_sequences(
            original_rows,
            revised_rows,
            lambda left, right: row_similarity(left.cells, right.cells),
            substitution_floor=0.45,
            substitution_ceiling=1.85,
        )
        for operation, original_index, revised_index in operations:
            left = original_rows[original_index] if original_index is not None else None
            right = revised_rows[revised_index] if revised_index is not None else None
            if operation == "insert":
                combined = " | ".join(right.cells)
                location = {
                    "part": part,
                    "container": "table_row",
                    "table_index": table_index,
                    "row_index": right.row_index,
                }
                change = _base_change("addition", "", combined, location)
                change["context"] = f"Table {table_index}, row {right.row_index} added: {combined}"
                change["_sort"] = (right.block_order, right.row_index, 0)
                changes.append(change)
                continue
            if operation == "delete":
                combined = " | ".join(left.cells)
                location = {
                    "part": part,
                    "container": "table_row",
                    "table_index": table_index,
                    "row_index": left.row_index,
                }
                change = _base_change("deletion", combined, "", location)
                change["context"] = f"Table {table_index}, row {left.row_index} removed: {combined}"
                change["_sort"] = (left.block_order, left.row_index, 0)
                changes.append(change)
                continue

            width = max(len(left.cells), len(right.cells))
            for cell_index in range(width):
                original_text = left.cells[cell_index] if cell_index < len(left.cells) else ""
                revised_text = right.cells[cell_index] if cell_index < len(right.cells) else ""
                if original_text == revised_text:
                    continue
                if not original_text:
                    change_type = "addition"
                elif not revised_text:
                    change_type = "deletion"
                else:
                    change_type = "modification"
                location = {
                    "part": part,
                    "container": "table_cell",
                    "table_index": table_index,
                    "row_index": right.row_index,
                    "cell_index": cell_index + 1,
                }
                change = _base_change(change_type, original_text, revised_text, location)
                change["_sort"] = (right.block_order, right.row_index, cell_index + 1)
                changes.append(change)
    return changes


def compare_semantic_changes(original_path: Path, revised_path: Path) -> list[dict[str, object]]:
    original: DocumentContent = read_document(original_path)
    revised: DocumentContent = read_document(revised_path)
    changes: list[dict[str, object]] = []
    part_names = sorted(
        set(original.parts) | set(revised.parts),
        key=lambda name: (0 if name == "document" else 1 if name.startswith("header") else 2, name),
    )
    for part_rank, part_name in enumerate(part_names):
        original_part = original.parts.get(part_name)
        revised_part = revised.parts.get(part_name)
        original_paragraphs = original_part.paragraphs if original_part else []
        revised_paragraphs = revised_part.paragraphs if revised_part else []
        original_rows = original_part.rows if original_part else []
        revised_rows = revised_part.rows if revised_part else []
        part_changes = _paragraph_changes(part_name, original_paragraphs, revised_paragraphs)
        part_changes.extend(_table_changes(part_name, original_rows, revised_rows))
        for change in part_changes:
            change["_part_rank"] = part_rank
        changes.extend(part_changes)

    changes.sort(key=lambda item: (item["_part_rank"], item["_sort"]))
    for change_id, change in enumerate(changes, start=1):
        change.pop("_part_rank")
        change.pop("_sort")
        change["id"] = change_id
    return changes
