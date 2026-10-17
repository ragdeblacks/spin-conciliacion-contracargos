from conciliador import observabilidad
from conciliador.observabilidad import NotificadorCompuesto, NotificadorCorreo, latido
from tests.fakes import NotificadorFalso


def test_compuesto_reparte_a_todos_los_canales():
    a, b = NotificadorFalso(), NotificadorFalso()
    NotificadorCompuesto([a, b]).enviar("t", "c", "critico")
    assert a.enviados == b.enviados == [("t", "c", "critico")]


def test_correo_solo_manda_lo_que_debe_quedar_registrado(monkeypatch):
    enviados = []

    class SMTPFalso:
        def __init__(self, *a, **k): ...
        def __enter__(self):
            return self

        def __exit__(self, *a): ...
        def send_message(self, m):
            enviados.append(m["Subject"])

    monkeypatch.setattr(observabilidad.smtplib, "SMTP", SMTPFalso)
    n = NotificadorCorreo("smtp", 587, "bot@spin.mx", ["ops@spin.mx"])
    n.enviar("resumen", "ok", "info")
    n.enviar("detenida", "G-CORE-VIVO", "critico")
    assert enviados == ["[Conciliación] detenida"]


def test_latido_usa_fail_cuando_la_corrida_no_cierra(monkeypatch):
    llamadas = []
    monkeypatch.setattr(observabilidad.httpx, "post", lambda url, **k: llamadas.append(url))
    latido("https://hc-ping.com/abc", True, 1)
    latido("https://hc-ping.com/abc", False, 2)
    latido("", True, 3)
    assert llamadas == ["https://hc-ping.com/abc", "https://hc-ping.com/abc/fail"]


def test_sentry_sin_dsn_no_hace_nada(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert observabilidad.iniciar_sentry() is False
