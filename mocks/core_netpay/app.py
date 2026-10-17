"""Core NetPay (simulado): transacciones, API de liberación de liquidación con idempotencia,
UI de bloqueo de saldo (lo único que hoy existe para bloquear) y, detrás de un flag,
la API de bloqueo que se le pediría al equipo del Core.

CORE_FALLAS_PROBABILIDAD=0.1 hace que el 10% de las liberaciones fallen con 503 al primer intento,
para ver reintentos e idempotencia trabajando.
"""

from __future__ import annotations

import os
import random
import secrets
from dataclasses import asdict
from datetime import date

from fastapi import Cookie, FastAPI, Form, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from mocks.datos_semilla import Dia, generar_dia

TOKEN_API = os.environ.get("CORE_API_TOKEN", "token-core-demo")
UI_USUARIO = os.environ.get("CORE_UI_USUARIO", "analista")
UI_CLAVE = os.environ.get("CORE_UI_CLAVE", "core-demo")
API_BLOQUEO = os.environ.get("CORE_API_BLOQUEO_HABILITADA", "0") == "1"
PROB_FALLA = float(os.environ.get("CORE_FALLAS_PROBABILIDAD", "0"))

app = FastAPI(title="Core NetPay (mock)")
DIAS: dict[str, Dia] = {}
COMERCIOS: dict[str, dict] = {}  # comercio_id → {bloqueado, saldo_bloqueado_centavos, bloqueos: [...]}
CLAVES_IDEMPOTENCIA: dict[str, dict] = {}
FALLAS_YA_DADAS: set[str] = set()
SESIONES: set[str] = set()
rnd = random.Random(7)


def _dia(fecha: date) -> Dia:
    k = fecha.isoformat()
    if k not in DIAS:
        d = generar_dia(fecha)
        DIAS[k] = d
        for c in d.comercios_bloqueados:
            _comercio(c)["bloqueado"] = True
    return DIAS[k]


def _comercio(cid: str) -> dict:
    return COMERCIOS.setdefault(cid, {"comercio_id": cid, "bloqueado": False, "saldo_bloqueado_centavos": 0, "bloqueos": []})


def _auth(authorization: str) -> None:
    if authorization != f"Bearer {TOKEN_API}":
        raise HTTPException(401, "token inválido")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/transacciones")
def transacciones(fecha: date = Query(...), authorization: str = Header("")):
    _auth(authorization)
    d = _dia(fecha)
    out = []
    for t in d.transacciones:
        fila = asdict(t)
        fila["fecha"] = t.fecha.isoformat()
        fila["comercio_bloqueado"] = _comercio(t.comercio_id)["bloqueado"]
        out.append(fila)
    return {"fecha": fecha.isoformat(), "transacciones": out}


class Liberar(BaseModel):
    transaccion_id: str


def _buscar_tx(tx_id: str):
    for d in DIAS.values():
        for t in d.transacciones:
            if t.id == tx_id:
                return t
    raise HTTPException(404, "transacción no existe")


@app.post("/api/liquidaciones/liberar")
def liberar(cuerpo: Liberar, authorization: str = Header(""), idempotency_key: str = Header("")):
    _auth(authorization)
    if not idempotency_key:
        raise HTTPException(400, "falta Idempotency-Key")
    if idempotency_key in CLAVES_IDEMPOTENCIA:
        return CLAVES_IDEMPOTENCIA[idempotency_key] | {"idempotente": True}
    if PROB_FALLA and idempotency_key not in FALLAS_YA_DADAS and rnd.random() < PROB_FALLA:
        FALLAS_YA_DADAS.add(idempotency_key)
        raise HTTPException(503, "core temporalmente no disponible")
    t = _buscar_tx(cuerpo.transaccion_id)
    if t.estado == "LIQUIDADA":
        raise HTTPException(409, "ya liquidada")
    if t.estado == "BLOQUEADA" or _comercio(t.comercio_id)["bloqueado"]:
        raise HTTPException(422, "comercio con saldo bloqueado")
    t.estado = "LIQUIDADA"
    resp = {"transaccion_id": t.id, "estado": t.estado, "monto_centavos": t.monto_centavos}
    CLAVES_IDEMPOTENCIA[idempotency_key] = resp
    return resp | {"idempotente": False}


@app.get("/api/comercios/{comercio_id}")
def comercio(comercio_id: str, authorization: str = Header("")):
    _auth(authorization)
    return _comercio(comercio_id)


class Bloqueo(BaseModel):
    referencia: str
    monto_centavos: int
    motivo: str


def _bloquear(comercio_id: str, referencia: str, monto_centavos: int, motivo: str, via: str) -> tuple[dict, bool]:
    c = _comercio(comercio_id)
    # Escenario B tal como opera hoy: el contracargo bloquea el saldo del comercio; no se le libera dinero
    # hasta que una persona lo desbloquee. El monto queda registrado para la gestión.
    ya = any(b["referencia"] == referencia for b in c["bloqueos"])
    if not ya:
        c["bloqueado"] = True
        c["saldo_bloqueado_centavos"] += monto_centavos
        c["bloqueos"].append({"referencia": referencia, "monto_centavos": monto_centavos, "motivo": motivo, "via": via})
        for d in DIAS.values():
            for t in d.transacciones:
                if t.referencia == referencia:
                    t.estado = "BLOQUEADA"
    return c, ya


