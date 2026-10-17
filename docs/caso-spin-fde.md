<div class="portada" markdown="1">
<div class="sup">Spin by OXXO · Caso de negocio · Forward Deployed Engineer</div>

# Operación Escaldada

<div class="sub">Automatización end-to-end de contracargos y liquidación</div>

<div class="meta">
<b>Edgar Alberto Sanabria Paredes</b> · 16 de octubre de 2026<br>
Prototipo funcional: github.com/ragdeblacks/spin-conciliacion-contracargos<br>
ragdeblack@gmail.com · linkedin.com/in/edgarsanp
</div>
</div>

[[SALTO]]

## 1. El problema y su causa raíz

Cada mañana un analista descarga el CSV del portal legacy del banco, lo cruza en Excel contra el Core de NetPay, libera liquidaciones por API y bloquea contracargos por la interfaz del Core. El volumen creció 300 % y el proceso no.

**La causa raíz no es la velocidad del analista: es que hay una persona en el camino crítico de cada transacción.** Mientras eso siga así, más volumen significa más retraso, sin importar cuánta gente se agregue.

Dos detalles del proceso definen la solución:

- **Los dos escenarios no pesan igual.** Una liquidación tarde es un comercio molesto; un contracargo sin bloquear es dinero perdido. El sistema tiene que bloquear primero y liberar después, siempre.
- **El banco va a cambiar dos veces** (portal en 3 meses, API en un año) y el Core tiene API para liberar pero no para bloquear. Todo lo que va a cambiar tiene que quedar aislado del núcleo desde el primer día.

| Métrica de éxito | Hoy | Objetivo |
|---|---|---|
| Hora en que queda liberada la liquidación del día | Cuando el analista termina | Antes de las 06:00 |
| Movimientos conciliados sin intervención humana | 0 % | Más del 95 % |
| Tiempo entre reporte del contracargo y bloqueo del saldo | Horas | Menos de 15 minutos desde la corrida |
| Liquidaciones duplicadas o liberadas a comercios con contracargo | Sin trazabilidad | Cero, con evidencia auditable |

Impacto esperado, con supuestos a validar en discovery: tres analistas pasan de la mañana completa a menos de 30 minutos de excepciones; cada contracargo bloqueado a tiempo es una pérdida directa evitada; y cualquier reclamo de un comercio se responde en minutos con el registro de auditoría.

## 2. La solución

Un pipeline diario, determinista y auditable, que saca al humano del camino feliz y lo deja donde aporta: en las excepciones y en las decisiones de monto alto.

**Tres principios.** El dinero lo mueven reglas deterministas con idempotencia y auditoría; ningún modelo decide liberar o bloquear. La IA acelera al humano en las excepciones, fuera del camino crítico. Todo lo que va a cambiar está detrás de un puerto: cambiarlo es configuración, no reescritura.

<figure>
<img src="img/arquitectura.svg" alt="Arquitectura">
<figcaption>Lo que va a cambiar (portal, API del banco, UI del Core, proveedor de IA) vive en adaptadores fuera del núcleo.</figcaption>
</figure>

| Paso del flujo diario (05:00) | Control | Si falla |
|---|---|---|
| Arranque: credenciales desde el gestor de secretos, Core vivo | G-SECRETOS, G-CORE-VIVO | No se toca nada; alerta |
| Ingesta del CSV por el adaptador activo: portal (RPA), API del banco, o archivo manual | G-ESQUEMA, G-VOLUMEN | Se detiene; Operaciones sigue con carga manual |
| Conciliación con reglas explicables: LIQUIDAR, BLOQUEAR, EXCEPCIÓN con motivo, YA PROCESADO | G-DUPLICADO | |
| Bloqueos por contracargo primero (hoy por la UI del Core, con captura de evidencia) | G-UMBRAL: montos altos y acumulación anómala van a doble control | Acción FALLIDA con rastro |
| Verificación de orden | G-ORDEN: ninguna liquidación arranca con un bloqueo sin intentar | No arrancan liquidaciones |
| Liquidaciones por API con clave de idempotencia | G-UMBRAL | Acción FALLIDA con rastro |
| Triaje de excepciones con el asistente de IA | G-LLM-PII, G-LLM-PRESUPUESTO (no críticos) | El analista trabaja sin sugerencia |
| Cierre, reporte matutino y alertas a Slack | G-CIERRE, G-DERIVA, G-LATENCIA | Corrida marcada para revisión |

**Tres modos de operación**, seleccionables por configuración y registrados en cada corrida: *sombra* (decide y registra, no toca el Core, se compara después con lo que hizo el analista), *asistida* (todo queda pendiente y el supervisor aprueba en lote) y *autónoma* (ejecuta bajo umbrales; el humano solo ve excepciones y doble control).

## 3. Protección del dinero

