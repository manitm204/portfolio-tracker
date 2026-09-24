import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, ClosedPosition, HistorySnapshot } from "../api/client";
import { useAppState } from "../state/AppState";
import { EmptyState, ErrorState, SectionTitle, Skeleton } from "../components/Primitives";
import { fmtDate, fmtMoney, fmtNum, fmtPct, fmtSignedMoney, fmtSignedPct, signClass } from "../lib/format";

function ClosedPositionsTable({ rows }: { rows: ClosedPosition[] }) {
  if (rows.length === 0) {
    return <div className="card p-6 text-sm text-[var(--text-muted)]">No fully closed positions yet — nothing has been sold out completely.</div>;
  }
  return (
    <div className="card table-scroll">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-[var(--text-muted)]">
            <th className="p-2">Ticker</th>
            <th className="p-2">Opened</th>
            <th className="p-2">Closed</th>
            <th className="p-2 text-right">Held</th>
            <th className="p-2 text-right">Cost</th>
            <th className="p-2 text-right">Proceeds</th>
            <th className="p-2 text-right">Gain $</th>
            <th className="p-2 text-right">Gain %</th>
            <th className="p-2 text-right">CAGR</th>
            <th className="p-2 text-right">CAGR vs SPY</th>
            <th className="p-2 text-right">CAGR vs QQQ</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.ticker}-${r.close_date}-${i}`} className="border-t border-[var(--border)]">
              <td className="p-2 font-semibold">{r.ticker}</td>
              <td className="p-2 text-[var(--text-secondary)]">{fmtDate(r.open_date)}</td>
              <td className="p-2 text-[var(--text-secondary)]">{fmtDate(r.close_date)}</td>
              <td className="p-2 text-right tabular">{r.hold_days}d</td>
              <td className="p-2 text-right tabular">{fmtMoney(r.total_cost)}</td>
              <td className="p-2 text-right tabular">{fmtMoney(r.total_proceeds)}</td>
              <td className={clsx("p-2 text-right tabular", signClass(r.gain_dollar))}>{fmtSignedMoney(r.gain_dollar)}</td>
              <td className={clsx("p-2 text-right tabular", signClass(r.gain_pct))}>{fmtSignedPct(r.gain_pct)}</td>
              <td className={clsx("p-2 text-right tabular", signClass(r.cagr))}>{r.cagr !== null ? fmtSignedPct(r.cagr) : "—"}</td>
              <td className={clsx("p-2 text-right tabular", signClass(r.cagr_excess_spy))}>{r.cagr_excess_spy !== null ? fmtSignedPct(r.cagr_excess_spy) : "—"}</td>
              <td className={clsx("p-2 text-right tabular", signClass(r.cagr_excess_qqq))}>{r.cagr_excess_qqq !== null ? fmtSignedPct(r.cagr_excess_qqq) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectorBar({ label, snapshot }: { label: string; snapshot: HistorySnapshot }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-xs font-medium text-[var(--text-muted)]">{label}</div>
      <div className="flex h-6 w-full overflow-hidden rounded-md border border-[var(--border)]">
        {snapshot.sector_allocation.map((s, i) => (
          <div
            key={s.sector}
            className="flex min-w-0 items-center justify-center overflow-hidden whitespace-nowrap text-[10px] text-white"
            style={{
              width: `${s.weight * 100}%`,
              background: `hsl(${(i * 57) % 360} 55% 42%)`,
            }}
            title={`${s.sector}: ${fmtPct(s.weight)}`}
          >
            {s.weight > 0.08 ? s.sector : ""}
          </div>
        ))}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--text-secondary)]">
        {snapshot.sector_allocation.map((s) => (
          <span key={s.sector}>
            {s.sector} <span className="tabular text-[var(--text-muted)]">{fmtPct(s.weight, 1)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function HoldingsTable({ label, snapshot }: { label: string; snapshot: HistorySnapshot }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-xs font-medium text-[var(--text-muted)]">{label}</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[320px] text-xs">
          <thead>
            <tr className="text-left text-[var(--text-muted)]">
              <th className="py-1">Ticker</th>
              <th className="py-1">Sector</th>
              <th className="py-1 text-right">Shares</th>
              <th className="py-1 text-right">Value</th>
              <th className="py-1 text-right">Weight</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.holdings.map((h) => (
              <tr key={h.ticker} className="border-t border-[var(--border)]">
                <td className="py-1 font-medium">{h.ticker}</td>
                <td className="py-1 text-[var(--text-secondary)]">{h.sector}</td>
                <td className="py-1 text-right tabular">{fmtNum(h.shares, 6)}</td>
                <td className="py-1 text-right tabular">{fmtMoney(h.value)}</td>
                <td className="py-1 text-right tabular">{fmtPct(h.weight, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-1 text-[11px] text-[var(--text-muted)]">
        Cash {fmtMoney(snapshot.cash)} · Total {fmtMoney(snapshot.total_value)}
      </div>
    </div>
  );
}

export default function History() {
  const { accountId } = useAppState();
  const q = useQuery({ queryKey: ["history", accountId], queryFn: () => api.history(accountId) });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;

  const events = q.data?.events ?? [];
  const closedPositions = q.data?.closed_positions ?? [];
  if (events.length === 0 && closedPositions.length === 0) {
    return <EmptyState message="No composition changes recorded for this account yet." />;
  }

  return (
    <div className="space-y-6">
      <SectionTitle hint="Positions that were bought and then fully sold out (0 shares remaining). Gain % and CAGR are computed on the total cost invested and proceeds received across the whole holding episode; re-buying the same ticker later starts a new episode.">
        Closed positions
      </SectionTitle>
      <ClosedPositionsTable rows={closedPositions} />

      <SectionTitle hint="Composition-change events: what was held before and after each rebalance, and how sector allocation shifted. Snapshots are captured at execution time using that day's official opening prices.">
        Portfolio History
      </SectionTitle>
      {events.map((e) => {
        const before = new Set(e.before.holdings.map((h) => h.ticker));
        const after = new Set(e.after.holdings.map((h) => h.ticker));
        const added = [...after].filter((t) => !before.has(t));
        const removed = [...before].filter((t) => !after.has(t));
        return (
          <div key={e.id} className="card p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="text-sm font-semibold">{fmtDate(e.event_date)}</div>
              <div className="flex gap-1 text-xs">
                {removed.map((t) => (
                  <span key={t} className="rounded bg-[rgba(208,59,59,0.12)] px-1.5 py-0.5 text-[var(--neg)]">
                    − {t}
                  </span>
                ))}
                {added.map((t) => (
                  <span key={t} className={clsx("rounded bg-[rgba(42,120,214,0.12)] px-1.5 py-0.5", "text-[var(--pos-text)]")}>
                    + {t}
                  </span>
                ))}
              </div>
            </div>
            {e.notes && <div className="mt-1 text-xs text-[var(--text-secondary)]">{e.notes}</div>}

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <SectorBar label="Sector allocation — before" snapshot={e.before} />
              <SectorBar label="Sector allocation — after" snapshot={e.after} />
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <HoldingsTable label="Holdings — before" snapshot={e.before} />
              <HoldingsTable label="Holdings — after" snapshot={e.after} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
