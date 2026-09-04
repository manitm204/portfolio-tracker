// Theme-aware Plotly wrapper: recessive grid, thin marks, unified hover.
import { useMemo } from "react";
import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import { useAppState } from "../state/AppState";

const Plot = createPlotlyComponent(Plotly as never);

export const SERIES = {
  portfolio: () => cssVar("--series-portfolio"),
  spy: () => cssVar("--series-spy"),
  qqq: () => cssVar("--series-qqq"),
  pos: () => cssVar("--pos"),
  neg: () => cssVar("--neg"),
  neutral: () => cssVar("--neutral-mid"),
};

/** Zero-anchored red→neutral→green diverging scale (green/red reserved for returns). */
export function divergingScale(): Array<[number, string]> {
  return [
    [0, SERIES.neg()],
    [0.5, SERIES.neutral()],
    [1, SERIES.pos()],
  ];
}

/**
 * Build sector-grouped treemap arrays. Plotly requires every parent to exist
 * as a node, so sector nodes (parent = root) are prepended with value 0 and
 * a neutral color; leaf tiles carry the weights/returns.
 */
export function sectorTreemap(
  tiles: { ticker: string; sector: string; size: number; ret: number | null; hoverValue?: number }[],
): {
  labels: string[];
  parents: string[];
  values: number[];
  colors: number[];
  text: string[];
  customdata: [number, number][];
} {
  const sectors = [...new Set(tiles.map((t) => t.sector))];
  const labels = [...sectors, ...tiles.map((t) => t.ticker)];
  const parents = [...sectors.map(() => ""), ...tiles.map((t) => t.sector)];
  const values = [...sectors.map(() => 0), ...tiles.map((t) => t.size)];
  const colors = [...sectors.map(() => 0), ...tiles.map((t) => t.ret ?? 0)];
  const text = [
    ...sectors.map(() => ""),
    ...tiles.map((t) => (t.ret !== null ? `${(t.ret * 100).toFixed(2)}%` : "n/a")),
  ];
  const customdata: [number, number][] = [
    ...sectors.map(() => [0, 0] as [number, number]),
    ...tiles.map((t) => [t.size, t.hoverValue ?? 0] as [number, number]),
  ];
  return { labels, parents, values, colors, text, customdata };
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#2a78d6";
}

export function useBaseLayout(): Partial<Plotly.Layout> {
  const { dark } = useAppState();
  return useMemo(() => {
    const grid = cssVar("--grid");
    const ink = cssVar("--text-secondary");
    const muted = cssVar("--text-muted");
    const surface = cssVar("--surface-1");
    return {
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "system-ui, -apple-system, 'Segoe UI', sans-serif", size: 12, color: ink },
      margin: { l: 56, r: 16, t: 8, b: 40 },
      hovermode: "x unified" as const,
      hoverlabel: { bgcolor: surface, bordercolor: grid, font: { color: ink, size: 12 } },
      xaxis: {
        gridcolor: grid,
        zerolinecolor: grid,
        linecolor: grid,
        tickfont: { color: muted, size: 11 },
        automargin: true,
      },
      yaxis: {
        gridcolor: grid,
        zerolinecolor: grid,
        linecolor: grid,
        tickfont: { color: muted, size: 11 },
        automargin: true,
      },
      legend: {
        orientation: "h" as const,
        y: 1.08,
        x: 0,
        font: { color: ink, size: 12 },
      },
      // dark is a dependency so the layout recomputes on theme change
      _theme: dark ? "dark" : "light",
    } as Partial<Plotly.Layout>;
  }, [dark]);
}

export default function Chart({
  data,
  layout,
  height = 320,
  config,
}: {
  data: Plotly.Data[];
  layout?: Partial<Plotly.Layout>;
  height?: number;
  config?: Partial<Plotly.Config>;
}) {
  const base = useBaseLayout();
  const merged = useMemo(() => {
    // Prevent sub-day ticks on short date ranges (e.g. "00:00 / 12:00" labels
    // when only a few daily bars exist).
    let dateTicks: Partial<Plotly.LayoutAxis> = {};
    const xs = (data.find((d) => Array.isArray((d as any).x)) as any)?.x as unknown[] | undefined;
    if (xs && xs.length > 0 && typeof xs[0] === "string" && /^\d{4}-\d{2}-\d{2}/.test(xs[0] as string)) {
      const spanDays =
        (new Date(String(xs[xs.length - 1])).getTime() - new Date(String(xs[0])).getTime()) / 86_400_000;
      if (spanDays <= 45) dateTicks = { dtick: 86_400_000, tickformat: "%b %d" };
    }
    return {
      ...base,
      ...layout,
      xaxis: { ...base.xaxis, ...dateTicks, ...(layout as any)?.xaxis },
      yaxis: { ...base.yaxis, ...(layout as any)?.yaxis },
    };
  }, [base, layout, data]);
  return (
    <Plot
      data={data}
      layout={merged as Plotly.Layout}
      config={{ displayModeBar: false, responsive: true, ...config }}
      style={{ width: "100%", height }}
      useResizeHandler
    />
  );
}
