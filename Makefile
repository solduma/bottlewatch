.PHONY: sync ontology validate-ontology ingest refresh-prices api web research db-upgrade db-downgrade recompute test test-pg schedule unschedule install-hooks check-migrations

sync:
	uv sync

ontology:
	uv run bottlewatch-build

validate-ontology:
	uv run bottlewatch-validate

ingest:
	uv run bottlewatch-refresh

refresh-prices:
	uv run bottlewatch-refresh-prices

api:
	uv run uvicorn bottlewatch.app.main:app --reload --host 127.0.0.1 --port 8000

recompute:
	uv run bottlewatch-recompute

backfill:
	uv run bottlewatch-recompute --backfill-since 2024-01-01

web:
	cd frontend && pnpm dev

research:
	$(MAKE) ontology
	$(MAKE) validate-ontology

db-upgrade:
	uv run alembic upgrade head

db-downgrade:
	uv run alembic downgrade -1

test:
	uv run pytest \
	  --cov=bottlewatch.app \
	  --cov=bottlewatch.jobs \
	  --cov-report=term-missing \
	  --cov-fail-under=$$(uv run python -c \
	    "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['tool']['bottlewatch']['coverage_threshold'])")

# Opt-in Postgres smoke test. Requires BOTTLEWATCH_PG_TEST_URL to be
# set in the env. The 5 tests in test_postgres_smoke.py are skipped
# when this var is absent.
test-pg:
	uv run pytest src/bottlewatch/tests/test_postgres_smoke.py -v

schedule:
	chmod +x launchd/install.sh
	./launchd/install.sh

unschedule:
	chmod +x launchd/uninstall.sh
	./launchd/uninstall.sh

install-hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit

check-migrations:
	# Run alembic's autogenerate in dry-run mode and assert no diff
	# is produced. If a model changed without a corresponding migration,
	# this fails. The generated revision file (if any) is removed.
	#
	# The rev-id is timestamped so re-running the check does not
	# collide with the prior check's revision (alembic's revision
	# graph tracks rev-ids and a repeat id raises a self-loop).
	uv run alembic upgrade head
	DRIFT_TS=$$(date +%s); \
	DRIFT_ID=zzz_drift_check_$$DRIFT_TS; \
	uv run alembic revision --autogenerate -m "drift-check" --rev-id=$$DRIFT_ID; \
	generated=alembic/versions/$${DRIFT_ID}_drift_check.py; \
	if [ -f "$$generated" ]; then \
	  if grep -q "^    pass$$" "$$generated" && [ "$$(grep -c "op\." "$$generated")" = "0" ]; then \
	    echo "OK: no model-migration drift (empty migration generated)"; \
	    rm "$$generated"; \
	  else \
	    echo "ERROR: model-migration drift detected. Review $$generated and write a real migration."; \
	    exit 1; \
	  fi; \
	fi
