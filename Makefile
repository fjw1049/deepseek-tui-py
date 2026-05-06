PYTHON := .venv/bin/python
PRE_COMMIT := .venv/bin/pre-commit

.PHONY: install-dev format lint typecheck test check pre-commit-install

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

format:
	PYTHONPATH=src $(PYTHON) -m ruff format src tests

lint:
	PYTHONPATH=src $(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m mypy src

test:
	PYTHONPATH=src $(PYTHON) -m pytest tests

check: lint typecheck test

pre-commit-install:
	$(PRE_COMMIT) install
