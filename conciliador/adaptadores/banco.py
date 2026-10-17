"""Adaptadores de la fuente de movimientos del banco.

Hoy: portal legacy por RPA (Playwright). Mañana: API. Siempre: archivo manual de respaldo.
Los tres cumplen el puerto FuenteMovimientosBanco y el orquestador no distingue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

# Selectores como configuración: cuando el banco cambie el portal (3 meses),
# esto es lo que se ajusta, no el pipeline. G-CONTRATO-PORTAL los prueba a diario.
SELECTORES_PORTAL_V1 = {
    "campo_usuario": "input[name='usuario']",
    "campo_clave": "input[name='clave']",
    "boton_entrar": "button[type='submit']",
    "campo_fecha": "input[name='fecha']",
    "boton_descargar": "a#descargar-csv",
    "senal_login_ok": "text=Movimientos del día",
}


@dataclass
class FuentePortalRPA:
    url: str
    usuario: str
    clave: str
    ruta_evidencia: Path
    selectores: dict = field(default_factory=lambda: dict(SELECTORES_PORTAL_V1))
    timeout_ms: int = 15_000
    nombre: str = "portal_rpa"

    def descargar_csv(self, fecha_operacion: date) -> str:
        from playwright.sync_api import sync_playwright

        self.ruta_evidencia.mkdir(parents=True, exist_ok=True)
        s = self.selectores
        with sync_playwright() as p:
            navegador = p.chromium.launch(headless=True)
            pagina = navegador.new_page(accept_downloads=True)
            pagina.set_default_timeout(self.timeout_ms)
            pagina.goto(f"{self.url}/login")
            pagina.fill(s["campo_usuario"], self.usuario)
            pagina.fill(s["campo_clave"], self.clave)
            pagina.click(s["boton_entrar"])
            pagina.wait_for_selector(s["senal_login_ok"])
            pagina.fill(s["campo_fecha"], fecha_operacion.isoformat())
            with pagina.expect_download() as descarga:
                pagina.click(s["boton_descargar"])
            destino = self.ruta_evidencia / f"banco_{fecha_operacion.isoformat()}.csv"
            descarga.value.save_as(destino)
            pagina.screenshot(path=str(self.ruta_evidencia / f"portal_{fecha_operacion.isoformat()}.png"))
            navegador.close()
        return destino.read_text(encoding="utf-8")

    def probar_contrato(self) -> tuple[bool, str]:
        """G-CONTRATO-PORTAL: ¿siguen existiendo los elementos que usamos?"""
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                navegador = p.chromium.launch(headless=True)
                pagina = navegador.new_page()
                pagina.set_default_timeout(self.timeout_ms)
                pagina.goto(f"{self.url}/login")
                for nombre in ("campo_usuario", "campo_clave", "boton_entrar"):
                    if pagina.locator(self.selectores[nombre]).count() == 0:
                        return False, f"selector {nombre} no encontrado en el portal"
                navegador.close()
            return True, "login del portal con los selectores esperados"
        except Exception as e:  # noqa: BLE001
            return False, f"portal inaccesible: {e}"


@dataclass
class FuenteAPIBanco:
    """Adaptador API-First. Hoy apunta al mock; cuando el banco libere su API,
    cambia este archivo y la variable FUENTE_BANCO=api."""

    url: str
    token: str
    nombre: str = "api"

    def descargar_csv(self, fecha_operacion: date) -> str:
        r = httpx.get(
            f"{self.url}/movimientos",
            params={"fecha": fecha_operacion.isoformat()},
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
        )
        r.raise_for_status()
        filas = r.json()["movimientos"]
        encabezado = "referencia,fecha,monto,moneda,tipo,comercio_id,tarjeta,descripcion"
        lineas = [encabezado] + [
            f"{m['referencia']},{m['fecha']},{m['monto']},{m['moneda']},{m['tipo']},{m['comercio_id']},{m.get('tarjeta', '')},{m.get('descripcion', '')}"
            for m in filas
        ]
        return "\n".join(lineas) + "\n"


@dataclass
class FuenteArchivoManual:
    """Modo degradado: el analista descarga el CSV a mano y el pipeline sigue desde ahí."""

    ruta: Path
    nombre: str = "archivo"

    def descargar_csv(self, fecha_operacion: date) -> str:
        return Path(self.ruta).read_text(encoding="utf-8")
