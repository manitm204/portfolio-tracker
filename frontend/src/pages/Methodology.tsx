const SECTIONS: { title: string; body: string[] }[] = [
  {
    title: "Accounts & bootstrap",
    body: [
      "PORTFOLIO_5 ($500, exactly $100 into each of GOOGL, IBKR, CIEN, SPGI, ADSK at the July 29 2026 open, full-precision fractional shares).",
      "The official opening prices were fetched from FMP exactly once at bootstrap, stored as immutable fills, and are never recomputed from newer data.",
    ],
  },
  {
    title: "Ledger & positions",
    body: [
      "All activity lives in an append-only transaction ledger (BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, FEE, SPLIT, SYMBOL_CHANGE). Daily positions and cash are reconstructed from the ledger on the trading calendar; nothing is ever edited in place.",
      "Dividends detected from FMP are credited as cash on the ex-date (shares held before the ex-date × dividend per share) until the payment date is known to have passed; splits multiply shares with zero economic return; symbol changes move the whole position.",
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
    title: "Risk",
    body: [
      "Portfolio beta = cov(portfolio daily returns, SPY daily returns) / var(SPY daily returns) on aligned dates — never a weighted average of vendor-supplied ticker betas. The separately-labelled 'security beta contribution' view (weight × each holding's own regression beta) is an approximation shown only when security betas have enough coverage.",
      "Volatility = sample stdev of daily returns × √252. Sharpe/Sortino use a configurable annual risk-free rate (default 4%). VaR/CVaR are historical quantiles of daily returns. Every statistic requires a configurable minimum number of observations and displays 'insufficient history' below it.",
      "Contribution to risk uses the marginal decomposition wᵢ·cov(rᵢ, r_p)/σ_p, which sums to total portfolio volatility.",
      "Security beta, factor exposure, the correlation matrix, and PCA diversification are all 'current holdings, trailing data' views: each currently-held ticker's own trailing ~1-year (up to 252 trading day) daily-return history, independent of the account's inception date or how long that specific position has actually been held — a stock bought 5 days ago still gets a real estimate from its last year of real trading, not 'insufficient history'. The ingestion job keeps that trailing window cached for every tracked symbol regardless of account age, so this is always a read against already-cached prices, never a live fetch inside a page load.",
      "Factor exposure is the current-weight-weighted average of each holding's own trailing beta/correlation to five single-factor iShares ETFs (MTUM momentum, VLUE value, QUAL quality, USMV low volatility, SIZE small-cap) — the same 'weighted sum of individual security betas' approximation already used for the SPY beta-contribution view, applied to factors instead. The portfolio's own live return series is too short to regress against a factor directly, so this is intentionally not portfolio-TWR-based.",
      "The correlation matrix and PCA diversification view use the current top 30 holdings by weight over their common (no-gap) trailing daily-return history — one newly-added or thinly-traded name can shrink the overlapping window for the whole matrix. Effective number of bets = exp(Shannon entropy of the correlation matrix's normalized eigenvalues): 1 means every holding moves as a single block, N means N fully independent return streams — a measure of return redundancy, distinct from the weight-only 'effective holdings' count shown on Allocation.",
    ],
  },
  {
    title: "Data caveats",
    body: [
      "FMP is the sole market-data source; the API key lives only on the backend. Missing data is surfaced, never zero-filled. Adjusted history is re-fetched over the account window on every refresh because adjustments are retroactive.",
      "With only days of history since inception, most risk statistics are legitimately 'insufficient history' — they will populate as observations accrue.",
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
