// Shared portfolio/sleeve vs SPY/QQQ views: equity curve, gain curve, stats table.
import clsx from "clsx";
import { Performance, RiskResponse, RiskComparisonRow, Series } from "../api/client";
import Chart, { SERIES } from "./Chart";
import { SectionTitle, Skeleton } from "./Primitives";
import { fmtNum, fmtPct, fmtSignedPct } from "../lib/format";

const STATS_ROWS: { key: keyof RiskComparisonRow; label: string; fmt: (v: number | null) => string; signed?: boolean }[] = [
  // Return
  { key: "cagr", label: "CAGR", fmt: (v) => (v !== null ? fmtSignedPct(v) : "—"), signed: true },
  // Risk
  { key: "volatility", label: "Volatility (ann.)", fmt: (v) => (v !== null ? fmtPct(v) : "—") },
  { key: "max_drawdown", label: "Max drawdown", fmt: (v) => (v !== null ? fmtPct(v) : "—"), signed: true },
  // Risk-adjusted (own risk)
  { key: "sharpe", label: "Sharpe", fmt: (v) => (v !== null ? fmtNum(v) : "—") },
  { key: "sortino", label: "Sortino", fmt: (v) => (v !== null ? fmtNum(v) : "—") },
  { key: "calmar", label: "Calmar", fmt: (v) => (v !== null ? fmtNum(v) : "—") },
  // Relative to SPY
  { key: "beta_spy", label: "Beta (vs SPY)", fmt: (v) => (v !== null ? fmtNum(v) : "—") },
  { key: "r_squared_spy", label: "R² (vs SPY)", fmt: (v) => (v !== null ? fmtNum(v) : "—") },
  { key: "correlation_spy", label: "Correlation (vs SPY)", fmt: (v) => (v !== null ? fmtNum(v) : "—") },
  { key: "alpha_spy", label: "Alpha (vs SPY, ann.)", fmt: (v) => (v !== null ? fmtSignedPct(v) : "—"), signed: true },
  { key: "information_ratio_spy", label: "Information ratio (vs SPY)", fmt: (v) => (v !== null ? fmtNum(v) : "—"), signed: true },
];

export function StatsTable({ comparison, label }: { comparison?: RiskResponse["comparison"]; label: string }) {
  return (
    <>
      <SectionTitle hint="Since inception, from daily returns over identical dates. CAGR annualizes the elapsed period, so it swings hard on short histories. Calmar is CAGR / |max drawdown|. Beta, R², correlation and alpha are measured against SPY (SPY vs itself: beta 1.00, alpha 0.00, R² 1.00). R² is correlation², the share of daily variance SPY explains; a low R² means beta and alpha are less trustworthy. Information ratio is annualized excess return over SPY divided by tracking error. A dash means there isn't enough history yet.">
        Statistics: {label} vs. SPY vs. QQQ
      </SectionTitle>
      <div className="card table-scroll">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--text-muted)]">
              <th className="p-2">Metric</th>
              <th className="p-2 text-right">{label}</th>
              <th className="p-2 text-right">SPY</th>
              <th className="p-2 text-right">QQQ</th>
            </tr>
          </thead>
          <tbody>
            {!comparison ? (
              <tr><td className="p-2 text-[var(--text-muted)]" colSpan={4}>Loading…</td></tr>
            ) : (
              <>
                {STATS_ROWS.map(({ key, label: rowLabel, fmt, signed }) => (
                  <tr key={key} className="border-t border-[var(--border)]">
                    <td className="p-2 font-medium">{rowLabel}</td>
                    {(["portfolio", "spy", "qqq"] as const).map((col) => {
                      const v = comparison[col][key];
                      const cls = signed && v != null
                        ? v > 0 ? "text-[var(--pos-text)]" : v < 0 ? "text-[var(--neg)]" : "text-[var(--text-muted)]"
                        : "";
                      return (
                        <td key={col} className={clsx("p-2 text-right tabular", cls)}>
                          {fmt(v)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                <tr className="border-t border-[var(--border)] text-xs text-[var(--text-muted)]">
                  <td className="p-2">Observations</td>
                  <td className="p-2 text-right tabular">{comparison.portfolio.observations}</td>
                  <td className="p-2 text-right tabular">{comparison.spy.observations}</td>
                  <td className="p-2 text-right tabular">{comparison.qqq.observations}</td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

const toGain = (s: Series | undefined) => ({
  x: s?.dates ?? [],
  y: (s?.values ?? []).map((v) => v / 100 - 1),
});

/** Equity ($, benchmarks given the same cash flows) beside gain (%, time-weighted). */
export function EquityAndGain({ perf, label }: { perf?: Performance; label: string }) {
  if (!perf) return <Skeleton className="h-80" />;
  const line = (color: string) => ({ type: "scatter" as const, mode: "lines" as const, line: { color, width: 2 } });
  const g = perf.growth_of_100;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <div className="card p-3">
        <div className="mb-1 text-xs text-[var(--text-muted)]">Gain curve: time-weighted return since inception</div>
        <Chart
          height={320}
          data={[
            { ...toGain(g.portfolio), name: label, ...line(SERIES.portfolio()), hovertemplate: "%{y:+.2%}" },
            { ...toGain(g.SPY), name: "SPY", ...line(SERIES.spy()), hovertemplate: "%{y:+.2%}" },
            { ...toGain(g.QQQ), name: "QQQ", ...line(SERIES.qqq()), hovertemplate: "%{y:+.2%}" },
          ]}
          layout={{ yaxis: { tickformat: "+.1%", zeroline: true } }}
        />
      </div>
      <div className="card p-3">
        <div className="mb-1 text-xs text-[var(--text-muted)]">Equity curve: dollar value, benchmarks funded on the same dates</div>
        <Chart
          height={320}
          data={[
            { x: perf.value.dates, y: perf.value.values, name: label, ...line(SERIES.portfolio()), hovertemplate: "%{y:$,.2f}" },
            { x: perf.benchmark_values.SPY?.dates ?? [], y: perf.benchmark_values.SPY?.values ?? [], name: "SPY", ...line(SERIES.spy()), hovertemplate: "%{y:$,.2f}" },
            { x: perf.benchmark_values.QQQ?.dates ?? [], y: perf.benchmark_values.QQQ?.values ?? [], name: "QQQ", ...line(SERIES.qqq()), hovertemplate: "%{y:$,.2f}" },
          ]}
          layout={{ yaxis: { tickprefix: "$" } }}
        />
      </div>
    </div>
  );
}
