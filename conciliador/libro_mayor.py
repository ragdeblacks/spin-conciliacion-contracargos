"""Libro mayor: registro append-only de corridas, decisiones, acciones y gates.

Es la fuente de verdad para idempotencia y auditoría. SQLite en el prototipo;
en producción, Postgres con la misma interfaz.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from .dominio.modelos import Accion, Decision, EstadoEjecucion, ResultadoGate

ESQUEMA = """
CREATE TABLE IF NOT EXISTS corridas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha_operacion TEXT NOT NULL,
  modo TEXT NOT NULL,
  fuente TEXT NOT NULL,
  inicio TEXT NOT NULL,
  fin TEXT,
  estado TEXT NOT NULL,
  resumen TEXT
);
CREATE TABLE IF NOT EXISTS decisiones (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id INTEGER NOT NULL REFERENCES corridas(id),
  referencia TEXT NOT NULL,
  tipo TEXT NOT NULL,
  comercio_id TEXT NOT NULL,
  monto_centavos INTEGER NOT NULL,
  fecha_movimiento TEXT NOT NULL,
  accion TEXT NOT NULL,
  motivo TEXT NOT NULL,
  regla TEXT NOT NULL,
  nota TEXT,
  transaccion_id TEXT,
  requiere_aprobacion INTEGER NOT NULL DEFAULT 0,
  estado_ejecucion TEXT NOT NULL,
  clave_idempotencia TEXT,
  candidatos TEXT,
  creada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS acciones (
  clave_idempotencia TEXT PRIMARY KEY,
  corrida_id INTEGER NOT NULL,
  decision_id INTEGER NOT NULL,
  tipo TEXT NOT NULL,
  estado TEXT NOT NULL,          -- INTENTADA | CONFIRMADA | FALLIDA
  intentos INTEGER NOT NULL DEFAULT 0,
  respuesta TEXT,
  evidencia TEXT,
  creada TEXT NOT NULL,
  actualizada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aprobaciones (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decision_id INTEGER NOT NULL,
  aprobador TEXT NOT NULL,
  momento TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id INTEGER NOT NULL,
  gate TEXT NOT NULL,
  ok INTEGER NOT NULL,
  critico INTEGER NOT NULL,
  detalle TEXT,
  momento TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sugerencias (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id INTEGER NOT NULL,
  decision_id INTEGER NOT NULL,
  proveedor TEXT NOT NULL,
  modelo TEXT,
  version_prompt TEXT,
  causa_probable TEXT,
  accion_sugerida TEXT,
  confianza REAL,
  explicacion TEXT,
  tokens_entrada INTEGER,
  tokens_salida INTEGER,
  valida INTEGER NOT NULL,
  decision_humana TEXT,
  momento TEXT NOT NULL
);
"""


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class LibroMayor:
    def __init__(self, ruta: Path | str):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.ruta)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)

    # --- corridas ---------------------------------------------------------
    def abrir_corrida(self, fecha_operacion: date, modo: str, fuente: str) -> int:
        cur = self.con.execute(
            "INSERT INTO corridas (fecha_operacion, modo, fuente, inicio, estado) VALUES (?,?,?,?,?)",
            (fecha_operacion.isoformat(), modo, fuente, _ahora(), "EN_CURSO"),
        )
        self.con.commit()
        return int(cur.lastrowid)

    def cerrar_corrida(self, corrida_id: int, estado: str, resumen: dict) -> None:
        self.con.execute(
            "UPDATE corridas SET fin=?, estado=?, resumen=? WHERE id=?",
            (_ahora(), estado, json.dumps(resumen, ensure_ascii=False), corrida_id),
        )
        self.con.commit()

    def corrida(self, corrida_id: int) -> dict:
        fila = self.con.execute("SELECT * FROM corridas WHERE id=?", (corrida_id,)).fetchone()
        if not fila:
            raise KeyError(f"corrida {corrida_id} no existe")
        d = dict(fila)
        d["resumen"] = json.loads(d["resumen"]) if d["resumen"] else {}
        return d

    def corridas(self) -> list[dict]:
        return [
            dict(f)
            for f in self.con.execute("SELECT id, fecha_operacion, modo, fuente, inicio, fin, estado FROM corridas ORDER BY id")
        ]

    def promedio_movimientos(self, ultimas: int = 10) -> float | None:
        filas = self.con.execute(
            "SELECT resumen FROM corridas WHERE estado='CERRADA' AND resumen IS NOT NULL ORDER BY id DESC LIMIT ?", (ultimas,)
        ).fetchall()
        totales = [json.loads(f["resumen"]).get("TOTAL", 0) for f in filas]
        totales = [t for t in totales if t]
        return sum(totales) / len(totales) if totales else None

    def tasa_excepciones_historica(self, ultimas: int = 10) -> float | None:
        filas = self.con.execute(
            "SELECT resumen FROM corridas WHERE estado='CERRADA' AND resumen IS NOT NULL ORDER BY id DESC LIMIT ?", (ultimas,)
        ).fetchall()
        tasas = []
        for f in filas:
            r = json.loads(f["resumen"])
            if r.get("TOTAL"):
                tasas.append(r.get("EXCEPCION", 0) / r["TOTAL"])
        return sum(tasas) / len(tasas) if tasas else None

    # --- decisiones -------------------------------------------------------
    def registrar_decisiones(self, corrida_id: int, decisiones: list[Decision]) -> None:
        for d in decisiones:
            cur = self.con.execute(
                """INSERT INTO decisiones (corrida_id, referencia, tipo, comercio_id, monto_centavos, fecha_movimiento,
                   accion, motivo, regla, nota, transaccion_id, requiere_aprobacion, estado_ejecucion, clave_idempotencia,
                   candidatos, creada) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    corrida_id,
                    d.movimiento.referencia,
                    d.movimiento.tipo.value,
                    d.movimiento.comercio_id,
                    d.movimiento.monto_centavos,
                    d.movimiento.fecha.isoformat(),
                    d.accion.value,
                    d.motivo.value,
                    d.regla,
                    d.nota,
                    d.transaccion.id if d.transaccion else None,
                    int(d.requiere_aprobacion),
                    d.estado_ejecucion.value,
                    d.clave_idempotencia if d.es_ejecutable else None,
                    json.dumps([asdict(c) | {"fecha": c.fecha.isoformat()} for c in d.candidatos], default=str),
                    _ahora(),
                ),
            )
            d.id = int(cur.lastrowid)
        self.con.commit()

    def actualizar_estado_decision(self, decision_id: int, estado: EstadoEjecucion) -> None:
        self.con.execute("UPDATE decisiones SET estado_ejecucion=? WHERE id=?", (estado.value, decision_id))
        self.con.commit()

    def decisiones_de(self, corrida_id: int) -> list[dict]:
        return [dict(f) for f in self.con.execute("SELECT * FROM decisiones WHERE corrida_id=? ORDER BY id", (corrida_id,))]

    def aprobar(self, decision_id: int, aprobador: str) -> None:
        self.con.execute(
            "INSERT INTO aprobaciones (decision_id, aprobador, momento) VALUES (?,?,?)", (decision_id, aprobador, _ahora())
        )
        self.con.execute("UPDATE decisiones SET estado_ejecucion=? WHERE id=?", (EstadoEjecucion.APROBADA.value, decision_id))
        self.con.commit()

    # --- acciones (idempotencia) ------------------------------------------
    def claves_confirmadas(self) -> set[str]:
        return {
            f["clave_idempotencia"] for f in self.con.execute("SELECT clave_idempotencia FROM acciones WHERE estado='CONFIRMADA'")
        }

    def accion(self, clave: str) -> dict | None:
        f = self.con.execute("SELECT * FROM acciones WHERE clave_idempotencia=?", (clave,)).fetchone()
        return dict(f) if f else None

    def intentar_accion(self, clave: str, corrida_id: int, decision_id: int, tipo: Accion) -> None:
        """Se escribe ANTES de llamar al sistema destino. Si el proceso muere, queda rastro."""
        ahora = _ahora()
        self.con.execute(
            """INSERT INTO acciones (clave_idempotencia, corrida_id, decision_id, tipo, estado, intentos, creada, actualizada)
               VALUES (?,?,?,?,'INTENTADA',1,?,?)
               ON CONFLICT(clave_idempotencia) DO UPDATE SET intentos=intentos+1, estado='INTENTADA', actualizada=excluded.actualizada""",
            (clave, corrida_id, decision_id, tipo.value, ahora, ahora),
        )
        self.con.commit()

    def confirmar_accion(self, clave: str, respuesta: dict, evidencia: str | None) -> None:
        self.con.execute(
            "UPDATE acciones SET estado='CONFIRMADA', respuesta=?, evidencia=?, actualizada=? WHERE clave_idempotencia=?",
            (json.dumps(respuesta, default=str), evidencia, _ahora(), clave),
        )
        self.con.commit()

    def fallar_accion(self, clave: str, error: str) -> None:
        self.con.execute(
            "UPDATE acciones SET estado='FALLIDA', respuesta=?, actualizada=? WHERE clave_idempotencia=?",
            (json.dumps({"error": error}), _ahora(), clave),
        )
        self.con.commit()

    def acciones_de(self, corrida_id: int) -> list[dict]:
        return [dict(f) for f in self.con.execute("SELECT * FROM acciones WHERE corrida_id=? ORDER BY creada", (corrida_id,))]

    # --- gates y sugerencias ----------------------------------------------
    def registrar_gate(self, corrida_id: int, r: ResultadoGate) -> None:
        self.con.execute(
            "INSERT INTO gates (corrida_id, gate, ok, critico, detalle, momento) VALUES (?,?,?,?,?,?)",
            (corrida_id, r.gate, int(r.ok), int(r.critico), r.detalle, _ahora()),
        )
        self.con.commit()

    def gates_de(self, corrida_id: int) -> list[dict]:
        return [dict(f) for f in self.con.execute("SELECT * FROM gates WHERE corrida_id=? ORDER BY id", (corrida_id,))]

    def registrar_sugerencia(self, corrida_id: int, decision_id: int, s) -> None:
        self.con.execute(
            """INSERT INTO sugerencias (corrida_id, decision_id, proveedor, modelo, version_prompt, causa_probable, accion_sugerida,
               confianza, explicacion, tokens_entrada, tokens_salida, valida, momento) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                corrida_id,
                decision_id,
                s.proveedor,
                s.modelo,
                s.version_prompt,
                s.causa_probable,
                s.accion_sugerida,
                s.confianza,
                s.explicacion,
                s.tokens_entrada,
                s.tokens_salida,
                int(s.valida),
                _ahora(),
            ),
        )
        self.con.commit()

    def sugerencias_de(self, corrida_id: int) -> list[dict]:
        return [dict(f) for f in self.con.execute("SELECT * FROM sugerencias WHERE corrida_id=? ORDER BY id", (corrida_id,))]

    def tokens_llm_hoy(self) -> int:
        hoy = date.today().isoformat()
        f = self.con.execute(
            "SELECT COALESCE(SUM(tokens_entrada+tokens_salida),0) AS t FROM sugerencias WHERE momento LIKE ?", (f"{hoy}%",)
        ).fetchone()
        return int(f["t"])

    def cerrar(self) -> None:
        self.con.close()
