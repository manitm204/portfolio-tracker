import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

interface AppState {
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
  const [dark, setDark] = useState(() => localStorage.getItem("theme") !== "light");
  const [range, setRange] = useState("SI");
  const [customStart, setCustomStart] = useState<string | null>(null);
  const [customEnd, setCustomEnd] = useState<string | null>(null);

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
      dark,
      toggleTheme,
      range,
      setRange,
      customStart,
      customEnd,
      setCustom,
    }),
    [dark, range, customStart, customEnd, toggleTheme, setCustom],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppState outside provider");
  return v;
}

export const PORTFOLIO = "combined";

/** The account a page shows: the sleeve in the URL, else the whole portfolio. */
export function useAccountId(): string {
  const { sleeve } = useParams();
  return sleeve ? `SLEEVE_${sleeve}` : PORTFOLIO;
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
