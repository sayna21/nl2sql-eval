"""Compare a predicted result set with a gold result set (execution accuracy)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

MATCH = "match"
COL_COUNT_MISMATCH = "col_count_mismatch"
WRONG_RESULT = "wrong_result"


def normalise_cell(value):
    """Make cells comparable: bools become ints, floats round to 2 dp, strings are stripped."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, str):
        return value.strip()
    return value


def _normalise(rows: Sequence[Sequence]) -> list[tuple]:
    return [tuple(normalise_cell(cell) for cell in row) for row in rows]


def compare_results(
    pred_rows: Sequence[Sequence], gold_rows: Sequence[Sequence], ordered: bool
) -> str:
    """Return MATCH, COL_COUNT_MISMATCH or WRONG_RESULT.

    Column names are ignored; only values and their positions matter. A different
    number of columns is reported separately because it is usually an extra or
    missing column rather than a wrong answer.
    """
    pred, gold = _normalise(pred_rows), _normalise(gold_rows)
    if pred and gold and len(pred[0]) != len(gold[0]):
        return COL_COUNT_MISMATCH
    if ordered:
        same = pred == gold
    else:
        same = Counter(pred) == Counter(gold)
    return MATCH if same else WRONG_RESULT


def results_match(
    pred_rows: Sequence[Sequence], gold_rows: Sequence[Sequence], ordered: bool
) -> bool:
    return compare_results(pred_rows, gold_rows, ordered) == MATCH
