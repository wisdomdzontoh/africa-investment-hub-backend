#!/bin/sh
# Production boot: migrate, optionally start the ARQ worker in-process,
# then serve the API. Used as the Docker command on Render.
#
# RUN_WORKER=true bundles the background worker into the same container —
# the $0 deployment shape. Split it into a dedicated Render Background
# Worker (command: `arq app.workers.worker.WorkerSettings`, RUN_WORKER=false
# here) once the app needs guaranteed job/cron execution.
set -e

alembic upgrade head

if [ "$RUN_WORKER" = "true" ]; then
  arq app.workers.worker.WorkerSettings &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
