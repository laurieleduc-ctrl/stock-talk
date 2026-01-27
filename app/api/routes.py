"""
API routes for Stock Talk application.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models import DailyReport, ReportStock, Stock
from app.services.report_generator import generate_daily_report

router = APIRouter()


@router.get("/reports")
def get_reports(
    limit: int = Query(default=30, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Get list of all reports with pagination."""
    reports = (
        db.query(DailyReport)
        .order_by(DailyReport.report_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total = db.query(DailyReport).count()

    return {
        "reports": [
            {
                "id": r.id,
                "date": r.report_date.isoformat(),
                "stocks_analyzed": r.total_stocks_analyzed,
                "stocks_in_report": r.stocks_passing_criteria,
            }
            for r in reports
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/reports/latest")
def get_latest_report(db: Session = Depends(get_db)):
    """Get the most recent report with full details."""
    report = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.stocks).joinedload(ReportStock.stock))
        .order_by(DailyReport.report_date.desc())
        .first()
    )

    if not report:
        raise HTTPException(status_code=404, detail="No reports found")

    return _format_report(report)


@router.get("/reports/generate")
def trigger_report_generation_get(db: Session = Depends(get_db)):
    """Manually trigger report generation (GET for easy browser access)."""
    try:
        report = generate_daily_report(db)
        if report:
            return {
                "status": "success",
                "report_id": report.id,
                "date": report.report_date.isoformat(),
                "message": "Report generated! Visit the homepage to view it.",
            }
        else:
            return {
                "status": "failed",
                "message": "No stocks met the criteria for today's report",
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    """Get a specific report by ID."""
    report = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.stocks).joinedload(ReportStock.stock))
        .filter(DailyReport.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return _format_report(report)


@router.get("/reports/date/{date}")
def get_report_by_date(date: str, db: Session = Depends(get_db)):
    """Get report for a specific date (YYYY-MM-DD format)."""
    try:
        report_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Look for report on this date
    start_of_day = report_date.replace(hour=0, minute=0, second=0)
    end_of_day = report_date.replace(hour=23, minute=59, second=59)

    report = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.stocks).joinedload(ReportStock.stock))
        .filter(DailyReport.report_date >= start_of_day)
        .filter(DailyReport.report_date <= end_of_day)
        .first()
    )

    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for {date}")

    return _format_report(report)


