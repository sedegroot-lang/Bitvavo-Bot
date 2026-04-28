# Bitvavo Bot — common tasks
# Use: make <target>  (requires GNU make; on Windows install via choco install make)

PY := .venv/Scripts/python.exe
PIP := $(PY) -m pip

.PHONY: help install install-ml install-dev test test-fast lint format run dashboard agents-demo health backup clean

help:
	@echo "Available targets:"
	@echo "  install      Install core runtime deps"
	@echo "  install-ml   Install ML extras (torch, xgboost, mapie)"
	@echo "  install-dev  Install dev tools (pytest, ruff, hypothesis, pre-commit)"
	@echo "  test         Run full test suite"
	@echo "  test-fast    Run tests in parallel (requires pytest-xdist)"
	@echo "  lint         Ruff check + mypy"
	@echo "  format       Ruff format + isort"
	@echo "  run          Start trailing_bot in foreground"
	@echo "  dashboard    Start Flask dashboard on :5001"
	@echo "  agents-demo  Run LangGraph + Ollama trade-review demo"
	@echo "  health       Run AI health check"
	@echo "  backup       Run auto-backup script"
	@echo "  clean        Remove __pycache__ and .pyc files"

install:
	$(PIP) install -r requirements-core.txt

install-ml:
	$(PIP) install -r requirements-ml.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

test:
	$(PY) -m pytest tests/ -v

test-fast:
	$(PY) -m pytest tests/ -n auto -q

lint:
	$(PY) -m ruff check bot/ core/ modules/ ai/ tests/
	$(PY) -m mypy --ignore-missing-imports --no-strict-optional bot/ core/ modules/

format:
	$(PY) -m ruff format bot/ core/ modules/ ai/ tests/
	$(PY) -m ruff check --fix bot/ core/ modules/ ai/ tests/

run:
	$(PY) trailing_bot.py

dashboard:
	$(PY) tools/dashboard_flask/app.py

agents-demo:
	$(PY) tools/agents_demo.py

health:
	$(PY) scripts/helpers/ai_health_check.py

backup:
	$(PY) scripts/auto_backup.py

clean:
	powershell -Command "Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force"
	powershell -Command "Get-ChildItem -Recurse -File -Include *.pyc,*.pyo | Remove-Item -Force"
