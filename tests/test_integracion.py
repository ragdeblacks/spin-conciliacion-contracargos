"""Integración real: mocks del banco y del Core levantados en hilos, adaptadores HTTP y RPA de verdad."""

from __future__ import annotations

import os
import socket
import threading
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import uvicorn

from conciliador.adaptadores.banco import FuenteAPIBanco, FuentePortalRPA
from conciliador.adaptadores.core import BloqueadorCoreAPI, BloqueadorCoreUI, CoreAPI
from conciliador.adaptadores.llm import AsistenteNulo
from conciliador.dominio.modelos import Accion, EstadoEjecucion
from conciliador.orquestador import Adaptadores, Orquestador
from tests.fakes import NotificadorFalso


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _levantar(app, puerto: int) -> uvicorn.Server:
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{puerto}/health", timeout=1)
            return srv
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError("servidor no levantó")


@pytest.fixture(scope="module")
def servicios():
    os.environ.setdefault("CORE_API_BLOQUEO_HABILITADA", "1")
    from mocks.banco_portal.app import app as banco
    from mocks.core_netpay import app as core_mod

    core_mod.API_BLOQUEO = True
    pb, pc = _puerto_libre(), _puerto_libre()
    sb, sc = _levantar(banco, pb), _levantar(core_mod.app, pc)
    yield {"banco": f"http://127.0.0.1:{pb}", "core": f"http://127.0.0.1:{pc}"}
    sb.should_exit = sc.should_exit = True


def _navegador_disponible() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def test_adaptadores_api_contra_mocks(servicios, cfg, libro, fecha):
    httpx.post(f"{servicios['core']}/admin/reset", headers={"Authorization": "Bearer token-core-demo"})
    cfg.modo = "autonoma"
    cfg.token_core = "token-core-demo"
    cfg.fuente_banco, cfg.bloqueador = "api", "api"
    cfg.token_api_banco = "token-banco-demo"
    core = CoreAPI(servicios["core"], "token-core-demo")
    ad = Adaptadores(
        FuenteAPIBanco(f"{servicios['banco']}/api/v2", "token-banco-demo"),
        core,
        core,
        BloqueadorCoreAPI(servicios["core"], "token-core-demo"),
        AsistenteNulo(),
        NotificadorFalso(),
    )
    r = Orquestador(cfg, libro, ad).correr(fecha, hoy=fecha + timedelta(days=1))
    assert r.estado == "CERRADA", [g for g in r.gates if not g.ok]
    ejecutadas = [d for d in r.decisiones if d.estado_ejecucion == EstadoEjecucion.EJECUTADA]
    assert len(ejecutadas) == r.resumen["LIQUIDAR"] + r.resumen["BLOQUEAR"] - r.resumen["REQUIERE_APROBACION"]
    # el Core refleja los cambios y una segunda corrida no repite nada
    r2 = Orquestador(cfg, libro, ad).correr(fecha, hoy=fecha + timedelta(days=1))
    assert r2.estado == "CERRADA" and r2.resumen["YA_PROCESADO"] >= len(ejecutadas)
    c = httpx.get(f"{servicios['core']}/api/comercios/COM-0007", headers={"Authorization": "Bearer token-core-demo"}).json()
    assert c["bloqueado"] and len(c["bloqueos"]) == 3  # el cuarto contracargo quedó pendiente de aprobación


def test_liberar_es_idempotente_en_el_core(servicios):
    core = CoreAPI(servicios["core"], "token-core-demo")
    tx = core.transacciones_del_dia(__import__("datetime").date(2026, 10, 14))[0]
    r1 = core.liberar(tx.id, "LIQ:prueba")
    r2 = core.liberar(tx.id, "LIQ:prueba")
    assert r1.ok and not r1.idempotente
    assert r2.ok and r2.idempotente


@pytest.mark.e2e
@pytest.mark.skipif(not _navegador_disponible(), reason="sin Chromium de Playwright")
def test_rpa_portal_y_ui_del_core(servicios, cfg, libro, fecha, tmp_path: Path):
    httpx.post(f"{servicios['core']}/admin/reset", headers={"Authorization": "Bearer token-core-demo"})
    cfg.modo = "autonoma"
    cfg.token_core = "token-core-demo"
    core = CoreAPI(servicios["core"], "token-core-demo")
    fuente = FuentePortalRPA(servicios["banco"], "operaciones", "portal-demo", tmp_path)
    bloqueador = BloqueadorCoreUI(servicios["core"], "analista", "core-demo", tmp_path)
    ad = Adaptadores(fuente, core, core, bloqueador, AsistenteNulo(), NotificadorFalso())
    ok, detalle = fuente.probar_contrato()
    assert ok, detalle
    r = Orquestador(cfg, libro, ad).correr(fecha, hoy=fecha + timedelta(days=1))
    assert r.estado == "CERRADA", [g for g in r.gates if not g.ok]
    bloqueos = [d for d in r.decisiones if d.accion == Accion.BLOQUEAR and d.estado_ejecucion == EstadoEjecucion.EJECUTADA]
    assert len(bloqueos) == 10
    capturas = list(tmp_path.glob("bloqueo_*.png"))
    assert len(capturas) == 10, "cada bloqueo por UI deja captura como evidencia"
    assert (tmp_path / f"banco_{fecha.isoformat()}.csv").exists()
    # volver a bloquear la misma referencia por UI es idempotente del lado del Core
    d = bloqueos[0]
    r2 = bloqueador.bloquear(d.movimiento.comercio_id, d.movimiento.referencia, d.movimiento.monto_centavos, "repetido", "BLQ:rep")
    assert r2.ok and r2.idempotente
