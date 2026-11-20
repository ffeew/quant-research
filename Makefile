PYTHON ?= python3
DATASET ?=

.PHONY: help install test test-random test-data coverage lint typecheck hygiene lock \
	package-smoke audit pre-commit gitleaks check format build-data datasets trials clean

help:
	@echo "make install          uv sync --locked (Python 3.12, dev group)"
	@echo "make lint             ruff check and ruff format --check"
	@echo "make typecheck        mypy (strict on src, relaxed on tests)"
	@echo "make test             compileall and pytest, stable order"
	@echo "make test-random      compileall and pytest in random order (pytest-randomly)"
	@echo "make coverage         pytest with the fail_under coverage gate"
	@echo "make hygiene          data files, bulky files, leaked paths and keys"
	@echo "make lock             uv lock --check"
	@echo "make pre-commit       pre-commit run --all-files"
	@echo "make package-smoke    uv build and import the wheel from a clean venv"
	@echo "make audit            pip-audit on the exported lock"
	@echo "make gitleaks         full-history secret scan (gitleaks 8.30.1 on PATH)"
	@echo "make check            lint, typecheck, coverage, test-random, hygiene, lock, pre-commit"
	@echo "make test-data        run all tests and fail if research data is missing"
	@echo "make format           ruff format"
	@echo "make datasets         list dataset builders"
	@echo "make build-data DATASET=<name>   build one dataset into \$$QR_DATA_DIR"
	@echo "make trials           list trials and verdicts"

install:
	uv sync --locked

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

test:
	uv run python -m compileall -q src tests scripts
	uv run pytest -p no:randomly

test-random:
	uv run python -m compileall -q src tests scripts
	uv run pytest

test-data:
	QR_REQUIRE_DATA=1 uv run pytest -p no:randomly

coverage:
	uv run python -m compileall -q src tests scripts
	uv run pytest -p no:randomly --cov --cov-report=term-missing --cov-report=xml --cov-report=html

hygiene:
	uv run python scripts/check_repo_hygiene.py

lock:
	uv lock --check

package-smoke:
	bash scripts/package_smoke.sh

audit:
	bash scripts/audit_deps.sh

pre-commit:
	uv run pre-commit run --all-files

gitleaks:
	gitleaks detect --source . --redact --no-banner --exit-code 1 --log-opts="--all"

check: lint typecheck coverage test-random hygiene lock pre-commit

format:
	uv run ruff format src tests scripts

datasets:
	uv run qr datasets

build-data:
	@test -n "$(DATASET)" || (echo "usage: make build-data DATASET=<name>  (see: make datasets)"; exit 2)
	@test -n "$$ALPHAVANTAGE_API_KEY" || echo "warning: ALPHAVANTAGE_API_KEY is not set"
	uv run qr build-data $(DATASET)

trials:
	uv run qr list

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache .mypy_cache .venv htmlcov
	rm -f .coverage coverage.xml
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
