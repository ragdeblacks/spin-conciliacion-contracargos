"""Modelos del dominio de conciliación.

Todo monto se maneja en centavos enteros: nunca flotantes para dinero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class TipoMovimiento(StrEnum):
    VENTA = "VENTA"
    CONTRACARGO = "CONTRACARGO"


class EstadoTransaccion(StrEnum):
    PENDIENTE_LIQUIDACION = "PENDIENTE_LIQUIDACION"
    LIQUIDADA = "LIQUIDADA"
    BLOQUEADA = "BLOQUEADA"


class Accion(StrEnum):
    LIQUIDAR = "LIQUIDAR"
    BLOQUEAR = "BLOQUEAR"
    EXCEPCION = "EXCEPCION"
    YA_PROCESADO = "YA_PROCESADO"


class Motivo(StrEnum):
    """Catálogo cerrado de motivos. Es el vocabulario compartido con Operaciones."""

    MATCH_EXACTO = "MATCH_EXACTO"
    CONTRACARGO_CON_MATCH = "CONTRACARGO_CON_MATCH"
    CONTRACARGO_PARCIAL = "CONTRACARGO_PARCIAL"
    CONTRACARGO_SOBRE_LIQUIDADA = "CONTRACARGO_SOBRE_LIQUIDADA"
    LIQUIDADA_EN_CORE = "LIQUIDADA_EN_CORE"
    COMERCIO_YA_BLOQUEADO = "COMERCIO_YA_BLOQUEADO"
    SIN_MATCH = "SIN_MATCH"
    CONTRACARGO_SIN_MATCH = "CONTRACARGO_SIN_MATCH"
    MONTO_DIFERENTE = "MONTO_DIFERENTE"
    FECHA_FUERA_DE_RANGO = "FECHA_FUERA_DE_RANGO"
    DUPLICADO_EN_ARCHIVO = "DUPLICADO_EN_ARCHIVO"
    COMERCIO_BLOQUEADO = "COMERCIO_BLOQUEADO"
    CONTRACARGO_MISMO_DIA = "CONTRACARGO_MISMO_DIA"
    MONEDA_DISTINTA = "MONEDA_DISTINTA"


class EstadoEjecucion(StrEnum):
    NO_APLICA = "NO_APLICA"  # excepciones y ya procesados
    SOMBRA = "SOMBRA"  # registrada, no ejecutada (modo sombra)
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION"
    APROBADA = "APROBADA"
    EJECUTADA = "EJECUTADA"
    FALLIDA = "FALLIDA"
    OMITIDA_IDEMPOTENTE = "OMITIDA_IDEMPOTENTE"


@dataclass(frozen=True)
class MovimientoBanco:
    referencia: str
    fecha: date
    monto_centavos: int
    moneda: str
    tipo: TipoMovimiento
    comercio_id: str
    tarjeta_mascara: str = ""
    descripcion: str = ""


@dataclass(frozen=True)
class TransaccionCore:
    id: str
    referencia: str
    fecha: date
    monto_centavos: int
    moneda: str
    comercio_id: str
    estado: EstadoTransaccion
    comercio_bloqueado: bool = False


@dataclass
class Decision:
    movimiento: MovimientoBanco
    accion: Accion
    motivo: Motivo
    transaccion: TransaccionCore | None = None
    candidatos: list[TransaccionCore] = field(default_factory=list)
    regla: str = ""
    nota: str = ""
    requiere_aprobacion: bool = False
    estado_ejecucion: EstadoEjecucion = EstadoEjecucion.NO_APLICA
    id: int | None = None  # asignado por el libro mayor

    @property
    def clave_idempotencia(self) -> str:
        """Clave única y legible por acción. Es lo que impide ejecutar dos veces."""
        prefijo = {Accion.LIQUIDAR: "LIQ", Accion.BLOQUEAR: "BLQ"}.get(self.accion, "NOP")
        return f"{prefijo}:{self.movimiento.referencia}:{self.movimiento.fecha.isoformat()}"

    @property
    def es_ejecutable(self) -> bool:
        return self.accion in (Accion.LIQUIDAR, Accion.BLOQUEAR)


@dataclass
class ResultadoGate:
    gate: str
    ok: bool
    critico: bool
    detalle: str = ""


class GateCriticoFallido(Exception):
    def __init__(self, resultado: ResultadoGate):
        super().__init__(f"{resultado.gate}: {resultado.detalle}")
        self.resultado = resultado


def centavos_a_texto(centavos: int, moneda: str = "MXN") -> str:
    signo = "-" if centavos < 0 else ""
    centavos = abs(centavos)
    return f"{signo}${centavos // 100:,}.{centavos % 100:02d} {moneda}"
