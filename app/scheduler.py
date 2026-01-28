"""
Scheduler for running daily report generation.
Runs at 9pm Pacific time.

This module runs as a separate worker process from the web server.
It handles the scheduled 9pm PT report generation with no timeout constraints,
allowing analysis of more stocks with full historical data.
"""

import logging
import os
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.services.report_generator import generate_daily_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for healthcheck endpoint."""

    def do_GET(self):
        """Respond to GET requests with 200 OK."""
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - Worker scheduler running")

    def log_message(self, format, *args):
        """Suppress default logging to avoid noise."""
        pass


def start_health_server():
    """Start a minimal HTTP server for healthchecks in a background thread."""
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Health check server listening on port {port}")
    server.serve_forever()


def run_daily_report():
    """Execute the daily report generation."""
    logger.info("Starting scheduled daily report generation...")

    # Get Pacific time for logging
    pacific = ZoneInfo("America/Los_Angeles")
    current_time = datetime.now(pacific)
    logger.info(f"Current Pacific time: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    db = SessionLocal()
    try:
        # Use full stock limit for scheduled worker (no timeout constraint)
        report = generate_daily_report(db, max_stocks=settings.MAX_STOCKS_WORKER)
        if report:
            logger.info(f"Daily report generated successfully: ID {report.id}")
        else:
            logger.warning("Daily report generation completed but no report was created")
    except Exception as e:
        logger.error(f"Error generating daily report: {e}", exc_info=True)
    finally:
        db.close()


def main():
    """Main entry point for the scheduler."""
    logger.info("Initializing Stock Talk scheduler...")

    # Start health check server in background thread (for Railway healthchecks)
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Create scheduler
    scheduler = BlockingScheduler()

    # Schedule daily report at 9pm Pacific
    # CronTrigger uses the system timezone by default, so we specify Pacific
    pacific = ZoneInfo("America/Los_Angeles")

    trigger = CronTrigger(
        hour=settings.REPORT_HOUR,  # 21 (9pm)
        minute=0,
        timezone=pacific,
    )

    scheduler.add_job(
        run_daily_report,
        trigger=trigger,
        id="daily_report",
        name="Generate daily stock report",
        replace_existing=True,
    )

    logger.info(f"Scheduled daily report generation at {settings.REPORT_HOUR}:00 Pacific")
    logger.info("Scheduler started. Press Ctrl+C to exit.")

    # Also run immediately on startup if no report exists for today
    # This helps when deploying or restarting
    try:
        from app.models import DailyReport
        db = SessionLocal()
        pacific = ZoneInfo("America/Los_Angeles")
        today = datetime.now(pacific).date()

        existing = db.query(DailyReport).filter(
            DailyReport.report_date >= datetime.combine(today, datetime.min.time()),
            DailyReport.report_date <= datetime.combine(today, datetime.max.time()),
        ).first()

        if not existing:
            logger.info("No report for today found, generating initial report...")
            run_daily_report()
        else:
            logger.info("Report for today already exists, skipping initial generation")

        db.close()
    except Exception as e:
        logger.error(f"Error checking for existing report: {e}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
