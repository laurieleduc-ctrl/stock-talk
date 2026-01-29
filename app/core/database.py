import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url_sync,
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations():
    """Run database migrations to add missing columns."""
    # Columns to add to report_stocks table (column_name, type)
    report_stocks_columns = [
        ("one_year_return", "FLOAT"),
        ("three_month_return", "FLOAT"),
        ("beta", "FLOAT"),
        ("business_summary", "TEXT"),
        ("fifty_two_week_high", "FLOAT"),
        ("fifty_two_week_low", "FLOAT"),
    ]

    with engine.connect() as conn:
        for column_name, column_type in report_stocks_columns:
            try:
                # Check if column exists
                result = conn.execute(text(f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'report_stocks' AND column_name = '{column_name}'
                """))
                if result.fetchone() is None:
                    # Column doesn't exist, add it
                    logger.info(f"Adding column {column_name} to report_stocks table")
                    conn.execute(text(f"""
                        ALTER TABLE report_stocks ADD COLUMN {column_name} {column_type}
                    """))
                    conn.commit()
                    logger.info(f"Successfully added column {column_name}")
            except Exception as e:
                logger.warning(f"Could not add column {column_name}: {e}")
                # Continue with other columns even if one fails


def init_db():
    """Initialize database tables."""
    from app.models import report, stock  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Run migrations to add any missing columns
    try:
        run_migrations()
    except Exception as e:
        logger.warning(f"Migration failed (may be SQLite or already migrated): {e}")
