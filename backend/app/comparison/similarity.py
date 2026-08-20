"""Text and table-row similarity helpers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize_text(value: str) -> str:
    value = re.sub(r"[\t\r\n ]+", " ", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return value.strip()


def text_similarity(original: str, revised: str) -> float:
    left = normalize_text(original).casefold()
    right = normalize_text(revised).casefold()
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def row_similarity(original_cells: list[str], revised_cells: list[str]) -> float:
    width = max(len(original_cells), len(revised_cells), 1)
    cell_scores = []
    exact_cells = 0
    for index in range(width):
        original = original_cells[index] if index < len(original_cells) else ""
        revised = revised_cells[index] if index < len(revised_cells) else ""
        score = text_similarity(original, revised)
        cell_scores.append(score)
        if normalize_text(original).casefold() == normalize_text(revised).casefold() and original:
            exact_cells += 1
    average = sum(cell_scores) / width
    exact_ratio = exact_cells / width
    whole_row = text_similarity(" | ".join(original_cells), " | ".join(revised_cells))
    return (0.55 * average) + (0.25 * exact_ratio) + (0.20 * whole_row)


def severity(original: str, revised: str) -> str:
    if min(len(normalize_text(original)), len(normalize_text(revised))) < 20:
        return "normal"
    return "heavily_revised" if text_similarity(original, revised) < 0.45 else "normal"

