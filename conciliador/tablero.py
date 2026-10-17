"""Tablero de gestión: una página HTML estática generada desde el libro mayor.

Pensada para el líder de Operaciones: semáforos contra objetivo, pestañas por día,
semana y mes, incidencias abiertas con antigüedad y cola de excepciones.
Sin servidor ni dependencias: en producción la misma consulta alimenta Grafana o Datadog.
"""

from __future__ import annotations

import html
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from .dominio.modelos import centavos_a_texto
from .libro_mayor import LibroMayor

OBJETIVOS = {"hora_cierre": "06:00", "auto_pct": 95.0, "min_bloqueo": 15.0, "fallidas": 0}


def _local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso).astimezone()


def _minutos(a: str | None, b: str | None) -> float | None:
    da, db = _local(a), _local(b)
    return (db - da).total_seconds() / 60 if da and db else None


@dataclass
class Dia:
    fecha: str
    corridas: int = 0
    cerradas: int = 0
    detenidas: int = 0
    modo: str = ""
    hora_cierre: str | None = None
    duracion_s: float = 0
    total: int = 0
    liquidar: int = 0
    bloquear: int = 0
    excepcion: int = 0
    ya_procesado: int = 0
    monto_liquidar: int = 0
    monto_bloquear: int = 0
    monto_excepcion: int = 0
    sin_humano: int = 0
    ejecutadas: int = 0
    fallidas: int = 0
    gates_criticos_fallidos: int = 0
    min_bloqueo: float | None = None
    aprobaciones: int = 0
    min_aprobacion: list[float] = field(default_factory=list)
    exc_resueltas: int = 0
    min_resolucion: list[float] = field(default_factory=list)
    sugerencias: int = 0
    sugerencias_modelo: int = 0
    sugerencias_seguidas: int = 0
    tokens: int = 0
    incidencias: int = 0
    incidencias_abiertas: int = 0

    @property
    def auto_pct(self) -> float | None:
        return 100 * self.sin_humano / self.total if self.total else None


