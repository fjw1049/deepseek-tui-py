PYTHON := .venv/bin/python
PRE_COMMIT := .venv/bin/pre-commit

.PHONY: requirements-lock check-lock
requirements-lock:
	$(PYTHON) scripts/export-requirements.py

check-lock:
	$(PYTHON) scripts/export-requirements.py --check

.PHONY: install-dev format lint typecheck test eval-validate eval-typecheck eval-offline eval-serve eval-full eval-history eval-personal check pre-commit-install

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
	MYPYPATH=src $(PYTHON) -m mypy evals --exclude 'evals/artifacts/' --ignore-missing-imports --follow-imports=silent

eval-serve:
	bash scripts/dev-eval.sh

eval-offline:
	PYTHONPATH=src:. $(PYTHON) -m evals run --mode offline --baseline evals/baselines/offline.json

# Standard live regression: one attempt, serial trials, a fresh artifact directory.
FLASH_EVAL = PYTHONPATH=src:. $(PYTHON) -m evals run --mode live --provider endpoint --model deepseek-v4-1-flash --timeout 360 --concurrency 1 --trials 1 --max-live-requests 500

eval-full: eval-validate
	$(FLASH_EVAL)

eval-history: eval-validate
	$(FLASH_EVAL) --suite personal_sessions --suite claude_sessions --suite claude_archived --suite history_pilot

eval-personal: eval-validate
	$(FLASH_EVAL) --suite personal_sessions

check: check-lock lint typecheck test eval-typecheck eval-offline

pre-commit-install:
	$(PRE_COMMIT) install
