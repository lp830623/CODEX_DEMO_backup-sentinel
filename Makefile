.PHONY: install test lint sample

install:
	python -m pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src tests
	ruff format --check src tests

sample:
	backup-sentinel run --config config.example.yaml --date 2026-10-14 --dry-run
