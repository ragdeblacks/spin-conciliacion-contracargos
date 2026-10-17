# Conciliación automática de contracargos y liquidación

Prototipo funcional para el caso de negocio **"Operación Escaldada"** de Spin by OXXO
(proceso de selección, Forward Deployed Engineer). Automatiza de extremo a extremo la
conciliación matutina entre los movimientos del banco adquirente y el Core de NetPay:

- **Ingesta** del CSV del portal legacy del banco por RPA (Playwright), por API cuando el banco la libere, o por archivo manual como respaldo.
- **Conciliación determinista** con reglas explicables (cada decisión lleva la regla que la produjo).
- **Ejecución idempotente**: por cada contracargo se retiene el importe en disputa en el saldo del comercio (hoy por la UI del Core, mañana por API) y después se liberan las liquidaciones (API REST con clave de idempotencia). El comercio sigue operando; suspenderlo es una decisión de Riesgos que el sistema solo propone cuando supera umbrales configurables (contracargos por día o ratio en 30 días, al estilo de Visa VAMP y Mastercard ECM).
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
tests/          40 pruebas: reglas, gates, privacidad, orquestador con fakes, integración HTTP real y RPA real
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

## Despliegue

El conciliador es un proceso por lotes dentro de un contenedor. No necesita servidor web ni orquestador: una tarea
programada lo ejecuta cada mañana y el estado vive en el libro mayor. Estos son los pasos, en orden.

### 1. Construir y publicar la imagen

```bash
docker build -t registry.spin.internal/conciliador:1.0.0 .
docker push registry.spin.internal/conciliador:1.0.0
```

La imagen parte de la oficial de Playwright (trae Chromium), corre con el usuario `ubuntu` (uid 1000, sin privilegios)
y recibe toda la configuración por variables de entorno. CI construye la misma imagen en cada cambio; a producción se
promueve por tag, nunca se construye aparte.

### 2. Preparar el entorno de producción

| Qué | Cómo |
|---|---|
| Secretos (portal del banco, Core, Slack, latido, llave del modelo) | En el gestor de secretos de la plataforma, inyectados como variables de entorno. Nunca en archivos del repo. El gate G-SECRETOS impide arrancar si faltan o traen valores de relleno |
| Usuario de servicio | Uno para el portal del banco y otro para la UI del Core, distintos de los analistas, con permisos mínimos |
| Persistencia | Un volumen para `/app/datos` (libro mayor SQLite) y otro para `/app/evidencia` (CSV y capturas), con respaldo diario. Pasar el libro mayor a Postgres es el siguiente paso cuando haya más de un ejecutor; la interfaz `LibroMayor` es la misma |
| Red | Salida HTTPS al portal del banco, al Core y, si aplica, al proveedor del modelo, a Slack y al monitor de latido |
| Observabilidad | `SLACK_WEBHOOK_URL`, `LATIDO_URL` (Healthchecks o Cronitor, alerta si no hay corrida a las 05:30), y opcionalmente `CORREO_*`, `TELEGRAM_*`, `SENTRY_DSN` |

### 3. Programar la corrida

Dos opciones listas en `deploy/`:

- **Kubernetes:** [`deploy/cronjob.yaml`](deploy/cronjob.yaml) con Secret, ConfigMap, volumen y CronJob a las 05:00 (lunes a sábado), `concurrencyPolicy: Forbid`, un reintento automático y usuario sin privilegios. Ajusta imagen, URLs y secretos y aplica con `kubectl apply -f deploy/cronjob.yaml`.
- **Host con Docker y cron:** [`deploy/crontab.example`](deploy/crontab.example) y [`deploy/conciliar.sh`](deploy/conciliar.sh). Corrida a las 05:00, reintento a las 05:20 (es idempotente, no duplica) y tablero a las 05:30.

### 4. Conectar a los sistemas reales

