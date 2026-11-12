import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, StockDetail } from "../api/client";
import { useAccountId } from "../state/AppState";
import Chart, { SERIES } from "../components/Chart";
import { EmptyState, ErrorState, Skeleton } from "../components/Primitives";
import { fmtDate, fmtMoney, fmtNum, fmtPct, fmtSignedPct, signClass } from "../lib/format";

/** Plain-language read of the market / sector / stock split. */
function verdict(s: StockDetail): string {
  const { sector, selection } = s.attribution;
  if (selection === null || sector === null || !s.sector_etf) return "No sector ETF comparison available.";
  const pick =
    selection >= 0
      ? `Beat ${s.sector_etf} by ${fmtPct(selection, 1)}`
      : `Lagged ${s.sector_etf} by ${fmtPct(-selection, 1)}`;
  const tide =
    sector >= 0
      ? `the sector itself ran ${fmtPct(sector, 1)} ahead of SPY`
      : `the sector itself trailed SPY by ${fmtPct(-sector, 1)}`;
  return `${pick}, while ${tide}.`;
}

function Metric({ label, value, signed, title }: { label: string; value: string; signed?: number | null; title?: string }) {
  return (
    <div title={title}>
      <div className="text-[11px] text-[var(--text-muted)]">{label}</div>
      <div className={clsx("text-sm font-semibold tabular", signClass(signed))}>{value}</div>
    </div>
  );
}

function StockCard({ s }: { s: StockDetail }) {
  const line = (color: string, width = 2, dash: "solid" | "dot" = "solid") => ({
    type: "scatter" as const,
    mode: "lines" as const,
    line: { color, width, dash },
    hovertemplate: "%{y:+.2%}",
  });
  const a = s.attribution;
  return (
    <section className="card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="text-base font-bold">{s.ticker}</span>
          <span className="ml-2 text-xs text-[var(--text-muted)]">{s.sector}</span>
        </div>
        <div className="text-xs text-[var(--text-muted)]">
          Bought {fmtDate(s.open_date)} · {s.hold_days}d · {fmtMoney(s.market_value)}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-3 sm:grid-cols-6">
        <Metric label="Return" value={fmtSignedPct(s.total_return)} signed={s.total_return} title={s.dividends > 0 ? `Includes ${fmtMoney(s.dividends)} of dividends` : undefined} />
        <Metric label="CAGR" value={fmtSignedPct(s.cagr)} signed={s.cagr} title={s.cagr === null ? "Held under a week: too short to annualize" : "Annualized from the holding period; sensitive while the holding is short"} />
        <Metric label="vs SPY" value={fmtSignedPct(s.excess_spy)} signed={s.excess_spy} />
        <Metric label="vs QQQ" value={fmtSignedPct(s.excess_qqq)} signed={s.excess_qqq} />
        <Metric label={`vs ${s.sector_etf ?? "sector"}`} value={fmtSignedPct(s.excess_sector)} signed={s.excess_sector} />
        <Metric label="β to SPY" value={s.beta_spy !== null ? fmtNum(s.beta_spy) : "—"} title="Beta to SPY from the last year of daily returns" />
      </div>

      <div className="mt-2">
        <Chart
          height={250}
          data={[
            { x: s.curves.stock.dates, y: s.curves.stock.values, name: s.ticker, ...line(SERIES.portfolio(), 2.5) },
            { x: s.curves.sector_etf.dates, y: s.curves.sector_etf.values, name: s.sector_etf ?? "Sector", ...line(SERIES.sector()) },
            { x: s.curves.SPY.dates, y: s.curves.SPY.values, name: "SPY", ...line(SERIES.spy()) },
            { x: s.curves.QQQ.dates, y: s.curves.QQQ.values, name: "QQQ", ...line(SERIES.qqq(), 2, "dot") },
          ]}
          layout={{ yaxis: { tickformat: "+.1%" }, margin: { l: 52, r: 8, t: 8, b: 32 } }}
        />
      </div>

      <div className="mt-3 border-t border-[var(--border)] pt-3">
        <div className="text-xs font-medium text-[var(--text-secondary)]" title="Market is SPY's return. Sector is the sector ETF's return above or below SPY. Stock is what's left, the part that comes from this company rather than the group it belongs to.">
          Where the return came from
        </div>
        <div className="mt-1.5 grid grid-cols-3 gap-3">
          <Metric label="Market (SPY)" value={fmtSignedPct(a.market)} signed={a.market} />
          <Metric label={`Sector (${s.sector_etf ?? "n/a"})`} value={fmtSignedPct(a.sector)} signed={a.sector} />
          <Metric label="Stock itself" value={fmtSignedPct(a.selection)} signed={a.selection} />
        </div>
        <p className="mt-2 text-xs text-[var(--text-secondary)]">
          {verdict(s)}
          {s.r_squared_sector !== null && (
            <span className="text-[var(--text-muted)]"> Over the past year, {fmtPct(s.r_squared_sector, 0)} of its daily moves tracked {s.sector_etf}.</span>
          )}
        </p>
      </div>
    </section>
  );
}

export default function SleeveStocks() {
  const id = useAccountId();
  const q = useQuery({ queryKey: ["stocks", id], queryFn: () => api.stocks(id) });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;
  const stocks = q.data!.stocks;
  if (stocks.length === 0) return <EmptyState message="This sleeve has no open positions." />;

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-muted)]">
        Every line starts at zero at the open on the purchase date, with dividends reinvested, so each stock races its sector ETF, SPY and QQQ from the same start.
      </p>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {stocks.map((s) => <StockCard key={`${s.ticker}-${s.open_date}`} s={s} />)}
      </div>
    </div>
  );
}