@router.get("/stocks/{ticker}")
def get_stock_history(
    ticker: str,
    limit: int = Query(default=30, le=100),
    db: Session = Depends(get_db),
):
    """Get historical report data for a specific stock."""
    stock = db.query(Stock).filter(Stock.ticker == ticker.upper()).first()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")

    report_entries = (
        db.query(ReportStock)
        .options(joinedload(ReportStock.report))
        .filter(ReportStock.stock_id == stock.id)
        .order_by(ReportStock.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "ticker": stock.ticker,
        "name": stock.name,
        "sector": stock.sector,
        "industry": stock.industry,
        "appearances": len(report_entries),
        "history": [
            {
                "report_date": entry.report.report_date.isoformat(),
                "rank": entry.rank,
                "is_dark_horse": entry.is_dark_horse,
                "price": entry.price_at_report,
                "pct_from_ath": entry.pct_from_ath,
                "pe_ratio": entry.pe_ratio,
                "rsi": entry.rsi,
                "reddit_mentions": entry.reddit_mentions_week,
                "sentiment": entry.sentiment_label,
                "buy_case": entry.buy_case,
            }
            for entry in report_entries
        ],
    }


@router.get("/stocks")
def search_stocks(
    q: str = Query(default="", min_length=1),
    sector: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Search stocks that have appeared in reports."""
    query = db.query(Stock)

    if q:
        search_term = f"%{q.upper()}%"
        query = query.filter(
            (Stock.ticker.ilike(search_term)) | (Stock.name.ilike(search_term))
        )

    if sector:
        query = query.filter(Stock.sector.ilike(f"%{sector}%"))

    stocks = query.limit(20).all()

    return {
        "results": [
            {
                "ticker": s.ticker,
                "name": s.name,
                "sector": s.sector,
                "industry": s.industry,
                "market_cap": s.market_cap,
            }
            for s in stocks
        ]
    }


@router.post("/reports/generate")
def trigger_report_generation(db: Session = Depends(get_db)):
    """Manually trigger report generation (for testing/admin use)."""
    try:
        report = generate_daily_report(db)
        if report:
            return {
                "status": "success",
                "report_id": report.id,
                "date": report.report_date.isoformat(),
            }
        else:
            return {
                "status": "failed",
                "message": "No stocks met the criteria for today's report",
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get overall statistics."""
    total_reports = db.query(DailyReport).count()
    total_stocks = db.query(Stock).count()

    # Most featured stocks
    from sqlalchemy import func

    top_stocks = (
        db.query(Stock.ticker, Stock.name, func.count(ReportStock.id).label("count"))
        .join(ReportStock)
        .group_by(Stock.id)
        .order_by(func.count(ReportStock.id).desc())
        .limit(10)
        .all()
    )

    # Sector distribution
    sector_dist = (
        db.query(ReportStock.sector_category, func.count(ReportStock.id).label("count"))
        .group_by(ReportStock.sector_category)
        .all()
    )

    return {
        "total_reports": total_reports,
        "total_unique_stocks": total_stocks,
        "top_featured_stocks": [
            {"ticker": t[0], "name": t[1], "appearances": t[2]} for t in top_stocks
        ],
        "sector_distribution": {s[0]: s[1] for s in sector_dist if s[0]},
    }


def _format_report(report: DailyReport) -> dict:
    """Format a report with all its stocks for API response."""
    stocks_data = []

    for rs in sorted(report.stocks, key=lambda x: x.rank):
        stock = rs.stock

        # Calculate 52-week position
        week_52_position = None
        if rs.fifty_two_week_high and rs.fifty_two_week_low and rs.price_at_report:
            range_size = rs.fifty_two_week_high - rs.fifty_two_week_low
            if range_size > 0:
                week_52_position = round(
                    ((rs.price_at_report - rs.fifty_two_week_low) / range_size) * 100, 1
                )

        stocks_data.append({
            "rank": rs.rank,
            "ticker": stock.ticker,
            "name": stock.name,
            "sector": stock.sector,
            "industry": stock.industry,
            "sector_category": rs.sector_category,
            "is_dark_horse": rs.is_dark_horse,
            "market_cap": stock.market_cap,
            "market_cap_category": stock.market_cap_category,

            # Price data
            "price": rs.price_at_report,
            "pct_from_ath": rs.pct_from_ath,
            "fifty_two_week_high": rs.fifty_two_week_high,
            "fifty_two_week_low": rs.fifty_two_week_low,
            "week_52_position": week_52_position,

            # Valuation
            "pe_ratio": rs.pe_ratio,
            "pb_ratio": rs.pb_ratio,
            "peg_ratio": rs.peg_ratio,

            # Financial health
            "debt_to_equity": rs.debt_to_equity,
            "free_cash_flow": rs.free_cash_flow,
            "profit_margin": rs.profit_margin,

            # Dividends
            "dividend_yield": rs.dividend_yield,

            # Technical
            "rsi": rs.rsi,
            "beta": rs.beta,
            "one_year_return": rs.one_year_return,

            # Ownership
            "short_interest": rs.short_interest,
            "institutional_ownership": rs.institutional_ownership,

            # Analyst
            "analyst_rating": rs.analyst_rating,
            "analyst_count": rs.analyst_count,
            "target_price_mean": rs.target_price_mean,
            "target_upside_pct": rs.target_upside_pct,

            # Earnings
            "next_earnings_date": rs.next_earnings_date.isoformat() if rs.next_earnings_date else None,

            # Reddit
            "reddit_mentions": rs.reddit_mentions_week,
            "reddit_sentiment": rs.reddit_sentiment,
            "sentiment_label": rs.sentiment_label,

            # Activity & News
            "insider_activity": rs.insider_activity or [],
            "recent_news": rs.recent_news or [],

            # Analysis
            "buy_case": rs.buy_case,
            "risk_factors": rs.risk_factors or [],
            "dark_horse_reasons": rs.dark_horse_reasons or [],

            # Signals
            "bullish_signals": rs.bullish_signals,
            "bearish_signals": rs.bearish_signals,
            "neutral_signals": rs.neutral_signals,
        })

    # Sector summary
    sector_counts = {}
    for s in stocks_data:
        cat = s["sector_category"] or "other"
        sector_counts[cat] = sector_counts.get(cat, 0) + 1

    return {
        "id": report.id,
        "date": report.report_date.isoformat(),
        "stocks_analyzed": report.total_stocks_analyzed,
        "stocks_passing_criteria": report.stocks_passing_criteria,
        "market_summary": report.market_summary,
        "sp500_change": report.sp500_change,
        "nasdaq_change": report.nasdaq_change,
        "tip_of_the_day": {
            "title": report.tip_of_the_day_title,
            "content": report.tip_of_the_day_content,
        },
        "sector_breakdown": sector_counts,
        "stocks": stocks_data,
    }
