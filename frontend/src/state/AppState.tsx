import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

interface AppState {
  accountId: string;
  setAccountId: (id: string) => void;
  dark: boolean;
  toggleTheme: () => void;
  range: string; // SI | YTD | 1M | 3M | 6M | 1Y | custom
  setRange: (r: string) => void;
  customStart: string | null;
  customEnd: string | null;
  setCustom: (start: string | null, end: string | null) => void;
}

const Ctx = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [accountId, setAccountId] = useState(
    () => localStorage.getItem("accountId") ?? "PORTFOLIO_125",
  );
  const [dark, setDark] = useState(() => localStorage.getItem("theme") !== "light");
  const [range, setRange] = useState("SI");
  const [customStart, setCustomStart] = useState<string | null>(null);
  const [customEnd, setCustomEnd] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem("accountId", accountId);
  }, [accountId]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);

  const toggleTheme = useCallback(() => setDark((d) => !d), []);
  const setCustom = useCallback((s: string | null, e: string | null) => {
    setCustomStart(s);
    setCustomEnd(e);
  }, []);

  const value = useMemo(
    () => ({
      accountId,
      setAccountId,
      dark,
      toggleTheme,
      range,
      setRange,
      customStart,
      customEnd,
      setCustom,
    }),
    [accountId, dark, range, customStart, customEnd, toggleTheme, setCustom],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppState outside provider");
  return v;
}

/** Translate the selected range into a start date (ISO) or undefined for SI. */
export function rangeToStart(range: string, customStart: string | null): string | undefined {
  const now = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  switch (range) {
    case "YTD":
      return `${now.getFullYear()}-01-01`;
    case "1M": {
      const d = new Date(now);
      d.setMonth(d.getMonth() - 1);
      return iso(d);
    }
    case "3M": {
      const d = new Date(now);
      d.setMonth(d.getMonth() - 3);
      return iso(d);
    }
    case "6M": {
      const d = new Date(now);
      d.setMonth(d.getMonth() - 6);
      return iso(d);
    }
    case "1Y": {
      const d = new Date(now);
      d.setFullYear(d.getFullYear() - 1);
      return iso(d);
    }
    case "custom":
      return customStart ?? undefined;
    default:
      return undefined; // SI
  }
}
