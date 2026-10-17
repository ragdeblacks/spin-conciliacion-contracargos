"""CLI del conciliador.

conciliador correr   --fecha 2026-10-15 [--modo sombra|asistida|autonoma]
conciliador aprobar  --corrida 3 --aprobador "Ana López" [--decision 12 --decision 15]
conciliador comparar --corrida 3
conciliador reporte  --corrida 3 [--salida reporte.md]
conciliador corridas
conciliador contrato-portal
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta

from .config import Configuracion
from .ensamblaje import construir_adaptadores
from .libro_mayor import LibroMayor
from .observabilidad import iniciar_sentry
from .orquestador import Orquestador
from .reporte import reporte_markdown


def _logging(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format='{"t":"%(asctime)s","nivel":"%(levelname)s","origen":"%(name)s","msg":"%(message)s"}',
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="conciliador", description="Conciliación diaria de contracargos y liquidaciones")
    p.add_argument("-v", "--verboso", action="store_true")
    sub = p.add_subparsers(dest="comando", required=True)

    c = sub.add_parser("correr", help="ejecuta la corrida del día")
    c.add_argument("--fecha", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    c.add_argument("--modo", choices=("sombra", "asistida", "autonoma"))
    c.add_argument("--fuente", choices=("portal_rpa", "api", "archivo"))
    c.add_argument("--json", action="store_true", help="imprime el resultado en JSON")

    a = sub.add_parser("aprobar", help="aprueba y ejecuta decisiones pendientes (doble control)")
    a.add_argument("--corrida", type=int, required=True)
    a.add_argument("--aprobador", required=True)
    a.add_argument("--decision", type=int, action="append", help="id de decisión; sin esta opción aprueba todas")

    s = sub.add_parser("comparar", help="modo sombra: compara contra lo que hizo el analista en el Core")
    s.add_argument("--corrida", type=int, required=True)

    r = sub.add_parser("reporte", help="reporte matutino en Markdown")
    r.add_argument("--corrida", type=int, required=True)
    r.add_argument("--salida")

    sub.add_parser("corridas", help="lista corridas")
    sub.add_parser("contrato-portal", help="G-CONTRATO-PORTAL: ¿los selectores siguen vivos?")

    args = p.parse_args(argv)
    _logging(args.verboso)
    iniciar_sentry()
    cfg = Configuracion.desde_entorno()
    if getattr(args, "modo", None):
        cfg.modo = args.modo
    if getattr(args, "fuente", None):
        cfg.fuente_banco = args.fuente
    libro = LibroMayor(cfg.ruta_libro_mayor)
    orq = Orquestador(cfg, libro, construir_adaptadores(cfg))

    if args.comando == "correr":
        res = orq.correr(args.fecha)
        if args.json:
            print(
                json.dumps(
                    {
                        "corrida": res.corrida_id,
                        "estado": res.estado,
                        "resumen": res.resumen,
                        "gates": [g.__dict__ for g in res.gates],
                        "duracion_s": round(res.duracion_s, 2),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"corrida {res.corrida_id}: {res.estado} en {res.duracion_s:.1f}s")
            for k, v in res.resumen.items():
                if "/" not in k:
                    print(f"  {k:<22} {v}")
            fallidos = [g for g in res.gates if not g.ok]
            for g in fallidos:
                print(f"  ❌ {g.gate}: {g.detalle}")
        return 0 if res.estado == "CERRADA" else 2

    if args.comando == "aprobar":
        decisiones = orq.aprobar_y_ejecutar(args.corrida, args.aprobador, args.decision)
        for d in decisiones:
            print(f"  {d.id:>4} {d.accion:<9} {d.movimiento.referencia:<14} {d.estado_ejecucion}")
        print(f"{len(decisiones)} decisiones aprobadas por {args.aprobador}")
        return 0

    if args.comando == "comparar":
        r = orq.comparar_sombra(args.corrida)
        print(f"{r['gate'].gate}: {'OK' if r['gate'].ok else 'FALLÓ'} — {r['gate'].detalle}")
        for d in r["diferencias"][:20]:
            print(f"  {d['referencia']}: pipeline={d['pipeline']} core={d['core']}")
        return 0 if r["gate"].ok else 2

    if args.comando == "reporte":
        md = reporte_markdown(libro, args.corrida)
        if args.salida:
            with open(args.salida, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"reporte escrito en {args.salida}")
        else:
            print(md)
        return 0

    if args.comando == "corridas":
        for c in libro.corridas():
            print(f"  {c['id']:>4} {c['fecha_operacion']} {c['modo']:<9} {c['fuente']:<11} {c['estado']:<9} {c['inicio']} → {c['fin'] or '-'}")
        return 0

    if args.comando == "contrato-portal":
        fuente = orq.ad.fuente_banco
        if not hasattr(fuente, "probar_contrato"):
            print("la fuente activa no es el portal RPA")
            return 0
        ok, detalle = fuente.probar_contrato()
        print(f"G-CONTRATO-PORTAL: {'OK' if ok else 'FALLÓ'} — {detalle}")
        return 0 if ok else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
