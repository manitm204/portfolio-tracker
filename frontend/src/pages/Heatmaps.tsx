import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, HeatmapTile } from "../api/client";
import { PORTFOLIO } from "../state/AppState";
import Chart, { SERIES, divergingScale, sectorTreemap } from "../components/Chart";
import { EmptyState, ErrorState, SectionTitle, Skeleton } from "../components/Primitives";
import { fmtDate, fmtPct, fmtSignedPct } from "../lib/format";

const PERIODS: { key: string; label: string; column: string }[] = [
  { key: "1D", label: "Today", column: "Today" },
  { key: "1W", label: "Week", column: "1W" },
  { key: "MTD", label: "Month to date", column: "MTD" },
  { key: "1M", label: "Month", column: "1M" },
  { key: "3M", label: "3 months", column: "3M" },
  { key: "YTD", label: "Year to date", column: "YTD" },
  { key: "1Y", label: "Year", column: "1Y" },
  { key: "SI", label: "Since purchase", column: "Held" },
];

const periodLabel = (key: string) => PERIODS.find((p) => p.key === key)?.label.toLowerCase() ?? key;

function Treemap({
  tiles,
  maxAbs,
  height,
  hovertemplate,
}: {
  tiles: { ticker: string; sector: string; size: number; ret: number | null; hoverValue?: number }[];
  maxAbs: number;
  height: number;
  hovertemplate: string;
}) {
  const t = sectorTreemap(tiles);
  return (
    <Chart
      height={height}
      data={[
        {
          type: "treemap",
          labels: t.labels,
          parents: t.parents,
          values: t.values,
          branchvalues: "remainder",
          text: t.text,
          textinfo: "label+text",
          marker: {
            colors: t.colors,
            colorscale: divergingScale(),
            cmin: -maxAbs,
            cmax: maxAbs,
            line: { color: SERIES.surface(), width: 1 },
            colorbar: { tickformat: ".1%", thickness: 10, outlinewidth: 0 },
            showscale: true,
          },
          customdata: t.customdata as never,
          hovertemplate,
        } as never,
      ]}
      layout={{ hovermode: "closest", margin: { l: 4, r: 4, t: 4, b: 4 } }}
    />
  );
}

/** Scale the color to the bulk of the moves, so one outlier doesn't wash out the map. */
function colorRange(returns: (number | null)[]): number {
  const abs = returns.filter((r): r is number => r !== null).map(Math.abs).sort((a, b) => a - b);
  if (abs.length === 0) return 0.005;
  return Math.max(abs[Math.floor((abs.length - 1) * 0.95)], 0.005);
}

function cellColor(v: number | null, maxAbs: number): string | undefined {
  if (v === null) return undefined;
  const strength = Math.min(Math.abs(v) / maxAbs, 1) * 0.55;
  const base = v >= 0 ? "12, 163, 12" : "208, 59, 59";
  return `rgba(${base}, ${strength.toFixed(3)})`;
}

