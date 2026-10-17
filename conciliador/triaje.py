"""Triaje de excepciones: arma el paquete tokenizado, aplica los gates del LLM y
registra la sugerencia. Fuera del camino crítico: si todo falla, el analista
trabaja con las reglas que fallaron y listo.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict

from .config import Configuracion
from .dominio.modelos import Accion, Decision, TipoMovimiento
from .gates import g_llm_pii, g_llm_presupuesto
from .libro_mayor import LibroMayor
from .privacidad import Tokenizador
from .puertos import AsistenteTriaje, ContextoExcepcion, SugerenciaTriaje


def armar_contexto(d: Decision, tok: Tokenizador, contracargos_comercio: int, max_candidatos: int = 5) -> ContextoExcepcion:
    t = d.transaccion
    return ContextoExcepcion(
        motivo=d.motivo.value,
        regla=d.regla,
        nota=d.nota,
        tipo_movimiento=d.movimiento.tipo.value,
        monto_banco=d.movimiento.monto_centavos,
        fecha_banco=d.movimiento.fecha.isoformat(),
        monto_core=t.monto_centavos if t else None,
        fecha_core=t.fecha.isoformat() if t else None,
        estado_core=t.estado.value if t else None,
        comercio_token=tok.comercio(d.movimiento.comercio_id),
        referencia_token=tok.referencia(d.movimiento.referencia),
        candidatos=[
            {
                "referencia": tok.referencia(c.referencia),
                "monto": c.monto_centavos,
                "fecha": c.fecha.isoformat(),
                "estado": c.estado.value,
            }
            for c in d.candidatos[:max_candidatos]
        ],
        contracargos_comercio_dia=contracargos_comercio,
    )


def _estimar_tokens(contexto: ContextoExcepcion) -> int:
    # aproximación conservadora: 1 token ≈ 3.5 caracteres en JSON en español
    return len(json.dumps(asdict(contexto), ensure_ascii=False)) * 2 // 7


def triar_excepciones(
    decisiones: list[Decision], asistente: AsistenteTriaje, libro: LibroMayor, corrida_id: int, cfg: Configuracion
) -> list[tuple[Decision, SugerenciaTriaje, list]]:
    tok = Tokenizador()
    contracargos = Counter(d.movimiento.comercio_id for d in decisiones if d.movimiento.tipo == TipoMovimiento.CONTRACARGO)
    resultados = []
    llamadas = 0
    tokens_dia = libro.tokens_llm_hoy()
    for d in decisiones:
        if d.accion != Accion.EXCEPCION:
            continue
        contexto = armar_contexto(d, tok, contracargos[d.movimiento.comercio_id])
        gates = []
        usar_modelo = asistente.nombre != "nulo"

        # recorte determinista: nunca se manda más de lo presupuestado por excepción
        while _estimar_tokens(contexto) > cfg.max_tokens_contexto_excepcion and contexto.candidatos:
            contexto.candidatos.pop()

        if usar_modelo:
            r_pii = g_llm_pii(json.dumps(asdict(contexto), ensure_ascii=False))
            gates.append(r_pii)
            r_pres = g_llm_presupuesto(llamadas, cfg.presupuesto_llm_llamadas_corrida, tokens_dia, cfg.presupuesto_llm_tokens_dia)
            gates.append(r_pres)
            usar_modelo = r_pii.ok and r_pres.ok

        if usar_modelo:
            sugerencia = asistente.sugerir(contexto)
            llamadas += 1
            tokens_dia += sugerencia.tokens_entrada + sugerencia.tokens_salida
        else:
            from .adaptadores.llm import AsistenteNulo

            sugerencia = AsistenteNulo().sugerir(contexto)

        sugerencia.explicacion = tok.destokenizar(sugerencia.explicacion)
        sugerencia.causa_probable = tok.destokenizar(sugerencia.causa_probable)
        for g in gates:
            libro.registrar_gate(corrida_id, g)
        libro.registrar_sugerencia(corrida_id, d.id, sugerencia)
        resultados.append((d, sugerencia, gates))
    return resultados
