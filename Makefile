PYTHON := .venv/bin/python
PRE_COMMIT := .venv/bin/pre-commit

.PHONY: install-dev format lint typecheck test eval-validate eval-typecheck eval-offline eval-serve check pre-commit-install

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

format:
	PYTHONPATH=src:. $(PYTHON) -m ruff format src tests evals

lint:
	PYTHONPATH=src:. $(PYTHON) -m ruff check src tests evals

typecheck:
	$(PYTHON) -m mypy src

test:
	PYTHONPATH=src $(PYTHON) -m pytest tests

eval-validate:
	PYTHONPATH=src:. $(PYTHON) -m evals validate

eval-typecheck:
	MYPYPATH=src $(PYTHON) -m mypy evals --ignore-missing-imports --follow-imports=silent

eval-serve:
	bash scripts/dev-eval.sh

eval-offline:
	PYTHONPATH=src:. $(PYTHON) -m evals run --mode offline --baseline evals/baselines/offline.json

check: lint typecheck test eval-typecheck eval-offline

pre-commit-install:
	$(PRE_COMMIT) install
