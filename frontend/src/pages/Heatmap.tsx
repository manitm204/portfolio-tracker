import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../api/client";
import { useAppState } from "../state/AppState";
import Chart, { divergingScale, sectorTreemap } from "../components/Chart";
import { EmptyState, ErrorState, SectionTitle, Skeleton } from "../components/Primitives";

function HeatmapTreemap({
  tiles,
  maxAbs,
}: {
  tiles: { ticker: string; sector: string; size: number; ret: number | null; hoverValue: number }[];
  maxAbs: number;
}) {
  const t = sectorTreemap(tiles);
  return (
    <Chart
      height={560}
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
            line: { color: "var(--surface-1)", width: 2 },
            colorbar: { tickformat: ".1%", thickness: 10, outlinewidth: 0 },
            showscale: true,
          },
          customdata: t.customdata as never,
          hovertemplate:
            "%{label} · %{text}<br>weight %{customdata[0]:.2%} · value %{customdata[1]:$,.2f}<extra></extra>",
        } as never,
      ]}
      layout={{ hovermode: "closest", margin: { l: 4, r: 4, t: 4, b: 4 } }}
    />
  );
}

const PERIOD_LABEL: Record<string, string> = {
  "1D": "Daily",
  "1W": "Weekly",
  "1M": "Monthly",
  MTD: "Month to date",
  SI: "Since inception",
};

export default function Heatmap() {
  const { accountId } = useAppState();
  const [period, setPeriod] = useState("1D");
  const q = useQuery({
    queryKey: ["heatmap", accountId, period],
    queryFn: () => api.heatmap(accountId, period),
  });

  if (q.isLoading) return <Skeleton className="h-[70vh]" />;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;
  const data = q.data!;
  if (data.tiles.length === 0) return <EmptyState message="No holdings to map." />;

  const maxAbs = Math.max(...data.tiles.map((t) => Math.abs(t.return ?? 0)), 0.005);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded-lg border border-[var(--border)]">
          {data.periods.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={clsx(
                "px-3 py-1.5 text-xs font-medium sm:text-sm",
                period === p ? "bg-[var(--series-portfolio)] text-white" : "text-[var(--text-secondary)] hover:bg-[var(--grid)]",
              )}
            >
              {PERIOD_LABEL[p] ?? p}
            </button>
          ))}
        </div>
        <span className="text-xs text-[var(--text-muted)]">
          Tile size = portfolio weight · color = {PERIOD_LABEL[period]?.toLowerCase()} return · grouped by sector · zero midpoint
        </span>
      </div>

      <SectionTitle hint="SPY-style map: every active holding, sized by current weight, grouped into sector blocks. 'Since inception' uses return on cost; shorter periods use adjusted closes.">
        Holdings heatmap
      </SectionTitle>
      <div className="card p-2">
        <HeatmapTreemap
          tiles={data.tiles.map((t) => ({
            ticker: t.ticker,
            sector: t.sector,
            size: t.weight,
            ret: t.return,
            hoverValue: t.value,
          }))}
          maxAbs={maxAbs}
        />
      </div>

      <SectionTitle hint="Weight-weighted average return of each sector for the selected period.">Sector performance</SectionTitle>
      <div className="card p-3">
        <Chart
          height={Math.max(220, data.sectors.length * 30)}
          data={[
            {
              y: data.sectors.map((s) => s.sector).reverse(),
              x: data.sectors.map((s) => s.return ?? 0).reverse(),
              type: "bar",
              orientation: "h",
              marker: {
                color: data.sectors.map((s) => ((s.return ?? 0) >= 0 ? "#0ca30c" : "#d03b3b")).reverse(),
              },
              customdata: data.sectors.map((s) => s.weight).reverse() as never,
              hovertemplate: "%{y}: %{x:+.2%} (weight %{customdata:.1%})<extra></extra>",
            },
          ]}
          layout={{ xaxis: { tickformat: "+.1%" }, hovermode: "closest", bargap: 0.3 }}
        />
      </div>

      <SectionTitle hint="My sector return minus the sector ETF's return over the same period — positive means your picks beat just buying the sector.">
        Sector excess vs. ETF
      </SectionTitle>
      <div className="card p-3">
        <Chart
          height={Math.max(220, data.sectors.length * 30)}
          data={[
            {
              y: data.sectors.map((s) => s.sector).reverse(),
              x: data.sectors.map((s) => s.excess_return ?? 0).reverse(),
              type: "bar",
              orientation: "h",
              marker: {
                color: data.sectors
                  .map((s) => ((s.excess_return ?? 0) >= 0 ? "#0ca30c" : "#d03b3b"))
                  .reverse(),
              },
              customdata: data.sectors.map((s) => s.etf_ticker ?? "—").reverse() as never,
              hovertemplate: "%{y} vs %{customdata}: %{x:+.2%}<extra></extra>",
            },
          ]}
          layout={{ xaxis: { tickformat: "+.1%" }, hovermode: "closest", bargap: 0.3 }}
        />
      </div>
    </div>
  );
}
