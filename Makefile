# Every target runs inside the locked environment (uv.lock) and never installs anything globally.
# Tests and validation that start containers check afterwards that none named evalh-* or
# inspect-evalh-* remains.

UV := uv run --frozen
# Extra arguments for the validator, e.g. VALIDATE_ARGS="--changed-since origin/main" to validate
# only the tasks a branch changed, or a list of task ids.
VALIDATE_ARGS ?=

.PHONY: sync lint test audit validate power

sync:
	uv sync --frozen

lint: sync
	uv lock --check
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) mypy

test: sync
	$(UV) pytest

# pip-audit on the exact locked versions, hashes checked, with no packages installed.
audit: sync
	@tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; \
	uv export --frozen --all-groups --no-emit-project --format requirements-txt \
		--output-file "$$tmp/requirements.txt" --quiet; \
	$(UV) pip-audit --strict --disable-pip --require-hashes \
		--requirement "$$tmp/requirements.txt"

validate: sync
	$(UV) python -m scripts.validate_tasks $(VALIDATE_ARGS)

# Writes the power and coverage table into docs/design.md 7.7 (D8).
power: sync
	$(UV) python -m scripts.power_estimate
