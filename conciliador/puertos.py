"""Puertos (interfaces) del sistema. El dominio solo conoce estas firmas.

Cada puerto tiene hoy un adaptador "de transición" (RPA sobre portal/UI) y
puede tener mañana un adaptador API-First sin tocar el orquestador.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from .dominio.modelos import TransaccionCore


@dataclass
class ResultadoAccion:
    ok: bool
    respuesta: dict = field(default_factory=dict)
    evidencia: Path | None = None  # captura de pantalla u otro artefacto
    idempotente: bool = False  # el sistema destino reportó "ya estaba hecho"
    error: str = ""


class FuenteMovimientosBanco(Protocol):
    """De dónde salen los movimientos del día: portal (RPA), API, o archivo manual."""

    nombre: str

    def descargar_csv(self, fecha_operacion: date) -> str: ...


class RepositorioCore(Protocol):
    def transacciones_del_dia(self, fecha_operacion: date) -> list[TransaccionCore]: ...

    def saludable(self) -> bool: ...


class LiberadorLiquidacion(Protocol):
    def liberar(self, transaccion_id: str, clave_idempotencia: str) -> ResultadoAccion: ...


class BloqueadorSaldo(Protocol):
    nombre: str

    def bloquear(
        self, comercio_id: str, referencia: str, monto_centavos: int, motivo: str, clave_idempotencia: str
    ) -> ResultadoAccion: ...


@dataclass
class ContextoExcepcion:
    """Paquete cerrado y tokenizado que recibe el asistente. Nunca el CSV completo."""

    motivo: str
    regla: str
    nota: str
    tipo_movimiento: str
    monto_banco: int
    fecha_banco: str
    monto_core: int | None
    fecha_core: str | None
    estado_core: str | None
    comercio_token: str
    referencia_token: str
    candidatos: list[dict]  # tokenizados
    contracargos_comercio_dia: int
    historial_similar: list[dict] = field(default_factory=list)


@dataclass
class SugerenciaTriaje:
    causa_probable: str
    accion_sugerida: str  # catálogo cerrado, ver triaje.ACCIONES_SUGERIBLES
    confianza: float  # 0..1
    explicacion: str
    proveedor: str = "nulo"
    modelo: str = ""
    version_prompt: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0
    valida: bool = True


class AsistenteTriaje(Protocol):
    nombre: str

    def sugerir(self, contexto: ContextoExcepcion) -> SugerenciaTriaje: ...


class Notificador(Protocol):
    def enviar(self, titulo: str, cuerpo: str, severidad: str = "info") -> None: ...
