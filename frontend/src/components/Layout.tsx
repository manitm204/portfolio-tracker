import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../api/client";
import { PORTFOLIO, useAppState } from "../state/AppState";
import { fmtDateTime, fmtDate, fmtSignedPct, signClass } from "../lib/format";

const PORTFOLIO_NAV = [
  { to: "/", label: "Overview", icon: "◧" },
  { to: "/performance", label: "Performance", icon: "◺" },
  { to: "/holdings", label: "Holdings", icon: "☰" },
  { to: "/heatmap", label: "Heatmaps", icon: "▦" },
  { to: "/risk", label: "Risk", icon: "◬" },
  { to: "/history", label: "History", icon: "◷" },
];

const DATA_NAV = [
  { to: "/transactions", label: "Transactions", icon: "⇄" },
  { to: "/data-quality", label: "Data Quality", icon: "✓" },
  { to: "/methodology", label: "Methodology", icon: "ℹ" },
];

function NavGroups({ onNavigate }: { onNavigate?: () => void }) {
  const sleeves = useQuery({ queryKey: ["sleeves"], queryFn: api.sleeves });
  const link = (to: string, label: React.ReactNode, end: boolean, key: string) => (
    <NavLink
      key={key}
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) =>
        clsx(
          "rounded-md px-3 py-2 text-sm",
          isActive ? "bg-[var(--grid)] font-semibold" : "text-[var(--text-secondary)] hover:bg-[var(--grid)]",
        )
      }
    >
      {label}
    </NavLink>
  );
  const heading = (text: string) => (
    <div className="mb-1 mt-4 px-3 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] first:mt-0">
      {text}
    </div>
  );
  const iconLabel = (icon: string, label: string) => (
    <>
      <span className="mr-2 opacity-60">{icon}</span>
      {label}
    </>
  );
  return (
    <nav className="flex flex-col gap-1">
      {heading("Portfolio")}
      {PORTFOLIO_NAV.map((n) => link(n.to, iconLabel(n.icon, n.label), n.to === "/", n.to))}
      {heading("Sleeves")}
      {(sleeves.data?.sleeves ?? []).map((s) =>
        link(
          `/sleeves/${s.number}`,
          <span className="flex items-center justify-between gap-2">
            <span>
              <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: `var(--sleeve-${s.number})` }} />
              {s.name}
            </span>
            {s.status === "active" ? (
              <span className={clsx("tabular text-xs", signClass(s.total?.pct))}>{fmtSignedPct(s.total?.pct, 1)}</span>
            ) : (
              <span className="text-[10px] text-[var(--text-muted)]">empty</span>
            )}
          </span>,
          false,
          s.id,
        ),
      )}
      {heading("Data")}
      {DATA_NAV.map((n) => link(n.to, iconLabel(n.icon, n.label), false, n.to))}
    </nav>
  );
}

export default function Layout() {
  const { dark, toggleTheme } = useAppState();
  const [menuOpen, setMenuOpen] = useState(false);
  const qc = useQueryClient();
  const summary = useQuery({
    queryKey: ["summary", PORTFOLIO],
    queryFn: () => api.summary(PORTFOLIO),
    refetchInterval: 5 * 60_000,
  });

  const refresh = useMutation({
    mutationFn: api.refresh,
    onSettled: () => qc.invalidateQueries(),
  });

  const fresh = summary.data?.freshness;
  const refreshState = refresh.isPending
    ? { label: "Refreshing…", cls: "text-[var(--text-muted)]" }
    : refresh.isError
      ? { label: "Refresh failed", cls: "text-[var(--neg)]" }
      : refresh.data && refresh.data.status === "partial"
        ? { label: `Partial: ${refresh.data.symbols_failed} failed`, cls: "text-[#c98500]" }
        : refresh.data
          ? { label: "Refreshed", cls: "text-[var(--pos-text)]" }
          : null;

  return (
    <div className="flex min-h-screen">
      {/* Sidebar (desktop) */}
      <aside className="hidden w-52 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-1)] p-4 md:flex">
        <div className="mb-6 text-lg font-bold">Portfolio<span className="text-[var(--series-portfolio)]">Tracker</span></div>
        <NavGroups />
        <div className="mt-auto pt-6 text-xs text-[var(--text-muted)]">
          {fresh && (
            <>
              <div>As of {fmtDate(fresh.as_of_date)}{fresh.as_of_provisional ? " (intraday)" : ""}</div>
              <div>Last refresh {fmtDateTime(fresh.last_refresh_at)}</div>
              <div>
                Coverage {fresh.symbols_ok}/{fresh.symbols_tracked}
                {fresh.symbol_errors.length > 0 && (
                  <span className="ml-1 text-[var(--neg)]" title={fresh.symbol_errors.map((e) => `${e.ticker}: ${e.error}`).join("\n")}>
                    ({fresh.symbol_errors.length} errors)
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-2">
          <button
            className="rounded-md border border-[var(--border)] px-2 py-1 text-sm md:hidden"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Menu"
          >
            ☰
          </button>
          <div className="ml-auto flex items-center gap-2">
            {refreshState && <span className={clsx("hidden text-xs sm:inline", refreshState.cls)}>{refreshState.label}</span>}
            {fresh?.as_of_provisional && (
              <span className="rounded-full border border-[#c98500] px-2 py-0.5 text-[10px] text-[#c98500]" title="Latest bar was fetched during the trading session and may change at the close.">
                intraday data
              </span>
            )}
            <button
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending}
              className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--grid)] disabled:opacity-50"
              title="Fetch latest market data now"
            >
              {refresh.isPending ? "⟳ Refreshing…" : "⟳ Refresh"}
            </button>
            <button
              onClick={toggleTheme}
              className="rounded-md border border-[var(--border)] px-2.5 py-1.5 text-sm hover:bg-[var(--grid)]"
              title="Toggle dark / light mode"
              aria-label="Toggle theme"
            >
              {dark ? "☀" : "☾"}
            </button>
          </div>
        </header>

        {/* Mobile nav drawer */}
        {menuOpen && (
          <div className="border-b border-[var(--border)] bg-[var(--surface-1)] p-3 md:hidden">
            <NavGroups onNavigate={() => setMenuOpen(false)} />
          </div>
        )}

        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
