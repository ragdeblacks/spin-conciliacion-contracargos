from datetime import timedelta

from conciliador.dominio.modelos import Accion, EstadoEjecucion
from conciliador.orquestador import Adaptadores, Orquestador
from conciliador.reporte import reporte_markdown
from mocks.datos_semilla import csv_con_esquema_roto
from tests.fakes import AsistenteFalso, CoreFalso, FuenteFalsa, NotificadorFalso


def _orq(cfg, libro, dia, modo="sombra", **kw):
    cfg.modo = modo
    core = kw.pop("core", None) or CoreFalso(dia)
    fuente = kw.pop("fuente", None) or FuenteFalsa(dia)
    asistente = kw.pop("asistente", None) or AsistenteFalso()
    notif = NotificadorFalso()
    ad = Adaptadores(fuente, core, core, core, asistente, notif)
    return Orquestador(cfg, libro, ad), core, notif


def test_modo_sombra_no_toca_el_core(cfg, libro, dia, fecha):
    orq, core, notif = _orq(cfg, libro, dia, "sombra")
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert r.estado == "CERRADA", [g for g in r.gates if not g.ok]
    assert core.liberadas == [] and core.bloqueos == []
    assert all(d.estado_ejecucion == EstadoEjecucion.SOMBRA for d in r.decisiones if d.es_ejecutable)
    assert r.resumen["LIQUIDAR"] > 120 and r.resumen["BLOQUEAR"] == 11 and r.resumen["EXCEPCION"] >= 9
    assert any("cerrada" in t for t, _, _ in notif.enviados)
    md = reporte_markdown(libro, r.corrida_id)
    assert "Cola de excepciones" in md and "G-CIERRE" in md


def test_modo_autonoma_ejecuta_bloqueos_antes_que_liquidaciones(cfg, libro, dia, fecha):
    orq, core, _ = _orq(cfg, libro, dia, "autonoma")
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert r.estado == "CERRADA", [g for g in r.gates if not g.ok]
    acciones = libro.acciones_de(r.corrida_id)
    tipos = [a["tipo"] for a in acciones]
    primer_liq = tipos.index("LIQUIDAR")
    assert "BLOQUEAR" not in tipos[primer_liq:], "ningún bloqueo después de la primera liquidación"
    pendientes = [d for d in r.decisiones if d.estado_ejecucion == EstadoEjecucion.PENDIENTE_APROBACION]
    assert {d.movimiento.referencia for d in pendientes} == {dia.casos["MONTO_ALTO"][0]}, "solo liberar dinero grande espera a una persona"
    assert len(core.bloqueos) == 11  # las 11 retenciones se ejecutan sin doble control


def test_repetir_la_corrida_no_mueve_dinero_dos_veces(cfg, libro, dia, fecha):
    """Caso normal: el Core ya refleja lo liquidado, las reglas lo ven como YA_PROCESADO."""
    orq, core, _ = _orq(cfg, libro, dia, "autonoma")
    r1 = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    liberadas_1 = len(core.liberadas)
    r2 = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert r2.estado == "CERRADA" and r1.corrida_id != r2.corrida_id
    assert len(core.liberadas) == liberadas_1, "la segunda corrida no libera nada dos veces"
    assert r2.resumen["YA_PROCESADO"] >= liberadas_1


def test_idempotencia_del_libro_mayor_con_core_atrasado(cfg, libro, dia, fecha):
    """Caso feo: el Core devuelve estados viejos (réplica atrasada) y las reglas vuelven a decir LIQUIDAR.
    El libro mayor es la última línea de defensa: G-DUPLICADO omite lo ya confirmado."""
    core = CoreFalso(dia, estado_congelado=True)
    orq, core, _ = _orq(cfg, libro, dia, "autonoma", core=core)
    r1 = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    liberadas_1 = len(core.liberadas)
    assert liberadas_1 > 100
    r2 = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert r2.estado == "CERRADA"
    assert len(core.liberadas) == liberadas_1
    omitidas = [d for d in r2.decisiones if d.estado_ejecucion == EstadoEjecucion.OMITIDA_IDEMPOTENTE]
    assert len(omitidas) == liberadas_1 + len(core.bloqueos)
    assert r1.resumen["LIQUIDAR"] == r2.resumen["LIQUIDAR"]


