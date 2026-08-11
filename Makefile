.PHONY: setup test lint format typecheck contracts foundation-check check local-up local-down

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e '.[dev]'

test:
	.venv/bin/python -m pytest

lint:
	.venv/bin/python -m ruff check .

format:
	.venv/bin/python -m ruff format .

typecheck:
	.venv/bin/python -m mypy

contracts:
	.venv/bin/python scripts/validate_contracts.py

foundation-check:
	.venv/bin/python scripts/check_foundation.py

check: lint typecheck contracts test foundation-check

local-up:
	docker-compose up -d --wait

local-down:
	docker-compose down
