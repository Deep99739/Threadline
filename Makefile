.PHONY: setup test lint format typecheck contracts foundation-check check clean-clone-check local-up local-down migrate demo api web mcp mcp-check phase1-eval phase2-graph-eval

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

clean-clone-check:
	.venv/bin/python scripts/verify_clean_clone.py

local-up:
	docker-compose up -d --wait

local-down:
	docker-compose down

migrate:
	.venv/bin/threadline migrate

demo:
	.venv/bin/threadline demo

api:
	.venv/bin/threadline api

web:
	npm --prefix apps/web run dev

mcp:
	.venv/bin/threadline mcp --demo

mcp-check:
	.venv/bin/python scripts/verify_mcp.py

phase1-eval:
	.venv/bin/python scripts/run_phase1_eval.py

phase2-graph-eval:
	.venv/bin/python scripts/run_phase2_graph_eval.py