def test_fallo_del_core_deja_rastro_y_cierre_falla(cfg, libro, dia, fecha):
    core = CoreFalso(dia)
    core.fallar_liberaciones = {dia.transacciones[-9].id}  # una venta normal
    orq, core, notif = _orq(cfg, libro, dia, "autonoma", core=core)
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert r.estado == "DETENIDA"
    cierre = [g for g in r.gates if g.gate == "G-CIERRE"][0]
    assert not cierre.ok and "1 acciones fallidas" in cierre.detalle
    fallidas = [a for a in libro.acciones_de(r.corrida_id) if a["estado"] == "FALLIDA"]
    assert len(fallidas) == 1 and "503" in fallidas[0]["respuesta"]
    assert notif.enviados[-1][2] == "critico"


def test_core_caido_no_toca_nada(cfg, libro, dia, fecha):
    core = CoreFalso(dia, vivo=False)
    orq, core, _ = _orq(cfg, libro, dia, "autonoma", core=core)
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert r.estado == "DETENIDA" and r.gates[-1].gate == "G-CORE-VIVO"
    assert libro.decisiones_de(r.corrida_id) == []


def test_esquema_roto_detiene_antes_de_conciliar(cfg, libro, dia, fecha):
    fuente = FuenteFalsa(dia, csv_override=csv_con_esquema_roto(dia))
    orq, core, _ = _orq(cfg, libro, dia, "autonoma", fuente=fuente)
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert r.estado == "DETENIDA" and r.gates[-1].gate == "G-ESQUEMA"
    assert core.liberadas == []


def test_no_se_concilia_el_dia_en_curso(cfg, libro, dia, fecha):
    orq, _, _ = _orq(cfg, libro, dia, "sombra")
    r = orq.correr(fecha, hoy=fecha)
    assert r.estado == "DETENIDA" and r.gates[-1].gate == "G-FECHA"


def test_modo_asistida_requiere_aprobacion_y_luego_ejecuta(cfg, libro, dia, fecha):
    orq, core, _ = _orq(cfg, libro, dia, "asistida")
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    assert r.estado == "CERRADA" and core.liberadas == []
    pend = [d for d in r.decisiones if d.estado_ejecucion == EstadoEjecucion.PENDIENTE_APROBACION]
    assert len(pend) == r.resumen["LIQUIDAR"] + r.resumen["BLOQUEAR"]
    bloqueos = [d.id for d in pend if d.accion == Accion.BLOQUEAR][:3]
    aprobadas = orq.aprobar_y_ejecutar(r.corrida_id, "Ana López", bloqueos)
    assert len(aprobadas) == 3 and len(core.bloqueos) == 3
    todas = orq.aprobar_y_ejecutar(r.corrida_id, "Ana López")
    assert len(core.liberadas) == r.resumen["LIQUIDAR"]
    assert all(d.estado_ejecucion == EstadoEjecucion.EJECUTADA for d in todas)


def test_comparar_sombra_contra_lo_que_hizo_el_analista(cfg, libro, dia, fecha):
    orq, core, _ = _orq(cfg, libro, dia, "sombra")
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    # "el analista" liquida todo y bloquea todo lo que el pipeline dijo
    for d in r.decisiones:
        if d.accion == Accion.LIQUIDAR:
            core.liberar(d.transaccion.id, "manual")
        elif d.accion == Accion.BLOQUEAR:
            core.bloquear(d.movimiento.comercio_id, d.movimiento.referencia, 0, "manual", "manual")
    comp = orq.comparar_sombra(r.corrida_id)
    assert comp["gate"].ok and comp["diferencias"] == []


def test_triaje_registra_sugerencias_y_respeta_presupuesto(cfg, libro, dia, fecha):
    asistente = AsistenteFalso()
    cfg.presupuesto_llm_llamadas_corrida = 3
    orq, _, _ = _orq(cfg, libro, dia, "sombra", asistente=asistente)
    r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
    sug = libro.sugerencias_de(r.corrida_id)
    assert len(sug) == r.resumen["EXCEPCION"]
    assert asistente.llamadas == 3, "el presupuesto corta las llamadas al modelo"
    assert sum(1 for s in sug if s["proveedor"] == "nulo") == len(sug) - 3, "el resto cae al fallback determinista"
    assert all(s["valida"] for s in sug)
    assert "REF_" not in sug[0]["explicacion"], "la explicación se destokeniza antes de mostrarla"


def test_libro_mayor_promedios_e_historico(cfg, libro, dia, fecha):
    orq, _, _ = _orq(cfg, libro, dia, "sombra")
    for i in range(3):
        orq.correr(fecha - timedelta(days=i), hoy=fecha + timedelta(days=1))
    assert libro.promedio_movimientos() and libro.promedio_movimientos() > 100
    assert 0 < libro.tasa_excepciones_historica() < 0.2
    assert len(libro.corridas()) == 3
