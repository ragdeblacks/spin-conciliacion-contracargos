"""Gates: puntos donde el pipeline se detiene si no se cumple una condición.

Críticos: protegen dinero, deterministas, bloquean la corrida.
No críticos: protegen calidad/privacidad; su peor caso es trabajar sin asistente.
"""

from __future__ import annotations

from datetime import date

from .config import PLACEHOLDERS_PROHIBIDOS
from .dominio.modelos import Accion, Decision, EstadoEjecucion, ResultadoGate
from .dominio.normalizacion import validar_esquema
from .privacidad import contiene_pii

# --- críticos -------------------------------------------------------------


def g_secretos(requeridos: dict[str, str]) -> ResultadoGate:
    malos = [k for k, v in requeridos.items() if v.strip().lower() in PLACEHOLDERS_PROHIBIDOS]
    if malos:
        return ResultadoGate("G-SECRETOS", False, True, f"credenciales ausentes o placeholder: {', '.join(malos)}")
    return ResultadoGate("G-SECRETOS", True, True, f"{len(requeridos)} credenciales cargadas desde el entorno")


def g_core_vivo(saludable: bool) -> ResultadoGate:
    return ResultadoGate("G-CORE-VIVO", saludable, True, "Core responde" if saludable else "Core no responde: no se toca nada")


def g_esquema(encabezados: list[str]) -> ResultadoGate:
    problemas = validar_esquema(encabezados)
    return ResultadoGate("G-ESQUEMA", not problemas, True, "; ".join(problemas) or f"{len(encabezados)} columnas válidas")


def g_volumen(cantidad: int, promedio_historico: float | None, minimo: int, factor_maximo: float) -> ResultadoGate:
    if cantidad < minimo:
        return ResultadoGate("G-VOLUMEN", False, True, f"{cantidad} movimientos: archivo vacío o incompleto")
    if promedio_historico and cantidad > promedio_historico * factor_maximo:
        return ResultadoGate(
            "G-VOLUMEN",
            False,
            True,
            f"{cantidad} movimientos supera {factor_maximo}x el promedio ({promedio_historico:.0f}); confirmar con Operaciones",
        )
    base = f"promedio histórico {promedio_historico:.0f}" if promedio_historico else "sin histórico aún"
    return ResultadoGate("G-VOLUMEN", True, True, f"{cantidad} movimientos ({base})")


def g_duplicado(decisiones: list[Decision], claves_ya_ejecutadas: set[str]) -> ResultadoGate:
    """Marca como idempotentes las decisiones cuya clave ya se ejecutó en corridas anteriores."""
    omitidas = 0
    for d in decisiones:
        if d.es_ejecutable and d.clave_idempotencia in claves_ya_ejecutadas:
            d.estado_ejecucion = EstadoEjecucion.OMITIDA_IDEMPOTENTE
            omitidas += 1
    return ResultadoGate("G-DUPLICADO", True, True, f"{omitidas} acciones ya ejecutadas en corridas previas, omitidas")


def g_orden(decisiones: list[Decision]) -> ResultadoGate:
    """Ninguna liquidación arranca si queda un bloqueo sin intentar."""
    pendientes = [d for d in decisiones if d.accion == Accion.BLOQUEAR and d.estado_ejecucion in (EstadoEjecucion.APROBADA, EstadoEjecucion.NO_APLICA)]
    if pendientes:
        return ResultadoGate("G-ORDEN", False, True, f"{len(pendientes)} bloqueos sin intentar antes de liquidar")
    return ResultadoGate("G-ORDEN", True, True, "todos los bloqueos intentados antes de la primera liquidación")


def g_cierre(decisiones: list[Decision], modo: str) -> ResultadoGate:
    ejecutables = [d for d in decisiones if d.es_ejecutable]
    finales = {
        EstadoEjecucion.EJECUTADA,
        EstadoEjecucion.OMITIDA_IDEMPOTENTE,
        EstadoEjecucion.SOMBRA,
        EstadoEjecucion.PENDIENTE_APROBACION,
    }
    fallidas = [d for d in ejecutables if d.estado_ejecucion == EstadoEjecucion.FALLIDA]
    sin_estado = [d for d in ejecutables if d.estado_ejecucion not in finales | {EstadoEjecucion.FALLIDA}]
    if fallidas or sin_estado:
        return ResultadoGate(
            "G-CIERRE",
            False,
            True,
            f"{len(fallidas)} acciones fallidas, {len(sin_estado)} sin estado final: revisar antes del corte",
        )
    return ResultadoGate("G-CIERRE", True, True, f"{len(ejecutables)} acciones con estado final consistente (modo {modo})")


# --- no críticos ----------------------------------------------------------


def g_llm_pii(texto_a_enviar: str) -> ResultadoGate:
    hallazgos = contiene_pii(texto_a_enviar)
    return ResultadoGate(
        "G-LLM-PII",
        not hallazgos,
        False,
        f"{len(hallazgos)} patrones de datos personales sin tokenizar" if hallazgos else "paquete limpio",
    )


def g_llm_presupuesto(llamadas_corrida: int, tope_corrida: int, tokens_dia: int, tope_dia: int) -> ResultadoGate:
    if llamadas_corrida >= tope_corrida:
        return ResultadoGate("G-LLM-PRESUPUESTO", False, False, f"tope de {tope_corrida} llamadas por corrida alcanzado")
    if tokens_dia >= tope_dia:
        return ResultadoGate("G-LLM-PRESUPUESTO", False, False, f"tope de {tope_dia} tokens por día alcanzado")
    return ResultadoGate("G-LLM-PRESUPUESTO", True, False, f"{llamadas_corrida}/{tope_corrida} llamadas, {tokens_dia}/{tope_dia} tokens")


def g_deriva(tasa_excepciones: float, tasa_historica: float | None, factor: float = 2.0) -> ResultadoGate:
    if tasa_historica is None or tasa_historica == 0:
        return ResultadoGate("G-DERIVA", True, False, f"tasa de excepciones {tasa_excepciones:.1%}, sin histórico")
    if tasa_excepciones > tasa_historica * factor and tasa_excepciones > 0.05:
        return ResultadoGate(
            "G-DERIVA",
            False,
            False,
            f"tasa de excepciones {tasa_excepciones:.1%} vs histórico {tasa_historica:.1%}: posible cambio en portal o banco",
        )
    return ResultadoGate("G-DERIVA", True, False, f"tasa de excepciones {tasa_excepciones:.1%} (histórico {tasa_historica:.1%})")


def g_latencia(hora_fin: str, hora_limite: str) -> ResultadoGate:
    ok = hora_fin <= hora_limite
    return ResultadoGate("G-LATENCIA", ok, False, f"corrida terminó {hora_fin}, límite {hora_limite}")


def g_sombra(coincidencias: int, total: int, umbral: float = 0.98) -> ResultadoGate:
    tasa = coincidencias / total if total else 1.0
    return ResultadoGate(
        "G-SOMBRA",
        tasa >= umbral,
        False,
        f"coincidencia con el analista {tasa:.1%} ({coincidencias}/{total}); umbral {umbral:.0%}",
    )


def fecha_operacion_valida(fecha: date, hoy: date) -> ResultadoGate:
    ok = fecha < hoy
    return ResultadoGate("G-FECHA", ok, True, "fecha de operación anterior a hoy" if ok else "no se concilia el día en curso")
