import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, ApiError, MonteCarloResponse, RiskComparisonRow } from "../api/client";
import { rangeToStart, useAppState } from "../state/AppState";
import Chart, { SERIES, divergingScale } from "../components/Chart";
import { EmptyState, ErrorState, SectionTitle, Skeleton } from "../components/Primitives";
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

const MONTE_CARLO_ACCOUNTS = new Set(["PORTFOLIO_5"]);
const MONTE_CARLO_DEFAULT_SIMS: Record<string, number> = {
  PORTFOLIO_5: 50,
};
const MONTE_CARLO_HINT: Record<string, string> = {
  PORTFOLIO_5:
    "Compares the actual equal-weight portfolio to N random same-size stock picks from the S&P 500, all invested equally on the same inception date and held (buy-and-hold, adjusted-close pricing).",
};

const RANGES = ["SI", "YTD", "1M", "3M", "6M", "1Y", "custom"];
const PERIOD_COLS = ["1D", "1W", "1M", "3M", "6M", "1Y", "YTD", "SI"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function Performance() {
  const { accountId, range, setRange, customStart, customEnd, setCustom } = useAppState();
  const [rollWin, setRollWin] = useState<"30" | "90" | "252">("30");
  const start = rangeToStart(range, customStart);
  const end = range === "custom" ? (customEnd ?? undefined) : undefined;

  const q = useQuery({
    queryKey: ["performance", accountId, start ?? "SI", end ?? ""],
    queryFn: () => api.performance(accountId, start, end),
  });
  const riskQ = useQuery({ queryKey: ["risk", accountId], queryFn: () => api.risk(accountId) });

  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;
  const p = q.data;
  const rc = riskQ.data?.comparison;

  return (
    <div className="space-y-4">
      {/* Range controls */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded-lg border border-[var(--border)]">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={clsx(
                "px-3 py-1.5 text-xs font-medium sm:text-sm",
                range === r ? "bg-[var(--series-portfolio)] text-white" : "text-[var(--text-secondary)] hover:bg-[var(--grid)]",
              )}
            >
              {r === "SI" ? "Inception" : r}
            </button>
          ))}
        </div>
        {range === "custom" && (
          <span className="flex items-center gap-1 text-sm">
            <input type="date" value={customStart ?? ""} onChange={(e) => setCustom(e.target.value || null, customEnd)} className="rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1" />
            –
            <input type="date" value={customEnd ?? ""} onChange={(e) => setCustom(customStart, e.target.value || null)} className="rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1" />
          </span>
        )}
      </div>

      {q.isLoading || !p ? (
        <div className="space-y-4"><Skeleton className="h-80" /><Skeleton className="h-64" /></div>
      ) : p.value.dates.length === 0 ? (
        <EmptyState message="No data in the selected range." />
      ) : (
        <>
          <SectionTitle hint="Growth of $100: every series compounds daily time-weighted returns from the window start, so external cash flows don't distort the comparison. The dollar comparison below invests the same external flows in the benchmark on the same dates.">
            Portfolio vs benchmarks
          </SectionTitle>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="card p-3">
              <div className="mb-1 text-xs text-[var(--text-muted)]">Growth of $100 (TWR-linked)</div>
              <Chart
                height={300}
                data={[
                  { x: p.growth_of_100.portfolio.dates, y: p.growth_of_100.portfolio.values, name: "Portfolio", type: "scatter", mode: "lines", line: { color: SERIES.portfolio(), width: 2 }, hovertemplate: "%{y:$.2f}" },
                  { x: p.growth_of_100.SPY?.dates ?? [], y: p.growth_of_100.SPY?.values ?? [], name: "SPY", type: "scatter", mode: "lines", line: { color: SERIES.spy(), width: 2 }, hovertemplate: "%{y:$.2f}" },
                  { x: p.growth_of_100.QQQ?.dates ?? [], y: p.growth_of_100.QQQ?.values ?? [], name: "QQQ", type: "scatter", mode: "lines", line: { color: SERIES.qqq(), width: 2 }, hovertemplate: "%{y:$.2f}" },
                ]}
                layout={{ yaxis: { tickprefix: "$" } }}
              />
            </div>
            <div className="card p-3">
              <div className="mb-1 text-xs text-[var(--text-muted)]">Matched-cash-flow dollar value</div>
              <Chart
                height={300}
                data={[
                  { x: p.value.dates, y: p.value.values, name: "Portfolio", type: "scatter", mode: "lines", line: { color: SERIES.portfolio(), width: 2 }, hovertemplate: "%{y:$,.2f}" },
                  { x: p.benchmark_values.SPY?.dates ?? [], y: p.benchmark_values.SPY?.values ?? [], name: "SPY (same flows)", type: "scatter", mode: "lines", line: { color: SERIES.spy(), width: 2 }, hovertemplate: "%{y:$,.2f}" },
                  { x: p.benchmark_values.QQQ?.dates ?? [], y: p.benchmark_values.QQQ?.values ?? [], name: "QQQ (same flows)", type: "scatter", mode: "lines", line: { color: SERIES.qqq(), width: 2 }, hovertemplate: "%{y:$,.2f}" },
                ]}
                layout={{ yaxis: { tickprefix: "$" } }}
              />
            </div>
          </div>

          <SectionTitle>Daily &amp; cumulative return</SectionTitle>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="card p-3">
              <div className="mb-1 text-xs text-[var(--text-muted)]">Daily TWR return</div>
              <Chart
                height={260}
                data={[
                  {
                    x: p.daily_returns.dates,
                    y: p.daily_returns.values,
                    type: "bar",
                    name: "Daily",
                    marker: { color: p.daily_returns.values.map((v) => (v >= 0 ? SERIES.pos() : SERIES.neg())) },
                    hovertemplate: "%{y:.2%}",
                  },
                ]}
                layout={{ yaxis: { tickformat: ".1%" }, bargap: 0.35 }}
              />
            </div>
            <div className="card p-3">
              <div className="mb-1 text-xs text-[var(--text-muted)]">Cumulative TWR return</div>
              <Chart
                height={260}
                data={[
                  { x: p.cumulative_returns.dates, y: p.cumulative_returns.values, type: "scatter", mode: "lines", name: "Cumulative", line: { color: SERIES.portfolio(), width: 2 }, hovertemplate: "%{y:.2%}" },
                ]}
                layout={{ yaxis: { tickformat: ".1%" } }}
              />
            </div>
          </div>

          <SectionTitle hint="Peak-to-trough decline of the cumulative TWR index. Benchmarks use their own matched-flow returns.">Drawdown</SectionTitle>
          <div className="card p-3">
            <Chart
              height={260}
              data={[
                { x: p.drawdown.dates, y: p.drawdown.values, name: "Portfolio", type: "scatter", mode: "lines", fill: "tozeroy", fillcolor: "rgba(208,59,59,0.10)", line: { color: SERIES.neg(), width: 2 }, hovertemplate: "%{y:.2%}" },
                { x: p.benchmark_drawdown.SPY?.dates ?? [], y: p.benchmark_drawdown.SPY?.values ?? [], name: "SPY", type: "scatter", mode: "lines", line: { color: SERIES.spy(), width: 1.5, dash: "dot" }, hovertemplate: "%{y:.2%}" },
                { x: p.benchmark_drawdown.QQQ?.dates ?? [], y: p.benchmark_drawdown.QQQ?.values ?? [], name: "QQQ", type: "scatter", mode: "lines", line: { color: SERIES.qqq(), width: 1.5, dash: "dot" }, hovertemplate: "%{y:.2%}" },
              ]}
              layout={{ yaxis: { tickformat: ".1%" } }}
            />
          </div>

          <SectionTitle hint="Rolling statistics need at least the window length of daily history; charts stay empty until then.">
            Rolling statistics
          </SectionTitle>
          <div className="mb-2 flex gap-1">
            {(["30", "90", "252"] as const).map((w) => (
              <button key={w} onClick={() => setRollWin(w)} className={clsx("rounded-md border border-[var(--border)] px-3 py-1 text-xs", rollWin === w ? "bg-[var(--series-portfolio)] text-white" : "text-[var(--text-secondary)]")}>
                {w}d
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            {(
              [
                ["Rolling beta vs SPY", [{ s: p.rolling[rollWin]?.beta_spy, name: "β vs SPY", color: SERIES.portfolio() }], ".2f"],
                ["Rolling volatility (ann.)", [{ s: p.rolling[rollWin]?.volatility, name: "Volatility", color: SERIES.portfolio() }], ".1%"],
                ["Rolling correlation", [
                  { s: p.rolling[rollWin]?.corr_spy, name: "vs SPY", color: SERIES.spy() },
                  { s: p.rolling[rollWin]?.corr_qqq, name: "vs QQQ", color: SERIES.qqq() },
                ], ".2f"],
              ] as const
            ).map(([title, series, fmt]) => {
              const has = series.some((x) => (x.s?.dates.length ?? 0) > 0);
              return (
                <div key={title} className="card p-3">
                  <div className="mb-1 text-xs text-[var(--text-muted)]">{title} ({rollWin} trading days)</div>
                  {has ? (
                    <Chart
                      height={240}
                      data={series.map((x) => ({ x: x.s?.dates ?? [], y: x.s?.values ?? [], name: x.name, type: "scatter" as const, mode: "lines" as const, line: { color: x.color, width: 2 } }))}
                      layout={{ yaxis: { tickformat: fmt } }}
                    />
                  ) : (
                    <div className="flex h-[240px] items-center justify-center text-sm text-[var(--text-muted)]">
                      insufficient history — needs ≥ {rollWin} trading days
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <SectionTitle>Period returns</SectionTitle>
          <div className="card table-scroll">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--text-muted)]">
                  <th className="p-2">Series</th>
                  {PERIOD_COLS.map((c) => (<th key={c} className="p-2 text-right whitespace-nowrap">{c === "SI" ? `Inception (${p.inception})` : c}</th>))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(p.period_returns).map(([name, row]) => (
                  <tr key={name} className="border-t border-[var(--border)]">
                    <td className="p-2 font-medium">{name === "portfolio" ? "Portfolio" : name}</td>
                    {PERIOD_COLS.map((c) => {
                      const v = row[c];
                      return (
                        <td key={c} className={clsx("p-2 text-right tabular", v != null && v > 0 ? "text-[var(--pos-text)]" : v != null && v < 0 ? "text-[var(--neg)]" : "text-[var(--text-muted)]")}>
                          {v != null ? fmtSignedPct(v) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <SectionTitle hint="Fixed since account inception, independent of the range selector above — the actual portfolio's own historical daily returns vs. SPY and QQQ's own returns over the same period. Ordered: return, risk, risk-adjusted ratios, then everything measured relative to SPY. CAGR is the geometrically compounded annual growth rate over the actual elapsed period; Calmar is CAGR / |max drawdown|. Beta, R², correlation, and alpha are all measured against SPY (SPY's own values vs. itself: beta 1.00, alpha 0.00, R² 1.00). R² is correlation² — the share of daily variance SPY explains; low R² means beta/alpha are less trustworthy. Information ratio is annualized excess return over SPY divided by tracking error (the volatility of that excess) — a risk-adjusted measure of edge over SPY that doesn't rely on the beta regression being stable.">
            Since-inception statistics: Portfolio vs. SPY vs. QQQ
          </SectionTitle>
          <div className="card table-scroll">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--text-muted)]">
                  <th className="p-2">Metric</th>
                  <th className="p-2 text-right">Portfolio</th>
                  <th className="p-2 text-right">SPY</th>
                  <th className="p-2 text-right">QQQ</th>
                </tr>
              </thead>
              <tbody>
                {!rc ? (
                  <tr><td className="p-2 text-[var(--text-muted)]" colSpan={4}>Loading…</td></tr>
                ) : (
                  <>
                    {STATS_ROWS.map(({ key, label, fmt, signed }) => (
                      <tr key={key} className="border-t border-[var(--border)]">
                        <td className="p-2 font-medium">{label}</td>
                        {(["portfolio", "spy", "qqq"] as const).map((col) => {
                          const v = rc[col][key];
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
                      <td className="p-2 text-right tabular">{rc.portfolio.observations}</td>
                      <td className="p-2 text-right tabular">{rc.spy.observations}</td>
                      <td className="p-2 text-right tabular">{rc.qqq.observations}</td>
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </div>

          <CalendarHeatmap dates={p.calendar_heatmap.dates} values={p.calendar_heatmap.values} />
          <MonthlyHeatmap rows={p.monthly_heatmap} />
        </>
      )}

      <MonteCarloSection accountId={accountId} />
    </div>
  );
}

/** Stock picking vs random selection: actual portfolio against N random
 * same-size, equal-weight S&P 500 picks invested on the same inception date. */
function MonteCarloSection({ accountId }: { accountId: string }) {
  const supported = MONTE_CARLO_ACCOUNTS.has(accountId);
  const [sims, setSims] = useState(MONTE_CARLO_DEFAULT_SIMS[accountId] ?? 50);

  useEffect(() => {
    setSims(MONTE_CARLO_DEFAULT_SIMS[accountId] ?? 50);
  }, [accountId]);

  const q = useQuery({
    queryKey: ["monte-carlo", accountId, sims],
    queryFn: () => api.monteCarlo(accountId, sims),
    enabled: false,
    staleTime: Infinity,
    retry: false,
  });

  return (
    <>
      <SectionTitle hint={`${MONTE_CARLO_HINT[accountId] ?? MONTE_CARLO_HINT.PORTFOLIO_5} Shows whether the stock picking beat random chance.`}>
        Monte Carlo: stock picking vs. random selection
      </SectionTitle>
      <div className="card p-3">
        {!supported ? (
          <EmptyState message="Monte Carlo comparison isn't available for this account." />
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                Simulations
                <input
                  type="number"
                  min={5}
                  max={200}
                  value={sims}
                  onChange={(e) => setSims(Math.max(5, Math.min(200, Number(e.target.value) || 50)))}
                  className="w-20 rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1 tabular"
                />
              </label>
              <button
                onClick={() => q.refetch()}
                disabled={q.isFetching}
                className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--grid)] disabled:opacity-50"
              >
                {q.isFetching ? "Running…" : q.data ? "Re-run" : "Run simulation"}
              </button>
              {q.isFetching && (
                <span className="text-xs text-[var(--text-muted)]">
                  First run may take a while — fetching price history for randomly picked tickers.
                </span>
              )}
              {q.data && !q.data.empty && (
                <span className="text-xs text-[var(--text-secondary)]">
                  {q.data.sims_run}/{q.data.sims_requested} simulations ran · universe {q.data.universe_size} tickers
                  {q.data.percentile_rank != null && (
                    <> · actual portfolio beat {fmtPct(q.data.percentile_rank)} of random picks</>
                  )}
                </span>
              )}
            </div>

            {q.isError ? (
              <ErrorState
                message={q.error instanceof ApiError ? q.error.message : "Simulation failed."}
                onRetry={() => q.refetch()}
              />
            ) : q.data ? (
              <MonteCarloChart data={q.data} />
            ) : (
              <div className="flex h-[320px] items-center justify-center text-sm text-[var(--text-muted)]">
                Click "Run simulation" to compare against random stock picks.
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

function MonteCarloChart({ data }: { data: MonteCarloResponse }) {
  if (data.empty) return <EmptyState message="No performance history yet." />;
  const grayLines = data.simulations.map((sim, i) => ({
    x: sim.dates,
    y: sim.values,
    type: "scatter" as const,
    mode: "lines" as const,
    line: { color: "rgba(140,140,150,0.35)", width: 1 },
    hoverinfo: "skip" as const,
    showlegend: i === 0,
    name: "Random picks",
    legendgroup: "sims",
  }));
  return (
    <Chart
      height={380}
      data={[
        ...grayLines,
        {
          x: data.median.dates,
          y: data.median.values,
          type: "scatter",
          mode: "lines",
          name: "Median (random)",
          line: { color: SERIES.qqq(), width: 2, dash: "dot" },
          hovertemplate: "%{y:$.2f}",
        },
        {
          x: data.mean.dates,
          y: data.mean.values,
          type: "scatter",
          mode: "lines",
          name: "Mean (random)",
          line: { color: SERIES.spy(), width: 2, dash: "dot" },
          hovertemplate: "%{y:$.2f}",
        },
        {
          x: data.actual.dates,
          y: data.actual.values,
          type: "scatter",
          mode: "lines",
          name: `Actual (${data.actual.tickers.join(", ")})`,
          line: { color: SERIES.portfolio(), width: 3 },
          hovertemplate: "%{y:$.2f}",
        },
      ]}
      layout={{ yaxis: { tickprefix: "$", title: { text: "Growth of $100" } } }}
    />
  );
}

/** Daily-return calendar: weeks as columns, weekdays as rows (GitHub style). */
function CalendarHeatmap({ dates, values }: { dates: string[]; values: number[] }) {
  const { z, x, y, text, maxAbs } = useMemo(() => {
    const byDate = new Map(dates.map((d, i) => [d, values[i]]));
    if (dates.length === 0) return { z: [], x: [], y: [], text: [], maxAbs: 0.01 };
    const first = new Date(`${dates[0]}T00:00:00`);
    const last = new Date(`${dates[dates.length - 1]}T00:00:00`);
    const weeks: string[] = [];
    const z: (number | null)[][] = [[], [], [], [], []]; // Mon..Fri
    const text: string[][] = [[], [], [], [], []];
    const cur = new Date(first);
    cur.setDate(cur.getDate() - ((cur.getDay() + 6) % 7)); // back to Monday
    let maxAbs = 0;
    while (cur <= last) {
      const weekLabel = cur.toISOString().slice(0, 10);
      weeks.push(weekLabel);
      for (let dow = 0; dow < 5; dow++) {
        const d = new Date(cur);
        d.setDate(d.getDate() + dow);
        const iso = d.toISOString().slice(0, 10);
        const v = byDate.get(iso);
        z[dow].push(v ?? null);
        text[dow].push(v !== undefined ? `${iso}: ${(v * 100).toFixed(2)}%` : iso);
        if (v !== undefined) maxAbs = Math.max(maxAbs, Math.abs(v));
      }
      cur.setDate(cur.getDate() + 7);
    }
    return { z, x: weeks, y: ["Mon", "Tue", "Wed", "Thu", "Fri"], text, maxAbs: maxAbs || 0.01 };
  }, [dates, values]);

  if (dates.length === 0) return null;
  return (
    <>
      <SectionTitle hint="Each cell is one trading day's TWR return. Gray cells: no data (holiday or out of range). Zero-anchored green/red scale.">
        Daily return calendar
      </SectionTitle>
      <div className="card p-3">
        <Chart
          height={200}
          data={[
            {
              z, x, y, text,
              type: "heatmap",
              hoverinfo: "text",
              zmin: -maxAbs, zmax: maxAbs,
              colorscale: divergingScale() as never,
              showscale: true,
              colorbar: { tickformat: ".1%", thickness: 10, outlinewidth: 0 },
              xgap: 2, ygap: 2,
            } as never,
          ]}
          layout={{ yaxis: { autorange: "reversed" }, hovermode: "closest" }}
        />
      </div>
    </>
  );
}

function MonthlyHeatmap({ rows }: { rows: { year: number; month: number; return: number }[] }) {
  if (rows.length === 0) return null;
  const years = [...new Set(rows.map((r) => r.year))].sort();
  const byKey = new Map(rows.map((r) => [`${r.year}-${r.month}`, r.return]));
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.return)), 0.01);
  const z = years.map((y) => MONTHS.map((_, i) => byKey.get(`${y}-${i + 1}`) ?? null));
  const text = years.map((y) =>
    MONTHS.map((m, i) => {
      const v = byKey.get(`${y}-${i + 1}`);
      return v !== undefined ? `${m} ${y}: ${(v * 100).toFixed(2)}%` : `${m} ${y}`;
    }),
  );
  return (
    <>
      <SectionTitle hint="Monthly compounded TWR returns; years as rows.">Monthly returns</SectionTitle>
      <div className="card p-3">
        <Chart
          height={Math.max(140, 60 + years.length * 40)}
          data={[
            {
              z, x: MONTHS, y: years.map(String), text,
              type: "heatmap",
              hoverinfo: "text",
              zmin: -maxAbs, zmax: maxAbs,
              colorscale: divergingScale() as never,
              showscale: true,
              colorbar: { tickformat: ".1%", thickness: 10, outlinewidth: 0 },
              xgap: 2, ygap: 2,
            } as never,
          ]}
          layout={{ hovermode: "closest", yaxis: { type: "category" }, xaxis: { type: "category" } }}
        />
      </div>
    </>
  );
}
