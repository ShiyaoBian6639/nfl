# NFL Big Data Bowl 2027
PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help setup data parquet audit clean-interim lint

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## create .venv and install dependencies
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@echo "ok: $$($(PY) -V)"

data: ## download the competition data (needs a Kaggle token + joined hackathon)
	./scripts/download_data.sh

parquet: ## convert raw CSVs to parquet
	$(PY) scripts/01_build_parquet.py

audit: ## re-derive every data claim from the shipped files -> reports/data_audit.md
	$(PY) scripts/00_audit_raw.py

clean-interim: ## drop the parquet mirrors (keeps data/raw)
	rm -rf data/interim/* data/processed/*

lint: ## syntax-check everything
	$(PY) -m compileall -q src scripts
