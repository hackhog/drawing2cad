// STEP previews that the user supplies, one per source. The store owns the GLB object URLs
// and frees each one when a preview is replaced or its source is removed.
import { useSyncExternalStore } from "react";

export type ModelState =
  | { state: "idle" }
  | { state: "run"; name: string }
  | { state: "done"; name: string; url: string }
  | { state: "error"; name: string; error: string };

const IDLE: ModelState = { state: "idle" };
const previews = new Map<string, ModelState>();
const listeners = new Set<() => void>();

function release(sourceId: string) {
  const old = previews.get(sourceId);
  if (old?.state === "done") URL.revokeObjectURL(old.url);
}

export function setStepPreview(sourceId: string, next: ModelState) {
  if (previews.get(sourceId) !== next) release(sourceId);
  previews.set(sourceId, next);
  listeners.forEach((l) => l());
}

export function clearStepPreview(sourceId: string) {
  release(sourceId);
  previews.delete(sourceId);
  listeners.forEach((l) => l());
}

const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); };

export const useStepPreview = (sourceId: string): ModelState =>
  useSyncExternalStore(subscribe, () => previews.get(sourceId) ?? IDLE);
