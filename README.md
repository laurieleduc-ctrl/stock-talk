# Stock Talk

Daily value stock analysis from Reddit sentiment and market data. Identifies beaten-down stocks mentioned on r/stocks and r/wallstreetbets that might be good value opportunities.

## Features

- **Daily Reports**: Automated reports at 9pm Pacific with top 20 value picks
- **Reddit Sentiment**: Tracks mentions and sentiment from r/stocks and r/wallstreetbets
- **Comprehensive Metrics**: P/E, P/B, PEG, debt ratios, RSI, insider activity, and more
- **Dark Horse Picks**: 2 under-the-radar stocks each day with strong fundamentals but low attention
- **Beginner-Friendly**: Plain-English explanations for all metrics
- **Historical Reports**: Browse and compare past reports

## Tech Stack

- **Backend**: Python, FastAPI
- **Database**: PostgreSQL
- **Frontend**: HTML, Tailwind CSS, Alpine.js, HTMX
- **Data Sources**: Reddit API (PRAW), Yahoo Finance (yfinance)
- **Hosting**: Railway

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL (or use Railway's hosted PostgreSQL)
- Reddit API credentials

### Reddit API Setup

1. Go to https://www.reddit.com/prefs/apps
2. Click "create another app..."
3. Select "script"
4. Fill in name and redirect URI (use http://localhost:8000)
5. Note your client ID (under the app name) and client secret

### Local Development

1. Clone the repository:
   ```bash
   cd stock-talk
   ```

2. Create virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -e .
   ```

4. Copy environment file and configure:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. Run the application:
   ```bash
   # Run web server
   uvicorn app.main:app --reload

   # In another terminal, run scheduler (or let it auto-generate on startup)
   python -m app.scheduler
   ```

6. Open http://localhost:8000

### Deploy to Railway

1. Create a new project on [Railway](https://railway.app)

2. Add PostgreSQL:
   - Click "New" → "Database" → "PostgreSQL"
   - Railway will automatically set `DATABASE_URL`

3. Connect your repository:
   - Click "New" → "GitHub Repo"
   - Select your stock-talk repository

4. Configure environment variables in Railway:
   ```
   REDDIT_CLIENT_ID=your_client_id
   REDDIT_CLIENT_SECRET=your_client_secret
   REDDIT_USER_AGENT=StockTalk/1.0
   ENVIRONMENT=production
   SECRET_KEY=generate-a-secure-key
   ```

5. Deploy:
   - Railway will automatically build and deploy
   - You'll get a public URL like `stock-talk.up.railway.app`

6. Set up the worker process:
   - In Railway, go to your service settings
   - Add a new service for the worker using the same repo
   - Set start command to: `python -m app.scheduler`

## Project Structure

```
stock-talk/
├── app/
│   ├── api/
│   │   └── routes.py       # API endpoints
│   ├── core/
│   │   ├── config.py       # App configuration
│   │   └── database.py     # Database setup
│   ├── models/
│   │   ├── report.py       # Report models
│   │   └── stock.py        # Stock models
│   ├── services/
│   │   ├── reddit_scraper.py   # Reddit data fetching
│   │   ├── stock_fetcher.py    # Stock data fetching
│   │   └── report_generator.py # Report generation logic
│   ├── static/
│   │   ├── css/
│   │   └── js/
│   ├── templates/          # Jinja2 HTML templates
│   ├── main.py            # FastAPI app entry point
│   └── scheduler.py       # Scheduled job runner
├── Dockerfile
├── railway.toml
├── pyproject.toml
└── README.md
```

## API Endpoints

- `GET /api/reports` - List all reports
- `GET /api/reports/latest` - Get today's report
- `GET /api/reports/{id}` - Get specific report
- `GET /api/reports/date/{YYYY-MM-DD}` - Get report by date
- `GET /api/stocks/{ticker}` - Get stock history
- `GET /api/stocks?q=search` - Search stocks
- `GET /api/stats` - Overall statistics
- `POST /api/reports/generate` - Manually trigger report (admin)

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | SQLite (dev) |
| `REDDIT_CLIENT_ID` | Reddit API client ID | Required |
| `REDDIT_CLIENT_SECRET` | Reddit API secret | Required |
| `REDDIT_USER_AGENT` | Reddit API user agent | StockTalk/1.0 |
| `REPORT_HOUR` | Hour to generate report (24h) | 21 (9pm) |
| `REPORT_TIMEZONE` | Timezone for scheduling | America/Los_Angeles |

## Disclaimer

This tool is for informational purposes only and does not constitute financial advice. Always do your own research before making investment decisions.
