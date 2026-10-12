from pathlib import Path

import pytest

from asksql.db import open_readonly
from asksql.schema import build_db_from_script

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tiny_db(tmp_path) -> Path:
    return build_db_from_script(FIXTURES / "tiny.sql", tmp_path / "tiny.db")


@pytest.fixture
def conn(tiny_db):
    connection = open_readonly(tiny_db)
    yield connection
    connection.close()
