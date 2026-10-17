"""Adaptadores del asistente de triaje. El dominio solo conoce el puerto AsistenteTriaje.

- AsistenteNulo: determinista, siempre disponible. Es el fallback de todos los demás.
- AsistenteAnthropic: SDK oficial, salida estructurada validada con el mismo esquema.
- AsistenteOpenAICompatible: cualquier servidor compatible (modelo abierto dentro del perímetro).
Cambiar de proveedor = cambiar LLM_PROVEEDOR. Retirar un modelo = cambiar LLM_MODELO.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..puertos import ContextoExcepcion, SugerenciaTriaje

log = logging.getLogger("conciliador.llm")

ACCIONES_SUGERIBLES = (
    "LIQUIDAR_MANUAL",
    "BLOQUEAR_MANUAL",
    "ESPERAR_SIGUIENTE_CORTE",
    "ESCALAR_AL_BANCO",
    "IGNORAR_DUPLICADO",
    "REVISAR_CON_COMERCIO",
)

RAIZ = Path(__file__).resolve().parents[2]


class EsquemaSugerencia(BaseModel):
    """Contrato de salida. Cualquier proveedor debe producir exactamente esto."""

    causa_probable: str = Field(max_length=200)
    accion_sugerida: str
    confianza: float = Field(ge=0, le=1)
    explicacion: str = Field(max_length=600)


def cargar_contexto_fijo() -> str:
    return (RAIZ / "contexto" / "negocio.md").read_text(encoding="utf-8")


def cargar_prompt(version: str = "triaje_v1") -> str:
    return (RAIZ / "prompts" / f"{version}.md").read_text(encoding="utf-8")


def armar_mensaje(contexto: ContextoExcepcion, version_prompt: str) -> str:
    return f"{cargar_prompt(version_prompt)}\n\n<excepcion>\n{json.dumps(asdict(contexto), ensure_ascii=False, indent=1)}\n</excepcion>"


def validar_salida(texto: str) -> EsquemaSugerencia | None:
    """G-LLM-ESQUEMA: si no valida, se descarta y entra el fallback."""
    try:
        inicio, fin = texto.find("{"), texto.rfind("}")
        datos = json.loads(texto[inicio : fin + 1])
        s = EsquemaSugerencia.model_validate(datos)
        if s.accion_sugerida not in ACCIONES_SUGERIBLES:
            return None
        return s
    except (ValueError, ValidationError):
        return None


# --- determinista -----------------------------------------------------------

SUGERENCIAS_POR_MOTIVO = {
    "SIN_MATCH": ("La venta no existe en el Core con esa referencia", "ESPERAR_SIGUIENTE_CORTE", 0.5),
    "CONTRACARGO_SIN_MATCH": ("Contracargo sobre una venta que el Core no reconoce", "ESCALAR_AL_BANCO", 0.6),
    "MONTO_DIFERENTE": ("Diferencia de monto entre banco y Core (comisión, propina o captura)", "REVISAR_CON_COMERCIO", 0.5),
    "FECHA_FUERA_DE_RANGO": ("Desfase de fecha mayor a la tolerancia", "LIQUIDAR_MANUAL", 0.5),
    "DUPLICADO_EN_ARCHIVO": ("Misma referencia repetida en el archivo del banco", "IGNORAR_DUPLICADO", 0.9),
    "COMERCIO_BLOQUEADO": ("Venta de un comercio con saldo bloqueado", "BLOQUEAR_MANUAL", 0.6),
    "CONTRACARGO_MISMO_DIA": ("Venta de un comercio que hoy recibió contracargo", "REVISAR_CON_COMERCIO", 0.6),
    "MONEDA_DISTINTA": ("Moneda del banco distinta a la del Core", "ESCALAR_AL_BANCO", 0.7),
}


@dataclass
class AsistenteNulo:
    nombre: str = "nulo"

    def sugerir(self, contexto: ContextoExcepcion) -> SugerenciaTriaje:
        causa, accion, conf = SUGERENCIAS_POR_MOTIVO.get(contexto.motivo, ("Sin regla de triaje para este motivo", "ESCALAR_AL_BANCO", 0.3))
        if contexto.motivo == "SIN_MATCH" and contexto.candidatos:
            causa, accion, conf = "Hay transacciones parecidas en el Core: posible referencia truncada", "LIQUIDAR_MANUAL", 0.6
        return SugerenciaTriaje(
            causa,
            accion,
            conf,
            f"Sugerencia determinista por motivo {contexto.motivo} ({contexto.regla}).",
            proveedor="nulo",
            modelo="reglas",
            version_prompt="",
        )


# --- Anthropic --------------------------------------------------------------


@dataclass
class AsistenteAnthropic:
    modelo: str = "claude-sonnet-5-5"
    version_prompt: str = "triaje_v1"
    nombre: str = "anthropic"
    _fallback: AsistenteNulo = field(default_factory=AsistenteNulo)

    def sugerir(self, contexto: ContextoExcepcion) -> SugerenciaTriaje:
        import anthropic

        cliente = anthropic.Anthropic()
        inicio = time.monotonic()
        try:
            respuesta = cliente.messages.parse(
                model=self.modelo,
                max_tokens=1024,
                output_config={"effort": "low"},
                system=[{"type": "text", "text": cargar_contexto_fijo(), "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": armar_mensaje(contexto, self.version_prompt)}],
                output_format=EsquemaSugerencia,
            )
        except anthropic.APIError as e:
            log.warning("anthropic no disponible (%s): fallback determinista", type(e).__name__)
            s = self._fallback.sugerir(contexto)
            s.valida = False
            return s
        if respuesta.stop_reason == "refusal" or respuesta.parsed_output is None:
            s = self._fallback.sugerir(contexto)
            s.valida = False
            return s
        p = respuesta.parsed_output
        if p.accion_sugerida not in ACCIONES_SUGERIBLES:
            s = self._fallback.sugerir(contexto)
            s.valida = False
            return s
        log.debug("anthropic %s en %.0f ms", self.modelo, (time.monotonic() - inicio) * 1000)
        return SugerenciaTriaje(
            p.causa_probable,
            p.accion_sugerida,
            p.confianza,
            p.explicacion,
            proveedor="anthropic",
            modelo=self.modelo,
            version_prompt=self.version_prompt,
            tokens_entrada=respuesta.usage.input_tokens,
            tokens_salida=respuesta.usage.output_tokens,
        )


# --- OpenAI-compatible (modelos abiertos / otros proveedores) ---------------


@dataclass
class AsistenteOpenAICompatible:
    url: str
    api_key: str
    modelo: str
    version_prompt: str = "triaje_v1"
    nombre: str = "openai_compatible"
    _fallback: AsistenteNulo = field(default_factory=AsistenteNulo)

    def sugerir(self, contexto: ContextoExcepcion) -> SugerenciaTriaje:
        cuerpo = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": cargar_contexto_fijo()},
                {"role": "user", "content": armar_mensaje(contexto, self.version_prompt)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            r = httpx.post(
                f"{self.url.rstrip('/')}/chat/completions",
                json=cuerpo,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=60,
            )
            r.raise_for_status()
            datos = r.json()
            texto = datos["choices"][0]["message"]["content"]
            uso = datos.get("usage", {})
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("proveedor compatible no disponible (%s): fallback determinista", type(e).__name__)
            s = self._fallback.sugerir(contexto)
            s.valida = False
            return s
        p = validar_salida(texto)
        if p is None:
            s = self._fallback.sugerir(contexto)
            s.valida = False
            return s
        return SugerenciaTriaje(
            p.causa_probable,
            p.accion_sugerida,
            p.confianza,
            p.explicacion,
            proveedor="openai_compatible",
            modelo=self.modelo,
            version_prompt=self.version_prompt,
            tokens_entrada=int(uso.get("prompt_tokens", 0)),
            tokens_salida=int(uso.get("completion_tokens", 0)),
        )
