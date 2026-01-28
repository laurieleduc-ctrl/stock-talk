#!/bin/sh
# Start the scheduler worker for daily report generation
exec python -m app.scheduler
