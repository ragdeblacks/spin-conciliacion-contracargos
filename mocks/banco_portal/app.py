"""Portal web legacy del banco adquirente (simulado) + la API que promete para el próximo año.

BANCO_PORTAL_VERSION=2 simula el cambio de portal (otros nombres de campos) para probar G-CONTRATO-PORTAL.
"""

from __future__ import annotations

import os
import secrets
from datetime import date

from fastapi import Cookie, FastAPI, Form, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from mocks.datos_semilla import csv_banco, generar_dia

USUARIO = os.environ.get("BANCO_PORTAL_USUARIO", "operaciones")
CLAVE = os.environ.get("BANCO_PORTAL_CLAVE", "portal-demo")
TOKEN_API = os.environ.get("BANCO_API_TOKEN", "token-banco-demo")
VERSION = os.environ.get("BANCO_PORTAL_VERSION", "1")
SESIONES: set[str] = set()

app = FastAPI(title="Portal Banco Adquirente (mock)")

CAMPOS = {"1": ("usuario", "clave"), "2": ("user", "pwd")}[VERSION]


@app.get("/login", response_class=HTMLResponse)
def login_form():
    u, c = CAMPOS
    return f"""<html><head><title>Banco Adquirente - Portal de Comercios</title></head>
<body style="font-family:Arial"><h2>Portal de Comercios (v{VERSION})</h2>
<form method="post" action="/login">
 <label>Usuario <input name="{u}"></label><br>
 <label>Contraseña <input name="{c}" type="password"></label><br>
 <button type="submit">Entrar</button>
</form></body></html>"""


@app.post("/login")
async def login(usuario: str = Form(None), clave: str = Form(None), user: str = Form(None), pwd: str = Form(None)):
    u, c = (usuario, clave) if VERSION == "1" else (user, pwd)
    if u != USUARIO or c != CLAVE:
        raise HTTPException(401, "credenciales inválidas")
    sid = secrets.token_hex(8)
    SESIONES.add(sid)
    r = RedirectResponse("/movimientos", status_code=303)
    r.set_cookie("sesion", sid, httponly=True)
    return r


def _exigir_sesion(sesion: str | None) -> None:
    if not sesion or sesion not in SESIONES:
        raise HTTPException(401, "sesión inválida")


@app.get("/movimientos", response_class=HTMLResponse)
def movimientos(sesion: str | None = Cookie(None)):
    _exigir_sesion(sesion)
    hoy = date.today().isoformat()
    return f"""<html><head><title>Movimientos</title></head><body style="font-family:Arial">
<h2>Movimientos del día</h2>
<p>Seleccione la fecha de operación y descargue el archivo.</p>
<label>Fecha <input name="fecha" id="fecha" value="{hoy}"></label>
<a id="descargar-csv" href="/movimientos/descargar?fecha={hoy}">Descargar CSV</a>
<script>
document.getElementById('fecha').addEventListener('input', e => {{
  document.getElementById('descargar-csv').href = '/movimientos/descargar?fecha=' + e.target.value;
}});
</script></body></html>"""


@app.get("/movimientos/descargar")
def descargar(fecha: date = Query(...), sesion: str | None = Cookie(None)):
    _exigir_sesion(sesion)
    contenido = csv_banco(generar_dia(fecha))
    return PlainTextResponse(
        contenido,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="movimientos_{fecha.isoformat()}.csv"'},
    )


@app.get("/api/v2/movimientos")
def api_movimientos(fecha: date = Query(...), authorization: str = Header("")):
    """La API que el banco promete liberar el próximo año. Hoy, el mock que permite construir el adaptador desde ya."""
    if authorization != f"Bearer {TOKEN_API}":
        raise HTTPException(401, "token inválido")
    dia = generar_dia(fecha)
    return {
        "fecha": fecha.isoformat(),
        "movimientos": [
            {
                "referencia": m.referencia,
                "fecha": m.fecha.isoformat(),
                "monto": f"{m.monto_centavos / 100:.2f}",
                "moneda": m.moneda,
                "tipo": m.tipo,
                "comercio_id": m.comercio_id,
                "tarjeta": m.tarjeta,
                "descripcion": m.descripcion,
            }
            for m in dia.movimientos
        ],
    }


@app.get("/health")
def health():
    return {"ok": True, "version_portal": VERSION}
