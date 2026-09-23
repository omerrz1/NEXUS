.PHONY: check lint format typecheck test install

VENV ?= .venv
PYTHON = $(VENV)/bin/python
RUFF = $(VENV)/bin/ruff
MYPY = $(VENV)/bin/mypy
PYTEST = $(VENV)/bin/pytest

install:
	$(PYTHON) -m pip install -e ".[dev]"

check: lint typecheck test

lint:
	$(RUFF) check src tests
	$(RUFF) format --check src tests

format:
	$(RUFF) format src tests
	$(RUFF) check --fix src tests

typecheck:
	$(MYPY) src tests

test:
	$(PYTEST) -v
