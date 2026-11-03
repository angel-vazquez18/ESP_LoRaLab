.PHONY: help setup serve frontend-dev test lint frontend contracts contracts-check repo-check check firmware-build diagnostic-build

help:
	@echo "setup serve frontend-dev test lint frontend contracts contracts-check repo-check check firmware-build diagnostic-build"

setup:
	uv sync --project testbed --locked
	npm --prefix testbed/frontend ci

serve:
	cd testbed && uv run lora-testbed serve

frontend-dev:
	npm --prefix testbed/frontend run dev

test:
	uv run --project testbed pytest testbed/tests

lint:
	uv run --project testbed ruff check testbed/src testbed/tests scripts

frontend:
	npm --prefix testbed/frontend run build

contracts:
	uv run --project testbed python scripts/generate_contract.py

contracts-check:
	uv run --project testbed python scripts/generate_contract.py --check

repo-check:
	python3 scripts/check_repository.py

check: test lint frontend contracts-check repo-check

firmware-build:
	idf.py -C firmware/lora_node build

diagnostic-build:
	idf.py -C firmware/diagnostic build
