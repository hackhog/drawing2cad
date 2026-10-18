import type { ExtractResult } from "./drawing";

/** Locale for all numbers, times, and amounts in the UI. */
export const LOCALE = "en-US";

export const fmt = (n: number) => n.toLocaleString(LOCALE);
export const pct = (x: number) => `${(x * 100).toLocaleString(LOCALE, { maximumFractionDigits: 1 })}%`;
export const partName = (filename: string) => filename.replace(/_dwg\.pdf$/i, "").replace(/\.pdf$/i, "");

export function explainedShare(result: ExtractResult) {
  const { strokes, by_kind: byKind } = result.drawing.summary;
  const explained = strokes - (byKind.unclear ?? 0);
  return { total: strokes, explained, share: strokes ? explained / strokes : 1 };
}

export const bytes = (n: number) =>
  n < 1024 * 1024 ? `${(n / 1024).toLocaleString(LOCALE, { maximumFractionDigits: 1 })} KB`
    : `${(n / 1024 / 1024).toLocaleString(LOCALE, { maximumFractionDigits: 1 })} MB`;
export const time = (iso: string) => new Date(iso).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
export const shortHash = (sha: string) => (sha ? sha.slice(0, 12) : "–");
export const duration = (seconds: number) => {
  const s = Math.round(seconds);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
};
/** A running stopwatch: minutes and seconds, for example 02:14. */
export const clock = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
export const hours = (h: number) => `${h.toLocaleString(LOCALE, { maximumFractionDigits: 1 })} h`;
export const euros = (n: number) => n.toLocaleString(LOCALE, { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
