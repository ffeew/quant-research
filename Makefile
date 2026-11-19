PYTHON ?= python3
DATASET ?=

.PHONY: help install test test-data lint format build-data datasets trials clean

help:
	@echo "make install          editable install with dev extras"
	@echo "make test             run unit tests (data-dependent tests skip without QR_DATA_DIR)"
	@echo "make test-data        run all tests and fail if research data is missing"
	@echo "make lint             ruff check"
	@echo "make datasets         list dataset builders"
	@echo "make build-data DATASET=<name>   build one dataset into \$$QR_DATA_DIR"
	@echo "make trials           list trials and verdicts"

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

test-data:
	QR_REQUIRE_DATA=1 $(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format src tests scripts

datasets:
	qr datasets

build-data:
	@test -n "$(DATASET)" || (echo "usage: make build-data DATASET=<name>  (see: make datasets)"; exit 2)
	@test -n "$$ALPHAVANTAGE_API_KEY" || echo "warning: ALPHAVANTAGE_API_KEY is not set"
	qr build-data $(DATASET)

trials:
	qr list

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
