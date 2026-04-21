.PHONY: dev down import-workflows test logs clean

# ── Local dev ─────────────────────────────────────────────────────────────────
dev:
	@cp -n .env.example .env 2>/dev/null || true
	docker compose up --build -d
	@echo ""
	@echo "  n8n      → http://localhost:5678"
	@echo "  FastAPI  → http://localhost:8000/docs"
	@echo "  Postgres → localhost:5432"

down:
	docker compose down

logs:
	docker compose logs -f

# ── Import n8n workflows ──────────────────────────────────────────────────────
import-workflows:
	@echo "Waiting for n8n to be ready..."
	@until curl -sf http://localhost:5678/healthz > /dev/null; do sleep 2; done
	@for f in workflows/*.json; do \
		echo "Importing $$f ..."; \
		curl -s -X POST http://localhost:5678/api/v1/workflows \
			-u $${N8N_USER:-admin}:$${N8N_PASSWORD:-changeme} \
			-H "Content-Type: application/json" \
			-d @$$f | python3 -m json.tool; \
	done
	@echo "Done. Activate workflows in the n8n UI."

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	docker compose exec fastapi python -m pytest tests/ -v

# ── Clean everything ─────────────────────────────────────────────────────────
clean:
	docker compose down -v --remove-orphans
	@echo "Volumes and containers removed."
