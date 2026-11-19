import type { Credits } from "./api/client";

const WORDS_PER_MINUTE = 150;   // the same figure the server uses to price a typed script

/** Credits a video will use: the narration's minutes divided by the minutes one credit pays for, rounded up, at least one (same rule as the server). */
export function costOfSeconds(seconds: number, perCredit = 1): number {
  return Math.max(1, Math.ceil(seconds / 60 / Math.max(0.1, perCredit)));
}

export function costOfScript(text: string, perCredit = 1): number {
  return costOfSeconds((text.trim().split(/\s+/).filter(Boolean).length / WORDS_PER_MINUTE) * 60, perCredit);
}

export const resetLabel = (iso: string): string => {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
};

export const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function creditsText(c: Credits): string {
  return c.unlimited ? "Unlimited (administrator)" : `${c.used} of ${c.monthly} video credits used`;
}
