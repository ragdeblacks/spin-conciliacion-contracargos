"""Genera 30 días de operación simulada en un libro mayor para ver el tablero lleno.

Reproduce el plan de adopción: 10 días en sombra, 10 en asistida (con aprobaciones) y 10 en autónoma,
con incidencias plantadas (Core caído, cambio de esquema del portal, una liberación fallida) y las
resoluciones que harían los analistas. Los tiempos se ajustan a horario de producción (05:00).

Uso:  uv run python scripts/poblar_demo.py [ruta_sqlite] [--hoy 2026-10-16]
"""

from __future__ import annotations

import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from conciliador.config import Configuracion  # noqa: E402
from conciliador.dominio.modelos import Accion, EstadoEjecucion  # noqa: E402
from conciliador.libro_mayor import LibroMayor  # noqa: E402
from conciliador.orquestador import Adaptadores, Orquestador  # noqa: E402
from mocks.datos_semilla import csv_con_esquema_roto, generar_dia  # noqa: E402
from tests.fakes import AsistenteFalso, CoreFalso, FuenteFalsa, NotificadorFalso  # noqa: E402

ANALISTAS = ["Ana López", "Carlos Ruiz", "María Torres"]
rnd = random.Random(42)


def main() -> None:
    argv = sys.argv[1:]
    hoy = date.today()
    if "--hoy" in argv:
        i = argv.index("--hoy")
        hoy = date.fromisoformat(argv[i + 1])
        del argv[i : i + 2]
    ruta = Path(argv[0]) if argv else RAIZ / "datos" / "libro_mayor_demo.sqlite"
    if ruta.exists():
        ruta.unlink()
    libro = LibroMayor(ruta)
    cfg = Configuracion(ruta_libro_mayor=ruta, token_core="t", usuario_portal="u", clave_portal="p", usuario_core_ui="u", clave_core_ui="p")

    for n in range(30, 0, -1):
        fecha = hoy - timedelta(days=n)
        if fecha.weekday() == 6:  # el domingo no hay corte del banco
            continue
        dia_n = 30 - n
        cfg.modo = "sombra" if dia_n < 10 else ("asistida" if dia_n < 20 else "autonoma")
        dia = generar_dia(fecha, n_ventas=rnd.randint(380, 560))
        core = CoreFalso(dia)
        fuente = FuenteFalsa(dia)
        if dia_n == 7:
            core.vivo = False  # Core caído
        if dia_n == 15:
            fuente.csv_override = csv_con_esquema_roto(dia)  # el banco cambió el portal
        if dia_n == 24:
            core.fallar_liberaciones = {dia.transacciones[-12].id}
        orq = Orquestador(cfg, libro, Adaptadores(fuente, core, core, core, AsistenteFalso(), NotificadorFalso()))
        r = orq.correr(fecha, hoy=fecha + timedelta(days=1))
        inicio = datetime.combine(fecha + timedelta(days=1), datetime.min.time(), tzinfo=UTC).replace(hour=11, minute=0)  # 05:00 CDMX
        _reubicar(libro, r.corrida_id, inicio, rnd)

        if r.estado != "CERRADA":
            for i in libro.incidencias(solo_abiertas=True):
                if i["corrida_id"] == r.corrida_id:
                    nota = (
                        "Se ajustaron los selectores del portal y se repitió con carga manual del CSV"
                        if dia_n == 15
                        else "Se repitió la corrida a las 06:10 tras recuperar el Core"
                    )
                    libro.resolver_incidencia(i["id"], rnd.choice(ANALISTAS), nota)
            continue
        if cfg.modo == "asistida" or any(d.estado_ejecucion == EstadoEjecucion.PENDIENTE_APROBACION for d in r.decisiones):
            orq.aprobar_y_ejecutar(r.corrida_id, "Ana López (supervisora)")
            libro.con.execute(
                "UPDATE aprobaciones SET momento=? WHERE decision_id IN (SELECT id FROM decisiones WHERE corrida_id=?)",
                ((inicio + timedelta(minutes=rnd.randint(12, 45))).isoformat(timespec="seconds"), r.corrida_id),
            )
        # el analista resuelve casi todas las excepciones durante la mañana
        for d in [d for d in r.decisiones if d.accion == Accion.EXCEPCION]:
            if rnd.random() < (0.97 if n > 2 else 0.5):
                sug = libro.con.execute("SELECT accion_sugerida FROM sugerencias WHERE decision_id=?", (d.id,)).fetchone()
                accion = sug["accion_sugerida"] if sug and rnd.random() < 0.78 else rnd.choice(["LIQUIDAR_MANUAL", "REVISAR_CON_COMERCIO", "ESCALAR_AL_BANCO"])
                libro.resolver_excepcion(d.id, accion, rnd.choice(ANALISTAS))
                libro.con.execute(
                    "UPDATE resoluciones SET momento=? WHERE decision_id=?",
                    ((inicio + timedelta(minutes=rnd.randint(40, 200))).isoformat(timespec="seconds"), d.id),
                )
        for i in libro.incidencias(solo_abiertas=True):
            if i["corrida_id"] == r.corrida_id and i["tipo"] != "CONTRACARGO_SIN_MATCH" and n > 2:
                libro.resolver_incidencia(i["id"], rnd.choice(ANALISTAS), "Revisado y resuelto a mano; registrado en el Core")
            elif i["corrida_id"] == r.corrida_id and i["tipo"] == "CONTRACARGO_SIN_MATCH" and (n > 3 or rnd.random() < 0.5):
                libro.resolver_incidencia(i["id"], rnd.choice(ANALISTAS), "Escalado al banco; aclaración recibida")
        libro.con.commit()
    print(
        f"libro mayor de demostración en {ruta}: {len(libro.corridas())} corridas, "
        f"{len(libro.incidencias())} incidencias ({len(libro.incidencias(solo_abiertas=True))} abiertas)"
    )


