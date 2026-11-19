PYTHON ?= python3
DATASET ?=

.PHONY: help install test test-data lint typecheck check format build-data datasets trials clean

help:
	@echo "make install          uv sync --locked (Python 3.12, dev group)"
	@echo "make lint             ruff check and ruff format --check"
	@echo "make typecheck        mypy (strict on src, relaxed on tests)"
	@echo "make check            lint, typecheck, and test"
	@echo "make test             compileall and pytest (data tests skip without QR_DATA_DIR)"
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
	uv run pytest

test-data:
	QR_REQUIRE_DATA=1 uv run pytest

check: lint typecheck test

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
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache .mypy_cache .venv
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
