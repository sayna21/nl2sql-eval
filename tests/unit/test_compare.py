import pytest

from asksql.evaluation.compare import (
    COL_COUNT_MISMATCH,
    MATCH,
    WRONG_RESULT,
    compare_results,
    normalise_cell,
    results_match,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (True, 1),
        (False, 0),
        (3.14159, 3.14),
        (2.0, 2.0),
        ("  JFK Airport ", "JFK Airport"),
        (7, 7),
    ],
)
def test_normalise_cell(raw, expected):
    assert normalise_cell(raw) == expected


def test_unordered_comparison_ignores_row_order():
    pred = [("Queens", 3), ("Manhattan", 9)]
    gold = [("Manhattan", 9), ("Queens", 3)]
    assert results_match(pred, gold, ordered=False)


def test_ordered_comparison_respects_row_order():
    pred = [("Queens", 3), ("Manhattan", 9)]
    gold = [("Manhattan", 9), ("Queens", 3)]
    assert not results_match(pred, gold, ordered=True)
    assert results_match(gold, gold, ordered=True)


def test_floats_match_after_rounding():
    assert results_match([(17.537293,)], [(17.54,)], ordered=False)
    assert not results_match([(17.53,)], [(17.55,)], ordered=False)


def test_integer_and_float_of_same_value_match():
    assert results_match([(5,)], [(5.0,)], ordered=False)


def test_none_is_kept_and_compared():
    assert results_match([(None, 1)], [(None, 1)], ordered=False)
    assert not results_match([(None, 1)], [(0, 1)], ordered=False)


def test_duplicate_rows_are_compared_as_a_multiset():
    assert results_match([(1,), (1,), (2,)], [(2,), (1,), (1,)], ordered=False)
    assert not results_match([(1,), (2,), (2,)], [(1,), (1,), (2,)], ordered=False)
    assert not results_match([(1,), (2,)], [(1,), (1,), (2,)], ordered=False)


def test_column_count_mismatch_has_its_own_category():
    pred = [("JFK Airport", 12221, 132)]
    gold = [("JFK Airport", 12221)]
    assert compare_results(pred, gold, ordered=False) == COL_COUNT_MISMATCH
    assert not results_match(pred, gold, ordered=False)


def test_wrong_values_are_wrong_result():
    assert compare_results([(1,)], [(2,)], ordered=False) == WRONG_RESULT


def test_two_empty_results_match():
    # A known weakness of execution accuracy: both queries returning nothing counts as correct.
    assert compare_results([], [], ordered=False) == MATCH


def test_strings_are_stripped_but_case_sensitive():
    assert results_match([(" Cash",)], [("Cash",)], ordered=False)
    assert not results_match([("cash",)], [("Cash",)], ordered=False)
