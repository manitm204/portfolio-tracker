const SECTIONS: { title: string; body: string[] }[] = [
  {
    title: "Sleeves & portfolio",
    body: [
      "The portfolio is four sleeves of 4–6 stocks. Every sleeve starts with the same capital, split equally across its stocks and filled at the official open of its purchase date, in full-precision fractional shares. Official opens are fetched once, stored as immutable fills, and never recomputed from newer data.",
      "Each sleeve has its own ledger. The portfolio merges them, and a sleeve's capital joins the portfolio on the day it's funded, as an external cash flow. Time-weighted returns ignore that flow, and SPY and QQQ receive the same money on the same dates, so an unfunded sleeve neither dilutes returns as idle cash nor shows up as a gain.",
      "Proceeds from a sale stay in the sleeve as cash until it's reinvested.",
    ],
  },
  {
    title: "Ledger & positions",
    body: [
      "All activity lives in an append-only transaction ledger (BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, FEE, SPLIT, SYMBOL_CHANGE). Daily positions and cash are reconstructed from the ledger on the trading calendar; nothing is ever edited in place.",
      "Dividends detected from the market-data provider are credited as cash on the ex-date (shares held before the ex-date × dividend per share) until the payment date is known to have passed; splits multiply shares with zero economic return; symbol changes move the whole position.",
      "Cost basis uses the average-cost method.",
    ],
  },
  {
    title: "Prices & calendar",
    body: [
      "Raw OHLC and dividend-adjusted closes are stored side by side. Market values use raw closes × actual shares (splits arrive as ledger rows); per-ticker return series use adjusted closes so corporate actions never fabricate returns. The two are never mixed silently.",
      "The trading calendar is the set of dates on which SPY has a bar — weekends and market holidays are simply absent. A symbol missing a price on a calendar date is forward-filled from its last close (a 0% return for that symbol, never a fabricated one, and never zero) and flagged as a coverage gap in Data Quality.",
      "Bars fetched during the trading session are marked provisional (the 'intraday' badge) and re-fetched at the next refresh.",
    ],
  },
  {
    title: "Returns",
    body: [
      "Daily time-weighted return: r_t = MV_t / (MV_{t−1} + F_t) − 1, with external flows (deposits/withdrawals only) treated as start-of-day. Same-day flows therefore create no false performance. Period TWR is the geometric link of daily returns.",
      "XIRR is the annualized money-weighted return solving the NPV equation over actual external flow dates plus terminal value. Early in an account's life, annualization amplifies small moves — read it with that caveat.",
      "Growth-of-$100 charts compound each series' own TWR from the window start.",
    ],
  },
  {
    title: "Benchmarks",
    body: [
      "SPY and QQQ receive the identical external cash flows on the identical dates as the account — including the inception deposit at that day's opening price. Distributions are reinvested via adjusted prices. A cash-flow-affected portfolio is never compared against a simple buy-and-hold line.",
    ],
  },
  {
    title: "Position excess & attribution",
    body: [
      "A position's return includes dividends received. SPY, QQQ and its sector ETF are measured over the identical window using adjusted prices: from the adjusted open on the buy date, matching a fill at the open, to the adjusted close on the sale date, or the latest close if the position is still open. Excess is the position's return minus that benchmark's. A sale filled at the open is therefore compared with a benchmark held through that day's close.",
      "Each stock's return splits into market (SPY's return), sector (its Select Sector SPDR's return minus SPY's), and stock itself (its return minus the sector ETF's). The three sum to the total. A stock that rose only because its sector did shows a near-zero or negative stock component.",
      "Stock charts use adjusted prices with dividends reinvested, while the Return figure uses dividends actually received from the ledger, so they can differ slightly, and more so if the price provider omits a dividend. CAGR needs at least a week of holding, and it's very sensitive while the holding period is short.",
    ],
  },
  {
    title: "Risk",
    body: [
      "Portfolio beta = cov(portfolio daily returns, SPY daily returns) / var(SPY daily returns) on aligned dates — never a weighted average of vendor-supplied ticker betas. The separately-labelled 'security beta contribution' view (weight × each holding's own regression beta) is an approximation shown only when security betas have enough coverage.",
      "Volatility = sample stdev of daily returns × √252. Sharpe/Sortino use a configurable annual risk-free rate (default 4%). VaR/CVaR are historical quantiles of daily returns. Every statistic requires a configurable minimum number of observations and displays 'insufficient history' below it.",
      "Contribution to risk uses the marginal decomposition wᵢ·cov(rᵢ, r_p)/σ_p, which sums to total portfolio volatility.",
      "The Risk page's cross-sectional views (risk profile, security beta, factor exposure, contribution to risk, correlation matrix and PCA) use each current holding's own daily returns over up to 252 trading days, independent of how long the position has been held. 'Year before purchase', the default, ends the day before the most recent purchase of a current holding, so it shows what was knowable when the stocks were bought with no look-ahead. 'Latest year' ends today. The ingestion job keeps that history cached back past a year before the first sleeve, so this is always a read of cached prices.",
      "The risk profile replays today's holdings and weights across that window. It describes the stocks, so it's available from a sleeve's first day, but it isn't a track record: nobody held that exact mix throughout. Average pairwise correlation is the mean across all pairs of holdings. Diversification ratio is the weighted average of stock volatilities divided by the combined volatility.",
      "Factor exposure is the current-weight-weighted average of each holding's own trailing beta/correlation to five single-factor iShares ETFs (MTUM momentum, VLUE value, QUAL quality, USMV low volatility, SIZE small-cap) — the same 'weighted sum of individual security betas' approximation already used for the SPY beta-contribution view, applied to factors instead. The portfolio's own live return series is too short to regress against a factor directly, so this is intentionally not portfolio-TWR-based.",
      "The correlation matrix and PCA diversification view use the current top 30 holdings by weight over their common (no-gap) trailing daily-return history — one newly-added or thinly-traded name can shrink the overlapping window for the whole matrix. Effective number of bets = exp(Shannon entropy of the correlation matrix's normalized eigenvalues): 1 means every holding moves as a single block, N means N fully independent return streams — a measure of return redundancy, distinct from the weight-only 'effective holdings' count shown on Allocation.",
    ],
  },
  {
    title: "Data caveats",
    body: [
      "Market data comes from one provider at a time, chosen by MARKET_DATA_PROVIDER: FMP when an FMP_API_KEY is configured, otherwise keyless Yahoo Finance (with the S&P 500 list from Wikipedia). There is no silent fallback between them, and the active source is shown on Data Quality; any API key lives only on the backend. Missing data is surfaced, never zero-filled. Adjusted history is re-fetched over the account window on every refresh because adjustments are retroactive.",
      "With only days of history since inception, most performance statistics are legitimately 'insufficient history' — they will populate as observations accrue.",
      "The S&P 500 heatmap sizes tiles by State Street's daily SPY holdings file and refreshes with market data, keeping its last snapshot if a download fails. Its returns are price moves with dividends adjusted, stored per period rather than as full price histories, and the map shows its as-of date.",
    ],
  },
];

export default function Methodology() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-xl font-bold">Methodology</h1>
      {SECTIONS.map((s) => (
        <section key={s.title} className="card p-5">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">{s.title}</h2>
          {s.body.map((p, i) => (
            <p key={i} className="mb-2 text-sm leading-relaxed text-[var(--text-secondary)] last:mb-0">{p}</p>
          ))}
        </section>
      ))}
    </div>
  );
}
