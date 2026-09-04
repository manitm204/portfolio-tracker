# Personal Portfolio Tracker

A private, responsive two-account portfolio dashboard: FastAPI + SQLAlchemy + pandas backend,
React + TypeScript + Vite + Tailwind + Plotly frontend, FMP market data, SQLite storage,
APScheduler end-of-day refresh, Docker Compose deployment.

## Accounts

- **`PORTFOLIO_125`** — ≈$5,000, 125 candidate rows, purchased at the **July 24, 2026** market
  open. Active holdings use two-decimal share quantities from the official opening price.
  `FDXF` is a zero-dollar inactive candidate kept as metadata and excluded from every statistic.
- **`PORTFOLIO_5`** — $500; exactly $100 into each of GOOGL, IBKR, CIEN, SPGI, ADSK at the
  **July 29, 2026** open. Fractional shares = `100 / official_open` at full float precision.
- **Combined** — mathematically correct union: values sum per date, and the combined SPY/QQQ
  benchmark receives each account's external flows on its own inception date.

## Repository layout

```
backend/          FastAPI app, analytics, ingestion, Alembic migrations, pytest suite
frontend/         React dashboard (Vite, Tailwind, Plotly), Vitest + Playwright tests
data/             Seed book CSVs + SQLite database (created at runtime)
screenshots/      Captured desktop/mobile screenshots (dark + light)
docker-compose.yml
```

## Setup (local development)

Prereqs: Python 3.11+, Node 20+.

```bash
# 1. Configure the environment (never commit .env)
cp .env.example .env          # then put your real FMP key in FMP_API_KEY

# 2. Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head              # create/migrate the SQLite schema

# 3. One-time seed hydration (fetches official opens from FMP exactly once)
.venv/bin/python -m app.cli bootstrap

# 4. First market-data refresh (prices + dividends/splits since inception)
.venv/bin/python -m app.cli refresh

# 5. Run the API
.venv/bin/uvicorn app.main:app --port 8000

# 6. Frontend (second terminal)
cd ../frontend
npm install
npm run dev                                  # http://localhost:5173
# If port 8000 is taken, run uvicorn on another port and:
# VITE_API_URL=http://localhost:8001 npm run dev
```

`python -m app.cli status` prints hydration/refresh state at any time.

### Hydrating real data — the single command

If the code was developed against fixtures or the key was unavailable, the one command that
hydrates real data once `FMP_API_KEY` is set:

```bash
cd backend && .venv/bin/python -m app.cli bootstrap && .venv/bin/python -m app.cli refresh
```

Bootstrap is guarded by `bootstrap_state` and unique source keys — running it again is a no-op.
Refresh is incremental and idempotent: run it as often as you like.

## Updates

- **Automatic**: APScheduler fires an EOD refresh Mon–Fri at `EOD_REFRESH_TIME`
  (default 18:00 `America/New_York`) inside the backend process.
- **Manual**: the ⟳ Refresh button in the header, or `POST /api/refresh`, or the CLI.
- Bars fetched during the trading session are marked *provisional* (an "intraday" badge is
  shown) and re-fetched at the next refresh. Per-symbol sync state, coverage and failures are
  on the **Data Quality** page.
- Future buys/sells/deposits/withdrawals/dividends/fees/splits/symbol changes need only a new
  transaction row — via CSV import on the Transactions page (schema:
  `data/transactions.example.csv`) — never a code change.

## Tests

```bash
# Backend: finance acceptance tests + API integration (29 tests)
cd backend && .venv/bin/python -m pytest tests

# Frontend unit (Vitest + Testing Library)
cd frontend && npm test

# End-to-end (Playwright; needs backend :8000 + hydrated data; browser: npx playwright install chromium)
cd frontend && npx playwright test
# against a non-default port: PW_BASE_URL=http://localhost:5174 npx playwright test
```

## Docker

Prereqs: the Docker Compose plugin (`docker compose version` should work) and a user in the
`docker` group (or run with `sudo`). Ports are overridable when 8000/3000 are taken:
`BACKEND_PORT=8010 FRONTEND_PORT=3010 docker compose up`.

```bash
cp .env.example .env      # set FMP_API_KEY
docker compose up --build # frontend at http://localhost:3000, API at :8000
# hydrate inside the container (first run only):
docker compose exec backend python -m app.cli bootstrap
docker compose exec backend python -m app.cli refresh
```

The SQLite DB persists in `./data/portfolio_tracker.db` via the volume mount. The schema is
managed by Alembic; the models keep to portable column types so the `DATABASE_URL` can point
at PostgreSQL later without code changes.

## Financial methodology (summary — full version on the in-app Methodology page)

- **Ledger**: append-only transactions (BUY/SELL/DIVIDEND/DEPOSIT/WITHDRAWAL/FEE/SPLIT/
  SYMBOL_CHANGE). Daily positions and cash are reconstructed from the ledger; nothing is
  edited in place. Machine-generated rows carry unique source keys, so hydration, dividend
  detection and CSV import can never duplicate.
- **Official fills**: opening prices fetched once at bootstrap, stored immutably, never
  recomputed from newer data. Where two-decimal rounding pushed the 125-book's cost slightly
  above $5,000, the initial deposit records the actual amount spent (documented on the
  transaction), so cash is never negative and benchmarks receive the true external flow.
- **Prices**: raw OHLC and dividend-adjusted closes stored side by side. Market value = raw
  close × actual shares; per-ticker return series use adjusted closes. Never mixed silently.
- **Calendar**: trading days = dates with a SPY bar. Missing symbol prices are forward-filled
  (0% return for that symbol, never zero value, never fabricated) and flagged in Data Quality.
- **TWR**: `r_t = MV_t / (MV_{t-1} + F_t) − 1` with start-of-day external flows; geometric
  linking. Same-day flows create no false performance.
- **XIRR**: bisection on the NPV of dated external flows + terminal value; annualized (read
  early-life values with the annualization caveat shown in the UI).
- **Benchmarks**: SPY/QQQ receive the identical external flows on the identical dates,
  entering at that session's (adjusted) open; distributions reinvested via adjusted prices.
  The combined benchmark respects both inception dates.
- **Beta**: `cov(r_p, r_SPY) / var(r_SPY)` on aligned daily returns — never a weighted
  average of vendor betas. The security-level "β·w" view is separately labelled. All risk
  statistics enforce configurable minimum observations and render "insufficient history".
- **Dividends**: credited on the ex-date (shares held before ex-date × per-share amount)
  until the payment date passes; declared-but-future ex-dates are never materialized early.
- **Splits**: multiply shares with zero economic return, applied from the effective date.

## Security

- `FMP_API_KEY` is read only by the backend process (`backend/app/config.py`), never enters
  the frontend bundle or API responses, and httpx request-URL logging is capped to keep the
  key out of logs. `.env` is git-ignored; only `.env.example` is committed.
