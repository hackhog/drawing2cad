// German labels of the review measurement answers.
import type { Estimator } from "./contract";

export const ESTIMATOR_LABEL: Record<Estimator, string> = { drafter: "Konstrukteur", guest: "Gast / Jury", team: "Team" };

/** Answers to "How long would a manual rebuild take?", in hours. */
export const MANUAL_ESTIMATES: [number, string][] = [
  [0.5, "unter 30 min"], [1, "ca. 1 h"], [2, "ca. 2 h"], [4, "ca. 4 h"], [8, "1 Tag oder mehr"],
];
