"""Orquestador del pipeline diario.

Pasos: arranque → ingesta → gates de entrada → conciliación → idempotencia →
ejecución (bloqueos primero, luego liquidaciones) → triaje de excepciones →
cierre → reporte. Cada paso deja rastro en el libro mayor.

Modos:
- sombra:   clasifica y registra, no toca el Core.
- asistida: ejecuta solo lo aprobado por un humano (comando `aprobar`).
- autonoma: ejecuta bajo umbrales; lo que supera umbral queda pendiente de aprobación.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import gates
from .config import Configuracion
from .dominio.modelos import Accion, Decision, EstadoEjecucion, GateCriticoFallido, ResultadoGate
from .dominio.normalizacion import ErrorEsquema, parsear_csv
from .dominio.reglas import conciliar, resumen
from .libro_mayor import LibroMayor
from .observabilidad import latido
from .puertos import (
    AsistenteTriaje,
    BloqueadorSaldo,
    FuenteMovimientosBanco,
    LiberadorLiquidacion,
    Notificador,
    RepositorioCore,
)
from .triaje import triar_excepciones

log = logging.getLogger("conciliador")


@dataclass
class Adaptadores:
    fuente_banco: FuenteMovimientosBanco
    core: RepositorioCore
    liberador: LiberadorLiquidacion
    bloqueador: BloqueadorSaldo
    asistente: AsistenteTriaje
    notificador: Notificador


@dataclass
class ResultadoCorrida:
    corrida_id: int
    estado: str
    decisiones: list[Decision]
    gates: list[ResultadoGate]
    resumen: dict
    duracion_s: float


class Orquestador:
    def __init__(self, cfg: Configuracion, libro: LibroMayor, ad: Adaptadores):
        self.cfg, self.libro, self.ad = cfg, libro, ad

    # --- utilidades -------------------------------------------------------
    def _gate(self, corrida_id: int, r: ResultadoGate, acumulado: list[ResultadoGate]) -> None:
        acumulado.append(r)
        self.libro.registrar_gate(corrida_id, r)
        log.info("gate %s %s: %s", r.gate, "OK" if r.ok else "FALLÓ", r.detalle)
        if not r.ok and r.critico:
            raise GateCriticoFallido(r)

    # --- corrida principal --------------------------------------------------
    def correr(self, fecha_operacion: date, hoy: date | None = None) -> ResultadoCorrida:
        hoy = hoy or date.today()
        inicio = time.monotonic()
        corrida_id = self.libro.abrir_corrida(fecha_operacion, self.cfg.modo, self.ad.fuente_banco.nombre)
        acumulado: list[ResultadoGate] = []
        decisiones: list[Decision] = []
        log.info("corrida %s: fecha %s, modo %s, fuente %s", corrida_id, fecha_operacion, self.cfg.modo, self.ad.fuente_banco.nombre)
        try:
            # 1. arranque
            self._gate(corrida_id, gates.fecha_operacion_valida(fecha_operacion, hoy), acumulado)
            self._gate(corrida_id, gates.g_secretos(self.cfg.secretos_requeridos()), acumulado)
            self._gate(corrida_id, gates.g_core_vivo(self.ad.core.saludable()), acumulado)

            # 2. ingesta
            csv = self.ad.fuente_banco.descargar_csv(fecha_operacion)
            encabezados = [h.strip() for h in csv.splitlines()[0].split(",")] if csv.strip() else []
            self._gate(corrida_id, gates.g_esquema(encabezados), acumulado)
            try:
                movimientos = parsear_csv(csv)
            except ErrorEsquema as e:
                self._gate(corrida_id, ResultadoGate("G-ESQUEMA", False, True, str(e)), acumulado)
                raise
            self._gate(
                corrida_id,
                gates.g_volumen(len(movimientos), self.libro.promedio_movimientos(), self.cfg.volumen_minimo, self.cfg.volumen_factor_maximo),
                acumulado,
            )

            # 3. conciliación (pura)
            transacciones = self.ad.core.transacciones_del_dia(fecha_operacion)
            historial = self.libro.historial_comercios((fecha_operacion - timedelta(days=self.cfg.ventana_riesgo_dias)).isoformat())
            decisiones = conciliar(movimientos, transacciones, self.cfg.parametros, historial)
            self._asignar_estado_inicial(decisiones)
            self._gate(corrida_id, gates.g_duplicado(decisiones, self.libro.claves_confirmadas()), acumulado)
            self.libro.registrar_decisiones(corrida_id, decisiones)

            # 4. ejecución
            if self.cfg.modo in ("autonoma",):
                self._ejecutar(corrida_id, decisiones, acumulado)

            # 5. triaje de excepciones (fuera del camino crítico)
            triar_excepciones(decisiones, self.ad.asistente, self.libro, corrida_id, self.cfg)

            # 6. cierre
            cierre = gates.g_cierre(decisiones, self.cfg.modo)
            self._gate(corrida_id, cierre, acumulado)
            res = resumen(decisiones)
            tasa = res.get("EXCEPCION", 0) / res["TOTAL"] if res.get("TOTAL") else 0.0
            self._gate(corrida_id, gates.g_deriva(tasa, self.libro.tasa_excepciones_historica()), acumulado)
            self._gate(corrida_id, gates.g_latencia(datetime.now().strftime("%H:%M"), self.cfg.hora_limite), acumulado)
            # lo que falló quedó aislado y con incidencia; el resto se ejecutó: la corrida cierra, no se detiene
            estado = "CERRADA" if cierre.ok else "CERRADA_CON_INCIDENCIAS"
        except GateCriticoFallido as e:
            estado = "DETENIDA"
            res = resumen(decisiones) if decisiones else {}
            self.ad.notificador.enviar(f"Conciliación {fecha_operacion} DETENIDA", f"{e.resultado.gate}: {e.resultado.detalle}", "critico")
        except Exception as e:  # noqa: BLE001
            estado = "ERROR"
            res = resumen(decisiones) if decisiones else {}
            log.exception("error no controlado")
            self.ad.notificador.enviar(f"Conciliación {fecha_operacion} ERROR", f"{type(e).__name__}: {e}", "critico")
        self.libro.cerrar_corrida(corrida_id, estado, res)
        self._abrir_incidencias(corrida_id, fecha_operacion, estado, decisiones, acumulado)
        latido(self.cfg.url_latido, estado.startswith("CERRADA"), corrida_id)
        duracion = time.monotonic() - inicio
        if estado.startswith("CERRADA"):
            self._notificar_resumen(fecha_operacion, res, decisiones, duracion, estado)
        return ResultadoCorrida(corrida_id, estado, decisiones, acumulado, res, duracion)

    def _abrir_incidencias(self, corrida_id: int, fecha: date, estado: str, decisiones: list[Decision], gates_evaluados: list[ResultadoGate]) -> None:
        """Todo lo que salió mal queda como incidencia con dueño pendiente, para la gestión del día siguiente."""
        f = fecha.isoformat()
        if not estado.startswith("CERRADA"):
            ultimo = next((g for g in reversed(gates_evaluados) if not g.ok and g.critico), None)
            desc = f"{ultimo.gate}: {ultimo.detalle}" if ultimo else "error no controlado"
            self.libro.abrir_incidencia(corrida_id, f, "CORRIDA_DETENIDA", "critica", desc)
        for d in decisiones:
            if d.estado_ejecucion == EstadoEjecucion.FALLIDA:
                self.libro.abrir_incidencia(corrida_id, f, "ACCION_FALLIDA", "critica", f"{d.accion.value} {d.movimiento.referencia} no se pudo ejecutar")
            elif d.accion == Accion.EXCEPCION and d.motivo.value == "CONTRACARGO_SIN_MATCH":
                self.libro.abrir_incidencia(corrida_id, f, "CONTRACARGO_SIN_MATCH", "alta", f"contracargo {d.movimiento.referencia} sin venta en el Core")
        for g in gates_evaluados:
            if not g.ok and not g.critico and g.gate in ("G-DERIVA", "G-SOMBRA", "G-CONTRATO-PORTAL"):
                self.libro.abrir_incidencia(corrida_id, f, "GATE", "media", f"{g.gate}: {g.detalle}")

    def _asignar_estado_inicial(self, decisiones: list[Decision]) -> None:
        for d in decisiones:
            if not d.es_ejecutable:
                d.estado_ejecucion = EstadoEjecucion.NO_APLICA
            elif self.cfg.modo == "sombra":
                d.estado_ejecucion = EstadoEjecucion.SOMBRA
            elif self.cfg.modo == "asistida" or d.requiere_aprobacion:
                d.estado_ejecucion = EstadoEjecucion.PENDIENTE_APROBACION
            else:
                d.estado_ejecucion = EstadoEjecucion.APROBADA

    # --- ejecución --------------------------------------------------------
    def _ejecutar(self, corrida_id: int, decisiones: list[Decision], acumulado: list[ResultadoGate]) -> None:
        aprobadas = [d for d in decisiones if d.estado_ejecucion == EstadoEjecucion.APROBADA]
        # contracargos primero: ahí se pierde dinero
        for d in [d for d in aprobadas if d.accion == Accion.BLOQUEAR]:
            self._ejecutar_una(corrida_id, d)
        self._gate(corrida_id, gates.g_orden(decisiones), acumulado)
        # procesamiento por excepciones: un bloqueo fallido aparta solo los pagos de ESE comercio; los demás avanzan
        con_bloqueo_fallido = {d.movimiento.comercio_id for d in decisiones if d.accion == Accion.BLOQUEAR and d.estado_ejecucion == EstadoEjecucion.FALLIDA}
        for d in [d for d in aprobadas if d.accion == Accion.LIQUIDAR]:
            if d.movimiento.comercio_id in con_bloqueo_fallido:
                d.estado_ejecucion = EstadoEjecucion.APARTADA
                d.nota = (d.nota + " " if d.nota else "") + "Apartada: el bloqueo de este comercio falló en esta corrida."
                self.libro.actualizar_estado_decision(d.id, d.estado_ejecucion)
                continue
            self._ejecutar_una(corrida_id, d)

    def _ejecutar_una(self, corrida_id: int, d: Decision) -> None:
        clave = d.clave_idempotencia
        previa = self.libro.accion(clave)
        if previa and previa["estado"] == "CONFIRMADA":
            d.estado_ejecucion = EstadoEjecucion.OMITIDA_IDEMPOTENTE
            self.libro.actualizar_estado_decision(d.id, d.estado_ejecucion)
            return
        self.libro.intentar_accion(clave, corrida_id, d.id, d.accion)  # rastro ANTES de tocar el Core
        if d.accion == Accion.BLOQUEAR:
            r = self.ad.bloqueador.bloquear(
                d.movimiento.comercio_id,
                d.movimiento.referencia,
                d.movimiento.monto_centavos,
                f"{d.motivo.value} corrida {corrida_id}",
                clave,
            )
        else:
            r = self.ad.liberador.liberar(d.transaccion.id, clave)
        if r.ok:
            self.libro.confirmar_accion(clave, r.respuesta, str(r.evidencia) if r.evidencia else None)
            d.estado_ejecucion = EstadoEjecucion.OMITIDA_IDEMPOTENTE if r.idempotente else EstadoEjecucion.EJECUTADA
        else:
            self.libro.fallar_accion(clave, r.error)
            d.estado_ejecucion = EstadoEjecucion.FALLIDA
            log.error("acción %s falló: %s", clave, r.error)
        self.libro.actualizar_estado_decision(d.id, d.estado_ejecucion)

    # --- aprobación humana (modo asistida / umbrales) ----------------------
    def aprobar_y_ejecutar(self, corrida_id: int, aprobador: str, decision_ids: list[int] | None = None) -> list[Decision]:
        filas = self.libro.decisiones_de(corrida_id)
        pendientes = [
            f for f in filas if f["estado_ejecucion"] == EstadoEjecucion.PENDIENTE_APROBACION.value and (decision_ids is None or f["id"] in decision_ids)
        ]
        decisiones = [_decision_desde_fila(f) for f in pendientes]
        for d in decisiones:
            self.libro.aprobar(d.id, aprobador)
            d.estado_ejecucion = EstadoEjecucion.APROBADA
        acumulado: list[ResultadoGate] = []
        for d in [d for d in decisiones if d.accion == Accion.BLOQUEAR]:
            self._ejecutar_una(corrida_id, d)
        for d in [d for d in decisiones if d.accion == Accion.LIQUIDAR]:
            self._ejecutar_una(corrida_id, d)
        self.libro.registrar_gate(corrida_id, gates.g_cierre(decisiones, "aprobacion"))
        del acumulado
        return decisiones

    # --- comparación en modo sombra ----------------------------------------
    def comparar_sombra(self, corrida_id: int) -> dict:
        """¿Lo que el pipeline habría hecho coincide con lo que hizo el analista en el Core?"""
        corrida = self.libro.corrida(corrida_id)
        fecha = date.fromisoformat(corrida["fecha_operacion"])
        actuales = {t.referencia: t for t in self.ad.core.transacciones_del_dia(fecha)}
        coincidencias, total, diferencias = 0, 0, []
        for f in self.libro.decisiones_de(corrida_id):
            if f["accion"] not in (Accion.LIQUIDAR.value, Accion.BLOQUEAR.value):
                continue
            total += 1
            t = actuales.get(f["referencia"])
            esperado = "LIQUIDADA" if f["accion"] == Accion.LIQUIDAR.value else "BLOQUEADA"
            real = t.estado.value if t else "AUSENTE"
            if real == esperado:
                coincidencias += 1
            else:
                diferencias.append({"referencia": f["referencia"], "pipeline": f["accion"], "core": real})
        r = gates.g_sombra(coincidencias, total)
        self.libro.registrar_gate(corrida_id, r)
        return {"gate": r, "coincidencias": coincidencias, "total": total, "diferencias": diferencias}

    def _notificar_resumen(self, fecha: date, res: dict, decisiones: list[Decision], duracion: float, estado: str) -> None:
        pend = sum(1 for d in decisiones if d.estado_ejecucion == EstadoEjecucion.PENDIENTE_APROBACION)
        fallidas = sum(1 for d in decisiones if d.estado_ejecucion == EstadoEjecucion.FALLIDA)
        apartadas = sum(1 for d in decisiones if d.estado_ejecucion == EstadoEjecucion.APARTADA)
        cuerpo = (
            f"modo {self.cfg.modo} · {res.get('TOTAL', 0)} movimientos · liquidar {res.get('LIQUIDAR', 0)} · "
            f"bloquear {res.get('BLOQUEAR', 0)} · excepciones {res.get('EXCEPCION', 0)} · "
            f"pendientes de aprobación {pend} · fallidas {fallidas} · apartadas {apartadas} · {duracion:.1f}s"
        )
        titulo = f"Conciliación {fecha} cerrada" + (" con incidencias" if estado != "CERRADA" else "")
        self.ad.notificador.enviar(titulo, cuerpo, "critico" if fallidas else ("alerta" if pend else "info"))


def _decision_desde_fila(f: dict) -> Decision:
    from .dominio.modelos import EstadoTransaccion, Motivo, MovimientoBanco, TipoMovimiento, TransaccionCore

    mov = MovimientoBanco(
        f["referencia"],
        date.fromisoformat(f["fecha_movimiento"]),
        f["monto_centavos"],
        "MXN",
        TipoMovimiento(f["tipo"]),
        f["comercio_id"],
    )
    t = (
        TransaccionCore(
            f["transaccion_id"],
            f["referencia"],
            mov.fecha,
            mov.monto_centavos,
            "MXN",
            f["comercio_id"],
            EstadoTransaccion.PENDIENTE_LIQUIDACION,
        )
        if f["transaccion_id"]
        else None
    )
    d = Decision(
        mov,
        Accion(f["accion"]),
        Motivo(f["motivo"]),
        transaccion=t,
        regla=f["regla"],
        nota=f["nota"] or "",
        requiere_aprobacion=bool(f["requiere_aprobacion"]),
        estado_ejecucion=EstadoEjecucion(f["estado_ejecucion"]),
    )
    d.id = f["id"]
    return d
