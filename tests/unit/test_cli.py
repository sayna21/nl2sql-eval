import pytest

from asksql.cli import main


@pytest.mark.parametrize(
    "arguments",
    [
        ["--strategies", ""],
        ["--strategies", "s9"],
        ["--limit", "0"],
        ["--limit", "-1"],
        ["--timeout", "0"],
        ["--timeout", "-1"],
    ],
)
def test_invalid_eval_options_fail_before_running(arguments, capsys):
    assert main(["eval", *arguments]) == 1
    assert "error:" in capsys.readouterr().err
