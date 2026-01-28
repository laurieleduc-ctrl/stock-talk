#!/bin/sh

# Check if this is a worker service (set WORKER=true in Railway env vars)
if [ "$WORKER" = "true" ]; then
    echo "Starting worker (scheduler)..."
    exec python -m app.scheduler
else
    echo "Starting web server..."
    exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
fi
