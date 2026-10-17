"""Composición: de la configuración a los adaptadores concretos. Único lugar que conoce ambos."""

from __future__ import annotations

import os
from pathlib import Path

from .adaptadores.banco import FuenteAPIBanco, FuenteArchivoManual, FuentePortalRPA
from .adaptadores.core import BloqueadorCoreAPI, BloqueadorCoreUI, CoreAPI
from .adaptadores.llm import AsistenteAnthropic, AsistenteNulo, AsistenteOpenAICompatible
from .adaptadores.notificador import NotificadorLog, NotificadorSlack
from .config import Configuracion
from .observabilidad import NotificadorCompuesto, NotificadorCorreo, NotificadorTelegram
from .orquestador import Adaptadores


def construir_adaptadores(cfg: Configuracion) -> Adaptadores:
    if cfg.fuente_banco == "portal_rpa":
        fuente = FuentePortalRPA(cfg.url_portal_banco, cfg.usuario_portal, cfg.clave_portal, cfg.ruta_evidencia)
    elif cfg.fuente_banco == "api":
        fuente = FuenteAPIBanco(cfg.url_api_banco, cfg.token_api_banco)
    else:
        fuente = FuenteArchivoManual(Path(cfg.archivo_csv_manual))

    core = CoreAPI(cfg.url_core, cfg.token_core)
    if cfg.bloqueador == "ui_rpa":
        bloqueador = BloqueadorCoreUI(cfg.url_core, cfg.usuario_core_ui, cfg.clave_core_ui, cfg.ruta_evidencia)
    else:
        bloqueador = BloqueadorCoreAPI(cfg.url_core, cfg.token_core)

    if cfg.proveedor_llm == "anthropic":
        asistente = AsistenteAnthropic(modelo=cfg.modelo_llm)
    elif cfg.proveedor_llm == "openai_compatible":
        asistente = AsistenteOpenAICompatible(cfg.url_llm, os.environ.get("LLM_API_KEY", ""), cfg.modelo_llm)
    else:
        asistente = AsistenteNulo()

    canales = []
    if cfg.slack_webhook:
        canales.append(NotificadorSlack(cfg.slack_webhook))
    if cfg.telegram_token and cfg.telegram_chat:
        canales.append(NotificadorTelegram(cfg.telegram_token, cfg.telegram_chat))
    if cfg.correo_servidor and cfg.correo_destinatarios:
        canales.append(
            NotificadorCorreo(cfg.correo_servidor, cfg.correo_puerto, cfg.correo_remitente, cfg.correo_destinatarios, cfg.correo_usuario, cfg.correo_clave)
        )
    notificador = NotificadorCompuesto(canales) if canales else NotificadorLog()
    return Adaptadores(fuente, core, core, bloqueador, asistente, notificador)
