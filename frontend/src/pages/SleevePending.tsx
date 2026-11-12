import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Sleeve } from "../api/client";
import { fmtMoney } from "../lib/format";
import { GICS_SECTORS } from "../lib/sectors";

const MIN = 4;
const MAX = 6;
const input = "rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1.5 text-sm";

export default function SleevePending({ sleeve }: { sleeve: Sleeve }) {
  const qc = useQueryClient();
  const [date, setDate] = useState("");
  const [rows, setRows] = useState(() => Array.from({ length: MIN }, () => ({ ticker: "", sector: "" })));
  const filled = rows.filter((r) => r.ticker.trim());

  const populate = useMutation({
    mutationFn: () =>
      api.populateSleeve(
        sleeve.id,
        date,
        filled.map((r) => ({ ticker: r.ticker.trim(), sector: r.sector || undefined })),
      ),
    onSuccess: () => qc.invalidateQueries(),
  });

  const update = (i: number, patch: Partial<{ ticker: string; sector: string }>) =>
    setRows((list) => list.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const perStock = filled.length ? sleeve.capital / filled.length : null;
  const ready = date && filled.length >= MIN && filled.length <= MAX;

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <h1 className="text-xl font-bold">{sleeve.name}</h1>
      <div className="card p-5">
        <p className="text-sm text-[var(--text-secondary)]">
          This sleeve is empty. Enter {MIN} to {MAX} stocks and the day you bought them. Its {fmtMoney(sleeve.capital)} is
          split equally, each filled at that day's opening price.
        </p>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            populate.mutate();
          }}
        >
          <label className="block text-sm">
            <span className="mb-1 block text-xs text-[var(--text-muted)]">Purchase date</span>
            <input type="date" required value={date} onChange={(e) => setDate(e.target.value)} className={input} />
          </label>
          <div className="space-y-2">
            <div className="text-xs text-[var(--text-muted)]">Stocks</div>
            {rows.map((r, i) => (
              <div key={i} className="flex gap-2">
                <input
                  aria-label={`Ticker ${i + 1}`}
                  value={r.ticker}
                  onChange={(e) => update(i, { ticker: e.target.value.toUpperCase() })}
                  placeholder="Ticker"
                  className={`${input} w-28 uppercase`}
                />
                <select
                  aria-label={`Sector ${i + 1}`}
                  value={r.sector}
                  onChange={(e) => update(i, { sector: e.target.value })}
                  className={`${input} min-w-0 flex-1`}
                >
                  <option value="">Sector: look up automatically</option>
                  {GICS_SECTORS.map((s) => <option key={s}>{s}</option>)}
                </select>
              </div>
            ))}
            {rows.length < MAX && (
              <button
                type="button"
                onClick={() => setRows((list) => [...list, { ticker: "", sector: "" }])}
                className="text-xs text-[var(--text-secondary)] underline"
              >
                Add another stock
              </button>
            )}
          </div>
          {populate.isError && (
            <p className="text-sm text-[var(--neg)]" role="alert">{(populate.error as Error).message}</p>
          )}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={!ready || populate.isPending}
              className="rounded-md bg-[var(--series-portfolio)] px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              {populate.isPending ? "Funding…" : `Fund ${sleeve.name}`}
            </button>
            {perStock !== null && (
              <span className="text-xs text-[var(--text-muted)]">{fmtMoney(perStock)} per stock</span>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
