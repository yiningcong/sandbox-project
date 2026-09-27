# Exact Python used for the virtualenv. Installed on demand via pyenv
# (brew's python@3.11 can't pin a specific patch version like 3.11.8).
PYTHON_VERSION ?= 3.11.8
VENV           ?= .venv
PY             := $(VENV)/bin/python
PYENV_PYTHON   := $(HOME)/.pyenv/versions/$(PYTHON_VERSION)/bin/python
DEPS_STAMP     := $(VENV)/.deps-installed
DOCKER_STAMP   := $(VENV)/.docker-deps-installed

.PHONY: setup sample-data run ccu dashboard docker-setup seed test clean

## Default: create the venv with the pinned Python and install dependencies.
setup: $(DEPS_STAMP)

# The pinned interpreter, installed on demand through pyenv.
$(PYENV_PYTHON):
	@if [ ! -x "$@" ]; then \
		echo ">> Installing Python $(PYTHON_VERSION) via pyenv (one-time, may take a few minutes)"; \
		pyenv install -s $(PYTHON_VERSION); \
	fi

$(PY): $(PYENV_PYTHON)
	$(PYENV_PYTHON) -m venv $(VENV)

$(DEPS_STAMP): $(PY) pyproject.toml
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	@touch $(DEPS_STAMP)

## Generate the deterministic sample dataset (data/sample/).
sample-data: $(DEPS_STAMP)
	$(PY) -m src.sample_data

## Run the full DAU pipeline on the sample data (local mock mode, full ~3y range).
run: $(DEPS_STAMP)
	$(PY) -m src.pipeline run --start-date 2023-01-01

## Run the hourly-CCU demo query against data/sample/detailed_ccu.csv.
ccu: $(DEPS_STAMP)
	$(PY) -m src.pipeline ccu

## Build the dashboard dataset + HTML (requires `make sample-data` and `make run`).
dashboard: $(DEPS_STAMP)
	$(PY) dashboard/build_data.py

## Install the optional deps (psycopg, elasticsearch) for the real-service adapters.
docker-setup: $(DOCKER_STAMP)

$(DOCKER_STAMP): $(DEPS_STAMP) pyproject.toml
	$(PY) -m pip install -e ".[docker]"
	@touch $(DOCKER_STAMP)

## Seed PostgreSQL/Elasticsearch from the sample data (requires `docker compose up -d`
## and POSTGRES_HOST / ELASTICSEARCH_URL exported — see src/seed.py).
seed: $(DOCKER_STAMP)
	$(PY) -m src.seed

## Run the test suite.
test: $(DEPS_STAMP)
	$(PY) -m pytest

## Remove generated data (regenerate with `make sample-data`).
clean:
	rm -f data/raw/* data/processed/* data/sample/*
	touch data/raw/.gitkeep data/processed/.gitkeep data/sample/.gitkeep