- **Idempotencia en toda acción.** Cada liquidación y bloqueo lleva una clave única derivada del movimiento, enviada al Core y guardada en el libro mayor. Repetir una corrida o reiniciar el proceso no ejecuta nada dos veces; una prueba lo demuestra contra un Core que devuelve estados atrasados.
- **Rastro antes y después.** El libro mayor, solo de inserción, escribe INTENTADA antes de llamar al Core y CONFIRMADA o FALLIDA después. Si el proceso muere a la mitad, se sabe exactamente qué quedó en el aire. Cada decisión guarda la regla que la produjo, la respuesta del Core, la evidencia y quién aprobó.
- **Contracargos primero.** Un gate impide que arranque cualquier liquidación mientras exista un bloqueo sin intentar. Las ventas de un comercio que hoy trae contracargo se retienen para revisión humana (regla configurable).
- **Doble control.** Montos sobre el umbral y comercios con más de tres contracargos en el día no se ejecutan solos: los aprueba un supervisor con su nombre registrado.
- **Límites de entrada.** Un archivo vacío, con más del triple del promedio histórico o con columnas distintas detiene la corrida antes de actuar. Dinero siempre en centavos enteros.
- **Cierre.** Al terminar se verifica que toda acción tenga estado final consistente; cualquier diferencia es alerta.

**Acceso y auditoría.** Credenciales en el gestor de secretos de la plataforma, inyectadas al contenedor; el sistema rechaza arrancar con valores ausentes o placeholder. Usuario de servicio dedicado, separado de los analistas, para que la auditoría del Core distinga al robot de la persona. CSV y capturas cifrados en reposo con retención acordada con Riesgos. Contenedor sin privilegios.

**Continuidad.** Si falla el portal, Operaciones sube el CSV a mano y el pipeline sigue. Si falla el Core, se detiene sin tocar nada. Si a las 05:30 no hay corrida exitosa, suena la alarma aunque nada haya fallado. Un supervisor puede parar todo con un comando, sin despliegue.

## 4. IA con criterio

| Determinista, siempre | Modelo de lenguaje, hoy | Nunca un modelo |
|---|---|---|
| Ingesta, validación, normalización, conciliación, clasificación, ejecución, idempotencia, umbrales, cierre, auditoría | Triaje de excepciones: causa probable y acción sugerida de un catálogo cerrado, con confianza y explicación de tres frases. Extracción de reglas del Excel del analista en discovery. Resumen matutino | Decidir liberar o bloquear. Llamar al Core. Cambiar reglas en producción sin humano |

El triaje convierte la cola de excepciones de "lista de errores" a "lista de decisiones de diez segundos". Modelo de referencia: Claude Sonnet 5.5; con 100 excepciones diarias cuesta centavos al día. Más adelante, cuando una excepción se repita con la misma resolución humana, el modelo propone la regla y se promueve a código tras revisión y pruebas.

- **Agnóstico al proveedor.** El modelo va detrás de un puerto con tres adaptadores: Anthropic, OpenAI-compatible (incluido un modelo abierto dentro del perímetro de Spin) y nulo (sugerencia determinista por motivo). Cambiar de proveedor o de modelo es una variable de entorno. Prompts y contexto de negocio versionados en el repositorio; la salida se valida contra un esquema y, si no cumple, entra el fallback. Un set de evaluación con excepciones reales resueltas por el analista decide si un cambio de modelo se despliega.
- **Contexto en capas.** Una capa fija y cacheada (glosario, reglas, catálogo de motivos y acciones, lo que nunca hace) mantenida con Operaciones; una capa por excepción armada por código (movimiento, candidatos cercanos del Core, reglas que fallaron). El modelo nunca recibe el CSV ni consulta el Core.
- **Datos sensibles.** Antes de salir del proceso, comercio y referencia se sustituyen por tokens opacos y la tarjeta desaparece; un gate busca patrones de tarjeta, CLABE, CURP y correo y bloquea la llamada si encuentra alguno. Presupuesto de llamadas por corrida y de tokens por día; al excederse, fallback. Cada sugerencia queda registrada con la decisión final del humano.

## 5. Continuidad y transición API-First

La forma de hacer cualquier transición es la misma: adaptador nuevo en sombra junto al viejo, comparación, cambio de flag, retiro del viejo.

| Cambio | Cuándo | Qué se toca | Qué no |
|---|---|---|---|
| El banco cambia su portal | 3 meses | Selectores en configuración o el adaptador del portal. Un test de contrato diario lo detecta el primer día; carga manual mientras tanto | Reglas, libro mayor, ejecución |
| El banco libera su API | Próximo año | Adaptador API (ya existe en el prototipo contra una API simulada); sombra contra el adaptador del portal; cambio de flag | Todo lo demás |
| El Core expone API de bloqueo | A negociar; prioridad uno con el equipo del Core | Cambio de flag al adaptador API (ya existe); se elimina el robot sobre la UI | Todo lo demás |
| Retiro o cambio de modelo de IA | Cuando ocurra | Variable de modelo o proveedor, previa evaluación | Todo lo demás |