@app.post("/api/comercios/{comercio_id}/bloqueos")
def bloqueo_api(comercio_id: str, cuerpo: Bloqueo, authorization: str = Header(""), idempotency_key: str = Header("")):
    """No existe hoy en el Core real. Se habilita con CORE_API_BLOQUEO_HABILITADA=1 para demostrar la transición."""
    _auth(authorization)
    if not API_BLOQUEO:
        raise HTTPException(404, "el Core aún no expone API de bloqueo; usar la UI")
    c, ya = _bloquear(comercio_id, cuerpo.referencia, cuerpo.monto_centavos, cuerpo.motivo, "api")
    return {"comercio": c, "idempotente": ya}


# --- UI del Core (lo que hoy usa el analista para bloquear) ---------------


@app.get("/ui/login", response_class=HTMLResponse)
def ui_login():
    return """<html><head><title>Core NetPay</title></head><body style="font-family:Arial">
<h2>Core NetPay — acceso</h2><form method="post" action="/ui/login">
<label>Usuario <input name="usuario"></label><br><label>Clave <input name="clave" type="password"></label><br>
<button type="submit">Entrar</button></form></body></html>"""


@app.post("/ui/login")
def ui_login_post(usuario: str = Form(...), clave: str = Form(...)):
    if usuario != UI_USUARIO or clave != UI_CLAVE:
        raise HTTPException(401, "credenciales inválidas")
    sid = secrets.token_hex(8)
    SESIONES.add(sid)
    r = RedirectResponse("/ui/comercios", status_code=303)
    r.set_cookie("sesion_core", sid, httponly=True)
    return r


def _ui_sesion(s: str | None) -> None:
    if not s or s not in SESIONES:
        raise HTTPException(401, "sesión inválida")


@app.get("/ui/comercios", response_class=HTMLResponse)
def ui_comercios(sesion_core: str | None = Cookie(None)):
    _ui_sesion(sesion_core)
    filas = "".join(
        f"<li><a href='/ui/comercios/{c['comercio_id']}'>{c['comercio_id']}</a> {'🔒' if c['bloqueado'] else ''}</li>"
        for c in sorted(COMERCIOS.values(), key=lambda c: c["comercio_id"])
    )
    return f"<html><body style='font-family:Arial'><h2>Comercios</h2><ul>{filas}</ul></body></html>"


@app.get("/ui/comercios/{comercio_id}", response_class=HTMLResponse)
def ui_comercio(comercio_id: str, sesion_core: str | None = Cookie(None)):
    _ui_sesion(sesion_core)
    c = _comercio(comercio_id)
    return f"""<html><head><title>Comercio {comercio_id}</title></head><body style="font-family:Arial">
<h2>Comercio {comercio_id}</h2>
<p>Estado: {"BLOQUEADO" if c["bloqueado"] else "ACTIVO"} · saldo bloqueado ${c["saldo_bloqueado_centavos"] / 100:,.2f}</p>
<h3>Bloquear saldo por contracargo</h3>
<form method="post" action="/ui/comercios/{comercio_id}/bloquear">
 <label>Referencia <input name="referencia"></label><br>
 <label>Monto <input name="monto"></label><br>
 <label>Motivo <input name="motivo"></label><br>
 <button id="bloquear" type="submit">Bloquear saldo</button>
</form></body></html>"""


@app.post("/ui/comercios/{comercio_id}/bloquear", response_class=HTMLResponse)
def ui_bloquear(
    comercio_id: str,
    referencia: str = Form(...),
    monto: str = Form(...),
    motivo: str = Form(""),
    sesion_core: str | None = Cookie(None),
):
    _ui_sesion(sesion_core)
    centavos = int(round(float(monto.replace(",", "")) * 100))
    c, ya = _bloquear(comercio_id, referencia.upper(), centavos, motivo, "ui")
    mensaje = "El saldo de este comercio ya estaba bloqueado por esa referencia." if ya else "Saldo bloqueado correctamente."
    return f"""<html><body style="font-family:Arial"><h2>Comercio {comercio_id}</h2>
<p class="resultado">{mensaje}</p>
<p>Saldo bloqueado: ${c["saldo_bloqueado_centavos"] / 100:,.2f} · referencia {referencia.upper()} · motivo: {motivo}</p>
<a href="/ui/comercios/{comercio_id}">Volver</a></body></html>"""


@app.post("/admin/reset")
def reset(authorization: str = Header("")):
    _auth(authorization)
    DIAS.clear()
    COMERCIOS.clear()
    CLAVES_IDEMPOTENCIA.clear()
    FALLAS_YA_DADAS.clear()
    return {"ok": True}
