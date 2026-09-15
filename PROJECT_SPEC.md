# Portfolio Tracker — Product and Engineering Specification

> **Note:** This spec originally covered two accounts, `PORTFOLIO_125` and `PORTFOLIO_5`, plus a
> `combined` pseudo-account view. The 125-stock portfolio and the combined view were retired; the
> product now tracks a single account, `PORTFOLIO_5`. Sections below that still describe the
> retired account or combined view are kept as historical record of the original design.

## Product goal

Build a private, responsive portfolio-tracking website for a personal investment account. It must show how the account has performed since inception, compare it fairly with SPY and QQQ, explain allocation and risk, and support end-of-day updates plus manual refreshes.

This is a tracking and analytics product, not a trade-recommendation engine.

## Canonical account

### $500 · 5 Stock Portfolio

- Account ID: `PORTFOLIO_5`
- Purchase date: July 29, 2026
- Total starting capital: $500
- Exactly $100 invested in each of GOOGL, IBKR, CIEN, SPGI, and ADSK at the official July 29 opening price.
- Fractional shares equal `100 / official_open`; retain at least six decimal places.

## Market data

- Use FMP as the primary provider because the user has an API key.
- The API key must remain server-side and must never be exposed in browser bundles, logs, screenshots, or committed files.
- Use adjusted end-of-day history for return series and corporate-action continuity.
- Store both raw OHLC and adjusted-close fields when available.
- Treat initial opening-price fills separately from adjusted return history.
- Cache fetched data and make refresh idempotent.
- Use retries with exponential backoff, rate-limit awareness, and clear stale-data indicators.
- Every displayed metric must include an `as of` timestamp.
- Never silently replace missing data with zero. Surface missing symbols, stale prices, and partial coverage.

## Fair performance methodology

- Store activity in an append-only transaction ledger supporting BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, FEE, SPLIT, and SYMBOL_CHANGE.
- Reconstruct daily positions and cash from transactions.
- Show both time-weighted return and money-weighted return/XIRR when mathematically available.
- For SPY and QQQ benchmarks, simulate the same external account cash flows on the same dates.
- Initial benchmark purchases occur at the same account inception opening price.
- Reinvest benchmark distributions consistently with the chosen adjusted-price methodology.
- Do not compare a cash-flow-affected portfolio against a simple buy-and-hold series without cash-flow matching.
- Show nominal dollar value and normalized growth of $100.

## Required navigation

- Date-range controls: since inception, YTD, 1M, 3M, 6M, 1Y, and custom.
- Manual refresh control with loading, success, partial-failure, and error states.
- Responsive desktop, tablet, and mobile layouts.

## Overview dashboard

Display:

- Current market value
- Invested capital
- Cash
- Today’s dollar and percentage change
- Total dollar and percentage return
- Time-weighted return
- Money-weighted return/XIRR
- SPY and QQQ returns over the identical period
- Excess return versus each benchmark
- Portfolio beta
- Annualized volatility
- Sharpe ratio
- Sortino ratio
- Maximum drawdown
- Number of active holdings
- Largest position
- Top-5, top-10, and top-20 concentration
- Effective number of holdings
- Last successful refresh and market-data coverage

## Performance views

- Interactive cumulative portfolio-value chart.
- Normalized growth-of-$100 chart for portfolio, SPY, and QQQ.
- Optional absolute-dollar benchmark comparison based on matched cash flows.
- Daily and cumulative return chart.
- Drawdown chart.
- Rolling 30-, 90-, and 252-trading-day beta versus SPY.
- Rolling volatility and rolling correlation versus SPY and QQQ.
- Period-return table: daily, weekly, monthly, quarterly, YTD, since inception.
- Calendar heatmap of daily portfolio returns.
- Monthly return heatmap with years as rows and months as columns.
- Tooltips must show date, account value, return, benchmark values, and excess return.

## Holdings and allocation

- Searchable, sortable holdings table with ticker, sector, original composite score, shares, cost basis, current price, market value, weight, unrealized gain/loss, daily change, total return, beta, and beta contribution.
- Sector-allocation donut or bar chart.
- Holdings treemap sized by current market value and colored by daily return.
- Top-holdings bar chart.
- Original target weight versus current drift.
- Concentration curve by holding rank.
- Sector and holding contribution to daily and cumulative return.
- Clearly separate original model metadata from current market-derived values.

## Heatmaps

