"""Generador determinista de datos de prueba con los casos feos incluidos.

Mismo (fecha, semilla) → mismos datos en el portal del banco y en el Core,
sin archivo compartido. Útil para demos y para los tests.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

COMERCIOS = [f"COM-{i:04d}" for i in range(1, 161)]


@dataclass
class TxCore:
    id: str
    referencia: str
    fecha: date
    monto_centavos: int
    moneda: str
    comercio_id: str
    estado: str = "PENDIENTE_LIQUIDACION"


@dataclass
class MovBanco:
    referencia: str
    fecha: date
    monto_centavos: int
    moneda: str
    tipo: str
    comercio_id: str
    tarjeta: str = ""
    descripcion: str = ""


@dataclass
class Dia:
    fecha: date
    transacciones: list[TxCore]
    movimientos: list[MovBanco]
    comercios_bloqueados: set[str] = field(default_factory=set)
    casos: dict[str, list[str]] = field(default_factory=dict)  # qué referencia cubre qué caso (para tests)


def generar_dia(fecha: date, semilla: int = 2026, n_ventas: int = 190) -> Dia:
    rnd = random.Random(f"{semilla}-{fecha.isoformat()}")
    tag = fecha.strftime("%m%d")
    txs: list[TxCore] = []
    for i in range(1, n_ventas + 1):
        monto = rnd.choice([rnd.randint(5_000, 80_000), rnd.randint(80_000, 800_000)])
        txs.append(
            TxCore(
                id=f"tx-{tag}-{i:05d}",
                referencia=f"SPN{tag}{i:05d}",
                fecha=fecha,
                monto_centavos=monto,
                moneda="MXN",
                comercio_id=rnd.choice(COMERCIOS),
            )
        )

    casos: dict[str, list[str]] = {}
    movs: list[MovBanco] = []

    def mov(t: TxCore, **kw) -> MovBanco:
        base = dict(
            referencia=t.referencia,
            fecha=t.fecha,
            monto_centavos=t.monto_centavos,
            moneda=t.moneda,
            tipo="VENTA",
            comercio_id=t.comercio_id,
            tarjeta=f"4111 **** **** {rnd.randint(1000, 9999)}",
            descripcion="VENTA TPV",
        )
        base.update(kw)
        return MovBanco(**base)

    def marcar(caso: str, ref: str) -> None:
        casos.setdefault(caso, []).append(ref)

    idx = 0

    def siguiente() -> TxCore:
        nonlocal idx
        t = txs[idx]
        idx += 1
        return t

    # 1 monto alto (> $50,000) → liquidar con doble control
    t = siguiente()
    t.monto_centavos = 7_500_000
    movs.append(mov(t))
    marcar("MONTO_ALTO", t.referencia)
    # 3 monto diferente (comisión / propina)
    for delta in (-250, 1_500, -1_000):
        t = siguiente()
        movs.append(mov(t, monto_centavos=t.monto_centavos + delta))
        marcar("MONTO_DIFERENTE", t.referencia)
    # 2 sin match: una con candidato (misma referencia truncada y monto), otra sin nada
    t = siguiente()
    movs.append(mov(t, referencia=t.referencia[:6] + "X" + t.referencia[7:]))
    marcar("SIN_MATCH_CON_CANDIDATO", movs[-1].referencia)
    movs.append(MovBanco(f"ZZZ{tag}99999", fecha, 12_345, "MXN", "VENTA", "COM-0099", descripcion="VENTA TPV"))
    marcar("SIN_MATCH_SIN_CANDIDATO", movs[-1].referencia)
    # 2 duplicados en archivo
    for _ in range(2):
        t = siguiente()
        movs.append(mov(t))
        movs.append(mov(t))
        marcar("DUPLICADO", t.referencia)
    # 2 ya liquidadas en el Core (el analista ya lo hizo)
    for _ in range(2):
        t = siguiente()
        t.estado = "LIQUIDADA"
        movs.append(mov(t))
        marcar("YA_LIQUIDADA", t.referencia)
    # 1 fecha fuera de rango (core 3 días antes)
    t = siguiente()
    t.fecha = fecha - timedelta(days=3)
    movs.append(mov(t, fecha=fecha))
    marcar("FECHA_FUERA", t.referencia)
    # 1 fecha con desfase de 1 día (tolerado)
    t = siguiente()
    t.fecha = fecha - timedelta(days=1)
    movs.append(mov(t, fecha=fecha))
    marcar("FECHA_TOLERADA", t.referencia)
    # 1 moneda distinta
    t = siguiente()
    movs.append(mov(t, moneda="USD"))
    marcar("MONEDA", t.referencia)
    # 1 venta de comercio bloqueado
    t = siguiente()
    t.comercio_id = "COM-0999"
    bloqueados = {t.comercio_id}
    movs.append(mov(t))
    marcar("COMERCIO_BLOQUEADO", t.referencia)
    # contracargos: 5 normales, 1 parcial, 1 sobre liquidada, 4 del mismo comercio (acumulación)
    for _ in range(5):
        t = siguiente()
        movs.append(mov(t, tipo="CONTRACARGO", descripcion="CONTRACARGO DISPUTA"))
        marcar("CONTRACARGO", t.referencia)
    t = siguiente()
    movs.append(mov(t, tipo="CONTRACARGO", monto_centavos=t.monto_centavos // 2, descripcion="CONTRACARGO PARCIAL"))
    marcar("CONTRACARGO_PARCIAL", t.referencia)
    t = siguiente()
    t.estado = "LIQUIDADA"
    movs.append(mov(t, tipo="CONTRACARGO", descripcion="CONTRACARGO DISPUTA"))
    marcar("CONTRACARGO_SOBRE_LIQUIDADA", t.referencia)
    comercio_malo = "COM-0007"
    for _ in range(4):
        t = siguiente()
        t.comercio_id = comercio_malo
        movs.append(mov(t, tipo="CONTRACARGO", descripcion="CONTRACARGO DISPUTA"))
        marcar("CONTRACARGO_ACUMULADO", t.referencia)
    # 1 contracargo sin match
    movs.append(MovBanco(f"SPN{tag}77777", fecha, 45_000, "MXN", "CONTRACARGO", "COM-0003", descripcion="CONTRACARGO DISPUTA"))
    marcar("CONTRACARGO_SIN_MATCH", movs[-1].referencia)
    # el resto: ventas normales (unas 8 quedan solo en el Core: el banco las reporta mañana)
    restantes = txs[idx:]
    for t in restantes[:-8]:
        movs.append(mov(t))
        marcar("NORMAL", t.referencia)
    for t in restantes[-8:]:
        marcar("SOLO_EN_CORE", t.referencia)

    rnd.shuffle(movs)
    con_cc = {m.comercio_id for m in movs if m.tipo == "CONTRACARGO" and any(t.referencia == m.referencia for t in txs)}
    casos["VENTA_DE_COMERCIO_CON_CONTRACARGO"] = [
        m.referencia for m in movs if m.tipo == "VENTA" and m.comercio_id in con_cc and m.referencia in casos.get("NORMAL", [])
    ]
    casos["NORMAL"] = [r for r in casos["NORMAL"] if r not in casos["VENTA_DE_COMERCIO_CON_CONTRACARGO"]]
    return Dia(fecha, txs, movs, bloqueados, casos)


def csv_banco(dia: Dia) -> str:
    lineas = ["referencia,fecha,monto,moneda,tipo,comercio_id,tarjeta,descripcion"]
    for m in dia.movimientos:
        lineas.append(f"{m.referencia},{m.fecha.isoformat()},{m.monto_centavos / 100:.2f},{m.moneda},{m.tipo},{m.comercio_id},{m.tarjeta},{m.descripcion}")
    return "\n".join(lineas) + "\n"


def csv_con_esquema_roto(dia: Dia) -> str:
    """Simula el cambio de portal: columnas renombradas. G-ESQUEMA debe detenerlo."""
    return csv_banco(dia).replace("referencia,fecha,monto", "ref,fecha_mov,importe", 1)
