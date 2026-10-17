from datetime import timedelta

from conciliador.orquestador import Adaptadores, Orquestador
from conciliador.tablero import agrupar, exportar_json, generar_html, recopilar
from mocks.datos_semilla import csv_con_esquema_roto
from tests.fakes import AsistenteFalso, CoreFalso, FuenteFalsa, NotificadorFalso


def _orq(cfg, libro, dia, modo, core=None, fuente=None):
    core = core or CoreFalso(dia)
    cfg.modo = modo
    return Orquestador(cfg, libro, Adaptadores(fuente or FuenteFalsa(dia), core, core, core, AsistenteFalso(), NotificadorFalso())), core


def test_las_fallas_abren_incidencias_y_se_resuelven(cfg, libro, dia, fecha):
    core = CoreFalso(dia)
    core.fallar_liberaciones = {dia.transacciones[-9].id}
    orq, _ = _orq(cfg, libro, dia, "autonoma", core=core)
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    abiertas = libro.incidencias(solo_abiertas=True)
    tipos = sorted({i["tipo"] for i in abiertas})
    assert tipos == ["ACCION_FALLIDA", "CONTRACARGO_SIN_MATCH", "CORRIDA_DETENIDA"]
    assert all(i["corrida_id"] == r.corrida_id for i in abiertas)
    # repetir la corrida no duplica incidencias abiertas iguales
    orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert len([i for i in libro.incidencias(solo_abiertas=True) if i["tipo"] == "ACCION_FALLIDA"]) == 2  # una por corrida
    inc = abiertas[0]
    libro.resolver_incidencia(inc["id"], "Ana López", "resuelto a mano")
    assert libro.incidencias(solo_abiertas=False)[-1]["estado"] in ("ABIERTA", "RESUELTA")
    assert all(i["id"] != inc["id"] for i in libro.incidencias(solo_abiertas=True))


def test_esquema_roto_abre_incidencia_critica(cfg, libro, dia, fecha):
    orq, _ = _orq(cfg, libro, dia, "sombra", fuente=FuenteFalsa(dia, csv_override=csv_con_esquema_roto(dia)))
    orq.correr(fecha, hoy=fecha + timedelta(days=1))
    (inc,) = libro.incidencias(solo_abiertas=True)
    assert inc["severidad"] == "critica" and "G-ESQUEMA" in inc["descripcion"]


def test_resolver_excepcion_registra_si_siguio_la_sugerencia(cfg, libro, dia, fecha):
    orq, _ = _orq(cfg, libro, dia, "sombra")
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    exc = [d for d in r.decisiones if d.accion.value == "EXCEPCION"]
    res = libro.resolver_excepcion(exc[0].id, "ESCALAR_AL_BANCO", "Carlos Ruiz")  # el asistente falso siempre sugiere eso
    assert res["siguio_sugerencia"] == 1
    res2 = libro.resolver_excepcion(exc[1].id, "LIQUIDAR_MANUAL", "Carlos Ruiz")
    assert res2["siguio_sugerencia"] == 0
    pendientes = libro.excepciones_pendientes()
    assert len(pendientes) == len(exc) - 2
    assert libro.sugerencias_de(r.corrida_id)[0]["decision_humana"] == "ESCALAR_AL_BANCO"


def test_tablero_agrega_por_dia_semana_y_mes(cfg, libro, dia, fecha):
    orq, _ = _orq(cfg, libro, dia, "autonoma")
    for n in range(0, 10):
        orq.correr(fecha - timedelta(days=n), hoy=fecha + timedelta(days=1))
    dias = recopilar(libro, fecha - timedelta(days=15))
    assert len(dias) == 10
    assert all(d.total > 100 and d.auto_pct and d.auto_pct > 70 for d in dias.values())
    semanas = agrupar(dias, "semana")
    assert 2 <= len(semanas) <= 3 and sum(len(s.dias) for s in semanas) == 10
    (mes,) = agrupar(dias, "mes")
    assert mes.suma("total") == sum(d.total for d in dias.values())
    html = generar_html(libro, 15, hoy=fecha + timedelta(days=1))
    for texto in ("Conciliado sin intervención humana", "Incidencias abiertas", "Excepciones por revisar", "Asistente de IA", "data-p='semana'"):
        assert texto in html
    datos = exportar_json(libro, 15, hoy=fecha + timedelta(days=1))
    assert '"auto_pct"' in datos and '"fecha"' in datos
