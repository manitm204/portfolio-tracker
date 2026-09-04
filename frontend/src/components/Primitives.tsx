import clsx from "clsx";
import { signClass } from "../lib/format";

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className ?? "h-24 w-full")} />;
}

export function SkeletonTiles({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="h-24" />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card p-6 text-center">
      <p className="text-sm font-medium text-[var(--neg)]">⚠ {message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--grid)]"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="card p-8 text-center text-sm text-[var(--text-muted)]">{message}</div>
  );
}

export function InsufficientHistory({ label, needed, have }: { label: string; needed?: number; have?: number }) {
  return (
    <span
      className="text-[var(--text-muted)]"
      title={
        needed !== undefined
          ? `${label}: needs ≥ ${needed} daily observations (have ${have ?? 0})`
          : label
      }
    >
      insufficient history
    </span>
  );
}

export function StatTile({
  label,
  value,
  sub,
  signed,
  title,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  /** numeric value used only to pick the green/red ink for returns */
  signed?: number | null;
  title?: string;
}) {
  return (
    <div className="card p-4" title={title}>
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
        {label}
      </div>
      <div className={clsx("mt-1 text-xl font-semibold tabular", signClass(signed))}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-[var(--text-secondary)]">{sub}</div>}
    </div>
  );
}

export function SectionTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <h2 className="mb-2 mt-6 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
      {children}
      {hint && (
        <span
          title={hint}
          className="cursor-help rounded-full border border-[var(--border)] px-1.5 text-[10px] font-normal normal-case text-[var(--text-muted)]"
        >
          ?
        </span>
      )}
    </h2>
  );
}
