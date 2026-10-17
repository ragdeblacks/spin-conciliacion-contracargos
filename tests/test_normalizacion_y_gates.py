import pytest

from conciliador import gates
from conciliador.dominio.modelos import Accion, Decision, EstadoEjecucion, Motivo, MovimientoBanco, TipoMovimiento
from conciliador.dominio.normalizacion import ErrorEsquema, parsear_csv
from conciliador.dominio.reglas import conciliar
from mocks.datos_semilla import csv_banco, csv_con_esquema_roto


def test_csv_del_banco_se_parsea(dia):
    movs = parsear_csv(csv_banco(dia))
    assert len(movs) == len(dia.movimientos)
    assert all(isinstance(m.monto_centavos, int) for m in movs)


def test_montos_con_formato_bancario():
    csv = 'referencia,fecha,monto,moneda,tipo,comercio_id\nabc,15/10/2026,"$1,234.56",mxn,venta,C1\n'
    (m,) = parsear_csv(csv)
    assert m.monto_centavos == 123456 and m.moneda == "MXN" and m.tipo == TipoMovimiento.VENTA and m.referencia == "ABC"


def test_esquema_roto_detiene(dia):
    roto = csv_con_esquema_roto(dia)
    encabezados = roto.splitlines()[0].split(",")
    r = gates.g_esquema(encabezados)
    assert not r.ok and r.critico and "faltantes" in r.detalle
    with pytest.raises(ErrorEsquema):
        parsear_csv(roto)


def test_g_volumen():
    assert not gates.g_volumen(0, 200, 1, 3.0).ok
    assert not gates.g_volumen(800, 200, 1, 3.0).ok
    assert gates.g_volumen(250, 200, 1, 3.0).ok
    assert gates.g_volumen(250, None, 1, 3.0).ok


def test_g_secretos_rechaza_placeholders():
    assert not gates.g_secretos({"CORE_API_TOKEN": "changeme"}).ok
    assert not gates.g_secretos({"CORE_API_TOKEN": ""}).ok
    assert gates.g_secretos({"CORE_API_TOKEN": "s3cr3t"}).ok


def test_g_orden_y_cierre(movimientos, transacciones):
    dec = conciliar(movimientos, transacciones)
    bloqueos = [d for d in dec if d.accion == Accion.BLOQUEAR]
    for d in dec:
        d.estado_ejecucion = EstadoEjecucion.APROBADA if d.es_ejecutable else EstadoEjecucion.NO_APLICA
    assert not gates.g_orden(dec).ok
    for d in bloqueos:
        d.estado_ejecucion = EstadoEjecucion.EJECUTADA
    assert gates.g_orden(dec).ok
    assert not gates.g_cierre(dec, "autonoma").ok  # las liquidaciones siguen en APROBADA sin estado final
    for d in dec:
        if d.accion == Accion.LIQUIDAR:
            d.estado_ejecucion = EstadoEjecucion.EJECUTADA
    assert gates.g_cierre(dec, "autonoma").ok


def test_g_duplicado_marca_idempotentes():
    mov = MovimientoBanco("R1", __import__("datetime").date(2026, 10, 15), 100, "MXN", TipoMovimiento.VENTA, "C")
    d = Decision(mov, Accion.LIQUIDAR, Motivo.MATCH_EXACTO)
    gates.g_duplicado([d], {d.clave_idempotencia})
    assert d.estado_ejecucion == EstadoEjecucion.OMITIDA_IDEMPOTENTE


def test_g_deriva():
    assert gates.g_deriva(0.30, 0.05).ok is False
    assert gates.g_deriva(0.06, 0.05).ok
    assert gates.g_deriva(0.5, None).ok