def _reubicar(libro: LibroMayor, corrida_id: int, inicio: datetime, rnd: random.Random) -> None:
    """Mueve todas las marcas de tiempo de la corrida a un horario de producción realista."""
    c = libro.corrida(corrida_id)
    real = datetime.fromisoformat(c["inicio"])
    delta = inicio - real

    def mover(iso):
        return (datetime.fromisoformat(iso) + delta).isoformat(timespec="seconds") if iso else None

    # la corrida real tarda milisegundos con fakes: se estira a una duración creíble (2 a 6 min)
    dur = timedelta(seconds=rnd.randint(120, 360))
    fin = inicio + dur if c["fin"] else None
    libro.con.execute(
        "UPDATE corridas SET inicio=?, fin=? WHERE id=?", (inicio.isoformat(timespec="seconds"), fin.isoformat(timespec="seconds") if fin else None, corrida_id)
    )
    for tabla, col in (("decisiones", "creada"), ("gates", "momento"), ("sugerencias", "momento"), ("incidencias", "abierta")):
        for f in libro.consultar(f"SELECT id, {col} v FROM {tabla} WHERE corrida_id=?", (corrida_id,)):
            libro.con.execute(f"UPDATE {tabla} SET {col}=? WHERE id=?", (mover(f["v"]), f["id"]))
    acciones = libro.consultar("SELECT clave_idempotencia k, tipo FROM acciones WHERE corrida_id=? ORDER BY creada", (corrida_id,))
    for idx, a in enumerate(acciones):
        # bloqueos primero (minutos 1 a 9), liquidaciones después
        t = inicio + timedelta(seconds=30 + idx * (dur.total_seconds() - 60) / max(len(acciones), 1))
        libro.con.execute(
            "UPDATE acciones SET creada=?, actualizada=? WHERE clave_idempotencia=?",
            (t.isoformat(timespec="seconds"), (t + timedelta(seconds=2)).isoformat(timespec="seconds"), a["k"]),
        )
    libro.con.commit()


if __name__ == "__main__":
    main()
