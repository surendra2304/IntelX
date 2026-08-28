.PHONY: setup dev test eval lint format migrate seed-demo worker verify-audit run-diary-check clean

setup:
	python -m pip install -e ".[dev]"

migrate:
	python -m alembic upgrade head

seed-demo:
	intelx seed-demo

worker:
	intelx worker

verify-audit:
	intelx verify-audit

dev:
	python -m uvicorn intelx.app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	python -m pytest -v tests/

eval:
	python -m evals.run

lint:
	python -m ruff check .
	python -m ruff format --check .

format:
	python -m ruff format .
	python -m ruff check --fix .

run-diary-check:
	python scripts/verify_diary.py

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.pytest_cache')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.ruff_cache')]"
