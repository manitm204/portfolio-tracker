import { NavLink, Outlet, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../api/client";
import { EmptyState, ErrorState, Skeleton } from "../components/Primitives";
import { fmtDate, fmtMoney } from "../lib/format";
import SleevePending from "./SleevePending";

const TABS = [
  { to: "", label: "Overview" },
  { to: "stocks", label: "Stocks" },
  { to: "performance", label: "Performance" },
  { to: "risk", label: "Risk" },
  { to: "history", label: "History" },
  { to: "transactions", label: "Transactions" },
];

export default function SleeveLayout() {
  const { sleeve: number } = useParams();
  const q = useQuery({ queryKey: ["sleeves"], queryFn: api.sleeves });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState message={String((q.error as Error).message)} onRetry={() => q.refetch()} />;
  const sleeve = q.data!.sleeves.find((s) => String(s.number) === number);
  if (!sleeve) return <EmptyState message={`There is no sleeve ${number}.`} />;
  if (sleeve.status === "pending") return <SleevePending sleeve={sleeve} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-xl font-bold">
          <span className="mr-2 inline-block h-3 w-3 rounded-full" style={{ background: `var(--sleeve-${sleeve.number})` }} />
          {sleeve.name}
        </h1>
        <span className="text-sm text-[var(--text-muted)]">
          Funded {fmtDate(sleeve.start_date)} with {fmtMoney(sleeve.invested)}
          {(sleeve.cash ?? 0) >= 0.01 && ` · ${fmtMoney(sleeve.cash)} cash`}
        </span>
      </div>
      <nav className="flex gap-1 overflow-x-auto border-b border-[var(--border)]">
        {TABS.map((t) => (
          <NavLink
            key={t.label}
            to={t.to}
            end={t.to === ""}
            className={({ isActive }) =>
              clsx(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm",
                isActive
                  ? "border-[var(--series-portfolio)] font-semibold"
                  : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
