# Conciliación automática de contracargos y liquidación

Prototipo funcional para el caso de negocio **"Operación Escaldada"** de Spin by OXXO
(proceso de selección, Forward Deployed Engineer). Automatiza de extremo a extremo la
conciliación matutina entre los movimientos del banco adquirente y el Core de NetPay:

- **Ingesta** del CSV del portal legacy del banco por RPA (Playwright), por API cuando el banco la libere, o por archivo manual como respaldo.
- **Conciliación determinista** con reglas explicables (cada decisión lleva la regla que la produjo).
- **Ejecución idempotente**: bloqueos de saldo por contracargo primero (hoy por la UI del Core, mañana por API), liquidaciones después (API REST con clave de idempotencia).
- **Doble control** para montos altos y acumulación anómala; **tres modos** de adopción: sombra, asistida, autónoma.
- **Triaje de excepciones asistido por IA**, fuera del camino crítico, con tokenización de datos sensibles, presupuesto y fallback determinista. Agnóstico al proveedor (Anthropic, OpenAI-compatible o ninguno).
- **Libro mayor** append-only, **gates** críticos y no críticos, evidencia en capturas, reporte matutino.
- **Gestión medible**: cada falla abre una incidencia con dueño; cada excepción se cierra registrando la decisión del analista; `conciliador tablero` genera una página con semáforos, pestañas día/semana/mes, incidencias, cola de excepciones y patrones recurrentes ([ver tablero de demostración](docs/tablero-demo.html)).
- **Observabilidad** detrás de un puerto de notificación: Slack, Telegram y correo (solo alertas), latido a un monitor tipo dead man's switch (Healthchecks/Cronitor) y Sentry opcional para errores no controlados. Cada canal se activa con su variable de entorno.

El documento de la solución (discovery, arquitectura, seguridad, IA, delivery y plan por fases) está en
[`docs/caso-spin-fde.pdf`](docs/caso-spin-fde.pdf).

## Correrlo en 3 minutos

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/) y, para el RPA, Chromium de Playwright (lo instala `make instalar`).
Alternativa sin instalar nada: Docker (`make docker-demo`).

```bash
make instalar                 # dependencias + Chromium
make mocks                    # terminal 1: portal del banco (8001) y Core NetPay (8002) simulados
make demo                     # terminal 2: corrida en modo sombra contra los mocks
MODO=autonoma make demo       # corrida autónoma: bloquea por UI (RPA) y libera por API
CORRIDA=2 make reporte        # reporte matutino de la corrida 2
```

Comandos del conciliador (`uv run conciliador --help`):

| Comando | Qué hace |
|---|---|
| `correr --fecha 2026-10-15 --modo sombra` | Corrida completa del día. Modo `sombra` no toca el Core; `asistida` deja todo pendiente de aprobación; `autonoma` ejecuta bajo umbrales. |
| `aprobar --corrida 2 --aprobador "Ana López"` | Doble control: aprueba y ejecuta lo pendiente (opcionalmente `--decision ID`). |
| `comparar --corrida 1` | Modo sombra: compara lo que el pipeline habría hecho con lo que el analista hizo en el Core (gate G-SOMBRA). |
| `reporte --corrida 2` | Reporte Markdown para Operaciones: resumen, pendientes, cola de excepciones con sugerencia, gates, evidencia. |
| `contrato-portal` | Gate G-CONTRATO-PORTAL: ¿los selectores del portal siguen vivos? |
| `corridas` | Historial. |
| `tablero --dias 30 --salida tablero.html [--json metricas.json]` | Tablero de gestión en HTML y métricas diarias en JSON para Grafana o Datadog. |
| `incidencias [--abiertas]` | Lista de incidencias con severidad y estado. |
| `resolver --incidencia 4 --por "Ana López"` / `resolver --excepcion 215 --accion ESCALAR_AL_BANCO --por "Ana López"` | Cierra una incidencia o registra la decisión del analista sobre una excepción. |

Datos de prueba: `mocks/datos_semilla.py` genera, de forma determinista por fecha, 190 transacciones en el Core
y 186 movimientos del banco con los casos feos incluidos (duplicados, montos distintos, sin match, contracargo
sobre venta ya liquidada, acumulación de contracargos, monto alto, moneda distinta, cambio de esquema del portal).

## Estructura

```
conciliador/
  dominio/      modelos, normalización del CSV y motor de reglas (puro, sin red)
  puertos.py    interfaces: fuente del banco, Core, liberador, bloqueador, asistente de triaje, notificador
  adaptadores/  banco (portal RPA | API | archivo), core (API | UI RPA | API de bloqueo), llm (nulo | anthropic | openai_compatible), notificador
  gates.py      críticos (dinero) y no críticos (calidad/privacidad)
  libro_mayor.py  SQLite append-only: corridas, decisiones, acciones (idempotencia), aprobaciones, gates, sugerencias
  privacidad.py   tokenización de identificadores y detección de PII antes de llamar al modelo
  triaje.py       arma el paquete por excepción, aplica gates del LLM, registra la sugerencia
  orquestador.py  pipeline diario, modos, ejecución ordenada, aprobación, comparación en sombra
  observabilidad.py  Sentry opcional, latido al monitor de cron, notificadores Telegram/correo/compuesto
  tablero.py      tablero de gestión (HTML estático + JSON) desde el libro mayor
  reporte.py / cli.py
scripts/poblar_demo.py  30 días de operación simulada (sombra → asistida → autónoma, con incidencias)
mocks/          portal del banco (con su API "futura") y Core NetPay (API + UI de bloqueo), FastAPI
contexto/       contexto de negocio fijo que recibe el asistente (versionado, revisado con Operaciones)
prompts/        prompts versionados
tests/          39 pruebas: reglas, gates, privacidad, orquestador con fakes, integración HTTP real y RPA real
```

## Configuración

Todo por variables de entorno (`.env.example` documenta cada una). Los secretos nunca viven en archivos en
producción: los inyecta el gestor de secretos. Cambios de adaptador sin tocar código:

| Variable | Hoy | Mañana |
|---|---|---|
| `FUENTE_BANCO` | `portal_rpa` | `api` cuando el banco libere su API (`archivo` como respaldo siempre) |
| `BLOQUEADOR_CORE` | `ui_rpa` | `api` cuando el equipo del Core exponga bloqueo por API |
| `LLM_PROVEEDOR` / `LLM_MODELO` | `nulo` (determinista) | `anthropic` + `claude-sonnet-5-5`, o `openai_compatible` + modelo interno |
| `CONCILIADOR_MODO` | `sombra` | `asistida` → `autonoma` según criterios de salida de cada fase |

## Pruebas

```bash
make test       # sin navegador
make test-e2e   # incluye RPA real contra los mocks (Chromium)
make lint
```

CI en GitHub Actions: lint, pruebas, corrida de demostración en modo sombra con reporte como artefacto, y build de la imagen.
