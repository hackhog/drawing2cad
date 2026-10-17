// Assumptions of the saving calculation. They are a setting of this browser, so they stay in local storage.
import { useState } from "react";
import type { Assumptions } from "./benefit";

const KEY = "drawing2cad.assumptions";
export const DEFAULT_ASSUMPTIONS: Assumptions = { hourlyRate: 85, manualHours: 3 };

function load(): Assumptions {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) ?? "null") as Partial<Assumptions> | null;
    return { ...DEFAULT_ASSUMPTIONS, ...stored };
  } catch {
    return DEFAULT_ASSUMPTIONS;
  }
}

export function useAssumptions(): [Assumptions, (next: Assumptions) => void] {
  const [assumptions, setAssumptions] = useState(load);
  const save = (next: Assumptions) => {
    setAssumptions(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      // Without storage the values apply until the page reloads.
    }
  };
  return [assumptions, save];
}
