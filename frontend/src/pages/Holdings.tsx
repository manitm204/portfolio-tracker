import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, Holding } from "../api/client";
import { useAppState } from "../state/AppState";
import Chart, { SERIES, divergingScale, sectorTreemap } from "../components/Chart";
import { EmptyState, ErrorState, SectionTitle, Skeleton } from "../components/Primitives";
import { fmtMoney, fmtNum, fmtPct, fmtSignedPct, signClass } from "../lib/format";

type SortKey = keyof Holding;

const COLS: { key: SortKey; label: string; title?: string }[] = [
  { key: "ticker", label: "Ticker" },
  { key: "sector", label: "Sector" },
  { key: "composite_score", label: "Score", title: "Original model composite score (seed metadata, not market data)" },
  { key: "shares", label: "Shares" },
  { key: "avg_cost", label: "Avg cost" },
  { key: "price", label: "Price" },
  { key: "market_value", label: "Value" },
  { key: "weight", label: "Weight" },
  { key: "day_return", label: "Day" },
  { key: "unrealized_pct", label: "Total" },
  { key: "unrealized_dollar", label: "Gain $" },
  { key: "beta", label: "β", title: "Security's trailing 1-year beta vs SPY (own daily returns over the last ~252 trading days, needs enough history)" },
  { key: "beta_contribution", label: "β·w", title: "Weight × security beta — the labelled contribution view, separate from portfolio beta" },
];

