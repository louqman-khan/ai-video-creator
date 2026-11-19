import { create } from "zustand";

export type ThemeMode = "system" | "light" | "dark";
const KEY = "avc-theme";

function read(): ThemeMode {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";   // storage can be blocked (private window): the system setting then applies
  }
}

/** Puts the choice on the page: "system" removes the attribute so the CSS follows the operating system. */
export function applyTheme(mode: ThemeMode): void {
  const root = document.documentElement;
  if (mode === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", mode);
}

interface ThemeState {
  mode: ThemeMode;
  set: (m: ThemeMode) => void;
}

export const useTheme = create<ThemeState>((set) => ({
  mode: read(),
  set: (mode) => {
    try {
      if (mode === "system") window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, mode);
    } catch {
      /* not saved: it still applies for this visit */
    }
    applyTheme(mode);
    set({ mode });
  },
}));

/** What the page looks like right now (an explicit choice, or the system's). */
export function isDark(mode: ThemeMode): boolean {
  return mode === "dark" || (mode === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
}