def recopilar(libro: LibroMayor, desde: date) -> dict[str, Dia]:
    d0 = desde.isoformat()
    dias: dict[str, Dia] = {}

    def dia(f: str) -> Dia:
        return dias.setdefault(f, Dia(f))

    corridas = {c["id"]: c for c in libro.consultar("SELECT * FROM corridas WHERE fecha_operacion>=? ORDER BY id", (d0,))}
    for c in corridas.values():
        x = dia(c["fecha_operacion"])
        x.corridas += 1
        x.modo = c["modo"]
        if c["estado"] == "CERRADA":
            x.cerradas += 1
            fin = _local(c["fin"])
            x.hora_cierre = fin.strftime("%H:%M") if fin else None
            m = _minutos(c["inicio"], c["fin"])
            x.duracion_s = (m or 0) * 60
        else:
            x.detenidas += 1
    if not corridas:
        return dias
    ids = tuple(corridas)
    marc = ",".join("?" * len(ids))

    for r in libro.consultar(f"SELECT * FROM decisiones WHERE corrida_id IN ({marc})", ids):
        x = dia(corridas[r["corrida_id"]]["fecha_operacion"])
        x.total += 1
        a = r["accion"]
        if a == "LIQUIDAR":
            x.liquidar += 1
            x.monto_liquidar += r["monto_centavos"]
        elif a == "BLOQUEAR":
            x.bloquear += 1
            x.monto_bloquear += r["monto_centavos"]
        elif a == "EXCEPCION":
            x.excepcion += 1
            x.monto_excepcion += r["monto_centavos"]
        else:
            x.ya_procesado += 1
        if (a in ("LIQUIDAR", "BLOQUEAR") and not r["requiere_aprobacion"]) or a == "YA_PROCESADO":
            x.sin_humano += 1
        if r["estado_ejecucion"] == "EJECUTADA":
            x.ejecutadas += 1
        elif r["estado_ejecucion"] == "FALLIDA":
            x.fallidas += 1

    # tiempo al bloqueo: solo los automáticos; los que pasaron por doble control dependen de una persona
    for r in libro.consultar(
        f"""SELECT a.corrida_id, a.actualizada FROM acciones a JOIN decisiones d ON d.id=a.decision_id
                                 WHERE a.corrida_id IN ({marc}) AND a.tipo='BLOQUEAR' AND a.estado='CONFIRMADA' AND d.requiere_aprobacion=0""",
        ids,
    ):
        c = corridas[r["corrida_id"]]
        x = dia(c["fecha_operacion"])
        m = _minutos(c["inicio"], r["actualizada"])
        if m is not None:
            x.min_bloqueo = max(x.min_bloqueo or 0, m)

    for r in libro.consultar(f"SELECT corrida_id, COUNT(*) n FROM gates WHERE corrida_id IN ({marc}) AND ok=0 AND critico=1 GROUP BY corrida_id", ids):
        dia(corridas[r["corrida_id"]]["fecha_operacion"]).gates_criticos_fallidos += r["n"]

    for r in libro.consultar(
        f"""SELECT a.momento, d.creada, d.corrida_id FROM aprobaciones a JOIN decisiones d ON d.id=a.decision_id
                                 WHERE d.corrida_id IN ({marc})""",
        ids,
    ):
        x = dia(corridas[r["corrida_id"]]["fecha_operacion"])
        x.aprobaciones += 1
        m = _minutos(r["creada"], r["momento"])
        if m is not None:
            x.min_aprobacion.append(m)

    for r in libro.consultar(
        f"""SELECT r.momento, r.siguio_sugerencia, d.creada, d.corrida_id FROM resoluciones r
                                 JOIN decisiones d ON d.id=r.decision_id WHERE d.corrida_id IN ({marc})""",
        ids,
    ):
        x = dia(corridas[r["corrida_id"]]["fecha_operacion"])
        x.exc_resueltas += 1
        if r["siguio_sugerencia"]:
            x.sugerencias_seguidas += 1
        m = _minutos(r["creada"], r["momento"])
        if m is not None:
            x.min_resolucion.append(m)

    for r in libro.consultar(f"SELECT * FROM sugerencias WHERE corrida_id IN ({marc})", ids):
        x = dia(corridas[r["corrida_id"]]["fecha_operacion"])
        x.sugerencias += 1
        if r["proveedor"] != "nulo":
            x.sugerencias_modelo += 1
        x.tokens += (r["tokens_entrada"] or 0) + (r["tokens_salida"] or 0)

    for r in libro.consultar("SELECT fecha_operacion, estado FROM incidencias WHERE fecha_operacion>=?", (d0,)):
        x = dia(r["fecha_operacion"])
        x.incidencias += 1
        if r["estado"] == "ABIERTA":
            x.incidencias_abiertas += 1
    return dict(sorted(dias.items()))


@dataclass
class Periodo:
    etiqueta: str
    dias: list[Dia]

    def suma(self, campo: str) -> int:
        return sum(getattr(d, campo) for d in self.dias)

    @property
    def auto_pct(self) -> float | None:
        t = self.suma("total")
        return 100 * self.suma("sin_humano") / t if t else None

    @property
    def dias_a_tiempo(self) -> tuple[int, int]:
        con = [d for d in self.dias if d.hora_cierre]
        return sum(1 for d in con if d.hora_cierre <= OBJETIVOS["hora_cierre"]), len(con)

    @property
    def min_bloqueo(self) -> float | None:
        v = [d.min_bloqueo for d in self.dias if d.min_bloqueo is not None]
        return max(v) if v else None

    def promedio(self, campo: str) -> float | None:
        v = [m for d in self.dias for m in getattr(d, campo)]
        return sum(v) / len(v) if v else None


def agrupar(dias: dict[str, Dia], nivel: str) -> list[Periodo]:
    grupos: dict[str, list[Dia]] = defaultdict(list)
    for f, d in dias.items():
        fecha = date.fromisoformat(f)
        if nivel == "dia":
            clave = f
        elif nivel == "semana":
            iso = fecha.isocalendar()
            clave = f"{iso.year}-S{iso.week:02d}"
        else:
            clave = fecha.strftime("%Y-%m")
        grupos[clave].append(d)
    return [Periodo(k, v) for k, v in sorted(grupos.items())]


# --- HTML -------------------------------------------------------------------

COLORES = {"liquidar": "#4f46e5", "bloquear": "#dc2626", "excepcion": "#f59e0b", "ya_procesado": "#9ca3af"}


def _semaforo(ok: bool | None, medio: bool = False) -> str:
    if ok is None:
        return "gris"
    return "verde" if ok else ("ambar" if medio else "rojo")


