import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAppState } from "../state/AppState";
import Chart, { SERIES } from "../components/Chart";
import {
  EmptyState,
  ErrorState,
  InsufficientHistory,
  SectionTitle,
  Skeleton,
  SkeletonTiles,
  StatTile,
} from "../components/Primitives";
import {
  fmtMoney,
  fmtNum,
  fmtPct,
  fmtSignedMoney,
  fmtSignedPct,
} from "../lib/format";

export default function Overview() {
  const { accountId } = useAppState();
  const summary = useQuery({ queryKey: ["summary", accountId], queryFn: () => api.summary(accountId) });
  const perf = useQuery({ queryKey: ["performance", accountId], queryFn: () => api.performance(accountId) });
  const contributions = useQuery({
    queryKey: ["contributions"],
    queryFn: api.contributions,
    enabled: accountId === "combined",
  });

  if (summary.isLoading) return (<div className="space-y-4"><SkeletonTiles /><Skeleton className="h-80" /></div>);
  if (summary.isError) return <ErrorState message={String((summary.error as Error).message)} onRetry={() => summary.refetch()} />;
  const s = summary.data!;
  if (s.empty) return <EmptyState message="No transactions yet for this account. Run the bootstrap to hydrate the seed book." />;

  const r = s.risk;
  const c = s.concentration;
  const g100 = perf.data?.growth_of_100;

  return (
    <div className="space-y-4">
      {/* Headline tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <StatTile label="Current value" value={fmtMoney(s.current_value)} sub={`Invested ${fmtMoney(s.invested_capital)}`} />
        <StatTile label="Today" signed={s.today.pct} value={fmtSignedPct(s.today.pct)} sub={s.today.dollar !== null ? fmtSignedMoney(s.today.dollar) : "first session"} />
        <StatTile label="Total return" signed={s.total.pct} value={fmtSignedPct(s.total.pct)} sub={fmtSignedMoney(s.total.dollar)} />
        <StatTile label="CAGR" signed={r.cagr} value={r.cagr !== null ? fmtSignedPct(r.cagr) : "—"} title="Geometrically compounded annual growth rate over the actual elapsed period since inception." />
        {(["SPY", "QQQ"] as const).map((b) => (
          <StatTile
            key={b}
            label={`${b} total return`}
            signed={s.benchmarks[b]?.twr}
            value={fmtSignedPct(s.benchmarks[b]?.twr)}
            title={`${b}'s own total return over the identical period (same inception-to-date window as the portfolio).`}
          />
        ))}
        {(["SPY", "QQQ"] as const).map((b) => (
          <StatTile
            key={`x${b}`}
            label={`Excess vs ${b}`}
            signed={s.benchmarks[b]?.excess}
            value={fmtSignedPct(s.benchmarks[b]?.excess)}
            title="Portfolio TWR minus benchmark TWR over the identical period."
          />
        ))}
      </div>

      {/* Growth of $100 */}
      <SectionTitle hint="Each series starts at $100 at inception and compounds daily time-weighted returns; external cash flows do not distort the comparison.">
        Growth of $100 — portfolio vs SPY vs QQQ
      </SectionTitle>
      <div className="card p-3">
        {perf.isLoading ? (
          <Skeleton className="h-72" />
        ) : g100 && g100.portfolio.dates.length > 0 ? (
          <Chart
            height={320}
            data={[
              { x: g100.portfolio.dates, y: g100.portfolio.values, name: "Portfolio", type: "scatter", mode: "lines", line: { color: SERIES.portfolio(), width: 2 }, hovertemplate: "%{y:$.2f}" },
              { x: g100.SPY?.dates ?? [], y: g100.SPY?.values ?? [], name: "SPY", type: "scatter", mode: "lines", line: { color: SERIES.spy(), width: 2 }, hovertemplate: "%{y:$.2f}" },
              { x: g100.QQQ?.dates ?? [], y: g100.QQQ?.values ?? [], name: "QQQ", type: "scatter", mode: "lines", line: { color: SERIES.qqq(), width: 2 }, hovertemplate: "%{y:$.2f}" },
            ]}
            layout={{ yaxis: { tickprefix: "$" } }}
          />
        ) : (
          <EmptyState message="No performance history yet." />
        )}
      </div>

      {/* Risk + concentration tiles */}
      <SectionTitle hint="Beta and alpha are estimated from this portfolio's own daily returns against SPY since inception — never a weighted average of vendor betas. Metrics show 'insufficient history' until enough observations accrue.">
        Risk &amp; concentration
      </SectionTitle>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
        <StatTile label="Beta (since inception)" value={r.beta !== null ? fmtNum(r.beta) : <InsufficientHistory label="Beta" needed={r.beta_min_obs} have={r.observations} />} title={`Covariance of daily portfolio returns vs SPY over variance of SPY, over the full since-inception window (SPY over the same dates as the base). Requires ≥ ${r.beta_min_obs} observations; have ${r.observations}.`} />
        <StatTile label="CAGR" signed={r.cagr} value={r.cagr !== null ? fmtSignedPct(r.cagr) : <InsufficientHistory label="CAGR" have={r.observations} />} title="Geometrically compounded annual growth rate since inception." />
        <StatTile label="Alpha (vs SPY, ann.)" signed={r.alpha} value={r.alpha !== null ? fmtSignedPct(r.alpha) : <InsufficientHistory label="Alpha" needed={r.beta_min_obs} have={r.observations} />} title="Annualized CAPM (Jensen's) alpha vs SPY, since inception." />
        <StatTile label="Holdings" value={c.num_holdings} title="Number of currently held positions." />
        <StatTile label="Effective holdings" value={c.effective_holdings !== null ? fmtNum(c.effective_holdings) : "—"} title="Effective number = 1 / Σ(weight²) — lower means more concentrated." />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Largest position" value={c.largest_position ? `${c.largest_position.ticker} ${fmtPct(c.largest_position.weight)}` : "—"} />
        <StatTile label="Top 5" value={fmtPct(c.top5)} />
        <StatTile label="Top 10" value={fmtPct(c.top10)} />
        <StatTile label="Top 20" value={fmtPct(c.top20)} />
      </div>

      {/* Combined view: account contributions */}
      {accountId === "combined" && contributions.data && (
        <>
          <SectionTitle>Account contributions</SectionTitle>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {contributions.data.accounts.map((a) => (
              <StatTile
                key={a.account}
                label={a.account}
                value={fmtMoney(a.value)}
                signed={a.twr}
                sub={`invested ${fmtMoney(a.invested)} · gain ${fmtSignedMoney(a.gain)} · TWR ${fmtSignedPct(a.twr)}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