export default function Holdings() {
  const { accountId } = useAppState();
  const holdings = useQuery({ queryKey: ["holdings", accountId], queryFn: () => api.holdings(accountId) });
  const allocation = useQuery({ queryKey: ["allocation", accountId], queryFn: () => api.allocation(accountId) });
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("market_value");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);

  const rows = useMemo(() => {
    const list = holdings.data?.holdings ?? [];
    const filtered = search
      ? list.filter((h) => h.ticker.toLowerCase().includes(search.toLowerCase()) || h.sector.toLowerCase().includes(search.toLowerCase()))
      : list;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string") return sortDir * av.localeCompare(bv as string);
      return sortDir * ((av as number) - (bv as number));
    });
  }, [holdings.data, search, sortKey, sortDir]);

  if (holdings.isLoading) return <div className="space-y-4"><Skeleton className="h-96" /></div>;
  if (holdings.isError) return <ErrorState message={String((holdings.error as Error).message)} onRetry={() => holdings.refetch()} />;
  const data = holdings.data!;
  if (data.holdings.length === 0) return <EmptyState message="No holdings — the account has no open positions." />;

  const a = allocation.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ticker or sector…"
          className="w-64 rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm"
        />
        <div className="text-xs text-[var(--text-muted)]">
          {rows.length} of {data.holdings.length} holdings
          {data.inactive.length > 0 && ` · ${data.inactive.length} inactive candidate (excluded from all statistics)`}
        </div>
      </div>

      <div className="card table-scroll max-h-[70vh] overflow-y-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-[var(--text-muted)]">
              {COLS.map((c) => (
                <th
                  key={c.key}
                  title={c.title}
                  onClick={() => {
                    if (sortKey === c.key) setSortDir((d) => (d === 1 ? -1 : 1));
                    else { setSortKey(c.key); setSortDir(-1); }
                  }}
                  className="cursor-pointer select-none whitespace-nowrap p-2 text-right first:text-left [&:nth-child(2)]:text-left hover:text-[var(--text-primary)]"
                >
                  {c.label}
                  {sortKey === c.key ? (sortDir === -1 ? " ↓" : " ↑") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={h.ticker} className="border-t border-[var(--border)]">
                <td className="p-2 font-semibold">
                  {h.ticker}
                  {h.price_stale && <span className="ml-1 text-[10px] text-[#c98500]" title={`Price forward-filled; last trade ${h.price_as_of ?? "unknown"}`}>stale</span>}
                </td>
                <td className="whitespace-nowrap p-2 text-[var(--text-secondary)]">{h.sector}</td>
                <td className="p-2 text-right tabular">{h.composite_score ?? "—"}</td>
                <td className="p-2 text-right tabular">{fmtNum(h.shares, h.shares < 10 ? 6 : 2)}</td>
                <td className="p-2 text-right tabular">{fmtMoney(h.avg_cost)}</td>
                <td className="p-2 text-right tabular">{fmtMoney(h.price)}</td>
                <td className="p-2 text-right tabular">{fmtMoney(h.market_value)}</td>
                <td className="p-2 text-right tabular">{fmtPct(h.weight)}</td>
                <td className={clsx("p-2 text-right tabular", signClass(h.day_return))}>{fmtSignedPct(h.day_return)}</td>
                <td className={clsx("p-2 text-right tabular", signClass(h.unrealized_pct))}>{fmtSignedPct(h.unrealized_pct)}</td>
                <td className={clsx("p-2 text-right tabular", signClass(h.unrealized_dollar))}>{fmtMoney(h.unrealized_dollar)}</td>
                <td className="p-2 text-right tabular">{h.beta !== null ? fmtNum(h.beta) : "—"}</td>
                <td className="p-2 text-right tabular">{h.beta_contribution !== null ? fmtNum(h.beta_contribution, 3) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {a && !a.empty && (
        <>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="card p-3">
              <SectionTitle hint="Share of current position value by sector (cash excluded).">Sector allocation</SectionTitle>
              <Chart
                height={300}
                data={[
                  {
                    labels: a.sector_allocation.map((s) => s.sector),
                    values: a.sector_allocation.map((s) => s.value),
                    type: "pie",
                    hole: 0.55,
                    textinfo: "label+percent",
                    textposition: "outside",
                    automargin: true,
                    marker: { line: { color: "var(--surface-1)", width: 2 } },
                    hovertemplate: "%{label}: %{value:$,.0f} (%{percent})<extra></extra>",
                  } as never,
                ]}
                layout={{ showlegend: false, hovermode: "closest", margin: { l: 16, r: 16, t: 8, b: 8 } }}
              />
            </div>
            <div className="card p-3">
              <SectionTitle hint="Tile area = current market value; color = today's return (zero-anchored green/red).">Holdings treemap</SectionTitle>
              <TreemapChart holdings={data.holdings} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="card p-3">
              <SectionTitle>Top holdings</SectionTitle>
              <Chart
                height={Math.max(240, a.top_holdings.length * 22)}
                data={[
                  {
                    y: a.top_holdings.map((t) => t.ticker).reverse(),
                    x: a.top_holdings.map((t) => t.weight).reverse(),
                    type: "bar",
                    orientation: "h",
                    marker: { color: SERIES.portfolio() },
                    hovertemplate: "%{y}: %{x:.2%}<extra></extra>",
                  },
                ]}
                layout={{ xaxis: { tickformat: ".0%" }, hovermode: "closest", bargap: 0.3 }}
              />
            </div>
            <div className="card p-3">
              <SectionTitle hint="Cumulative weight of the top N holdings, by rank.">Concentration curve</SectionTitle>
              <Chart
                height={300}
                data={[
                  {
                    x: a.concentration_curve.map((c) => c.rank),
                    y: a.concentration_curve.map((c) => c.cumulative),
                    type: "scatter",
                    mode: "lines",
                    line: { color: SERIES.portfolio(), width: 2 },
                    text: a.concentration_curve.map((c) => c.ticker),
                    hovertemplate: "top %{x} (%{text}): %{y:.1%}<extra></extra>",
                  },
                ]}
                layout={{ yaxis: { tickformat: ".0%", range: [0, 1.02] }, xaxis: { title: { text: "rank" } }, hovermode: "closest" }}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="card p-3">
              <SectionTitle hint="Original model target weight vs today's actual weight; bars show the drift.">Target vs current drift</SectionTitle>
              <DriftChart drift={a.drift} />
            </div>
            <div className="card p-3">
              <SectionTitle hint="weight_(t−1) × daily return, an arithmetic attribution. Cumulative = sum of daily contributions since inception (approximation of the geometric link), restricted to positions still held today — a fully closed-out position no longer appears, even though it contributed while held.">
                Return contribution
              </SectionTitle>
              <ContributionChart contribution={a.contribution} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function TreemapChart({ holdings }: { holdings: Holding[] }) {
  const maxAbs = Math.max(...holdings.map((h) => Math.abs(h.day_return ?? 0)), 0.005);
  const t = sectorTreemap(
    holdings.map((h) => ({
      ticker: h.ticker,
      sector: h.sector,
      size: h.market_value,
      ret: h.day_return,
      hoverValue: h.market_value,
    })),
  );
  return (
    <Chart
      height={380}
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
          },
          customdata: t.customdata as never,
          hovertemplate: "%{label}: %{customdata[1]:$,.2f} · day %{text}<extra></extra>",
        } as never,
      ]}
      layout={{ hovermode: "closest", margin: { l: 4, r: 4, t: 4, b: 4 } }}
    />
  );
}

function DriftChart({ drift }: { drift: { ticker: string; current: number; target: number; drift: number }[] }) {
  const top = drift.slice(0, 25);
  return (
    <Chart
      height={Math.max(280, top.length * 20)}
      data={[
        {
          y: top.map((d) => d.ticker).reverse(),
          x: top.map((d) => d.drift).reverse(),
          type: "bar",
          orientation: "h",
          marker: { color: top.map((d) => (d.drift >= 0 ? SERIES.pos() : SERIES.neg())).reverse() },
          customdata: top.map((d) => [d.target, d.current]).reverse() as never,
          hovertemplate: "%{y}: drift %{x:+.2%} (target %{customdata[0]:.2%} → now %{customdata[1]:.2%})<extra></extra>",
        },
      ]}
      layout={{ xaxis: { tickformat: "+.1%" }, hovermode: "closest", bargap: 0.3 }}
    />
  );
}

function ContributionChart({
  contribution,
}: {
  contribution: {
    daily: { ticker: string; contribution: number }[];
    cumulative: { ticker: string; contribution: number }[];
  };
}) {
  const [mode, setMode] = useState<"daily" | "cumulative">("daily");
  const rows = (mode === "daily" ? contribution.daily : contribution.cumulative).slice(0, 20);
  return (
    <div>
      <div className="mb-2 flex gap-1">
        {(["daily", "cumulative"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} className={clsx("rounded-md border border-[var(--border)] px-3 py-1 text-xs", mode === m ? "bg-[var(--series-portfolio)] text-white" : "text-[var(--text-secondary)]")}>
            {m}
          </button>
        ))}
      </div>
      <Chart
        height={Math.max(260, rows.length * 20)}
        data={[
          {
            y: rows.map((r) => r.ticker).reverse(),
            x: rows.map((r) => r.contribution).reverse(),
            type: "bar",
            orientation: "h",
            marker: { color: rows.map((r) => (r.contribution >= 0 ? SERIES.pos() : SERIES.neg())).reverse() },
            hovertemplate: "%{y}: %{x:+.3%}<extra></extra>",
          },
        ]}
        layout={{ xaxis: { tickformat: "+.2%" }, hovermode: "closest", bargap: 0.3 }}
      />
    </div>
  );
}
