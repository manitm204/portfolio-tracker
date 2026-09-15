import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../api/client";
import { useAppState } from "../state/AppState";
import { fmtDateTime, fmtDate } from "../lib/format";

const NAV = [
  { to: "/", label: "Overview", icon: "◧" },
  { to: "/performance", label: "Performance", icon: "◺" },
  { to: "/holdings", label: "Holdings", icon: "☰" },
  { to: "/heatmap", label: "Heatmap", icon: "▦" },
  { to: "/risk", label: "Risk", icon: "◬" },
  { to: "/transactions", label: "Transactions", icon: "⇄" },
  { to: "/history", label: "History", icon: "◷" },
  { to: "/data-quality", label: "Data Quality", icon: "✓" },
  { to: "/methodology", label: "Methodology", icon: "ℹ" },
];

export default function Layout() {
  const { accountId, dark, toggleTheme } = useAppState();
  const [menuOpen, setMenuOpen] = useState(false);
  const qc = useQueryClient();
  const summary = useQuery({
    queryKey: ["summary", accountId],
    queryFn: () => api.summary(accountId),
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
        <nav className="flex flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                clsx(
                  "rounded-md px-3 py-2 text-sm",
                  isActive
                    ? "bg-[var(--grid)] font-semibold"
                    : "text-[var(--text-secondary)] hover:bg-[var(--grid)]",
                )
              }
            >
              <span className="mr-2 opacity-60">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
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
          <nav className="flex flex-col gap-1 border-b border-[var(--border)] bg-[var(--surface-1)] p-3 md:hidden">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  clsx("rounded-md px-3 py-2 text-sm", isActive ? "bg-[var(--grid)] font-semibold" : "text-[var(--text-secondary)]")
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
        )}

        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
