import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, Sleeve } from "../api/client";
import { PORTFOLIO } from "../state/AppState";
import Chart, { SERIES } from "../components/Chart";
import { EquityAndGain, StatsTable } from "../components/Comparison";
import { EmptyState, ErrorState, SectionTitle, Skeleton, SkeletonTiles, StatTile } from "../components/Primitives";
import { fmtDate, fmtMoney, fmtPct, fmtSignedMoney, fmtSignedPct, signClass } from "../lib/format";

function monthLabel(ym: string | null): string {
  if (!ym) return "later";
  return new Date(`${ym}-01T00:00:00`).toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

function SleeveCard({ s }: { s: Sleeve }) {
  const accent = { borderTopColor: `var(--sleeve-${s.number})` };
  if (s.status === "pending") {
    return (
      <Link to={`/sleeves/${s.number}`} className="card block border-t-2 p-4 hover:bg-[var(--grid)]" style={accent}>
        <div className="text-sm font-semibold">{s.name}</div>
        <div className="mt-2 text-sm text-[var(--text-secondary)]">Planned for {monthLabel(s.planned_start)}</div>
        <div className="mt-1 text-xs text-[var(--text-muted)]">{fmtMoney(s.capital)} when funded</div>
      </Link>
    );
  }
  const spy = s.benchmarks?.SPY;
  const qqq = s.benchmarks?.QQQ;
  return (
    <Link to={`/sleeves/${s.number}`} className="card block border-t-2 p-4 hover:bg-[var(--grid)]" style={accent}>
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-sm font-semibold">{s.name}</div>
        <div className="text-xs text-[var(--text-muted)]">since {fmtDate(s.start_date)}</div>
      </div>
      <div className="mt-2 flex items-baseline justify-between gap-2">
        <div className="text-xl font-semibold tabular">{fmtMoney(s.value)}</div>
        <div className={clsx("text-lg font-semibold tabular", signClass(s.twr))}>{fmtSignedPct(s.twr)}</div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-sm text-[var(--text-secondary)]">
        {([["SPY", spy], ["QQQ", qqq]] as const).map(([name, b]) => (
          <span key={name} title={`${name}'s own return over the same dates. The number in parentheses is the sleeve return minus ${name}.`}>
            {name} <span className={clsx("tabular font-medium", signClass(b?.twr))}>{fmtSignedPct(b?.twr)}</span>{" "}
            <span className={clsx("tabular text-xs", signClass(b?.excess))}>({fmtSignedPct(b?.excess)})</span>
          </span>
        ))}
        <span>
          Today <span className={clsx("tabular", signClass(s.today?.pct))}>{fmtSignedPct(s.today?.pct)}</span>
        </span>
        <span>
          Weight <span className="tabular">{fmtPct(s.portfolio_weight, 1)}</span>
        </span>
      </div>
      <div className="mt-2 truncate text-xs text-[var(--text-muted)]" title={s.tickers.join(", ")}>
        {s.tickers.join(" · ")}
      </div>
    </Link>
  );
}

export default function PortfolioOverview() {
  const summary = useQuery({ queryKey: ["summary", PORTFOLIO], queryFn: () => api.summary(PORTFOLIO) });
  const perf = useQuery({ queryKey: ["performance", PORTFOLIO], queryFn: () => api.performance(PORTFOLIO) });
  const risk = useQuery({ queryKey: ["risk", PORTFOLIO, "purchase"], queryFn: () => api.risk(PORTFOLIO) });
  const sleeves = useQuery({ queryKey: ["sleeves"], queryFn: api.sleeves });

  if (summary.isLoading) return <div className="space-y-4"><SkeletonTiles /><Skeleton className="h-80" /></div>;
  if (summary.isError) return <ErrorState message={String((summary.error as Error).message)} onRetry={() => summary.refetch()} />;
  const s = summary.data!;
  if (s.empty) return <EmptyState message="No sleeves funded yet. Open a sleeve to add its first holdings." />;

  const active = (sleeves.data?.sleeves ?? []).filter((x) => x.status === "active");
  const r = s.risk;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <StatTile label="Portfolio value" value={fmtMoney(s.current_value)} sub={`Invested ${fmtMoney(s.invested_capital)}`} />
        <StatTile label="Today" signed={s.today.pct} value={fmtSignedPct(s.today.pct)} sub={s.today.dollar !== null ? fmtSignedMoney(s.today.dollar) : "first session"} />
        <StatTile label="Total gain" signed={s.total.dollar} value={fmtSignedMoney(s.total.dollar)} sub={`${fmtSignedPct(s.total.pct)} on capital`} title="Dollars gained on all capital invested so far, whenever it arrived." />
        <StatTile label="Return (TWR)" signed={s.twr} value={fmtSignedPct(s.twr)} sub={`since ${fmtDate(s.inception)}`} title="Time-weighted: new sleeve funding doesn't distort it, so it compares directly with SPY and QQQ." />
        {(["SPY", "QQQ"] as const).map((b) => (
          <StatTile
            key={b}
            label={`${b} return`}
            signed={s.benchmarks[b]?.twr}
            value={fmtSignedPct(s.benchmarks[b]?.twr)}
            title={`${b}'s total return over the identical period.`}
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

      <SectionTitle hint="Each sleeve starts with the same capital. Open one for its holdings, stock charts, risk and history.">Sleeves</SectionTitle>
      {sleeves.isLoading ? (
        <Skeleton className="h-36" />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {(sleeves.data?.sleeves ?? []).map((x) => <SleeveCard key={x.id} s={x} />)}
        </div>
      )}

      <SectionTitle hint="Capital joins the portfolio on the day each sleeve is funded. SPY and QQQ receive the same money on the same dates, so the dollar comparison stays fair, and the time-weighted gain curve is unaffected by the new money.">
        Portfolio vs SPY and QQQ
      </SectionTitle>
      <EquityAndGain perf={perf.data} label="Portfolio" />

      <StatsTable comparison={risk.data?.comparison} label="Portfolio" />

      {active.length > 0 && (
        <>
          <SectionTitle hint="Each sleeve's time-weighted return from its own first day, so later sleeves start at zero on their own date.">Sleeves side by side</SectionTitle>
          <div className="card p-3">
            <Chart
              height={300}
              data={active.map((x) => ({
                x: x.curve?.dates ?? [],
                y: x.curve?.values ?? [],
                name: x.name,
                type: "scatter" as const,
                mode: "lines" as const,
                line: { color: SERIES.sleeve(x.number), width: 2 },
                hovertemplate: "%{y:+.2%}",
              }))}
              layout={{ yaxis: { tickformat: "+.1%" } }}
            />
          </div>
        </>
      )}

      <div className="text-xs text-[var(--text-muted)]">
        {r.observations} daily observations. Annualized figures such as CAGR, alpha and Sharpe are noisy until the portfolio has more history.
      </div>
    </div>
  );
}
