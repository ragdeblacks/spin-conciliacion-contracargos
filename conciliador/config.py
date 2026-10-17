"""Configuración por variables de entorno. En producción las inyecta el gestor
de secretos (Vault / AWS Secrets Manager / K8s Secrets); en local, un .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .dominio.reglas import ParametrosConciliacion

MODOS = ("sombra", "asistida", "autonoma")
FUENTES_BANCO = ("portal_rpa", "api", "archivo")
BLOQUEADORES = ("ui_rpa", "api")
PROVEEDORES_LLM = ("nulo", "anthropic", "openai_compatible")

PLACEHOLDERS_PROHIBIDOS = {"", "cambiar", "changeme", "password", "secret", "xxx"}


def _env(nombre: str, defecto: str = "") -> str:
    return os.environ.get(nombre, defecto).strip()


def _env_int(nombre: str, defecto: int) -> int:
    v = _env(nombre)
    return int(v) if v else defecto


@dataclass
class Configuracion:
    modo: str = "sombra"
    fuente_banco: str = "portal_rpa"
    bloqueador: str = "ui_rpa"
    proveedor_llm: str = "nulo"
    modelo_llm: str = "claude-sonnet-5-5"
    url_llm: str = ""  # para openai_compatible
    presupuesto_llm_llamadas_corrida: int = 200
    presupuesto_llm_tokens_dia: int = 2_000_000
    max_tokens_contexto_excepcion: int = 1500

    url_portal_banco: str = "http://localhost:8001"
    usuario_portal: str = ""
    clave_portal: str = ""
    url_api_banco: str = "http://localhost:8001/api/v2"
    token_api_banco: str = ""
    archivo_csv_manual: str = ""

    url_core: str = "http://localhost:8002"
    token_core: str = ""
    usuario_core_ui: str = ""
    clave_core_ui: str = ""

    ruta_libro_mayor: Path = Path("datos/libro_mayor.sqlite")
    ruta_evidencia: Path = Path("evidencia")
    slack_webhook: str = ""
    telegram_token: str = ""
    telegram_chat: str = ""
    correo_servidor: str = ""
    correo_puerto: int = 587
    correo_remitente: str = ""
    correo_destinatarios: list[str] = field(default_factory=list)
    correo_usuario: str = ""
    correo_clave: str = ""
    url_latido: str = ""
    hora_limite: str = "06:00"
    volumen_minimo: int = 1
    volumen_factor_maximo: float = 3.0  # G-VOLUMEN: más de 3x el promedio histórico detiene
    parametros: ParametrosConciliacion = field(default_factory=ParametrosConciliacion)

    @classmethod
    def desde_entorno(cls) -> Configuracion:
        c = cls(
            modo=_env("CONCILIADOR_MODO", "sombra"),
            fuente_banco=_env("FUENTE_BANCO", "portal_rpa"),
            bloqueador=_env("BLOQUEADOR_CORE", "ui_rpa"),
            proveedor_llm=_env("LLM_PROVEEDOR", "nulo"),
            modelo_llm=_env("LLM_MODELO", "claude-sonnet-5-5"),
            url_llm=_env("LLM_URL"),
            presupuesto_llm_llamadas_corrida=_env_int("LLM_PRESUPUESTO_LLAMADAS_CORRIDA", 200),
            presupuesto_llm_tokens_dia=_env_int("LLM_PRESUPUESTO_TOKENS_DIA", 2_000_000),
            url_portal_banco=_env("BANCO_PORTAL_URL", "http://localhost:8001"),
            usuario_portal=_env("BANCO_PORTAL_USUARIO"),
            clave_portal=_env("BANCO_PORTAL_CLAVE"),
            url_api_banco=_env("BANCO_API_URL", "http://localhost:8001/api/v2"),
            token_api_banco=_env("BANCO_API_TOKEN"),
            archivo_csv_manual=_env("BANCO_CSV_MANUAL"),
            url_core=_env("CORE_URL", "http://localhost:8002"),
            token_core=_env("CORE_API_TOKEN"),
            usuario_core_ui=_env("CORE_UI_USUARIO"),
            clave_core_ui=_env("CORE_UI_CLAVE"),
            ruta_libro_mayor=Path(_env("LIBRO_MAYOR_RUTA", "datos/libro_mayor.sqlite")),
            ruta_evidencia=Path(_env("EVIDENCIA_RUTA", "evidencia")),
            slack_webhook=_env("SLACK_WEBHOOK_URL"),
            telegram_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat=_env("TELEGRAM_CHAT_ID"),
            correo_servidor=_env("CORREO_SMTP_SERVIDOR"),
            correo_puerto=_env_int("CORREO_SMTP_PUERTO", 587),
            correo_remitente=_env("CORREO_REMITENTE"),
            correo_destinatarios=[d.strip() for d in _env("CORREO_DESTINATARIOS").split(",") if d.strip()],
            correo_usuario=_env("CORREO_SMTP_USUARIO"),
            correo_clave=_env("CORREO_SMTP_CLAVE"),
            url_latido=_env("LATIDO_URL"),
            hora_limite=_env("HORA_LIMITE", "06:00"),
            volumen_factor_maximo=float(_env("VOLUMEN_FACTOR_MAXIMO", "3.0")),
            parametros=ParametrosConciliacion(
                tolerancia_monto_centavos=_env_int("TOLERANCIA_MONTO_CENTAVOS", 0),
                tolerancia_dias=_env_int("TOLERANCIA_DIAS", 1),
                umbral_aprobacion_centavos=_env_int("UMBRAL_APROBACION_CENTAVOS", 50_000_00),
                max_contracargos_comercio_dia=_env_int("MAX_CONTRACARGOS_COMERCIO_DIA", 3),
            ),
        )
        c.validar()
        return c

    def validar(self) -> None:
        if self.modo not in MODOS:
            raise ValueError(f"modo inválido {self.modo!r}; opciones: {MODOS}")
        if self.fuente_banco not in FUENTES_BANCO:
            raise ValueError(f"fuente_banco inválida {self.fuente_banco!r}; opciones: {FUENTES_BANCO}")
        if self.bloqueador not in BLOQUEADORES:
            raise ValueError(f"bloqueador inválido {self.bloqueador!r}; opciones: {BLOQUEADORES}")
        if self.proveedor_llm not in PROVEEDORES_LLM:
            raise ValueError(f"proveedor_llm inválido {self.proveedor_llm!r}; opciones: {PROVEEDORES_LLM}")

    def secretos_requeridos(self) -> dict[str, str]:
        """Qué credenciales exige la combinación de adaptadores activa (para G-SECRETOS)."""
        req = {"CORE_API_TOKEN": self.token_core}
        if self.fuente_banco == "portal_rpa":
            req |= {"BANCO_PORTAL_USUARIO": self.usuario_portal, "BANCO_PORTAL_CLAVE": self.clave_portal}
        elif self.fuente_banco == "api":
            req |= {"BANCO_API_TOKEN": self.token_api_banco}
        if self.bloqueador == "ui_rpa":
            req |= {"CORE_UI_USUARIO": self.usuario_core_ui, "CORE_UI_CLAVE": self.clave_core_ui}
        if self.proveedor_llm == "anthropic":
            req |= {"ANTHROPIC_API_KEY": _env("ANTHROPIC_API_KEY")}
        if self.proveedor_llm == "openai_compatible":
            req |= {"LLM_API_KEY": _env("LLM_API_KEY")}
        return req