def _barras(periodos: list[Periodo], campos: list[str], ancho: int = 860, alto: int = 180) -> str:
    if not periodos:
        return "<p class='vacio'>Sin datos en el periodo.</p>"
    maximo = max(sum(p.suma(c) for c in campos) for p in periodos) or 1
    n = len(periodos)
    paso = ancho / n
    w = max(6, min(40, paso * 0.7))
    out = [f"<svg viewBox='0 0 {ancho} {alto + 30}' class='grafica' role='img'>"]
    for i, p in enumerate(periodos):
        x = i * paso + (paso - w) / 2
        y = alto
        for c in campos:
            v = p.suma(c)
            h = alto * v / maximo
            y -= h
            out.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' fill='{COLORES[c]}'><title>{p.etiqueta}: {c} {v}</title></rect>")
        et = p.etiqueta[-5:] if len(periodos) > 12 else p.etiqueta
        if n <= 31 or i % max(1, n // 15) == 0:
            out.append(f"<text x='{x + w / 2:.1f}' y='{alto + 16}' text-anchor='middle' class='eje'>{html.escape(et)}</text>")
    out.append("</svg>")
    leyenda = " ".join(f"<span class='ley'><i style='background:{COLORES[c]}'></i>{c.replace('_', ' ')}</span>" for c in campos)
    return "".join(out) + f"<div class='leyenda'>{leyenda}</div>"


def _linea(periodos: list[Periodo], valor, objetivo: float, ancho: int = 860, alto: int = 140) -> str:
    puntos = [(i, valor(p)) for i, p in enumerate(periodos)]
    puntos = [(i, v) for i, v in puntos if v is not None]
    if not puntos:
        return "<p class='vacio'>Sin datos en el periodo.</p>"
    n = max(len(periodos), 1)
    paso = ancho / n

    def escala(v: float) -> float:  # eje de 50 % a 100 %: lo que importa es la distancia al objetivo
        return alto - alto * (min(max(v, 50), 100) - 50) / 50

    def xy(i, v):
        return f"{i * paso + paso / 2:.1f},{escala(v):.1f}"

    yobj = escala(objetivo)
    path = " ".join(("M" if k == 0 else "L") + xy(i, v) for k, (i, v) in enumerate(puntos))
    circ = "".join(
        f"<circle cx='{xy(i, v).split(',')[0]}' cy='{xy(i, v).split(',')[1]}' r='3' fill='#4f46e5'><title>{periodos[i].etiqueta}: {v:.1f}%</title></circle>"
        for i, v in puntos
    )
    return (
        f"<svg viewBox='0 0 {ancho} {alto + 10}' class='grafica'><line x1='0' y1='{yobj:.1f}' x2='{ancho}' y2='{yobj:.1f}' stroke='#16a34a' stroke-dasharray='6 4'/>"
        f"<text x='{ancho - 4}' y='{yobj + 14:.1f}' text-anchor='end' class='eje'>objetivo {objetivo:.0f} %</text>"
        f"<text x='4' y='{alto:.0f}' class='eje'>50 %</text><text x='4' y='12' class='eje'>100 %</text>"
        f"<path d='{path}' fill='none' stroke='#4f46e5' stroke-width='2'/>{circ}</svg>"
    )


def _tarjetas(p: Periodo | None) -> str:
    if not p:
        return "<p class='vacio'>Sin corridas en el periodo.</p>"
    a_tiempo, con = p.dias_a_tiempo
    auto = p.auto_pct
    minb = p.min_bloqueo
    fall = p.suma("fallidas")
    abiertas = p.suma("incidencias_abiertas")
    tarjetas = [
        (
            "Liquidación liberada antes de las 06:00",
            f"{a_tiempo} de {con} días" if con else "sin corridas",
            _semaforo(None if not con else a_tiempo == con, con and a_tiempo >= con * 0.8),
            "objetivo: todos los días",
        ),
        (
            "Conciliado sin intervención humana",
            f"{auto:.1f} %" if auto is not None else "—",
            _semaforo(None if auto is None else auto >= OBJETIVOS["auto_pct"], auto is not None and auto >= 85),
            "objetivo: más del 95 %",
        ),
        (
            "Minutos hasta el último bloqueo de contracargo",
            f"{minb:.0f} min" if minb is not None else "—",
            _semaforo(None if minb is None else minb <= OBJETIVOS["min_bloqueo"], minb is not None and minb <= 30),
            "objetivo: menos de 15 min",
        ),
        ("Acciones fallidas", str(fall), _semaforo(fall == 0), "objetivo: cero"),
        ("Incidencias abiertas", str(abiertas), _semaforo(abiertas == 0, abiertas <= 2), "pendientes de un responsable"),
        ("Excepciones por revisar", str(p.suma("excepcion") - p.suma("exc_resueltas")), "gris", f"de {p.suma('excepcion')} en el periodo"),
    ]
    return (
        "<div class='tarjetas'>"
        + "".join(
            f"<div class='tarjeta {s}'><div class='valor'>{html.escape(v)}</div><div class='titulo'>{t}</div><div class='pie'>{pie}</div></div>"
            for t, v, s, pie in tarjetas
        )
        + "</div>"
    )


def _tabla(cabeceras: list[str], filas: list[list[str]], vacio: str = "Nada pendiente.") -> str:
    if not filas:
        return f"<p class='vacio'>{vacio}</p>"
    th = "".join(f"<th>{html.escape(c)}</th>" for c in cabeceras)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in f) + "</tr>" for f in filas)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