function HeatTable({
  tiles,
  benchmarks,
  active,
  onPick,
}: {
  tiles: HeatmapTile[];
  benchmarks: Record<string, Record<string, number | null>>;
  active: string;
  onPick: (p: string) => void;
}) {
  const rows = useMemo(
    () => [...tiles].sort((a, b) => (b.returns[active] ?? -Infinity) - (a.returns[active] ?? -Infinity)),
    [tiles, active],
  );
  // Each column has its own scale: a 2% day is a big move, a 2% year isn't.
  const ranges = useMemo(
    () => Object.fromEntries(PERIODS.map((p) => [p.key, colorRange(tiles.map((t) => t.returns[p.key] ?? null))])),
    [tiles],
  );
  const cell = (key: string, v: number | null | undefined) => (
    <td
      key={key}
      className={clsx("p-2 text-right tabular", key === active && "font-semibold")}
      style={{ background: cellColor(v ?? null, ranges[key]) }}
    >
      {fmtSignedPct(v ?? null, 1)}
    </td>
  );
  return (
    <div className="card table-scroll">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-right text-xs text-[var(--text-muted)]">
            <th className="p-2 text-left">Ticker</th>
            <th className="p-2 text-left">Sleeve</th>
            <th className="p-2 text-left">Sector</th>
            <th className="p-2">Weight</th>
            {PERIODS.map((p) => (
              <th key={p.key} className="p-2">
                <button onClick={() => onPick(p.key)} className={clsx("hover:text-[var(--text-primary)]", p.key === active && "font-semibold text-[var(--text-primary)]")}>
                  {p.column}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.ticker} className="border-t border-[var(--border)]">
              <td className="p-2 font-semibold">{t.ticker}</td>
              <td className="whitespace-nowrap p-2 text-xs text-[var(--text-secondary)]">{t.sleeves.join(", ")}</td>
              <td className="whitespace-nowrap p-2 text-xs text-[var(--text-secondary)]">{t.sector}</td>
              <td className="p-2 text-right tabular">{fmtPct(t.weight, 1)}</td>
              {PERIODS.map((p) => cell(p.key, t.returns[p.key]))}
            </tr>
          ))}
          {Object.entries(benchmarks).map(([b, returns]) => (
            <tr key={b} className="border-t-2 border-[var(--border)] text-[var(--text-secondary)]">
              <td className="p-2 font-semibold">{b}</td>
              <td className="p-2 text-xs" colSpan={3}>Benchmark</td>
              {PERIODS.map((p) => (
                <td key={p.key} className="p-2 text-right tabular">{fmtSignedPct(returns[p.key] ?? null, 1)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectorBars({ rows }: { rows: { sector: string; return: number | null; weight: number }[] }) {
  const ordered = [...rows].sort((a, b) => (a.return ?? 0) - (b.return ?? 0));
  return (
    <Chart
      height={Math.max(220, rows.length * 30)}
      data={[
        {
          y: ordered.map((s) => s.sector),
          x: ordered.map((s) => s.return ?? 0),
          type: "bar",
          orientation: "h",
          marker: { color: ordered.map((s) => ((s.return ?? 0) >= 0 ? SERIES.pos() : SERIES.neg())) },
          customdata: ordered.map((s) => s.weight) as never,
          hovertemplate: "%{y}: %{x:+.2%} (weight %{customdata:.1%})<extra></extra>",
        },
      ]}
      layout={{ xaxis: { tickformat: "+.1%" }, hovermode: "closest", bargap: 0.3 }}
    />
  );
}

export default function Heatmaps() {
  const [period, setPeriod] = useState("1D");
  // "Since purchase" has no meaning for the index, which shows YTD instead.
  const marketPeriod = period === "SI" ? "YTD" : period;
  const mine = useQuery({
    queryKey: ["heatmap", PORTFOLIO, period],
    queryFn: () => api.heatmap(PORTFOLIO, period),
    placeholderData: (prev) => prev,
  });
  const market = useQuery({
    queryKey: ["market-heatmap", marketPeriod],
    queryFn: () => api.marketHeatmap(marketPeriod),
    placeholderData: (prev) => prev,
  });

  return (
    <div className="space-y-4">
      <div className="flex overflow-x-auto rounded-lg border border-[var(--border)] sm:w-fit" role="group" aria-label="Heatmap period">
        {PERIODS.map((p) => (
          <button
            key={p.key}
            onClick={() => setPeriod(p.key)}
            className={clsx(
              "whitespace-nowrap px-3 py-1.5 text-xs font-medium sm:text-sm",
              period === p.key ? "bg-[var(--series-portfolio)] text-white" : "text-[var(--text-secondary)] hover:bg-[var(--grid)]",
            )}
          >
            {p.label}
          </button>
        ))}
      </div>

      <SectionTitle hint="Every holding across all sleeves, sized by its weight in the portfolio and grouped by sector. Returns are the stock's own move over the period, even if you've held it for less time. 'Since purchase' uses your cost.">
        My portfolio
      </SectionTitle>
      {mine.isLoading ? (
        <Skeleton className="h-[420px]" />
      ) : mine.isError ? (
        <ErrorState message={String((mine.error as Error).message)} onRetry={() => mine.refetch()} />
      ) : mine.data!.tiles.length === 0 ? (
        <EmptyState message="No holdings to map." />
      ) : (
        <>
          <div className="card p-2">
            <Treemap
              height={420}
              tiles={mine.data!.tiles.map((t) => ({ ticker: t.ticker, sector: t.sector, size: t.weight, ret: t.return, hoverValue: t.value }))}
              maxAbs={colorRange(mine.data!.tiles.map((t) => t.return))}
              hovertemplate="%{label} · %{text}<br>weight %{customdata[0]:.2%} · value %{customdata[1]:$,.2f}<extra></extra>"
            />
          </div>
          <SectionTitle hint="Every holding over every period. Each column has its own color scale, since a 2% day is a bigger move than a 2% year. Click a column to sort by it and switch the maps. A dash means the stock has no price history that far back.">
            All holdings by period
          </SectionTitle>
          <HeatTable tiles={mine.data!.tiles} benchmarks={mine.data!.benchmarks ?? {}} active={period} onPick={setPeriod} />
        </>
      )}

      <SectionTitle hint="Every S&P 500 company, sized by its weight in SPY from State Street's daily holdings file, grouped by sector. Updated with each market-data refresh.">
        S&P 500 (SPY)
      </SectionTitle>
      {market.isLoading ? (
        <Skeleton className="h-[640px]" />
      ) : market.isError ? (
        <ErrorState message={String((market.error as Error).message)} onRetry={() => market.refetch()} />
      ) : market.data!.tiles.length === 0 ? (
        <EmptyState message="No S&P 500 data yet. Press Refresh to download it." />
      ) : (
        <>
          <div className="text-xs text-[var(--text-muted)]">
            {period === "SI" ? "“Since purchase” doesn't apply to the index, so this shows year to date. " : ""}
            {market.data!.tiles.length} companies, {periodLabel(marketPeriod)}, as of {fmtDate(market.data!.as_of)}
            {market.data!.unpriced.length > 0 && ` · no price data for ${market.data!.unpriced.join(", ")}`}
          </div>
          <div className="card p-2">
            <Treemap
              height={640}
              tiles={market.data!.tiles.map((t) => ({ ticker: t.ticker, sector: t.sector, size: t.weight, ret: t.return, hoverValue: 0 }))}
              maxAbs={colorRange(market.data!.tiles.map((t) => t.return))}
              hovertemplate="%{label} · %{text}<br>weight in SPY %{customdata[0]:.2%}<extra></extra>"
            />
          </div>
        </>
      )}

      {mine.data && market.data && mine.data.sectors.length > 0 && (
        <>
          <SectionTitle hint="Weight-weighted return of each sector over the selected period: your holdings on the left, the whole S&P 500 on the right.">
            Sector returns
          </SectionTitle>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="card p-3">
              <div className="mb-1 text-xs text-[var(--text-muted)]">My holdings</div>
              <SectorBars rows={mine.data.sectors} />
            </div>
            <div className="card p-3">
              <div className="mb-1 text-xs text-[var(--text-muted)]">S&amp;P 500</div>
              <SectorBars rows={market.data.sectors.filter((s) => s.sector !== "Unknown")} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
