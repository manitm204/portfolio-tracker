import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api, Txn } from "../api/client";
import { useAppState } from "../state/AppState";
import { EmptyState, ErrorState, Skeleton } from "../components/Primitives";
import { fmtDate, fmtMoney, fmtNum, signClass } from "../lib/format";

const TYPES = ["ALL", "BUY", "SELL", "DIVIDEND", "DEPOSIT", "WITHDRAWAL", "FEE", "SPLIT", "SYMBOL_CHANGE"];

export default function Transactions() {
  const { accountId } = useAppState();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["transactions", accountId], queryFn: () => api.transactions(accountId) });
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("ALL");
  const fileRef = useRef<HTMLInputElement>(null);
  const [importMsg, setImportMsg] = useState<string | null>(null);

  const importMut = useMutation({
    mutationFn: (file: File) => api.importTransactions(accountId, file),
    onSuccess: (res) => {
      setImportMsg(
        res.committed
          ? `Imported ${res.created} rows (${res.skipped} duplicates skipped).`
          : `Rejected: ${res.errors.slice(0, 3).join("; ")}${res.errors.length > 3 ? "…" : ""}`,
      );
      qc.invalidateQueries();
    },
    onError: (e) => setImportMsg(`Import failed: ${(e as Error).message}`),
  });

  const rows = useMemo(() => {
    let list = q.data?.transactions ?? [];
    if (typeFilter !== "ALL") list = list.filter((t) => t.type === typeFilter);
    if (search) {
      const s = search.toLowerCase();
      list = list.filter(
        (t) =>
          (t.ticker ?? "").toLowerCase().includes(s) ||
          t.type.toLowerCase().includes(s) ||
          (t.notes ?? "").toLowerCase().includes(s) ||
          t.trade_date.includes(s),
      );
    }
    return list;
  }, [q.data, search, typeFilter]);

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ticker, type, date, notes…"
          className="w-64 rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1.5 text-sm"
        >
          {TYPES.map((t) => (<option key={t}>{t}</option>))}
        </select>
        <div className="ml-auto flex items-center gap-2">
          <a
            href={api.exportUrl(accountId)}
            download
            className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--grid)]"
          >
            ⤓ Export CSV
          </a>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={importMut.isPending}
            className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--grid)] disabled:opacity-50"
            title="Import a CSV using the canonical transaction schema. Future buys/sells/deposits need only a CSV row — no code changes."
          >
            {importMut.isPending ? "Importing…" : "⤒ Import CSV"}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importMut.mutate(f);
              e.target.value = "";
            }}
          />
        </div>
      </div>
      {importMsg && (
        <div className="card px-3 py-2 text-sm" role="status">
          {importMsg}
          <button className="ml-2 text-xs text-[var(--text-muted)]" onClick={() => setImportMsg(null)}>✕</button>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState message="No transactions match." />
      ) : (
        <div className="card table-scroll max-h-[75vh] overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-muted)]">
                <th className="p-2">Date</th>
                <th className="p-2">Account</th>
                <th className="p-2">Type</th>
                <th className="p-2">Ticker</th>
                <th className="p-2 text-right">Shares</th>
                <th className="p-2 text-right">Price</th>
                <th className="p-2 text-right">Fees</th>
                <th className="p-2 text-right">Cash flow</th>
                <th className="p-2">Source</th>
                <th className="p-2">Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t: Txn) => (
                <tr key={t.id} className="border-t border-[var(--border)]">
                  <td className="whitespace-nowrap p-2 tabular">{fmtDate(t.trade_date)}</td>
                  <td className="p-2 text-xs text-[var(--text-secondary)]">{t.account_id}</td>
                  <td className="p-2">
                    <span className={clsx("rounded px-1.5 py-0.5 text-xs font-medium", t.type === "BUY" ? "bg-[rgba(42,120,214,0.12)]" : t.type === "SELL" ? "bg-[rgba(208,59,59,0.12)]" : "bg-[var(--grid)]")}>
                      {t.type}
                    </span>
                  </td>
                  <td className="p-2 font-medium">
                    {t.ticker ?? "—"}
                    {t.type === "SYMBOL_CHANGE" && t.new_ticker ? ` → ${t.new_ticker}` : ""}
                    {t.type === "SPLIT" && t.split_ratio ? ` (${fmtNum(t.split_ratio, 2)}×)` : ""}
                  </td>
                  <td className="p-2 text-right tabular">{t.shares !== null ? fmtNum(t.shares, t.shares < 10 ? 6 : 2) : "—"}</td>
                  <td className="p-2 text-right tabular">{fmtMoney(t.price)}</td>
                  <td className="p-2 text-right tabular">{t.fees ? fmtMoney(t.fees) : "—"}</td>
                  <td className={clsx("p-2 text-right tabular", signClass(t.cash_flow))}>{t.cash_flow !== null ? fmtMoney(t.cash_flow) : "—"}</td>
                  <td className="p-2 text-xs text-[var(--text-muted)]">{t.source}</td>
                  <td className="max-w-[240px] truncate p-2 text-xs text-[var(--text-muted)]" title={t.notes ?? undefined}>{t.notes ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
