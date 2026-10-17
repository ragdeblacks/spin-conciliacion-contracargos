"""Adaptadores falsos en memoria para probar el orquestador sin red ni navegador."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from conciliador.dominio.modelos import EstadoTransaccion, TransaccionCore
from conciliador.puertos import ContextoExcepcion, ResultadoAccion, SugerenciaTriaje
from mocks.datos_semilla import Dia, csv_banco


@dataclass
class FuenteFalsa:
    dia: Dia
    nombre: str = "archivo"
    csv_override: str | None = None

    def descargar_csv(self, fecha_operacion: date) -> str:
        return self.csv_override if self.csv_override is not None else csv_banco(self.dia)


@dataclass
class CoreFalso:
    dia: Dia
    vivo: bool = True
    fallar_liberaciones: set[str] = field(default_factory=set)  # ids que fallan
    liberadas: list[str] = field(default_factory=list)
    bloqueos: list[tuple[str, str]] = field(default_factory=list)
    estado_congelado: bool = False  # simula un Core que devuelve estados viejos (réplica atrasada)
    nombre: str = "fake"

    def __post_init__(self):
        self._estados_iniciales = {t.id: t.estado for t in self.dia.transacciones}

    def saludable(self) -> bool:
        return self.vivo

    def transacciones_del_dia(self, fecha_operacion: date) -> list[TransaccionCore]:
        return [
            TransaccionCore(
                t.id,
                t.referencia,
                t.fecha,
                t.monto_centavos,
                t.moneda,
                t.comercio_id,
                EstadoTransaccion(self._estados_iniciales[t.id] if self.estado_congelado else t.estado),
                comercio_bloqueado=t.comercio_id in self.dia.comercios_bloqueados,
            )
            for t in self.dia.transacciones
        ]

    def liberar(self, transaccion_id: str, clave_idempotencia: str) -> ResultadoAccion:
        if transaccion_id in self.fallar_liberaciones:
            return ResultadoAccion(ok=False, error="HTTP 503 simulado")
        tx = next(t for t in self.dia.transacciones if t.id == transaccion_id)
        if tx.comercio_id in self.dia.comercios_bloqueados:
            return ResultadoAccion(ok=False, error="HTTP 422: comercio suspendido por Riesgos")
        if any(r == tx.referencia for _, r in self.bloqueos):
            return ResultadoAccion(ok=False, error="HTTP 422: la venta está en disputa")
        ya = transaccion_id in self.liberadas
        if not ya:
            self.liberadas.append(transaccion_id)
            for t in self.dia.transacciones:
                if t.id == transaccion_id:
                    t.estado = "LIQUIDADA"
        return ResultadoAccion(ok=True, respuesta={"estado": "LIQUIDADA"}, idempotente=ya)

    def bloquear(self, comercio_id, referencia, monto_centavos, motivo, clave_idempotencia) -> ResultadoAccion:
        ya = (comercio_id, referencia) in self.bloqueos
        if not ya:
            self.bloqueos.append((comercio_id, referencia))
            for t in self.dia.transacciones:  # la venta queda en disputa, igual que en el Core
                if t.referencia == referencia:
                    t.estado = "BLOQUEADA"
        return ResultadoAccion(ok=True, respuesta={"via": "fake"}, idempotente=ya)


@dataclass
class AsistenteFalso:
    nombre: str = "falso"
    llamadas: int = 0
    salida_invalida: bool = False

    def sugerir(self, contexto: ContextoExcepcion) -> SugerenciaTriaje:
        self.llamadas += 1
        return SugerenciaTriaje(
            "causa falsa",
            "ESCALAR_AL_BANCO",
            0.8,
            f"explica {contexto.referencia_token}",
            proveedor="falso",
            modelo="m",
            version_prompt="v",
            tokens_entrada=300,
            tokens_salida=50,
        )


@dataclass
class NotificadorFalso:
    enviados: list[tuple[str, str, str]] = field(default_factory=list)

    def enviar(self, titulo: str, cuerpo: str, severidad: str = "info") -> None:
        self.enviados.append((titulo, cuerpo, severidad))
