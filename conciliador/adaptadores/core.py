"""Adaptadores del Core NetPay: lectura, liberación por API y bloqueo por UI (RPA) o API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import httpx

from ..dominio.modelos import EstadoTransaccion, TransaccionCore
from ..puertos import ResultadoAccion

SELECTORES_CORE_UI_V1 = {
    "campo_usuario": "input[name='usuario']",
    "campo_clave": "input[name='clave']",
    "boton_entrar": "button[type='submit']",
    "campo_referencia": "input[name='referencia']",
    "campo_monto": "input[name='monto']",
    "campo_motivo": "input[name='motivo']",
    "boton_bloquear": "button#bloquear",
    "senal_ok": "p.resultado",
    "senal_ya_bloqueado": "p.resultado:has-text('ya estaba bloqueado')",
}


@dataclass
class CoreAPI:
    url: str
    token: str
    reintentos: int = 3

    def _cliente(self) -> httpx.Client:
        return httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {self.token}"}, timeout=30)

    def saludable(self) -> bool:
        try:
            with self._cliente() as c:
                return c.get("/health").status_code == 200
        except httpx.HTTPError:
            return False

    def transacciones_del_dia(self, fecha_operacion: date) -> list[TransaccionCore]:
        with self._cliente() as c:
            r = c.get("/api/transacciones", params={"fecha": fecha_operacion.isoformat()})
            r.raise_for_status()
        return [
            TransaccionCore(
                id=t["id"],
                referencia=t["referencia"],
                fecha=datetime.strptime(t["fecha"], "%Y-%m-%d").date(),
                monto_centavos=int(t["monto_centavos"]),
                moneda=t["moneda"],
                comercio_id=t["comercio_id"],
                estado=EstadoTransaccion(t["estado"]),
                comercio_bloqueado=bool(t["comercio_bloqueado"]),
            )
            for t in r.json()["transacciones"]
        ]

    def liberar(self, transaccion_id: str, clave_idempotencia: str) -> ResultadoAccion:
        ultimo_error = ""
        for intento in range(1, self.reintentos + 1):
            try:
                with self._cliente() as c:
                    r = c.post(
                        "/api/liquidaciones/liberar",
                        json={"transaccion_id": transaccion_id},
                        headers={"Idempotency-Key": clave_idempotencia},
                    )
                if r.status_code in (200, 201):
                    cuerpo = r.json()
                    return ResultadoAccion(ok=True, respuesta=cuerpo, idempotente=bool(cuerpo.get("idempotente")))
                if r.status_code == 409:
                    return ResultadoAccion(ok=True, respuesta=r.json(), idempotente=True)
                if r.status_code < 500:
                    return ResultadoAccion(ok=False, error=f"HTTP {r.status_code}: {r.text[:200]}")
                ultimo_error = f"HTTP {r.status_code} (intento {intento})"
            except httpx.HTTPError as e:
                ultimo_error = f"{type(e).__name__} (intento {intento})"
        return ResultadoAccion(ok=False, error=ultimo_error)


@dataclass
class BloqueadorCoreUI:
    """Bloqueo de saldo por la UI del Core (RPA). Deja captura como evidencia.
    Es el adaptador de transición: la petición de una API de bloqueo al equipo del Core
    es la prioridad uno del roadmap, y este archivo es lo único que se reemplaza."""

    url: str
    usuario: str
    clave: str
    ruta_evidencia: Path
    selectores: dict = field(default_factory=lambda: dict(SELECTORES_CORE_UI_V1))
    timeout_ms: int = 15_000
    nombre: str = "ui_rpa"

    def bloquear(self, comercio_id: str, referencia: str, monto_centavos: int, motivo: str, clave_idempotencia: str) -> ResultadoAccion:
        from playwright.sync_api import sync_playwright

        self.ruta_evidencia.mkdir(parents=True, exist_ok=True)
        s = self.selectores
        evidencia = self.ruta_evidencia / f"bloqueo_{clave_idempotencia.replace(':', '_')}.png"
        try:
            with sync_playwright() as p:
                navegador = p.chromium.launch(headless=True)
                pagina = navegador.new_page()
                pagina.set_default_timeout(self.timeout_ms)
                pagina.goto(f"{self.url}/ui/login")
                pagina.fill(s["campo_usuario"], self.usuario)
                pagina.fill(s["campo_clave"], self.clave)
                pagina.click(s["boton_entrar"])
                pagina.goto(f"{self.url}/ui/comercios/{comercio_id}")
                pagina.fill(s["campo_referencia"], referencia)
                pagina.fill(s["campo_monto"], f"{monto_centavos / 100:.2f}")
                pagina.fill(s["campo_motivo"], motivo)
                pagina.click(s["boton_bloquear"])
                pagina.wait_for_selector(f"{s['senal_ok']}, {s['senal_ya_bloqueado']}")
                ya_estaba = pagina.locator(s["senal_ya_bloqueado"]).count() > 0
                pagina.screenshot(path=str(evidencia), full_page=True)
                navegador.close()
            return ResultadoAccion(ok=True, respuesta={"via": "ui", "ya_estaba_bloqueado": ya_estaba}, evidencia=evidencia, idempotente=ya_estaba)
        except Exception as e:  # noqa: BLE001
            return ResultadoAccion(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")


@dataclass
class BloqueadorCoreAPI:
    """Adaptador API-First para el bloqueo. Existe para demostrar que el cambio es un flag."""

    url: str
    token: str
    nombre: str = "api"

    def bloquear(self, comercio_id: str, referencia: str, monto_centavos: int, motivo: str, clave_idempotencia: str) -> ResultadoAccion:
        try:
            r = httpx.post(
                f"{self.url}/api/comercios/{comercio_id}/bloqueos",
                json={"referencia": referencia, "monto_centavos": monto_centavos, "motivo": motivo},
                headers={"Authorization": f"Bearer {self.token}", "Idempotency-Key": clave_idempotencia},
                timeout=30,
            )
            if r.status_code in (200, 201):
                cuerpo = r.json()
                return ResultadoAccion(ok=True, respuesta=cuerpo, idempotente=bool(cuerpo.get("idempotente")))
            return ResultadoAccion(ok=False, error=f"HTTP {r.status_code}: {r.text[:200]}")
        except httpx.HTTPError as e:
            return ResultadoAccion(ok=False, error=type(e).__name__)
