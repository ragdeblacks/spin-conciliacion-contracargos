from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("conciliador.notificaciones")


@dataclass
class NotificadorSlack:
    webhook: str

    def enviar(self, titulo: str, cuerpo: str, severidad: str = "info") -> None:
        icono = {"info": "ℹ️", "alerta": "⚠️", "critico": "🚨"}.get(severidad, "ℹ️")
        try:
            httpx.post(self.webhook, json={"text": f"{icono} *{titulo}*\n{cuerpo}"}, timeout=10)
        except httpx.HTTPError as e:
            log.warning("no se pudo notificar a Slack: %s", e)


@dataclass
class NotificadorLog:
    def enviar(self, titulo: str, cuerpo: str, severidad: str = "info") -> None:
        log.info(
            json.dumps({"evento": "notificacion", "severidad": severidad, "titulo": titulo, "cuerpo": cuerpo}, ensure_ascii=False)
        )
