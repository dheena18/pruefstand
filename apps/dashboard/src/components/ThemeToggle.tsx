"use client";

import { useEffect, useState } from "react";

import { t, type Locale } from "@/lib/i18n";

export type ThemeMode = "system" | "light" | "dark";
const ORDER: readonly ThemeMode[] = ["system", "light", "dark"];
const KEY = "pruefstand.theme";

export function nextMode(mode: ThemeMode): ThemeMode {
  return ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length] ?? "system";
}

function stored(): ThemeMode {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

/** Three-state theme button (system → light → dark); `public/theme-init.js` applies it before first paint. */
export function ThemeToggle({ locale }: { locale: Locale }) {
  const [mode, setMode] = useState<ThemeMode>("system");

  useEffect(() => {
    setMode(stored());
  }, []);

  function cycle() {
    const next = nextMode(mode);
    setMode(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // storage blocked: the choice still applies to this page view
    }
  }

  const label = t(locale, "theme.label", { mode: t(locale, `theme.${mode}`) });
  return (
    <button type="button" className="btn" aria-label={label} title={label} onClick={cycle}>
      <span aria-hidden="true">{mode === "light" ? "☀" : mode === "dark" ? "☾" : "◐"}</span>
    </button>
  );
}