- SPY-style holdings heatmap:
  - tile size equals current portfolio weight;
  - tile color equals selected period return;
  - grouping by sector;
  - selectable daily, weekly, monthly, and since-inception periods.
- Sector performance heatmap.
- Daily portfolio calendar heatmap.
- Provide a readable legend, zero midpoint, accessible colors, and hover details.

## Risk analytics

- Calculate portfolio beta from daily return covariance versus SPY, not by merely averaging third-party ticker betas.
- Require a configurable minimum observation count and show `insufficient history` when unavailable.
- Also show weighted security beta contribution when security-level betas have sufficient coverage.
- Historical volatility, downside deviation, Sharpe, Sortino, max drawdown, Value at Risk, Conditional VaR, and benchmark correlations.
- Sector concentration, top-position concentration, and effective number of holdings.
- Contribution-to-risk chart by holding and sector.
- Display methodology explanations in tooltips or an Analytics Glossary.

## Combined view

- Combine account values without losing account identity.
- Aggregate transactions and positions correctly.
- Show account contribution to total value and return.
- The combined benchmark must cash-flow-match both accounts’ separate inception dates and deposits.
- Allow every table and chart to filter by account.

## Updates and maintenance

- Automatic EOD update on trading days after data is available, using `America/New_York`.
- Manual update at any time.
- Persist last successful date per symbol.
- Incrementally fetch only missing dates.
- Provide an admin/data-quality page listing missing prices, stale symbols, duplicate transactions, negative holdings, and reconciliation differences.
- Support CSV import/export for transactions.
- Future buys and sells should require only a new transaction, not code changes.

## Visual design

- Professional dark-first financial dashboard with an equally polished light mode.
- Clean spacing, restrained color palette, high information density without clutter.
- Green/red reserved for positive/negative returns.
- Avoid decorative gradients that reduce readability.
- Use Plotly or another accessible interactive chart library.
- Include skeleton loaders, empty states, error states, and helpful tooltips.
- Charts must resize without clipping on mobile.
- Tables must support sticky headers and horizontal scrolling on small screens.

## Suggested architecture

- Frontend: React + TypeScript + Vite, Tailwind CSS, Plotly.
- Backend: FastAPI + Pydantic + SQLAlchemy.
- Database: SQLite for local/single-user use, with a clean path to PostgreSQL.
- Data processing: pandas and NumPy.
- Scheduling: APScheduler in the backend for a simple deployment, with the refresh service independently callable.
- Testing: pytest for finance calculations and API behavior; Vitest/React Testing Library for UI; Playwright for critical end-to-end flows.
- Containerization: Docker and Docker Compose.

## Required API surface

- `GET /api/accounts`
- `GET /api/accounts/{id}/summary`
- `GET /api/accounts/{id}/performance`
- `GET /api/accounts/{id}/holdings`
- `GET /api/accounts/{id}/allocation`
- `GET /api/accounts/{id}/risk`
- `GET /api/accounts/{id}/heatmap`
- `GET /api/accounts/{id}/transactions`
- `POST /api/accounts/{id}/transactions/import`
- `POST /api/refresh`
- `GET /api/data-quality`
- Equivalent support for `combined`.

## Financial-calculation acceptance tests

- A one-stock portfolio’s value exactly equals shares × price plus cash.
- BUY and SELL transactions alter shares and cash on the correct dates.
- Dividends and fees affect cash and returns correctly.
- A split changes shares without creating a false economic return.
- Same-day external cash flows do not create false time-weighted performance.
- SPY and QQQ receive identical external cash flows as the selected account.
- Combined account value equals the sum of its account values for every date.
- Portfolio beta matches a direct covariance/variance calculation on aligned returns.
- Missing price dates use an explicitly documented market-calendar policy and never fabricate a return.
- FDXF contributes exactly zero to all active-portfolio metrics.
- The five-stock initial transactions total $500 within a small floating-point tolerance.

## Delivery requirements

- Fully working application, not mock data after bootstrap.
- README with setup, FMP key configuration, database initialization, refresh, tests, and deployment.
- Database migrations.
- Seed/import command for both supplied portfolios.
- `.env.example`, never a real secret.
- Unit, integration, and end-to-end tests.
- Docker Compose development environment.
- Screenshots of desktop and mobile dashboards.
- A concise methodology page describing returns, beta, benchmarks, corporate actions, and data caveats.
