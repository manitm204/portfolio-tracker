import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, RiskWindow } from "../api/client";
import { PORTFOLIO, useAccountId } from "../state/AppState";
import Chart, { SERIES } from "../components/Chart";
import { ErrorState, InsufficientHistory, SectionTitle, Skeleton, StatTile } from "../components/Primitives";
import { fmtDate, fmtNum, fmtPct, fmtSignedPct } from "../lib/format";

/** Blue↔orange diverging scale for correlation (−1…+1): green/red are reserved for returns elsewhere. */
function correlationScale(): Array<[number, string]> {
  return [
    [0, SERIES.spy()],
    [0.5, SERIES.neutral()],
    [1, SERIES.portfolio()],
  ];
}

const WINDOWS: { key: RiskWindow; label: string }[] = [
  { key: "purchase", label: "Year before purchase" },
  { key: "trailing", label: "Latest year" },
];

export default function Risk() {
  const accountId = useAccountId();
  const [window, setWindow] = useState<RiskWindow>("purchase");
  const q = useQuery({
    queryKey: ["risk", accountId, window],
    queryFn: () => api.risk(accountId, window),
    placeholderData: (prev) => prev,
  });

  if (q.isLoading) return <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-72" /></div>;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;
  const r = q.data!;

  const ih = (needed: number) => <InsufficientHistory label="metric" needed={needed} have={r.observations} />;
  const h = r.historical;
  const w = r.trailing_window;
  const subject = accountId === PORTFOLIO ? "the portfolio" : "this sleeve";
  const sectorRows = [...r.sector_vs_index].reverse();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded-lg border border-[var(--border)]" role="group" aria-label="Risk window">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              onClick={() => setWindow(w.key)}
              className={clsx(
                "px-3 py-1.5 text-xs font-medium sm:text-sm",
                window === w.key ? "bg-[var(--series-portfolio)] text-white" : "text-[var(--text-secondary)] hover:bg-[var(--grid)]",
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-[var(--text-muted)]">
          {fmtDate(w.start)} to {fmtDate(w.end)} · {h?.observations ?? 0} sessions
          {w.anchor_date && ` · ending the day before the ${fmtDate(w.anchor_date)} purchase`}
        </span>
      </div>

      <SectionTitle hint={`What ${subject} would have looked like over this window: today's holdings and weights replayed across their actual daily returns. It describes the stocks themselves, so it works from day one and doesn't need any time in the sleeve. It isn't a track record: nobody held this exact mix over the whole window.`}>
        Risk profile
      </SectionTitle>
      {h ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Beta vs SPY" value={h.beta_spy !== null ? fmtNum(h.beta_spy) : "—"} sub={`vs QQQ ${h.beta_qqq !== null ? fmtNum(h.beta_qqq) : "—"}`} />
            <StatTile label="Volatility (ann.)" value={fmtPct(h.volatility, 1)} sub={`SPY ${fmtPct(h.spy_volatility, 1)}`} />
            <StatTile label="Max drawdown" signed={h.max_drawdown} value={fmtPct(h.max_drawdown, 1)} sub={`SPY ${fmtPct(h.spy_max_drawdown, 1)}`} />
            <StatTile label="Window return" signed={h.total_return} value={fmtSignedPct(h.total_return, 1)} sub={`SPY ${fmtSignedPct(h.spy_total_return, 1)}`} />
            <StatTile label="Avg pairwise correlation" value={h.average_correlation !== null ? fmtNum(h.average_correlation) : "—"} title="Mean correlation across every pair of holdings. Lower means they diversify each other." />
            <StatTile label="Correlation to SPY" value={h.correlation_spy !== null ? fmtNum(h.correlation_spy) : "—"} sub={`to QQQ ${h.correlation_qqq !== null ? fmtNum(h.correlation_qqq) : "—"}`} />
            <StatTile label="Diversification ratio" value={h.diversification_ratio !== null ? fmtNum(h.diversification_ratio) : "—"} title="Weighted average of each stock's volatility divided by the combined volatility. 1 means no diversification benefit; higher is better." />
            <StatTile label="Sharpe" value={h.sharpe !== null ? fmtNum(h.sharpe) : "—"} sub={`Sortino ${h.sortino !== null ? fmtNum(h.sortino) : "—"}`} />
          </div>
          <SectionTitle hint="Historical 1-day quantiles of the replayed daily returns. CVaR is the average of the days at or beyond the VaR level.">
            Value at Risk (1-day)
          </SectionTitle>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="VaR 95%" signed={h.var_95} value={fmtPct(h.var_95)} />
            <StatTile label="CVaR 95%" signed={h.cvar_95} value={fmtPct(h.cvar_95)} />
            <StatTile label="VaR 99%" signed={h.var_99} value={fmtPct(h.var_99)} />
            <StatTile label="CVaR 99%" signed={h.cvar_99} value={fmtPct(h.cvar_99)} />
          </div>
        </>
      ) : (
        <div className="card p-6 text-sm text-[var(--text-muted)]">Not enough overlapping price history in this window.</div>
      )}

      {r.sector_vs_index.length > 0 && (
        <>
          <SectionTitle hint="Current weight in each sector next to that sector's weight in SPY, so over- and underweights stand out.">
            Sector exposure vs S&amp;P 500
          </SectionTitle>
          <div className="card p-3">
            <Chart
              height={Math.max(280, r.sector_vs_index.length * 34)}
              data={[
                {
                  y: sectorRows.map((s) => s.sector),
                  x: sectorRows.map((s) => s.index_weight ?? 0),
                  name: "S&P 500",
                  type: "bar",
                  orientation: "h",
                  marker: { color: SERIES.spy() },
                  hovertemplate: "S&P 500: %{x:.1%}<extra></extra>",
                },
                {
                  y: sectorRows.map((s) => s.sector),
                  x: sectorRows.map((s) => s.weight),
                  name: accountId === PORTFOLIO ? "Portfolio" : "Sleeve",
                  type: "bar",
                  orientation: "h",
                  marker: { color: SERIES.portfolio() },
                  hovertemplate: "%{fullData.name}: %{x:.1%}<extra></extra>",
                },
              ]}
              layout={{ barmode: "group", xaxis: { tickformat: ".0%" }, hovermode: "closest", bargap: 0.25, bargroupgap: 0.05 }}
            />
          </div>
        </>
      )}

      <SectionTitle hint="Current estimated beta: each currently-held security's own beta vs SPY × its current weight. Each security's beta comes from its own daily returns over the selected window, so a stock bought 5 days ago still gets a real estimate. This reflects today's holdings and weights only, not the portfolio's own (shorter) historical return series — it will jump whenever positions change. Only holdings with enough trailing history appear; the weighted sum is labelled as an approximation.">
        Beta contributions {r.weighted_security_beta !== null && <span className="ml-1 font-normal normal-case text-[var(--text-muted)]">weighted sum ≈ {fmtNum(r.weighted_security_beta)}</span>}
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

      <SectionTitle hint="Marginal contribution to annualized volatility over the selected window: wᵢ × cov(rᵢ, r_p) / σ_p. Contributions sum to total volatility.">
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

      <SectionTitle hint="Weighted average of each currently-held security's own beta/correlation to single-factor style ETFs (MTUM momentum, VLUE value, QUAL quality, USMV low-vol, SIZE small-cap), each estimated from that stock's daily returns over the selected window and weighted by its current portfolio weight — the same 'current holdings, trailing-year data' approach as security beta above, and for the same reason: the portfolio's own live track record is too short to regress against a factor directly. A large beta to one factor alongside a high correlation means the book is effectively making one concentrated style bet, not just holding many names — that's factor crowding, even when sector and single-name diversification look fine.">
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

      <SectionTitle hint="PCA on the correlation matrix of currently-held tickers' daily returns over the selected window (top 30 by weight; common history across all 30, so one thinly-traded or newly-listed name can shrink the observation count for the whole matrix). Effective number of bets = exp(entropy of the normalized eigenvalues): 1 means every holding moves as a single block, N means N fully independent return streams. This is a property of how correlated the holdings' last year of trading has been — independent of position sizing (see Allocation's weight-based 'effective holdings' count for that view) and independent of how long you've actually owned each name.">
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
            <StatTile label="Top holding on PC1" value={r.diversification.pc1_loadings[0]?.ticker ?? "—"} title="The stock most aligned with the dominant common factor." />
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

      <SectionTitle hint="Pairwise Pearson correlation of each ticker's daily returns over the selected window across currently-held tickers (top 30 by weight, common history across all 30 only) — not the account's own since-inception window, so newer positions still get a full year of real market history. Blocks of dark blue off the diagonal are holdings that move together — real diversification needs orange/neutral cells too, not just more tickers.">
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
