# Imagen del conciliador. Base oficial de Playwright: trae Chromium y sus dependencias del sistema.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY conciliador ./conciliador
COPY mocks ./mocks
COPY contexto ./contexto
COPY prompts ./prompts
RUN uv pip install --no-cache . && playwright install chromium
# usuario sin privilegios: `ubuntu` (uid/gid 1000) ya existe en la imagen base y coincide con el uid
# habitual del desarrollador, así que los volúmenes montados (datos/, evidencia/) son escribibles
RUN mkdir -p /app/datos /app/evidencia && chown -R ubuntu:ubuntu /app
USER ubuntu
ENTRYPOINT ["conciliador"]
CMD ["--help"]
