.PHONY: instalar test test-e2e lint mocks demo reporte docker-demo tablero limpiar

instalar:          ## dependencias + Chromium de Playwright
	uv sync && uv run playwright install chromium

test:              ## pruebas unitarias e integración HTTP (sin navegador)
	uv run pytest -m "not e2e"

test-e2e:          ## todo, incluido RPA real con Chromium
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

mocks:             ## levanta portal del banco (8001) y Core (8002) en local
	uv run uvicorn mocks.banco_portal.app:app --port 8001 & \
	uv run uvicorn mocks.core_netpay.app:app --port 8002 & \
	wait

FECHA ?= 2026-10-15
demo:              ## corrida completa en local contra los mocks (requiere `make mocks` en otra terminal)
	set -a && . ./.env.example && set +a && uv run conciliador correr --fecha $(FECHA) --modo $${MODO:-sombra}

reporte:
	set -a && . ./.env.example && set +a && uv run conciliador reporte --corrida $(CORRIDA)

docker-demo:       ## lo mismo pero todo en contenedores
	docker compose up -d banco-portal core-netpay
	docker compose run --rm conciliador correr --fecha $(FECHA) --modo $${MODO:-sombra}

tablero:           ## 30 días de operación simulada y el tablero de gestión (docs/tablero-demo.html)
	uv run python scripts/poblar_demo.py
	LIBRO_MAYOR_RUTA=datos/libro_mayor_demo.sqlite CORE_API_TOKEN=demo uv run conciliador tablero --dias 30 --salida docs/tablero-demo.html --json docs/metricas-demo.json

limpiar:
	rm -rf datos/*.sqlite evidencia/*
