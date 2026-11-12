import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api, HistorySnapshot, Position } from "../api/client";
import { PORTFOLIO, useAccountId } from "../state/AppState";
import Chart, { SERIES } from "../components/Chart";
import { EmptyState, ErrorState, SectionTitle, Skeleton } from "../components/Primitives";
import { fmtDate, fmtMoney, fmtNum, fmtPct, fmtSignedMoney, fmtSignedPct, signClass } from "../lib/format";
import { GICS_SECTORS } from "../lib/sectors";

function PositionsTable({ rows, showSleeve }: { rows: Position[]; showSleeve: boolean }) {
  return (
    <div className="card table-scroll">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-right text-xs text-[var(--text-muted)]">
            <th className="p-2 text-left">Ticker</th>
            {showSleeve && <th className="p-2 text-left">Sleeve</th>}
            <th className="p-2 text-left">Opened</th>
            <th className="p-2 text-left">Closed</th>
            <th className="p-2">Held</th>
            <th className="p-2">Cost</th>
            <th className="p-2" title="Current value for open positions, sale proceeds for closed ones">Value</th>
            <th className="p-2">Gain $</th>
            <th className="p-2" title="Includes dividends received">Return</th>
            <th className="p-2" title="SPY's total return from the open on the buy date to the close on the end date">SPY</th>
            <th className="p-2" title="Position return minus SPY over the identical window">Excess vs SPY</th>
            <th className="p-2">Excess vs QQQ</th>
            <th className="p-2" title="Position return minus its sector ETF over the identical window">Excess vs sector</th>
            <th className="p-2" title="Annualized return. Blank when held under a week.">CAGR</th>
            <th className="p-2" title="Position CAGR minus SPY's CAGR over the identical window">CAGR vs SPY</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.account_id}-${r.ticker}-${r.open_date}`} className="border-t border-[var(--border)] text-right">
              <td className="p-2 text-left font-semibold">{r.ticker}</td>
              {showSleeve && <td className="whitespace-nowrap p-2 text-left text-xs text-[var(--text-secondary)]">{r.sleeve}</td>}
              <td className="whitespace-nowrap p-2 text-left text-[var(--text-secondary)]">{fmtDate(r.open_date)}</td>
              <td className="whitespace-nowrap p-2 text-left text-[var(--text-secondary)]">{r.close_date ? fmtDate(r.close_date) : "Open"}</td>
              <td className="p-2 tabular">{r.hold_days}d</td>
              <td className="p-2 tabular">{fmtMoney(r.total_cost)}</td>
              <td className="p-2 tabular">{fmtMoney(r.status === "open" ? r.market_value : r.total_proceeds)}</td>
              <td className={clsx("p-2 tabular", signClass(r.gain_dollar))}>{fmtSignedMoney(r.gain_dollar)}</td>
              <td className={clsx("p-2 tabular font-medium", signClass(r.total_return))}>{fmtSignedPct(r.total_return)}</td>
              <td className="p-2 tabular text-[var(--text-secondary)]">{fmtSignedPct(r.spy_return)}</td>
              <td className={clsx("p-2 tabular font-medium", signClass(r.excess_spy))}>{fmtSignedPct(r.excess_spy)}</td>
              <td className={clsx("p-2 tabular", signClass(r.excess_qqq))}>{fmtSignedPct(r.excess_qqq)}</td>
              <td className={clsx("whitespace-nowrap p-2 tabular", signClass(r.excess_sector))}>
                {fmtSignedPct(r.excess_sector)}
                {r.sector_etf && <span className="ml-1 text-[10px] text-[var(--text-muted)]">{r.sector_etf}</span>}
              </td>
              <td className={clsx("p-2 tabular", signClass(r.cagr))}>{fmtSignedPct(r.cagr)}</td>
              <td className={clsx("p-2 tabular", signClass(r.cagr_excess_spy))}>{fmtSignedPct(r.cagr_excess_spy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExcessChart({ rows }: { rows: Position[] }) {
  const scored = rows
    .filter((r) => r.excess_spy !== null)
    .sort((a, b) => (a.excess_spy ?? 0) - (b.excess_spy ?? 0));
  if (scored.length === 0) return null;
  const label = (r: Position) => (r.status === "open" ? r.ticker : `${r.ticker} (closed)`);
  return (
    <div className="card p-3">
      <Chart
        height={Math.max(200, scored.length * 26)}
        data={[
          {
            y: scored.map(label),
            x: scored.map((r) => r.excess_spy ?? 0),
            type: "bar",
            orientation: "h",
            marker: { color: scored.map((r) => ((r.excess_spy ?? 0) >= 0 ? SERIES.pos() : SERIES.neg())) },
            customdata: scored.map((r) => [r.total_return, r.spy_return, r.hold_days]) as never,
            hovertemplate: "%{y}: %{x:+.2%} vs SPY<br>position %{customdata[0]:+.2%} · SPY %{customdata[1]:+.2%} · %{customdata[2]}d<extra></extra>",
          },
        ]}
        layout={{ xaxis: { tickformat: "+.1%" }, hovermode: "closest", bargap: 0.3 }}
      />
    </div>
  );
}

const fieldClass = "rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1.5 text-sm";

function TradeForm({ accountId, holdings }: { accountId: string; holdings: string[] }) {
  const qc = useQueryClient();
  const [side, setSide] = useState<"SELL" | "BUY">("SELL");
  const [ticker, setTicker] = useState("");
  const [date, setDate] = useState("");
  const [price, setPrice] = useState("");
  const [amount, setAmount] = useState("");
  const [sector, setSector] = useState("");

  const trade = useMutation({
    mutationFn: () =>
      api.recordTrade(accountId, {
        side,
        ticker,
        trade_date: date,
        price: price ? Number(price) : undefined,
        dollars: side === "BUY" ? Number(amount) : undefined,
        shares: side === "SELL" && amount ? Number(amount) : undefined,
        sector: side === "BUY" && sector ? sector : undefined,
      }),
    onSuccess: () => {
      setTicker("");
      setPrice("");
      setAmount("");
      qc.invalidateQueries();
    },
  });

  return (
    <form
      className="card flex flex-wrap items-end gap-3 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        trade.mutate();
      }}
    >
      <label className="text-xs text-[var(--text-muted)]">
        <span className="mb-1 block">Action</span>
        <select value={side} onChange={(e) => setSide(e.target.value as "SELL" | "BUY")} className={fieldClass}>
          <option value="SELL">Sell</option>
          <option value="BUY">Buy</option>
        </select>
      </label>
      <label className="text-xs text-[var(--text-muted)]">
        <span className="mb-1 block">Ticker</span>
        {side === "SELL" ? (
          <select required value={ticker} onChange={(e) => setTicker(e.target.value)} className={fieldClass}>
            <option value="">Choose</option>
            {holdings.map((t) => <option key={t}>{t}</option>)}
          </select>
        ) : (
          <input required value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} className={`${fieldClass} w-24 uppercase`} />
        )}
      </label>
      <label className="text-xs text-[var(--text-muted)]">
        <span className="mb-1 block">Date</span>
        <input required type="date" value={date} onChange={(e) => setDate(e.target.value)} className={fieldClass} />
      </label>
      <label className="text-xs text-[var(--text-muted)]">
        <span className="mb-1 block">{side === "SELL" ? "Shares (blank = all)" : "Dollars"}</span>
        <input type="number" step="any" min="0" required={side === "BUY"} value={amount} onChange={(e) => setAmount(e.target.value)} className={`${fieldClass} w-32`} />
      </label>
      <label className="text-xs text-[var(--text-muted)]">
        <span className="mb-1 block">Price (blank = open)</span>
        <input type="number" step="any" min="0" value={price} onChange={(e) => setPrice(e.target.value)} className={`${fieldClass} w-32`} />
      </label>
      {side === "BUY" && (
        <label className="text-xs text-[var(--text-muted)]">
          <span className="mb-1 block">Sector</span>
          <select value={sector} onChange={(e) => setSector(e.target.value)} className={fieldClass}>
            <option value="">Look up automatically</option>
            {GICS_SECTORS.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
      )}
      <button
        type="submit"
        disabled={trade.isPending}
        className="rounded-md bg-[var(--series-portfolio)] px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        {trade.isPending ? "Recording…" : "Record trade"}
      </button>
      {trade.isError && <p className="w-full text-sm text-[var(--neg)]" role="alert">{(trade.error as Error).message}</p>}
      {trade.isSuccess && <p className="w-full text-sm text-[var(--text-secondary)]" role="status">Trade recorded.</p>}
    </form>
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
  const accountId = useAccountId();
  const q = useQuery({ queryKey: ["history", accountId], queryFn: () => api.history(accountId) });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;

  const events = q.data?.events ?? [];
  const open = q.data?.open_positions ?? [];
  const closed = q.data?.closed_positions ?? [];
  const isPortfolio = accountId === PORTFOLIO;
  if (open.length === 0 && closed.length === 0) {
    return <EmptyState message="No positions yet." />;
  }

  return (
    <div className="space-y-4">
      <SectionTitle hint="Each position's return minus SPY's return over exactly the same window, from the open on the day it was bought to its sale date (or the latest close if it's still open). Dividends count on both sides.">
        Excess return vs SPY
      </SectionTitle>
      <ExcessChart rows={[...open, ...closed]} />

      <SectionTitle hint="Positions you still hold, measured to the latest close.">Open positions</SectionTitle>
      {open.length > 0 ? (
        <PositionsTable rows={open} showSleeve={isPortfolio} />
      ) : (
        <div className="card p-6 text-sm text-[var(--text-muted)]">No open positions.</div>
      )}

      <SectionTitle hint="Positions fully sold. Buying the same ticker again later starts a new row.">Closed positions</SectionTitle>
      {closed.length > 0 ? (
        <PositionsTable rows={closed} showSleeve={isPortfolio} />
      ) : (
        <div className="card p-6 text-sm text-[var(--text-muted)]">Nothing closed yet. Positions move here once fully sold.</div>
      )}

      {!isPortfolio && (
        <>
          <SectionTitle hint="Sales stay in the sleeve as cash until you buy with it. With no price entered, the fill uses that day's official open.">
            Record a trade
          </SectionTitle>
          <TradeForm accountId={accountId} holdings={open.map((p) => p.ticker)} />
        </>
      )}

      {events.length > 0 && (
        <>
      <SectionTitle hint="Composition-change events: what was held before and after each rebalance, and how sector allocation shifted. Snapshots are captured at execution time using that day's official opening prices.">
        Rebalances
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
        </>
      )}
    </div>
  );
}
