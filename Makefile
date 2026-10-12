ifeq ($(OS),Windows_NT)
  SHELL := cmd.exe
  .SHELLFLAGS := /C
  PY := .venv\Scripts\python.exe
  SYS_PY := python
else
  PY := .venv/bin/python
  SYS_PY := python3
endif

.PHONY: setup data synthetic lint fmt test eval eval-draft eval-mock report verify-gold demo serve clean

setup:
	$(SYS_PY) -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev]"

data:
	$(PY) scripts/load_nyc_tlc.py

synthetic:
	$(PY) scripts/make_synthetic.py

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

test:
	$(PY) -m pytest --cov=asksql --cov-report=term-missing:skip-covered

# Needs Ollama running. Scores only questions with verified_by set.
eval:
	$(PY) -m asksql.cli eval --strategies s1,s2 --provider ollama

# Same run over every question, verified or not. The report is marked DRAFT.
eval-draft:
	$(PY) -m asksql.cli eval --strategies s1,s2 --provider ollama --include-unverified

# No model and no network: mock provider on the fixture database.
eval-mock:
	$(PY) -m asksql.cli eval --strategies s1,s2 --provider mock --fixture-db --include-unverified --skip-tests --out-dir build/eval-mock

report:
	$(PY) -m asksql.cli report

verify-gold:
	$(PY) -m asksql.cli gold

demo:
	$(PY) scripts/demo.py

serve:
	$(PY) -m asksql.cli serve

clean:
	$(SYS_PY) -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['build', '.pytest_cache', '.ruff_cache', 'asksql.egg-info', 'htmlcov']]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__') if '.venv' not in p.parts]; pathlib.Path('.coverage').unlink(missing_ok=True)"
