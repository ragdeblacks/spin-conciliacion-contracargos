"""Motor de conciliación. Puro: entra datos, sale decisiones. Sin IA, sin red.

Cada decisión lleva la regla que la produjo para que un analista (o Auditoría)
pueda explicarla sin leer código.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .modelos import (
    Accion,
    Decision,
    EstadoTransaccion,
    Motivo,
    MovimientoBanco,
    TipoMovimiento,
    TransaccionCore,
)


@dataclass(frozen=True)
class ParametrosConciliacion:
    tolerancia_monto_centavos: int = 0  # diferencia aceptada entre banco y core
    tolerancia_dias: int = 1  # desfase de fecha aceptado (corte nocturno)
    ventana_candidatos_dias: int = 3  # para buscar parecidos cuando no hay match
    umbral_aprobacion_centavos: int = 50_000_00  # $50,000.00: liberar más que esto exige doble control
    # Riesgo por comercio, inspirado en los programas de monitoreo de las redes (Visa VAMP 1.5 %; Mastercard ECM 1.5 % y 100+):
    # si el comercio supera cualquiera de estos umbrales, sus ventas pasan a revisión y Riesgos decide si suspende.
    max_contracargos_comercio_dia: int = 3
    ratio_contracargos_comercio: float = 0.015  # contracargos / ventas del comercio en la ventana histórica
    min_contracargos_para_ratio: int = 10  # el ratio solo cuenta con volumen suficiente


def _candidatos_cercanos(
    mov: MovimientoBanco,
    por_comercio: dict[str, list[TransaccionCore]],
    params: ParametrosConciliacion,
) -> list[TransaccionCore]:
    out = []
    for t in por_comercio.get(mov.comercio_id, []):
        if abs((t.fecha - mov.fecha).days) > params.ventana_candidatos_dias:
            continue
        mismo_monto = t.monto_centavos == mov.monto_centavos
        ref_parecida = t.referencia[:6] == mov.referencia[:6]
        if mismo_monto or ref_parecida:
            out.append(t)
    # los más parecidos primero: mismo monto y referencia parecida
    out.sort(key=lambda t: (t.monto_centavos != mov.monto_centavos, abs((t.fecha - mov.fecha).days)))
    return out[:5]


def comercios_en_riesgo(
    movimientos: list[MovimientoBanco],
    por_referencia: dict[str, TransaccionCore],
    params: ParametrosConciliacion,
    historial: dict[str, tuple[int, int]] | None = None,
) -> set[str]:
    """Comercios que superan los umbrales de riesgo: contracargos del día, o ratio histórico
    contracargos / ventas con volumen suficiente. `historial` = {comercio: (contracargos, ventas)} en la ventana."""
    hoy: Counter[str] = Counter(m.comercio_id for m in movimientos if m.tipo == TipoMovimiento.CONTRACARGO and m.referencia in por_referencia)
    riesgo = {c for c, n in hoy.items() if n > params.max_contracargos_comercio_dia}
    for c, (cc, ventas) in (historial or {}).items():
        cc_total = cc + hoy.get(c, 0)
        if cc_total >= params.min_contracargos_para_ratio and ventas and cc_total / ventas >= params.ratio_contracargos_comercio:
            riesgo.add(c)
    return riesgo


def conciliar(
    movimientos: list[MovimientoBanco],
    transacciones: list[TransaccionCore],
    params: ParametrosConciliacion | None = None,
    historial_comercios: dict[str, tuple[int, int]] | None = None,
) -> list[Decision]:
    params = params or ParametrosConciliacion()
    por_referencia = {t.referencia: t for t in transacciones}
    por_comercio: dict[str, list[TransaccionCore]] = defaultdict(list)
    for t in transacciones:
        por_comercio[t.comercio_id].append(t)

    repetidos = Counter((m.referencia, m.tipo) for m in movimientos)
    en_riesgo = comercios_en_riesgo(movimientos, por_referencia, params, historial_comercios)
    vistos: set[tuple[str, TipoMovimiento]] = set()
    decisiones: list[Decision] = []

    for mov in movimientos:
        llave = (mov.referencia, mov.tipo)
        if repetidos[llave] > 1 and llave in vistos:
            decisiones.append(Decision(mov, Accion.EXCEPCION, Motivo.DUPLICADO_EN_ARCHIVO, regla="R0-duplicado"))
            continue
        vistos.add(llave)

        t = por_referencia.get(mov.referencia)
        if t is None:
            cand = _candidatos_cercanos(mov, por_comercio, params)
            motivo = Motivo.CONTRACARGO_SIN_MATCH if mov.tipo == TipoMovimiento.CONTRACARGO else Motivo.SIN_MATCH
            decisiones.append(Decision(mov, Accion.EXCEPCION, motivo, candidatos=cand, regla="R1-sin-match"))
            continue

        if t.moneda != mov.moneda:
            decisiones.append(Decision(mov, Accion.EXCEPCION, Motivo.MONEDA_DISTINTA, transaccion=t, regla="R2-moneda"))
            continue

        if mov.tipo == TipoMovimiento.CONTRACARGO:
            if t.estado == EstadoTransaccion.BLOQUEADA:  # la retención ya se aplicó en una corrida anterior o a mano
                decisiones.append(Decision(mov, Accion.YA_PROCESADO, Motivo.RETENCION_YA_APLICADA, transaccion=t, regla="R3-ya-retenida"))
                continue
            motivo = Motivo.CONTRACARGO_CON_MATCH
            nota = ""
            if t.estado == EstadoTransaccion.LIQUIDADA:
                motivo = Motivo.CONTRACARGO_SOBRE_LIQUIDADA
                nota = "El dinero ya salió al comercio: bloquear saldo es urgente."
            elif abs(t.monto_centavos - mov.monto_centavos) > params.tolerancia_monto_centavos:
                motivo = Motivo.CONTRACARGO_PARCIAL
                nota = f"Contracargo por {mov.monto_centavos} sobre venta de {t.monto_centavos}."
            if mov.comercio_id in en_riesgo:
                nota = (nota + " " if nota else "") + "Comercio sobre el umbral de riesgo: Riesgos decide si suspende."
            # retener el importe en disputa es protector y reversible: se ejecuta sin doble control
            decisiones.append(Decision(mov, Accion.BLOQUEAR, motivo, transaccion=t, regla="R4-contracargo", nota=nota))
            continue

        # VENTA
        if abs(t.monto_centavos - mov.monto_centavos) > params.tolerancia_monto_centavos:
            decisiones.append(
                Decision(
                    mov,
                    Accion.EXCEPCION,
                    Motivo.MONTO_DIFERENTE,
                    transaccion=t,
                    regla="R5-monto",
                    nota=f"banco={mov.monto_centavos} core={t.monto_centavos}",
                )
            )
            continue
        if abs((t.fecha - mov.fecha).days) > params.tolerancia_dias:
            decisiones.append(
                Decision(
                    mov,
                    Accion.EXCEPCION,
                    Motivo.FECHA_FUERA_DE_RANGO,
                    transaccion=t,
                    regla="R6-fecha",
                    nota=f"banco={mov.fecha} core={t.fecha}",
                )
            )
            continue
        if t.estado == EstadoTransaccion.LIQUIDADA:
            decisiones.append(Decision(mov, Accion.YA_PROCESADO, Motivo.LIQUIDADA_EN_CORE, transaccion=t, regla="R7-ya-liquidada"))
            continue
        if t.estado == EstadoTransaccion.BLOQUEADA or t.comercio_bloqueado:
            decisiones.append(
                Decision(
                    mov,
                    Accion.EXCEPCION,
                    Motivo.COMERCIO_BLOQUEADO,
                    transaccion=t,
                    regla="R8-bloqueada",
                    nota="No se libera dinero a un comercio con saldo bloqueado sin revisión.",
                )
            )
            continue
        if mov.comercio_id in en_riesgo:
            decisiones.append(
                Decision(
                    mov,
                    Accion.EXCEPCION,
                    Motivo.COMERCIO_EN_RIESGO,
                    transaccion=t,
                    regla="R8b-comercio-en-riesgo",
                    nota="El comercio supera el umbral de contracargos: Riesgos decide si libera, retiene o suspende.",
                )
            )
            continue
        d = Decision(mov, Accion.LIQUIDAR, Motivo.MATCH_EXACTO, transaccion=t, regla="R9-match")
        d.requiere_aprobacion = mov.monto_centavos > params.umbral_aprobacion_centavos
        decisiones.append(d)

    return decisiones


def resumen(decisiones: list[Decision]) -> dict[str, int]:
    c: Counter[str] = Counter()
    for d in decisiones:
        c[d.accion.value] += 1
        c[f"{d.accion.value}/{d.motivo.value}"] += 1
        if d.requiere_aprobacion:
            c["REQUIERE_APROBACION"] += 1
    c["TOTAL"] = len(decisiones)
    return dict(sorted(c.items()))
