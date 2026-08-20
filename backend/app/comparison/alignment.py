"""Order-preserving alignment for paragraphs and table rows."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


def align_sequences(
    original: Sequence[T],
    revised: Sequence[T],
    similarity: Callable[[T, T], float],
    *,
    substitution_floor: float = 0.55,
    substitution_ceiling: float = 1.65,
) -> list[tuple[str, int | None, int | None]]:
    """Return ordered match/insert/delete operations using dynamic programming."""
    rows = len(original) + 1
    columns = len(revised) + 1
    costs = [[0.0] * columns for _ in range(rows)]
    choices: list[list[str | None]] = [[None] * columns for _ in range(rows)]

    for i in range(1, rows):
        costs[i][0] = float(i)
        choices[i][0] = "delete"
    for j in range(1, columns):
        costs[0][j] = float(j)
        choices[0][j] = "insert"

    for i in range(1, rows):
        for j in range(1, columns):
            score = similarity(original[i - 1], revised[j - 1])
            substitute_cost = (
                0.0
                if score == 1.0
                else substitution_floor
                + (1.0 - score) * (substitution_ceiling - substitution_floor)
            )
            candidates = (
                (costs[i - 1][j - 1] + substitute_cost, "match"),
                (costs[i - 1][j] + 1.0, "delete"),
                (costs[i][j - 1] + 1.0, "insert"),
            )
            costs[i][j], choices[i][j] = min(candidates, key=lambda item: item[0])

    operations: list[tuple[str, int | None, int | None]] = []
    i, j = len(original), len(revised)
    while i or j:
        choice = choices[i][j]
        if choice == "match":
            operations.append(("match", i - 1, j - 1))
            i -= 1
            j -= 1
        elif choice == "delete":
            operations.append(("delete", i - 1, None))
            i -= 1
        else:
            operations.append(("insert", None, j - 1))
            j -= 1
    operations.reverse()
    return operations
