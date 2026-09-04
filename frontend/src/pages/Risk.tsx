import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAppState } from "../state/AppState";
import Chart, { SERIES } from "../components/Chart";
import { ErrorState, InsufficientHistory, SectionTitle, Skeleton, StatTile } from "../components/Primitives";
import { fmtNum, fmtPct } from "../lib/format";

/** Blue↔orange diverging scale for correlation (−1…+1): green/red are reserved for returns elsewhere. */
function correlationScale(): Array<[number, string]> {
  return [
    [0, SERIES.spy()],
    [0.5, SERIES.neutral()],
    [1, SERIES.portfolio()],
  ];
}

export default function Risk() {
  const { accountId } = useAppState();
  const q = useQuery({ queryKey: ["risk", accountId], queryFn: () => api.risk(accountId) });

  if (q.isLoading) return <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-72" /></div>;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;
  const r = q.data!;

  const ih = (needed: number) => <InsufficientHistory label="metric" needed={needed} have={r.observations} />;

  return (
    <div className="space-y-4">
      <div className="text-xs text-[var(--text-muted)]">
        {r.observations} daily observations since inception · minimums: beta {r.min_obs.beta}, volatility {r.min_obs.volatility}, VaR {r.min_obs.var} · risk-free rate {fmtPct(r.risk_free_rate, 1)} annual
        <br />
        Security beta, factor exposure, correlation matrix &amp; PCA below use each stock's own trailing {r.trailing_window.observations} of {r.trailing_window.target_trading_days} target trading days (~1 year) — independent of how long you've actually held the position.
      </div>

      <SectionTitle hint="Portfolio beta is cov(portfolio, benchmark) / var(benchmark) on aligned daily TWR returns — never a weighted average of vendor betas. This uses the portfolio's own trailing ~1-year (up to 252 trading day) daily returns vs. SPY/QQQ's returns over the same window, not the full since-inception history. For the full since-inception comparison against SPY and QQQ (alpha, Sharpe, Sortino, Calmar, drawdown), see the Performance page.">
        Market sensitivity (trailing 1 year)
      </SectionTitle>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Beta vs SPY" value={r.beta_spy ?? ih(r.min_obs.beta)} title="Direct covariance/variance estimate on aligned daily returns, trailing ~1 year." />
        <StatTile label="Beta vs QQQ" value={r.beta_qqq ?? ih(r.min_obs.beta)} />
        <StatTile label="Correlation SPY" value={r.correlation_spy !== null ? fmtNum(r.correlation_spy) : ih(r.min_obs.beta)} />
        <StatTile label="Correlation QQQ" value={r.correlation_qqq !== null ? fmtNum(r.correlation_qqq) : ih(r.min_obs.beta)} />
      </div>

      <SectionTitle hint="Historical (empirical) quantiles of daily TWR returns. CVaR is the mean of returns at or below the VaR quantile.">
        Value at Risk (1-day, historical)
      </SectionTitle>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="VaR 95%" signed={r.var_95} value={r.var_95 !== null ? fmtPct(r.var_95) : ih(r.min_obs.var)} />
        <StatTile label="CVaR 95%" signed={r.cvar_95} value={r.cvar_95 !== null ? fmtPct(r.cvar_95) : ih(r.min_obs.var)} />
        <StatTile label="VaR 99%" signed={r.var_99} value={r.var_99 !== null ? fmtPct(r.var_99) : ih(r.min_obs.var)} />
        <StatTile label="CVaR 99%" signed={r.cvar_99} value={r.cvar_99 !== null ? fmtPct(r.cvar_99) : ih(r.min_obs.var)} />
      </div>

      <SectionTitle hint="Current estimated beta: each currently-held security's own beta vs SPY × its current weight. Each security's beta is estimated from its own trailing ~1-year daily price history — the same window regardless of when it was actually added to the portfolio, so a stock bought 5 days ago still gets a real estimate instead of 'insufficient history'. This reflects today's holdings and weights only, not the portfolio's own (shorter) historical return series — it will jump whenever positions change. Only holdings with enough trailing history appear; the weighted sum is labelled as an approximation.">
        Security beta contributions (current holdings) {r.weighted_security_beta !== null && <span className="ml-1 font-normal normal-case text-[var(--text-muted)]">weighted sum ≈ {fmtNum(r.weighted_security_beta)}</span>}
      </SectionTitle>
      {r.beta_contributions.length > 0 ? (
        <div className="card p-3">
          <Chart
            height={Math.max(240, Math.min(30, r.beta_contributions.length) * 20)}
            data={[
              {
                y: r.beta_contributions.slice(0, 30).map((b) => b.ticker).reverse(),
                x: r.beta_contributions.slice(0, 30).map((b) => b.contribution).reverse(),
                type: "bar",
                orientation: "h",
                marker: { color: SERIES.portfolio() },
                customdata: r.beta_contributions.slice(0, 30).map((b) => [b.beta, b.weight]).reverse() as never,
                hovertemplate: "%{y}: β %{customdata[0]:.2f} × w %{customdata[1]:.2%} = %{x:.4f}<extra></extra>",
              },
            ]}
            layout={{ hovermode: "closest", bargap: 0.3 }}
          />
        </div>
      ) : (
        <div className="card p-6 text-sm text-[var(--text-muted)]">Security betas need ≥ {r.min_obs.beta} daily observations — insufficient history so far.</div>
      )}

      <SectionTitle hint="Marginal contribution to annualized portfolio volatility: wᵢ × cov(rᵢ, r_p) / σ_p. Contributions sum to total volatility.">
        Contribution to risk
      </SectionTitle>
      {r.risk_contributions.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="card p-3">
            <div className="mb-1 text-xs text-[var(--text-muted)]">By holding (top 30)</div>
            <Chart
              height={Math.max(240, Math.min(30, r.risk_contributions.length) * 18)}
              data={[
                {
                  y: r.risk_contributions.slice(0, 30).map((c) => c.ticker).reverse(),
                  x: r.risk_contributions.slice(0, 30).map((c) => c.contribution).reverse(),
                  type: "bar",
                  orientation: "h",
                  marker: { color: SERIES.portfolio() },
                  hovertemplate: "%{y}: %{x:.2%} of ann. volatility<extra></extra>",
                },
              ]}
              layout={{ xaxis: { tickformat: ".1%" }, hovermode: "closest", bargap: 0.3 }}
            />
          </div>
          <div className="card p-3">
            <div className="mb-1 text-xs text-[var(--text-muted)]">By sector</div>
            <Chart
              height={Math.max(240, r.risk_contributions_by_sector.length * 28)}
              data={[
                {
                  y: r.risk_contributions_by_sector.map((c) => c.sector).reverse(),
                  x: r.risk_contributions_by_sector.map((c) => c.contribution).reverse(),
                  type: "bar",
                  orientation: "h",
                  marker: { color: SERIES.qqq() },
                  hovertemplate: "%{y}: %{x:.2%}<extra></extra>",
                },
              ]}
              layout={{ xaxis: { tickformat: ".1%" }, hovermode: "closest", bargap: 0.3 }}
            />
          </div>
        </div>
      ) : (
        <div className="card p-6 text-sm text-[var(--text-muted)]">Risk contributions need more overlapping daily history.</div>
      )}

      <SectionTitle hint="Weighted average of each currently-held security's own beta/correlation to single-factor style ETFs (MTUM momentum, VLUE value, QUAL quality, USMV low-vol, SIZE small-cap), each estimated from that stock's trailing ~1-year daily price history and weighted by its current portfolio weight — the same 'current holdings, trailing-year data' approach as security beta above, and for the same reason: the portfolio's own live track record is too short to regress against a factor directly. A large beta to one factor alongside a high correlation means the book is effectively making one concentrated style bet, not just holding many names — that's factor crowding, even when sector and single-name diversification look fine.">
        Factor exposure
      </SectionTitle>
      {r.factor_exposure.some((f) => f.beta !== null) ? (
        <div className="card p-3">
          <Chart
            height={260}
            data={[
              {
                y: r.factor_exposure.map((f) => f.label).reverse(),
                x: r.factor_exposure.map((f) => f.beta ?? 0).reverse(),
                type: "bar",
                orientation: "h",
                marker: { color: SERIES.portfolio() },
                customdata: r.factor_exposure.map((f) => [f.correlation]).reverse() as never,
                hovertemplate: "%{y}: β %{x:.2f} · corr %{customdata[0]:.2f}<extra></extra>",
              },
            ]}
            layout={{ hovermode: "closest", bargap: 0.4 }}
          />
        </div>
      ) : (
        <div className="card p-6 text-sm text-[var(--text-muted)]">Factor exposure needs ≥ {r.min_obs.beta} daily observations — {ih(r.min_obs.beta)}.</div>
      )}

      <SectionTitle hint="PCA on the correlation matrix of currently-held tickers' trailing ~1-year daily-return history (top 30 by weight; common history across all 30, so one thinly-traded or newly-listed name can shrink the observation count for the whole matrix). Effective number of bets = exp(entropy of the normalized eigenvalues): 1 means every holding moves as a single block, N means N fully independent return streams. This is a property of how correlated the holdings' last year of trading has been — independent of position sizing (see Allocation's weight-based 'effective holdings' count for that view) and independent of how long you've actually owned each name.">
        Diversification (PCA)
      </SectionTitle>
      {r.diversification ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile
              label="Effective number of bets"
              value={fmtNum(r.diversification.effective_bets)}
              sub={`of ${r.diversification.num_holdings} holdings analyzed`}
            />
            <StatTile
              label="PC1 variance explained"
              value={fmtPct(r.diversification.variance_explained[0]?.variance_pct ?? 0)}
              title="Share of total variance explained by the single dominant common factor across these holdings."
            />
            <StatTile label="Holdings analyzed" value={r.diversification.num_holdings} title="Top 30 current holdings by weight with sufficient common history." />
            <StatTile label="Observations" value={r.diversification.observations} />
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="card p-3">
              <div className="mb-1 text-xs text-[var(--text-muted)]">Variance explained by component (scree)</div>
              <Chart
                height={220}
                data={[
                  {
                    x: r.diversification.variance_explained.map((v) => `PC${v.component}`),
                    y: r.diversification.variance_explained.map((v) => v.variance_pct),
                    type: "bar",
                    marker: { color: SERIES.portfolio() },
                    hovertemplate: "%{x}: %{y:.1%}<extra></extra>",
                  },
                ]}
                layout={{ yaxis: { tickformat: ".0%" }, hovermode: "closest", bargap: 0.3 }}
              />
            </div>
            <div className="card p-3">
              <div className="mb-1 text-xs text-[var(--text-muted)]">Top PC1 loadings (dominant common factor)</div>
              <Chart
                height={220}
                data={[
                  {
                    y: r.diversification.pc1_loadings.slice(0, 10).map((l) => l.ticker).reverse(),
                    x: r.diversification.pc1_loadings.slice(0, 10).map((l) => l.loading).reverse(),
                    type: "bar",
                    orientation: "h",
                    marker: { color: SERIES.qqq() },
                    hovertemplate: "%{y}: %{x:.2f}<extra></extra>",
                  },
                ]}
                layout={{ hovermode: "closest", bargap: 0.3 }}
              />
            </div>
          </div>
        </>
      ) : (
        <div className="card p-6 text-sm text-[var(--text-muted)]">Diversification analysis needs ≥ {r.min_obs.beta} daily observations of overlapping holding history — {ih(r.min_obs.beta)}.</div>
      )}

      <SectionTitle hint="Pairwise Pearson correlation of each ticker's own trailing ~1-year daily returns across currently-held tickers (top 30 by weight, common history across all 30 only) — not the account's own since-inception window, so newer positions still get a full year of real market history. Blocks of dark blue off the diagonal are holdings that move together — real diversification needs orange/neutral cells too, not just more tickers.">
        Correlation matrix
      </SectionTitle>
      {r.correlation_matrix ? (
        <div className="card p-3">
          <Chart
            height={Math.max(320, r.correlation_matrix.tickers.length * 22)}
            data={[
              {
                x: r.correlation_matrix.tickers,
                y: r.correlation_matrix.tickers,
                z: r.correlation_matrix.matrix,
                text: r.correlation_matrix.matrix.map((row) => row.map((v) => v.toFixed(2))),
                texttemplate: "%{text}",
                textfont: { size: 9 },
                type: "heatmap",
                colorscale: correlationScale(),
                zmin: -1,
                zmax: 1,
                colorbar: { tickformat: ".1f" },
                hovertemplate: "%{y} × %{x}: %{z:.2f}<extra></extra>",
              } as never,
            ]}
            layout={{ yaxis: { autorange: "reversed" } }}
          />
        </div>
      ) : (
        <div className="card p-6 text-sm text-[var(--text-muted)]">Correlation matrix needs ≥ {r.min_obs.beta} daily observations of overlapping holding history — {ih(r.min_obs.beta)}.</div>
      )}
    </div>
  );
}
