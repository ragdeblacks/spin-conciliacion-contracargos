"""Parseo y normalización del CSV del banco a movimientos del dominio.

Lo único que sabe de formato bancario vive aquí. Si el banco cambia columnas,
cambia este archivo (y el gate G-ESQUEMA lo detecta antes de que duela).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .modelos import MovimientoBanco, TipoMovimiento

COLUMNAS_REQUERIDAS = ("referencia", "fecha", "monto", "moneda", "tipo", "comercio_id")
COLUMNAS_OPCIONALES = ("tarjeta", "descripcion")
TIPOS_VALIDOS = {t.value for t in TipoMovimiento}


class ErrorEsquema(ValueError):
    pass


def validar_esquema(encabezados: list[str]) -> list[str]:
    """Devuelve la lista de problemas. Vacía = esquema correcto."""
    problemas = []
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in encabezados]
    if faltantes:
        problemas.append(f"columnas faltantes: {', '.join(faltantes)}")
    desconocidas = [c for c in encabezados if c not in COLUMNAS_REQUERIDAS + COLUMNAS_OPCIONALES]
    if desconocidas:
        problemas.append(f"columnas desconocidas: {', '.join(desconocidas)}")
    return problemas


def _parsear_monto(texto: str) -> int:
    limpio = texto.replace("$", "").replace(",", "").strip()
    try:
        return int((Decimal(limpio) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError) as e:
        raise ErrorEsquema(f"monto inválido: {texto!r}") from e


def _parsear_fecha(texto: str) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(texto.strip(), fmt).date()
        except ValueError:
            continue
    raise ErrorEsquema(f"fecha inválida: {texto!r}")


def parsear_csv(contenido: str) -> list[MovimientoBanco]:
    lector = csv.DictReader(io.StringIO(contenido))
    encabezados = [h.strip() for h in (lector.fieldnames or [])]
    problemas = validar_esquema(encabezados)
    if problemas:
        raise ErrorEsquema("; ".join(problemas))

    movimientos: list[MovimientoBanco] = []
    for n, fila in enumerate(lector, start=2):
        fila = {k.strip(): (v or "").strip() for k, v in fila.items() if k}
        tipo = fila["tipo"].upper()
        if tipo not in TIPOS_VALIDOS:
            raise ErrorEsquema(f"línea {n}: tipo desconocido {tipo!r}")
        movimientos.append(
            MovimientoBanco(
                referencia=fila["referencia"].upper(),
                fecha=_parsear_fecha(fila["fecha"]),
                monto_centavos=_parsear_monto(fila["monto"]),
                moneda=fila["moneda"].upper() or "MXN",
                tipo=TipoMovimiento(tipo),
                comercio_id=fila["comercio_id"],
                tarjeta_mascara=fila.get("tarjeta", ""),
                descripcion=fila.get("descripcion", ""),
            )
        )
    return movimientos
