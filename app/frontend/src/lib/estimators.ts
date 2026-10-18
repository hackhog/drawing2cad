// German labels of the review measurement answers.
import type { Estimator } from "./contract";

export const ESTIMATOR_LABEL: Record<Estimator, string> = { drafter: "Designer", guest: "Guest / jury", team: "Team" };

/** Answers to "How long would a manual rebuild take?", in hours. */
export const MANUAL_ESTIMATES: [number, string][] = [
  [0.5, "under 30 min"], [1, "approx. 1 h"], [2, "approx. 2 h"], [4, "approx. 4 h"], [8, "1 day or more"],
];
