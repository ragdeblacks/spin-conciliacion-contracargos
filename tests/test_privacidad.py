import json
from dataclasses import asdict

from conciliador.dominio.reglas import conciliar
from conciliador.gates import g_llm_pii
from conciliador.privacidad import Tokenizador, contiene_pii, enmascarar_tarjeta
from conciliador.triaje import armar_contexto


def test_tokenizador_ida_y_vuelta():
    t = Tokenizador()
    assert t.comercio("COM-0001") == "COMERCIO_1"
    assert t.comercio("COM-0001") == "COMERCIO_1"
    assert t.referencia("SPN101500001") == "REF_1"
    assert t.destokenizar("revisar COMERCIO_1 y REF_1") == "revisar COM-0001 y SPN101500001"


def test_detecta_pii():
    assert contiene_pii("tarjeta 4111111111111111")
    assert contiene_pii("correo juan@dominio.com")
    assert not contiene_pii("REF_3 monto 12345 COMERCIO_2")


def test_paquete_al_modelo_no_lleva_identificadores_reales(movimientos, transacciones):
    tok = Tokenizador()
    for d in conciliar(movimientos, transacciones):
        if d.accion.value != "EXCEPCION":
            continue
        ctx = armar_contexto(d, tok, 0)
        texto = json.dumps(asdict(ctx))
        assert d.movimiento.comercio_id not in texto
        assert d.movimiento.referencia not in texto
        assert "4111" not in texto
        assert g_llm_pii(texto).ok


def test_enmascarar_tarjeta():
    assert enmascarar_tarjeta("4111 **** **** 1234") == "****1234"
