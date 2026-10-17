"""Tokenización de datos sensibles antes de que algo salga del proceso.

El modelo de lenguaje recibe `COMERCIO_A`, `REF_1`, nunca el identificador real.
La tabla de correspondencia vive en memoria y muere con la corrida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PATRONES_PII = [
    re.compile(r"\b\d{13,19}\b"),  # PAN completo
    re.compile(r"\b\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b\d{18}\b"),  # CLABE
    re.compile(r"\b[A-Z]{4}\d{6}[A-Z0-9]{8}\b"),  # CURP
]


@dataclass
class Tokenizador:
    _comercios: dict[str, str] = field(default_factory=dict)
    _referencias: dict[str, str] = field(default_factory=dict)
    _inverso: dict[str, str] = field(default_factory=dict)

    def comercio(self, comercio_id: str) -> str:
        if comercio_id not in self._comercios:
            token = f"COMERCIO_{len(self._comercios) + 1}"
            self._comercios[comercio_id] = token
            self._inverso[token] = comercio_id
        return self._comercios[comercio_id]

    def referencia(self, referencia: str) -> str:
        if referencia not in self._referencias:
            token = f"REF_{len(self._referencias) + 1}"
            self._referencias[referencia] = token
            self._inverso[token] = referencia
        return self._referencias[referencia]

    def destokenizar(self, texto: str) -> str:
        for token, real in self._inverso.items():
            texto = texto.replace(token, real)
        return texto


def contiene_pii(texto: str) -> list[str]:
    """Gate G-LLM-PII: devuelve los fragmentos sospechosos encontrados."""
    hallazgos = []
    for patron in PATRONES_PII:
        hallazgos.extend(patron.findall(texto))
    return hallazgos


def enmascarar_tarjeta(mascara: str) -> str:
    digitos = re.sub(r"\D", "", mascara)
    return f"****{digitos[-4:]}" if len(digitos) >= 4 else ""
