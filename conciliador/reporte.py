"""Reporte matutino para el líder de Operaciones: qué se hizo, qué quedó pendiente, qué revisar."""

from __future__ import annotations

from collections import defaultdict

from .dominio.modelos import centavos_a_texto
from .libro_mayor import LibroMayor


def reporte_markdown(libro: LibroMayor, corrida_id: int) -> str:
    c = libro.corrida(corrida_id)
    decisiones = libro.decisiones_de(corrida_id)
    gates = libro.gates_de(corrida_id)
    sugerencias = {s["decision_id"]: s for s in libro.sugerencias_de(corrida_id)}
    acciones = {a["decision_id"]: a for a in libro.acciones_de(corrida_id)}
    res = c["resumen"]

    por_accion = defaultdict(list)
    for d in decisiones:
        por_accion[d["accion"]].append(d)

    def monto_total(lista):
        return centavos_a_texto(sum(d["monto_centavos"] for d in lista))

    lineas = [
        f"# Conciliación {c['fecha_operacion']} — corrida {corrida_id}",
        "",
        f"- Estado: **{c['estado']}** · modo **{c['modo']}** · fuente **{c['fuente']}**",
        f"- Inicio {c['inicio']} · fin {c['fin'] or '-'}",
        "",
        "## Resumen",
        "",
        "| Resultado | Movimientos | Monto |",
        "|---|---:|---:|",
        f"| Liquidar | {len(por_accion['LIQUIDAR'])} | {monto_total(por_accion['LIQUIDAR'])} |",
        f"| Bloquear (contracargos) | {len(por_accion['BLOQUEAR'])} | {monto_total(por_accion['BLOQUEAR'])} |",
        f"| Excepciones para revisión | {len(por_accion['EXCEPCION'])} | {monto_total(por_accion['EXCEPCION'])} |",
        f"| Ya procesados | {len(por_accion['YA_PROCESADO'])} | {monto_total(por_accion['YA_PROCESADO'])} |",
        f"| **Total** | **{res.get('TOTAL', len(decisiones))}** | |",
        "",
        "## Estado de ejecución",
        "",
    ]
    estados = defaultdict(int)
    for d in decisiones:
        if d["accion"] in ("LIQUIDAR", "BLOQUEAR"):
            estados[d["estado_ejecucion"]] += 1
    for k, v in sorted(estados.items()):
        lineas.append(f"- {k}: {v}")

    pendientes = [d for d in decisiones if d["estado_ejecucion"] == "PENDIENTE_APROBACION"]
    if pendientes:
        lineas += [
            "",
            "## Requieren aprobación (doble control)",
            "",
            "| ID | Acción | Referencia | Comercio | Monto | Motivo |",
            "|---|---|---|---|---:|---|",
        ]
        for d in pendientes:
            lineas.append(f"| {d['id']} | {d['accion']} | {d['referencia']} | {d['comercio_id']} | {centavos_a_texto(d['monto_centavos'])} | {d['motivo']} |")

    excepciones = por_accion["EXCEPCION"]
    if excepciones:
        lineas += [
            "",
            "## Cola de excepciones (con sugerencia del asistente)",
            "",
            "| ID | Referencia | Tipo | Monto | Motivo | Causa probable | Acción sugerida | Conf. |",
            "|---|---|---|---:|---|---|---|---:|",
        ]
        prioridad = {"CONTRACARGO_SIN_MATCH": 0, "COMERCIO_BLOQUEADO": 1}
        for d in sorted(excepciones, key=lambda d: (prioridad.get(d["motivo"], 9), -d["monto_centavos"])):
            s = sugerencias.get(d["id"], {})
            lineas.append(
                f"| {d['id']} | {d['referencia']} | {d['tipo']} | {centavos_a_texto(d['monto_centavos'])} | {d['motivo']} | "
                f"{s.get('causa_probable', '-')} | {s.get('accion_sugerida', '-')} | {s.get('confianza', 0):.0%} |"
            )

    apartado = [a for a in libro.dinero_apartado() if any(d["comercio_id"] == a["comercio_id"] for d in decisiones)]
    if apartado:
        lineas += ["", "## Dinero apartado por comercio (espera a una persona)", "", "| Comercio | Por qué | Movs | Monto |", "|---|---|---:|---:|"]
        for a in apartado[:20]:
            lineas.append(f"| {a['comercio_id']} | {a['motivo']} | {a['n']} | {centavos_a_texto(a['monto'])} |")

    fallidas = [d for d in decisiones if d["estado_ejecucion"] == "FALLIDA"]
    if fallidas:
        lineas += ["", "## ⚠ Acciones fallidas (atender antes del corte)", ""]
        for d in fallidas:
            a = acciones.get(d["id"], {})
            lineas.append(f"- {d['accion']} {d['referencia']} {centavos_a_texto(d['monto_centavos'])}: {a.get('respuesta', '')}")

    lineas += ["", "## Gates", "", "| Gate | Resultado | Crítico | Detalle |", "|---|---|---|---|"]
    vistos = set()
    for g in gates:
        if g["gate"] in vistos and g["gate"].startswith("G-LLM"):
            continue
        vistos.add(g["gate"])
        lineas.append(f"| {g['gate']} | {'✅' if g['ok'] else '❌'} | {'sí' if g['critico'] else 'no'} | {g['detalle']} |")

    evidencias = [a["evidencia"] for a in acciones.values() if a.get("evidencia")]
    if evidencias:
        lineas += ["", f"Evidencia adjunta: {len(evidencias)} capturas en `evidencia/`."]
    return "\n".join(lineas) + "\n"