1. **Portal del banco.** Apunta `BANCO_PORTAL_URL` al portal real y ajusta los selectores en `conciliador/adaptadores/banco.py` (`SELECTORES_PORTAL_V1`) a los campos de login y descarga reales. Verifica con `conciliador contrato-portal`. Si el banco ofrece SFTP o correo, conviene más un adaptador de archivo que el robot.
2. **Core NetPay.** `CORE_URL` y `CORE_API_TOKEN` para leer transacciones y liberar liquidaciones; los nombres de ruta y campos están en `conciliador/adaptadores/core.py` y se ajustan al contrato real de la API. `CORE_UI_USUARIO`/`CORE_UI_CLAVE` y `SELECTORES_CORE_UI_V1` para el bloqueo por interfaz.
3. **Reglas y tolerancias** acordadas con Operaciones: `TOLERANCIA_MONTO_CENTAVOS`, `TOLERANCIA_DIAS`, `UMBRAL_APROBACION_CENTAVOS`, `MAX_CONTRACARGOS_COMERCIO_DIA`.
4. **Primera corrida en QA** contra el Core de pruebas con un CSV real anonimizado: `conciliador correr --fecha AAAA-MM-DD --modo sombra`.

### 5. Fases de adopción

| Fase | `CONCILIADOR_MODO` | Qué hace Operaciones cada mañana |
|---|---|---|
| Sombra (3 semanas) | `sombra` | Su proceso de siempre; después `conciliador comparar --corrida N` para ver la coincidencia |
| Asistida | `asistida` | Revisa el reporte y aprueba en lote: `conciliador aprobar --corrida N --aprobador "Nombre"` |
| Autónoma | `autonoma` | Solo excepciones y doble control; el tablero y las incidencias marcan qué atender |

Cambiar de fase es cambiar una variable; no hay despliegue.

### 6. Operación diaria

```bash
conciliador reporte --corrida N                 # reporte matutino en Markdown
conciliador incidencias --abiertas              # qué hay que atender y desde cuándo
conciliador resolver --incidencia 4 --por "Ana López" --nota "Se repitió la corrida tras recuperar el Core"
conciliador resolver --excepcion 215 --accion ESCALAR_AL_BANCO --por "Ana López"
conciliador tablero --dias 30 --salida /srv/tablero/index.html --json /srv/tablero/metricas.json
```

El tablero es una página estática: se sirve desde cualquier servidor de archivos o se abre directo. El JSON alimenta Grafana o Datadog.

### 7. Actualizar y revertir

Una versión nueva es una imagen nueva con otro tag. El libro mayor es compatible hacia atrás (solo se agregan tablas y
columnas), así que revertir es volver al tag anterior. Para detener todo sin desplegar: `CONCILIADOR_MODO=sombra` o
suspender el CronJob (`kubectl patch cronjob conciliacion-diaria -p '{"spec":{"suspend":true}}'`).

### Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `G-SECRETOS` detiene la corrida | Falta una variable o trae un valor de relleno | Revisar el Secret; la lista exacta la imprime el gate |
| `G-ESQUEMA` o `G-CONTRATO-PORTAL` fallan | El banco cambió el portal o el archivo | Ajustar selectores o columnas; mientras, `FUENTE_BANCO=archivo` con `BANCO_CSV_MANUAL=/app/datos/manual.csv` |
| `G-CORE-VIVO` falla | El Core no responde | Nada se tocó; repetir la corrida cuando vuelva (idempotente) |
| Acciones `FALLIDA` en el reporte | Rechazo del Core (422) o fallo de red | Revisar la respuesta guardada en `acciones`; repetir la corrida o resolver a mano y cerrar la incidencia |
| El contenedor no puede escribir en `/app/datos` | El volumen no es escribible por el uid 1000 | `chown -R 1000:1000` del directorio en el host, o `fsGroup: 1000` en Kubernetes |
| El robot falla en Chromium | Falta el navegador (solo fuera de la imagen oficial) | `playwright install --with-deps chromium` |

## Pruebas

```bash
make test       # sin navegador
make test-e2e   # incluye RPA real contra los mocks (Chromium)
make lint
```

CI en GitHub Actions: lint, pruebas, corrida de demostración en modo sombra con reporte como artefacto, y build de la imagen.
