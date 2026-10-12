from asksql.extract import extract_sql


def test_fenced_sql_block():
    assert extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"


def test_prose_before_and_after_a_fence():
    text = (
        "Sure! Here is the query:\n\n```sql\nSELECT COUNT(*) FROM trips;\n```\n\nThis counts trips."
    )
    assert extract_sql(text) == "SELECT COUNT(*) FROM trips"


def test_first_sql_block_wins():
    text = "```sql\nSELECT 1\n```\nor alternatively\n```sql\nSELECT 2\n```"
    assert extract_sql(text) == "SELECT 1"


def test_sql_tagged_block_beats_an_earlier_untagged_block():
    text = "```\nsome output\n```\n```sql\nSELECT 2\n```"
    assert extract_sql(text) == "SELECT 2"


def test_untagged_fence_that_looks_like_sql():
    assert extract_sql("```\nWITH x AS (SELECT 1) SELECT * FROM x\n```") == (
        "WITH x AS (SELECT 1) SELECT * FROM x"
    )


def test_bare_sql():
    assert extract_sql("SELECT zone FROM zones") == "SELECT zone FROM zones"


def test_bare_sql_with_leading_prose_and_trailing_explanation():
    text = "The answer is:\nSELECT zone\nFROM zones;\n\nThis lists the zones."
    assert extract_sql(text) == "SELECT zone\nFROM zones"


def test_bare_sql_without_semicolon_stops_at_blank_line():
    text = "select zone from zones\n\nHope that helps"
    assert extract_sql(text) == "select zone from zones"


def test_trailing_semicolons_and_whitespace_are_removed():
    assert extract_sql("```sql\nSELECT 1 ;;  \n```") == "SELECT 1"


def test_stacked_statements_are_kept_for_the_guard():
    assert extract_sql("```sql\nSELECT 1; DROP TABLE trips;\n```") == "SELECT 1; DROP TABLE trips"


def test_no_sql_found():
    assert extract_sql("I cannot answer that.") is None
    assert extract_sql("") is None
    assert extract_sql("```python\nprint('hi')\n```") is None


def test_non_select_statement_is_not_extracted():
    assert extract_sql("DROP TABLE trips") is None
