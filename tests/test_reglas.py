"""El motor de conciliación clasifica cada caso feo de la semilla como se espera."""

from conciliador.dominio.modelos import Accion, Motivo
from conciliador.dominio.reglas import ParametrosConciliacion, conciliar, resumen


def _por_ref(decisiones):
    out = {}
    for d in decisiones:
        out.setdefault(d.movimiento.referencia, []).append(d)
    return out


def test_casos_de_la_semilla(movimientos, transacciones, dia):
    dec = conciliar(movimientos, transacciones)
    por = _por_ref(dec)
    c = dia.casos

    for ref in c["NORMAL"]:
        assert por[ref][0].accion == Accion.LIQUIDAR and por[ref][0].motivo == Motivo.MATCH_EXACTO
    for ref in c["VENTA_DE_COMERCIO_CON_CONTRACARGO"]:
        assert por[ref][0].motivo == Motivo.CONTRACARGO_MISMO_DIA and por[ref][0].accion == Accion.EXCEPCION
    assert c["VENTA_DE_COMERCIO_CON_CONTRACARGO"], "la semilla debe incluir ventas de comercios con contracargo"
    (alto,) = c["MONTO_ALTO"]
    assert por[alto][0].accion == Accion.LIQUIDAR and por[alto][0].requiere_aprobacion
    for ref in c["MONTO_DIFERENTE"]:
        assert por[ref][0].motivo == Motivo.MONTO_DIFERENTE
    (con_cand,) = c["SIN_MATCH_CON_CANDIDATO"]
    assert por[con_cand][0].motivo == Motivo.SIN_MATCH and por[con_cand][0].candidatos
    (sin_cand,) = c["SIN_MATCH_SIN_CANDIDATO"]
    assert por[sin_cand][0].motivo == Motivo.SIN_MATCH and not por[sin_cand][0].candidatos
    for ref in c["DUPLICADO"]:
        acciones = sorted(d.accion for d in por[ref])
        assert acciones == [Accion.EXCEPCION, Accion.LIQUIDAR]
        assert any(d.motivo == Motivo.DUPLICADO_EN_ARCHIVO for d in por[ref])
    for ref in c["YA_LIQUIDADA"]:
        assert por[ref][0].accion == Accion.YA_PROCESADO
    (fuera,) = c["FECHA_FUERA"]
    assert por[fuera][0].motivo == Motivo.FECHA_FUERA_DE_RANGO
    (tolerada,) = c["FECHA_TOLERADA"]
    assert por[tolerada][0].accion == Accion.LIQUIDAR
    (moneda,) = c["MONEDA"]
    assert por[moneda][0].motivo == Motivo.MONEDA_DISTINTA
    (bloq,) = c["COMERCIO_BLOQUEADO"]
    assert por[bloq][0].motivo == Motivo.COMERCIO_BLOQUEADO and por[bloq][0].accion == Accion.EXCEPCION
    for ref in c["CONTRACARGO"]:
        assert por[ref][0].accion == Accion.BLOQUEAR and por[ref][0].motivo == Motivo.CONTRACARGO_CON_MATCH
    (parcial,) = c["CONTRACARGO_PARCIAL"]
    assert por[parcial][0].accion == Accion.BLOQUEAR and por[parcial][0].motivo == Motivo.CONTRACARGO_PARCIAL
    (sobre_liq,) = c["CONTRACARGO_SOBRE_LIQUIDADA"]
    assert por[sobre_liq][0].motivo == Motivo.CONTRACARGO_SOBRE_LIQUIDADA
    acumulados = [por[r][0] for r in c["CONTRACARGO_ACUMULADO"]]
    assert all(d.accion == Accion.BLOQUEAR for d in acumulados)
    assert sum(d.requiere_aprobacion for d in acumulados) == 1, "el cuarto contracargo del mismo comercio pide aprobación"
    (cc_sin,) = c["CONTRACARGO_SIN_MATCH"]
    assert por[cc_sin][0].motivo == Motivo.CONTRACARGO_SIN_MATCH
    for ref in c["SOLO_EN_CORE"]:
        assert ref not in por


def test_resumen_cuadra(movimientos, transacciones):
    dec = conciliar(movimientos, transacciones)
    r = resumen(dec)
    assert r["TOTAL"] == len(movimientos)
    assert r["LIQUIDAR"] + r["BLOQUEAR"] + r["EXCEPCION"] + r["YA_PROCESADO"] == r["TOTAL"]


def test_tolerancia_de_monto_configurable(movimientos, transacciones, dia):
    params = ParametrosConciliacion(tolerancia_monto_centavos=2_000)
    dec = conciliar(movimientos, transacciones, params)
    por = _por_ref(dec)
    # los tres casos de monto diferente (-250, +1500, -1000) quedan dentro de $20 de tolerancia
    for ref in dia.casos["MONTO_DIFERENTE"]:
        assert por[ref][0].accion in (Accion.LIQUIDAR, Accion.EXCEPCION)
        assert por[ref][0].motivo != Motivo.MONTO_DIFERENTE


def test_decision_es_explicable(movimientos, transacciones):
    for d in conciliar(movimientos, transacciones):
        assert d.regla, "toda decisión lleva la regla que la produjo"
        assert d.motivo
