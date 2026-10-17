from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from conciliador.config import Configuracion
from conciliador.dominio.modelos import EstadoTransaccion, MovimientoBanco, TipoMovimiento, TransaccionCore
from conciliador.libro_mayor import LibroMayor
from mocks.datos_semilla import generar_dia

FECHA = date(2026, 10, 15)


@pytest.fixture
def fecha() -> date:
    return FECHA


@pytest.fixture
def dia():
    return generar_dia(FECHA)


@pytest.fixture
def movimientos(dia) -> list[MovimientoBanco]:
    return [
        MovimientoBanco(m.referencia, m.fecha, m.monto_centavos, m.moneda, TipoMovimiento(m.tipo), m.comercio_id, m.tarjeta, m.descripcion)
        for m in dia.movimientos
    ]


@pytest.fixture
def transacciones(dia) -> list[TransaccionCore]:
    return [
        TransaccionCore(
            t.id,
            t.referencia,
            t.fecha,
            t.monto_centavos,
            t.moneda,
            t.comercio_id,
            EstadoTransaccion(t.estado),
            comercio_bloqueado=t.comercio_id in dia.comercios_bloqueados,
        )
        for t in dia.transacciones
    ]


@pytest.fixture
def libro(tmp_path: Path) -> LibroMayor:
    return LibroMayor(tmp_path / "libro.sqlite")


@pytest.fixture
def cfg(tmp_path: Path) -> Configuracion:
    c = Configuracion(
        ruta_libro_mayor=tmp_path / "libro.sqlite",
        ruta_evidencia=tmp_path / "evidencia",
        token_core="t",
        usuario_portal="u",
        clave_portal="p",
        usuario_core_ui="u",
        clave_core_ui="p",
    )
    return c
