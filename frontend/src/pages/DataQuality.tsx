import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../api/client";
import { EmptyState, ErrorState, SectionTitle, Skeleton } from "../components/Primitives";
import { fmtDateTime } from "../lib/format";

export default function DataQuality() {
  const q = useQuery({ queryKey: ["data-quality"], queryFn: api.dataQuality });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;
  const d = q.data!;

  return (
    <div className="space-y-4">
      <div className="text-sm text-[var(--text-secondary)]">{d.symbols} symbols tracked (holdings + benchmarks).</div>

      <SectionTitle>Issues</SectionTitle>
      {d.issues.length === 0 ? (
        <div className="card p-4 text-sm text-[var(--pos-text)]">✓ No issues detected — prices complete, no duplicates, no negative holdings, accounts reconcile.</div>
      ) : (
        <div className="card table-scroll">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-muted)]">
                <th className="p-2">Type</th><th className="p-2">Ticker</th><th className="p-2">Detail</th>
              </tr>
            </thead>
            <tbody>
              {d.issues.map((i, idx) => (
                <tr key={idx} className="border-t border-[var(--border)]">
                  <td className="p-2 font-medium text-[var(--neg)]">{i.type}</td>
                  <td className="p-2">{i.ticker ?? "—"}</td>
                  <td className="p-2 text-[var(--text-secondary)]">{i.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SectionTitle>Stale / failed symbols</SectionTitle>
      {d.stale_symbols.length === 0 ? (
        <div className="card p-4 text-sm text-[var(--pos-text)]">✓ All symbols synced.</div>
      ) : (
        <div className="card table-scroll">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-muted)]">
                <th className="p-2">Ticker</th><th className="p-2">Status</th><th className="p-2">Last success</th><th className="p-2">Error</th>
              </tr>
            </thead>
            <tbody>
              {d.stale_symbols.map((s) => (
                <tr key={s.ticker} className="border-t border-[var(--border)]">
                  <td className="p-2 font-medium">{s.ticker}</td>
                  <td className="p-2 text-[var(--neg)]">{s.status}</td>
                  <td className="p-2 tabular">{s.last_success_date ?? "never"}</td>
                  <td className="max-w-[360px] truncate p-2 text-xs text-[var(--text-muted)]" title={s.error ?? undefined}>{s.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SectionTitle>Refresh history</SectionTitle>
      {d.refresh_runs.length === 0 ? (
        <EmptyState message="No refresh runs recorded yet." />
      ) : (
        <div className="card table-scroll">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-muted)]">
                <th className="p-2">#</th><th className="p-2">Trigger</th><th className="p-2">Status</th>
                <th className="p-2">Started</th><th className="p-2">Finished</th>
                <th className="p-2 text-right">OK</th><th className="p-2 text-right">Failed</th><th className="p-2">Detail</th>
              </tr>
            </thead>
            <tbody>
              {d.refresh_runs.map((r) => (
                <tr key={r.id} className="border-t border-[var(--border)]">
                  <td className="p-2 tabular">{r.id}</td>
                  <td className="p-2">{r.trigger}</td>
                  <td className={clsx("p-2 font-medium", r.status === "success" ? "text-[var(--pos-text)]" : r.status === "partial" ? "text-[#c98500]" : "text-[var(--neg)]")}>{r.status}</td>
                  <td className="p-2 tabular text-xs">{fmtDateTime(r.started_at)}</td>
                  <td className="p-2 tabular text-xs">{fmtDateTime(r.finished_at)}</td>
                  <td className="p-2 text-right tabular">{r.symbols_ok}</td>
                  <td className="p-2 text-right tabular">{r.symbols_failed}</td>
                  <td className="max-w-[280px] truncate p-2 text-xs text-[var(--text-muted)]" title={r.detail ?? undefined}>{r.detail ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
