.PHONY: up down test smoke bootstrap sync-plan gate
up:
	docker compose up --build -d
down:
	docker compose down
test:
	python -m pytest -q
smoke:
	python scripts/smoke_demo.py
bootstrap:
	bash scripts/bootstrap.sh
sync-plan:
	bash scripts/sync-plan.sh
gate:
	bash scripts/gate.sh M0
