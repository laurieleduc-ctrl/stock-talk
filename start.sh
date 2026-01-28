#!/bin/sh

# Check if this is a worker service (set WORKER=true or WORKER=TRUE in Railway env vars)
# Convert to lowercase for comparison
WORKER_LOWER=$(echo "$WORKER" | tr '[:upper:]' '[:lower:]')

if [ "$WORKER_LOWER" = "true" ]; then
    echo "Starting worker (scheduler)..."
    exec python -m app.scheduler
else
    echo "Starting web server..."
    exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
fi
