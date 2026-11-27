# Every target runs inside the locked environment (uv.lock) and never installs anything globally.
# Tests and validation that start containers check afterwards that none named evalh-* or
# inspect-evalh-* remains.

UV := uv run --frozen
# Extra arguments for the validator, e.g. VALIDATE_ARGS="--changed-since origin/main" to validate
# only the tasks a branch changed, or a list of task ids.
VALIDATE_ARGS ?=

.PHONY: sync lint test audit validate power timing estimate eval report demo

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

# The oracle on one task per language, timed, logged to results/timing/ (Phase 5).
timing: sync
	$(UV) python -m harness.agents.run timing

# Attempts, containers at once and expected wall time of the full run, from the timing log (R1,
# D22). Starts nothing.
estimate: sync
	$(UV) python -m scripts.estimate_run

# The full scripted run, logged to results/logs/ (D19). Needs the owner's go-ahead on the
# `make estimate` output first.
eval: sync
	$(UV) python -m harness.agents.run eval

# Rebuilds the report in results/reports/ from the committed logs alone (R2, R13).
report: sync
	$(UV) python -m stats.report

# Two RL episodes on one task, an honest scripted agent and a cheater, with their rewards (P6-3).
demo: sync
	$(UV) python -m harness.agents.demo_episode