def _resumen_periodos(periodos: list[Periodo]) -> str:
    filas = []
    for p in reversed(periodos):
        a, c = p.dias_a_tiempo
        ap = p.promedio("min_aprobacion")
        rs = p.promedio("min_resolucion")
        filas.append(
            [
                html.escape(p.etiqueta),
                str(p.suma("total")),
                str(p.suma("liquidar")),
                str(p.suma("bloquear")),
                str(p.suma("excepcion")),
                f"{p.auto_pct:.1f} %" if p.auto_pct is not None else "—",
                f"{a}/{c}",
                str(p.suma("fallidas")),
                str(p.suma("aprobaciones")),
                f"{ap:.0f} min" if ap is not None else "—",
                f"{p.suma('exc_resueltas')}/{p.suma('excepcion')}",
                f"{rs:.0f} min" if rs is not None else "—",
                f"{p.suma('sugerencias_seguidas')}/{p.suma('exc_resueltas')}" if p.suma("exc_resueltas") else "—",
                str(p.suma("incidencias")),
            ]
        )
    return _tabla(
        [
            "Periodo",
            "Movs",
            "Liquidar",
            "Bloquear",
            "Excepc.",
            "Sin humano",
            "A tiempo",
            "Fallidas",
            "Aprobac.",
            "Tiempo aprob.",
            "Exc. resueltas",
            "Tiempo resol.",
            "Siguió sugerencia",
            "Incid.",
        ],
        filas,
    )


def _antiguedad(iso: str) -> str:
    d = _local(iso)
    if not d:
        return ""
    h = (datetime.now(UTC).astimezone() - d).total_seconds() / 3600
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.0f} días"


