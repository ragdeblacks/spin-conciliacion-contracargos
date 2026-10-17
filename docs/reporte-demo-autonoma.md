# Conciliación 2026-10-15 — corrida 2

- Estado: **CERRADA** · modo **autonoma** · fuente **portal_rpa**
- Inicio 2026-10-17T01:08:57+00:00 · fin 2026-10-17T01:09:07+00:00

## Resumen

| Resultado | Movimientos | Monto |
|---|---:|---:|
| Liquidar | 143 | $435,811.46 MXN |
| Bloquear (contracargos) | 11 | $30,081.16 MXN |
| Excepciones para revisión | 30 | $102,606.07 MXN |
| Ya procesados | 2 | $1,818.80 MXN |
| **Total** | **186** | |

## Estado de ejecución

- EJECUTADA: 154

## Cola de excepciones (con sugerencia del asistente)

| ID | Referencia | Tipo | Monto | Motivo | Causa probable | Acción sugerida | Conf. |
|---|---|---|---:|---|---|---|---:|
| 215 | SPN101577777 | CONTRACARGO | $450.00 MXN | CONTRACARGO_SIN_MATCH | Contracargo sobre una venta que el Core no reconoce | ESCALAR_AL_BANCO | 60% |
| 356 | SPN101500013 | VENTA | $2,049.41 MXN | COMERCIO_BLOQUEADO | Venta de un comercio con saldo bloqueado | BLOQUEAR_MANUAL | 60% |
| 320 | SPN101500101 | VENTA | $7,865.64 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 338 | SPN101500007 | VENTA | $7,695.59 MXN | DUPLICADO_EN_ARCHIVO | Misma referencia repetida en el archivo del banco | IGNORAR_DUPLICADO | 90% |
| 315 | SPN101500084 | VENTA | $7,387.95 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 319 | SPN101500149 | VENTA | $6,781.44 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 354 | SPN101500012 | VENTA | $5,935.24 MXN | MONEDA_DISTINTA | Moneda del banco distinta a la del Core | ESCALAR_AL_BANCO | 70% |
| 304 | SPN101500002 | VENTA | $5,553.93 MXN | MONTO_DIFERENTE | Diferencia de monto entre banco y Core (comisión, propina o captura) | REVISAR_CON_COMERCIO | 50% |
| 218 | SPN101500049 | VENTA | $5,253.69 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 345 | SPN101500006 | VENTA | $5,051.08 MXN | DUPLICADO_EN_ARCHIVO | Misma referencia repetida en el archivo del banco | IGNORAR_DUPLICADO | 90% |
| 359 | SPN101500010 | VENTA | $5,006.02 MXN | FECHA_FUERA_DE_RANGO | Desfase de fecha mayor a la tolerancia | LIQUIDAR_MANUAL | 50% |
| 231 | SPN101500004 | VENTA | $4,928.25 MXN | MONTO_DIFERENTE | Diferencia de monto entre banco y Core (comisión, propina o captura) | REVISAR_CON_COMERCIO | 50% |
| 358 | SPN101500181 | VENTA | $4,645.68 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 253 | SPN101500093 | VENTA | $4,622.21 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 267 | SPN101500119 | VENTA | $4,537.44 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 343 | SPN101500153 | VENTA | $4,199.61 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 329 | SPN101500176 | VENTA | $4,105.16 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 257 | SPN101500072 | VENTA | $4,093.35 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 228 | SPN101500163 | VENTA | $3,936.32 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 248 | SPN101500108 | VENTA | $3,346.26 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 234 | SPN101X00005 | VENTA | $1,249.65 MXN | SIN_MATCH | Hay transacciones parecidas en el Core: posible referencia truncada | LIQUIDAR_MANUAL | 60% |
| 191 | SPN101500141 | VENTA | $795.65 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 233 | SPN101500156 | VENTA | $728.34 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 209 | SPN101500110 | VENTA | $651.55 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 260 | SPN101500003 | VENTA | $502.36 MXN | MONTO_DIFERENTE | Diferencia de monto entre banco y Core (comisión, propina o captura) | REVISAR_CON_COMERCIO | 50% |
| 366 | SPN101500121 | VENTA | $470.21 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 370 | SPN101500167 | VENTA | $255.92 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 297 | SPN101500038 | VENTA | $236.43 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 309 | SPN101500103 | VENTA | $148.24 MXN | CONTRACARGO_MISMO_DIA | Venta de un comercio que hoy recibió contracargo | REVISAR_CON_COMERCIO | 60% |
| 372 | ZZZ101599999 | VENTA | $123.45 MXN | SIN_MATCH | La venta no existe en el Core con esa referencia | ESPERAR_SIGUIENTE_CORTE | 50% |

## Gates

| Gate | Resultado | Crítico | Detalle |
|---|---|---|---|
| G-FECHA | ✅ | sí | fecha de operación anterior a hoy |
| G-SECRETOS | ✅ | sí | 5 credenciales cargadas desde el entorno |
| G-CORE-VIVO | ✅ | sí | Core responde |
| G-ESQUEMA | ✅ | sí | 8 columnas válidas |
| G-VOLUMEN | ✅ | sí | 186 movimientos (promedio histórico 186) |
| G-DUPLICADO | ✅ | sí | 0 acciones ya ejecutadas en corridas previas, omitidas |
| G-ORDEN | ✅ | sí | todos los bloqueos intentados antes de la primera liquidación |
| G-CIERRE | ✅ | sí | 154 acciones con estado final consistente (modo autonoma) |
| G-DERIVA | ✅ | no | tasa de excepciones 16.1% (histórico 16.1%) |
| G-LATENCIA | ❌ | no | corrida terminó 19:09, límite 06:00 |
| G-CIERRE | ✅ | sí | 2 acciones con estado final consistente (modo aprobacion) |

Evidencia adjunta: 11 capturas en `evidencia/`.
