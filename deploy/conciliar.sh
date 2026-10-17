#!/usr/bin/env bash
# Envoltura para cron: corre el contenedor con el entorno de producción y los volúmenes persistentes.
set -euo pipefail
exec docker run --rm \
  --env-file /etc/conciliador/prod.env \
  -v /srv/conciliador/datos:/app/datos \
  -v /srv/conciliador/evidencia:/app/evidencia \
  registry.spin.internal/conciliador:1.0.0 "$@"