def generar_html(libro: LibroMayor, dias_atras: int = 30, hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    desde = hoy - timedelta(days=dias_atras)
    dias = recopilar(libro, desde)
    por_nivel = {n: agrupar(dias, n) for n in ("dia", "semana", "mes")}
    incidencias = libro.incidencias(desde=desde.isoformat())
    abiertas = [i for i in incidencias if i["estado"] == "ABIERTA"]
    pendientes = libro.excepciones_pendientes(desde=desde.isoformat())
    prioridad = {"CONTRACARGO_SIN_MATCH": 0, "COMERCIO_BLOQUEADO": 1, "COMERCIO_EN_RIESGO": 2}
    pendientes.sort(key=lambda e: (prioridad.get(e["motivo"], 9), -e["monto_centavos"]))

    recurrentes = libro.consultar(
        """SELECT d.motivo, d.comercio_id, COUNT(*) n, SUM(d.monto_centavos) monto FROM decisiones d JOIN corridas c ON c.id=d.corrida_id
           WHERE d.accion='EXCEPCION' AND c.fecha_operacion>=? GROUP BY d.motivo, d.comercio_id HAVING n>=3 ORDER BY n DESC LIMIT 10""",
        (desde.isoformat(),),
    )

    def seccion(nivel: str, titulo: str) -> str:
        ps = por_nivel[nivel]
        ultimo = ps[-1] if ps else None
        return f"""<section id='{nivel}' class='pestana'>
<h2>{titulo} <span class='sub'>{html.escape(ultimo.etiqueta) if ultimo else ""}</span></h2>
{_tarjetas(ultimo)}
<h3>Movimientos por resultado</h3>{_barras(ps, ["liquidar", "bloquear", "excepcion", "ya_procesado"])}
<h3>Conciliado sin intervención humana</h3>{_linea(ps, lambda p: p.auto_pct, OBJETIVOS["auto_pct"])}
<h3>Detalle por {titulo.lower()}</h3>{_resumen_periodos(ps)}
</section>"""

    filas_inc = [
        [
            f"<span class='sev {i['severidad']}'>{i['severidad']}</span>",
            html.escape(i["fecha_operacion"]),
            html.escape(i["tipo"].replace("_", " ").lower()),
            html.escape(i["descripcion"]),
            _antiguedad(i["abierta"]),
            f'<code>conciliador resolver --incidencia {i["id"]} --por "…"</code>',
        ]
        for i in abiertas
    ]
    resueltas = [i for i in incidencias if i["estado"] == "RESUELTA"][:15]
    filas_res = [
        [
            html.escape(i["fecha_operacion"]),
            html.escape(i["tipo"].replace("_", " ").lower()),
            html.escape(i["descripcion"]),
            html.escape(i["resuelta_por"] or ""),
            html.escape(i["nota"] or ""),
        ]
        for i in resueltas
    ]
    filas_exc = [
        [
            str(e["id"]),
            html.escape(e["fecha_operacion"]),
            html.escape(e["referencia"]),
            html.escape(e["comercio_id"]),
            centavos_a_texto(e["monto_centavos"]),
            html.escape(e["motivo"].replace("_", " ").lower()),
            html.escape(e["causa_probable"] or ""),
            html.escape(e["accion_sugerida"] or ""),
            f"{(e['confianza'] or 0):.0%}",
        ]
        for e in pendientes[:25]
    ]
    filas_rec = [
        [html.escape(r["motivo"].replace("_", " ").lower()), html.escape(r["comercio_id"]), str(r["n"]), centavos_a_texto(r["monto"])] for r in recurrentes
    ]

    tot_sug = sum(d.sugerencias for d in dias.values())
    tot_modelo = sum(d.sugerencias_modelo for d in dias.values())
    tot_res = sum(d.exc_resueltas for d in dias.values())
    tot_seg = sum(d.sugerencias_seguidas for d in dias.values())
    tokens = sum(d.tokens for d in dias.values())
    ia = (
        f"<p>En el periodo el asistente emitió <b>{tot_sug}</b> sugerencias ({tot_modelo} con modelo, {tot_sug - tot_modelo} con la regla determinista). "
        f"De las <b>{tot_res}</b> excepciones ya resueltas por un analista, en <b>{tot_seg}</b> la decisión coincidió con la sugerencia"
        f"{f' ({100 * tot_seg / tot_res:.0f} %)' if tot_res else ''}. Tokens consumidos: {tokens:,}, costo estimado "
        f"{tokens / 1_000_000 * 4:.2f} USD.</p>"
    )

    generado = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Conciliación · tablero de gestión</title>
<style>
:root{{--ink:#111827;--mut:#6b7280;--lin:#e5e7eb;--fon:#f8fafc;--ind:#4f46e5}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;color:var(--ink);background:var(--fon)}}
header{{background:#1e1b4b;color:#fff;padding:18px 28px}}header h1{{margin:0;font-size:20px}}header .m{{color:#c7d2fe;font-size:13px;margin-top:4px}}
main{{max-width:1100px;margin:0 auto;padding:18px 20px 60px}}
nav{{display:flex;gap:8px;margin:6px 0 18px}}nav button{{border:1px solid var(--lin);background:#fff;padding:8px 16px;border-radius:999px;cursor:pointer;font-size:14px}}
nav button.activo{{background:var(--ind);color:#fff;border-color:var(--ind)}}
.pestana{{display:none}}.pestana.activa{{display:block}}
h2{{font-size:18px;margin:8px 0 12px}}h2 .sub{{color:var(--mut);font-weight:normal;font-size:14px;margin-left:8px}}h3{{font-size:14px;color:#312e81;margin:22px 0 8px}}
.tarjetas{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.tarjeta{{background:#fff;border:1px solid var(--lin);border-left:6px solid #9ca3af;border-radius:8px;padding:12px 14px}}
.tarjeta.verde{{border-left-color:#16a34a}}.tarjeta.ambar{{border-left-color:#f59e0b}}.tarjeta.rojo{{border-left-color:#dc2626}}
.valor{{font-size:26px;font-weight:700}}.titulo{{font-size:13px;margin-top:2px}}.pie{{font-size:11px;color:var(--mut);margin-top:4px}}
.grafica{{width:100%;height:auto;background:#fff;border:1px solid var(--lin);border-radius:8px;padding:8px}}.eje{{font-size:11px;fill:var(--mut)}}
.leyenda{{font-size:12px;color:var(--mut);margin:4px 0 0}}.ley{{margin-right:14px}}.ley i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:12.5px;border:1px solid var(--lin);border-radius:8px}}th,td{{padding:7px 8px;border-bottom:1px solid var(--lin);text-align:left;vertical-align:top}}th{{background:#eef2ff;color:#1e1b4b;font-weight:600}}
.vacio{{color:var(--mut);font-size:13px;background:#fff;border:1px dashed var(--lin);padding:10px;border-radius:8px}}
.sev{{padding:2px 8px;border-radius:999px;font-size:11px;color:#fff;background:#9ca3af}}.sev.critica{{background:#dc2626}}.sev.alta{{background:#f59e0b}}.sev.media{{background:#6366f1}}
code{{font-size:11px;background:#f3f4f6;padding:1px 4px;border-radius:3px}}
section.gestion{{margin-top:34px;border-top:2px solid var(--lin);padding-top:10px}}
</style></head><body>
<header><h1>Conciliación de contracargos y liquidación · tablero de gestión</h1>
<div class='m'>Últimos {dias_atras} días hasta {hoy.isoformat()} · generado {generado} · fuente: libro mayor</div></header>
<main>
<nav><button data-p='dia' class='activo'>Día</button><button data-p='semana'>Semana</button><button data-p='mes'>Mes</button></nav>
{seccion("dia", "Día")}{seccion("semana", "Semana")}{seccion("mes", "Mes")}
<section class='gestion'>
<h2>Incidencias abiertas <span class='sub'>{len(abiertas)} pendientes de un responsable</span></h2>
{_tabla(["Severidad", "Fecha", "Tipo", "Qué pasó", "Antigüedad", "Cómo cerrarla"], filas_inc, "No hay incidencias abiertas.")}
<h3>Resueltas recientemente</h3>
{_tabla(["Fecha", "Tipo", "Qué pasó", "Quién", "Qué se hizo"], filas_res, "Ninguna resuelta en el periodo.")}
<h2 style='margin-top:30px'>Excepciones por revisar <span class='sub'>{len(pendientes)} en total, ordenadas por riesgo y monto</span></h2>
{_tabla(["ID", "Fecha", "Referencia", "Comercio", "Monto", "Motivo", "Causa probable", "Acción sugerida", "Conf."], filas_exc, "Cola vacía.")}
<h3>Excepciones recurrentes (candidatas a regla nueva)</h3>
{_tabla(["Motivo", "Comercio", "Veces", "Monto acumulado"], filas_rec, "Sin patrones repetidos en el periodo.")}
<h2 style='margin-top:30px'>Asistente de IA</h2>{ia}
</section>
</main>
<script>
document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>{{
 document.querySelectorAll('nav button').forEach(x=>x.classList.remove('activo'));b.classList.add('activo');
 document.querySelectorAll('.pestana').forEach(s=>s.classList.toggle('activa',s.id===b.dataset.p));}}));
document.getElementById('dia').classList.add('activa');
</script></body></html>"""


def exportar_json(libro: LibroMayor, dias_atras: int = 30, hoy: date | None = None) -> str:
    """Las mismas métricas en JSON, para alimentar Grafana, Datadog o una hoja de cálculo."""
    hoy = hoy or date.today()
    dias = recopilar(libro, hoy - timedelta(days=dias_atras))
    out = []
    for d in dias.values():
        fila = {k: v for k, v in d.__dict__.items() if not isinstance(v, list)}
        fila["auto_pct"] = d.auto_pct
        fila["min_aprobacion_prom"] = sum(d.min_aprobacion) / len(d.min_aprobacion) if d.min_aprobacion else None
        fila["min_resolucion_prom"] = sum(d.min_resolucion) / len(d.min_resolucion) if d.min_resolucion else None
        out.append(fila)
    return json.dumps(out, ensure_ascii=False, indent=1)
