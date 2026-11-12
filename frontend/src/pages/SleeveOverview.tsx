import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../api/client";
import { useAccountId } from "../state/AppState";
import { EquityAndGain, StatsTable } from "../components/Comparison";
import { ErrorState, InsufficientHistory, SectionTitle, Skeleton, SkeletonTiles, StatTile } from "../components/Primitives";
import { fmtDate, fmtMoney, fmtPct, fmtSignedMoney, fmtSignedPct, signClass } from "../lib/format";

export default function SleeveOverview() {
  const id = useAccountId();
  const summary = useQuery({ queryKey: ["summary", id], queryFn: () => api.summary(id) });
  const perf = useQuery({ queryKey: ["performance", id], queryFn: () => api.performance(id) });
  const risk = useQuery({ queryKey: ["risk", id, "purchase"], queryFn: () => api.risk(id) });
  const holdings = useQuery({ queryKey: ["holdings", id], queryFn: () => api.holdings(id) });
  const stocks = useQuery({ queryKey: ["stocks", id], queryFn: () => api.stocks(id) });

  if (summary.isLoading) return <SkeletonTiles />;
  if (summary.isError) return <ErrorState message={String((summary.error as Error).message)} onRetry={() => summary.refetch()} />;
  const s = summary.data!;
  const byTicker = new Map((holdings.data?.holdings ?? []).map((h) => [h.ticker, h]));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Value" value={fmtMoney(s.current_value)} sub={`Invested ${fmtMoney(s.invested_capital)}`} />
        <StatTile label="Today" signed={s.today.pct} value={fmtSignedPct(s.today.pct)} sub={s.today.dollar !== null ? fmtSignedMoney(s.today.dollar) : "first session"} />
        <StatTile label="Return" signed={s.twr} value={fmtSignedPct(s.twr)} sub={fmtSignedMoney(s.total.dollar)} />
        <StatTile
          label="CAGR"
          signed={s.risk.cagr}
          value={s.risk.cagr !== null ? fmtSignedPct(s.risk.cagr) : <InsufficientHistory label="CAGR" needed={5} have={s.risk.observations} />}
          sub={`${s.risk.observations} sessions, annualized`}
          title="Compound annual growth rate over the elapsed period. Very sensitive on short histories."
        />
        <StatTile label="Excess vs SPY" signed={s.benchmarks.SPY?.excess} value={fmtSignedPct(s.benchmarks.SPY?.excess)} sub={`SPY ${fmtSignedPct(s.benchmarks.SPY?.twr)}`} />
        <StatTile label="Excess vs QQQ" signed={s.benchmarks.QQQ?.excess} value={fmtSignedPct(s.benchmarks.QQQ?.excess)} sub={`QQQ ${fmtSignedPct(s.benchmarks.QQQ?.twr)}`} />
      </div>

      <SectionTitle hint="Sleeve and benchmarks all start from the opening price on the sleeve's first day.">Sleeve vs SPY and QQQ</SectionTitle>
      <EquityAndGain perf={perf.data} label="Sleeve" />

      <SectionTitle hint="Return includes dividends. Every comparison column measures the benchmark from the open on this stock's purchase date to the latest close.">
        Current holdings
      </SectionTitle>
      {stocks.isLoading ? (
        <Skeleton className="h-56" />
      ) : (
        <div className="card table-scroll">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-right text-xs text-[var(--text-muted)]">
                <th className="p-2 text-left">Ticker</th>
                <th className="p-2 text-left">Sector</th>
                <th className="p-2">Bought</th>
                <th className="p-2">Weight</th>
                <th className="p-2">Value</th>
                <th className="p-2">Today</th>
                <th className="p-2">Return</th>
                <th className="p-2">CAGR</th>
                <th className="p-2">vs SPY</th>
                <th className="p-2">vs QQQ</th>
                <th className="p-2">vs sector ETF</th>
              </tr>
            </thead>
            <tbody>
              {(stocks.data?.stocks ?? []).map((r) => {
                const h = byTicker.get(r.ticker);
                return (
                  <tr key={r.ticker} className="border-t border-[var(--border)] text-right">
                    <td className="p-2 text-left font-semibold">
                      <Link to="stocks" className="hover:underline">{r.ticker}</Link>
                    </td>
                    <td className="whitespace-nowrap p-2 text-left text-[var(--text-secondary)]">{r.sector}</td>
                    <td className="whitespace-nowrap p-2 text-[var(--text-secondary)]">{fmtDate(r.open_date)}</td>
                    <td className="p-2 tabular">{fmtPct(h?.weight, 1)}</td>
                    <td className="p-2 tabular">{fmtMoney(r.market_value)}</td>
                    <td className={clsx("p-2 tabular", signClass(h?.day_return))}>{fmtSignedPct(h?.day_return)}</td>
                    <td className={clsx("p-2 tabular font-medium", signClass(r.total_return))}>{fmtSignedPct(r.total_return)}</td>
                    <td className={clsx("p-2 tabular", signClass(r.cagr))} title={r.cagr === null ? "Held under a week: too short to annualize" : undefined}>{fmtSignedPct(r.cagr)}</td>
                    <td className={clsx("p-2 tabular", signClass(r.excess_spy))}>{fmtSignedPct(r.excess_spy)}</td>
                    <td className={clsx("p-2 tabular", signClass(r.excess_qqq))}>{fmtSignedPct(r.excess_qqq)}</td>
                    <td className={clsx("whitespace-nowrap p-2 tabular", signClass(r.excess_sector))}>
                      {fmtSignedPct(r.excess_sector)}
                      {r.sector_etf && <span className="ml-1 text-[10px] text-[var(--text-muted)]">{r.sector_etf}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <StatsTable comparison={risk.data?.comparison} label="Sleeve" />
    </div>
  );
}