## 6. Puesta en producción

**Empaquetado.** Un contenedor con la imagen oficial de Playwright, configurado solo por variables de entorno, idéntico en desarrollo (contra los servicios simulados del repositorio), QA (Core de pruebas y CSV real anonimizado, en sombra) y producción. Libro mayor en Postgres; evidencia en almacenamiento de objetos cifrado.

**Ejecución.** Tarea programada a las 05:00 (CronJob o tarea del servicio de contenedores de Spin), reintento a las 05:20 y alerta por ausencia a las 05:30. Es un proceso por lotes con estado en base de datos: se repite o reanuda sin duplicar acciones. Operaciones tiene comandos propios para correr, aprobar, comparar y generar el reporte.

**CI/CD.** En cada cambio: lint, pruebas unitarias e integración, prueba de RPA real con navegador, corrida de demostración y construcción de la imagen (el repositorio ya lo trae). Despliegue por promoción de la misma imagen: automático a QA, a producción con aprobación. Cambios de reglas y umbrales siguen el mismo camino que el código.

**Observabilidad.** Logs estructurados por corrida, métricas por resultado y duración, alertas a Slack (corrida detenida, acciones fallidas, deriva de excepciones, ausencia) y tablero con las métricas de la sección 1.

| Situación | El sistema | Operaciones |
|---|---|---|
| El portal no responde o cambió | Detiene la corrida; alerta | Sube el CSV a mano y continúa; Tecnología ajusta selectores |
| El Core no responde | Detiene sin tocar nada; reintento | Escala al equipo del Core; la corrida se repite sin duplicar |
| Acciones fallidas al cierre | Las lista en el reporte | Revisa, vuelve a correr o resuelve a mano y lo registra |
| El modelo de IA no responde | Fallback determinista | Nada |
| Hay que detener todo | Modo sombra o tarea suspendida | Un comando del supervisor |

| Fase | Semanas | Qué cambia | Criterio de salida |
|---|---|---|---|
| Discovery y MVP | 1 a 2 | Reglas extraídas y validadas con el analista; adaptador contra el portal real; despliegue en QA | Reglas aprobadas por Operaciones |
| Sombra | 3 a 5 | Corre cada mañana en producción sin tocar dinero; comparación diaria contra el analista | Coincidencia mayor al 98 % durante 3 semanas; cero falsos LIQUIDAR |
| Asistida | 6 a 8 | Ejecución real tras aprobación en lote; asistente con proveedor real | Cero fallas sin explicación en 2 semanas; aprobación en menos de 20 minutos |
| Autónoma | 9 a 12 | Ejecuta bajo umbrales; humano solo en excepciones y doble control | Métricas de la sección 1 cumplidas 2 semanas seguidas |
| Cambio de portal y API del banco | Mes 3 y cuando se libere | Adaptador nuevo en sombra; cambio de flag | Coincidencia entre adaptadores mayor al 99.5 % |

**Riesgos principales.** Las reglas del analista son más complejas de lo que parecen: discovery con el analista y fase sombra larga. El Core rechaza acciones por reglas internas desconocidas: ya ocurrió en el prototipo y cada rechazo se convierte en regla explícita. Operaciones no confía en el sistema: sombra con comparación visible y asistida con la última palabra humana. El robot sobre la UI del Core es frágil: evidencia por acción y la API de bloqueo como primera petición al equipo del Core.

## 7. Prototipo y resultados

El repositorio contiene un sistema que corre de punta a punta con un comando: portal del banco y Core de NetPay simulados (incluida la API "futura" del banco, la API de bloqueo detrás de un flag y un modo que simula el cambio de portal), el conciliador completo con los adaptadores descritos, datos de prueba con todos los casos feos (duplicados, montos distintos, contracargos sobre ventas ya liquidadas, acumulación anómala, monto alto, cambio de esquema), 31 pruebas automatizadas, Docker Compose y CI.

| Corrida real contra los servicios simulados | Resultado |
|---|---|
| Sombra, 0.9 s | 186 movimientos: 143 a liquidar, 11 a bloquear, 30 excepciones con sugerencia, 2 ya procesados. No tocó el Core |
| Autónoma, 9.6 s | 154 acciones: 10 bloqueos por la UI del Core con captura de evidencia, 141 liquidaciones por API con idempotencia. 2 decisiones en doble control, aprobadas por un supervisor y ejecutadas |
| Comparación sombra vs. Core | 100 % de coincidencia (154 de 154) |

**Lo que no cubre, a propósito.** Corre contra servicios simulados; los adaptadores son lo único que cambia. El libro mayor es SQLite, en producción Postgres con la misma interfaz. Los adaptadores de IA están implementados con validación y fallback, pero las pruebas usan el adaptador nulo para no depender de una llave ni gastar en CI.

```
make instalar && make mocks      # dependencias, navegador y servicios simulados
make demo                        # corrida en modo sombra
MODO=autonoma make demo          # corrida autónoma
```
