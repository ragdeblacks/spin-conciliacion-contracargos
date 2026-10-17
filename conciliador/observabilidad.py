"""Observabilidad: errores a Sentry, latido a un monitor de cron (Healthchecks / Cronitor)
y notificadores por canal. Todo opcional: sin la variable de entorno, no hace nada.
"""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage

import httpx

log = logging.getLogger("conciliador.observabilidad")


def iniciar_sentry(release: str = "conciliador@0.1.0") -> bool:
    """Captura excepciones no controladas con contexto de corrida. Requiere SENTRY_DSN."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk  # dependencia opcional
    except ImportError:
        log.warning("SENTRY_DSN definido pero sentry-sdk no está instalado")
        return False
    sentry_sdk.init(dsn=dsn, release=release, environment=os.environ.get("ENTORNO", "local"), traces_sample_rate=0.0, send_default_pii=False)
    return True


def latido(url: str | None, ok: bool, corrida_id: int | None = None) -> None:
    """Dead man's switch: si el monitor no recibe el latido antes de la hora límite, él mismo alerta.
    Convención de Healthchecks.io: <url> = éxito, <url>/fail = fallo."""
    if not url:
        return
    destino = url if ok else f"{url.rstrip('/')}/fail"
    try:
        httpx.post(destino, content=f"corrida={corrida_id}", timeout=10)
    except httpx.HTTPError as e:
        log.warning("no se pudo enviar el latido al monitor: %s", e)


@dataclass
class NotificadorTelegram:
    token_bot: str
    chat_id: str

    def enviar(self, titulo: str, cuerpo: str, severidad: str = "info") -> None:
        icono = {"info": "ℹ️", "alerta": "⚠️", "critico": "🚨"}.get(severidad, "ℹ️")
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self.token_bot}/sendMessage", json={"chat_id": self.chat_id, "text": f"{icono} {titulo}\n{cuerpo}"}, timeout=10
            )
        except httpx.HTTPError as e:
            log.warning("no se pudo notificar a Telegram: %s", e)


@dataclass
class NotificadorCorreo:
    servidor: str
    puerto: int
    remitente: str
    destinatarios: list[str]
    usuario: str = ""
    clave: str = ""
    solo_severidades: tuple[str, ...] = ("alerta", "critico")  # el correo es para lo que debe quedar registrado

    def enviar(self, titulo: str, cuerpo: str, severidad: str = "info") -> None:
        if severidad not in self.solo_severidades:
            return
        msg = EmailMessage()
        msg["Subject"] = f"[Conciliación] {titulo}"
        msg["From"], msg["To"] = self.remitente, ", ".join(self.destinatarios)
        msg.set_content(cuerpo)
        try:
            with smtplib.SMTP(self.servidor, self.puerto, timeout=15) as s:
                if self.usuario:
                    s.starttls()
                    s.login(self.usuario, self.clave)
                s.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            log.warning("no se pudo enviar el correo: %s", e)


@dataclass
class NotificadorCompuesto:
    canales: list = field(default_factory=list)

    def enviar(self, titulo: str, cuerpo: str, severidad: str = "info") -> None:
        for c in self.canales:
            c.enviar(titulo, cuerpo, severidad)
