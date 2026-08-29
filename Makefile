.PHONY: install install311 infra-up infra-down api frontend dev test lint run up down postgres-init ingest index-slice index-language index-all evaluate evaluate-fast
install:
	.venv/bin/python -m pip install -e '.[dev,ingest]'
# datasets streaming needs Python 3.11 (dill is broken on 3.14); ingestion tooling runs here.
install311:
	python3.11 -m venv .venv311
	.venv311/bin/pip install -e '.[dev,ingest]'
infra-up:
	docker compose up -d qdrant postgres
infra-down:
	docker compose stop qdrant postgres
postgres-init:
	docker compose --profile init run --rm postgres-init
api:
	.venv/bin/uvicorn voice_rag.app:app --host 127.0.0.1 --port 8000
frontend:
	cd frontend && npm run dev
dev:
	@echo "Start infrastructure with: make infra-up"
	@echo "Then use two terminals: make api  and  make frontend"
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check src tests
run:
	.venv/bin/uvicorn voice_rag.app:app --host 127.0.0.1 --port 8000
up:
	cp -n .env.example .env || true
	docker compose up --build
down:
	docker compose down
ingest:
	.venv311/bin/voice-rag-ingest --input $(INPUT) --language $(LANGUAGE) --output $(OUTPUT)
index-slice:
	.venv311/bin/voice-rag-index --all --split validation --limit 1000 --version slice-$(shell date +%Y%m%d%H%M%S) --no-semantic
index-language:
	.venv311/bin/voice-rag-index --language $(LANG) --version $(VERSION)
index-all:
	.venv311/bin/voice-rag-index --all --version $(VERSION)
# ---- Easy one-command reindex / data-feed -------------------------------------------------
# voice-rag-reindex wraps the versioned worker: auto version name -> build -> validate -> promote.
reindex:
	.venv311/bin/voice-rag-reindex --all
reindex-slice:
	.venv311/bin/voice-rag-reindex --slice
reindex-language:
	.venv311/bin/voice-rag-reindex --language $(LANG)
reindex-version:
	.venv311/bin/voice-rag-reindex --all --version $(VERSION)
index-status:
	.venv311/bin/voice-rag-reindex --status
index-promote:
	.venv311/bin/voice-rag-reindex --promote $(VERSION)
index-rollback:
	.venv311/bin/voice-rag-reindex --rollback $(VERSION)
evaluate:
	.venv/bin/voice-rag-evaluate $(QUERIES)
evaluate-fast:
	.venv/bin/voice-rag-evaluate $(QUERIES) --mode end-to-end --answer-mode fast --output results/latency-fast.json
