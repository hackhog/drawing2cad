// Stapel-Upload (ADR 0007): jede Zeichnung durchläuft wait → run → done | error, höchstens
// PARALLEL_UPLOADS gleichzeitig. Die Übersicht füllt sich live aus dieser Liste.
import { useCallback, useEffect, useRef, useState } from "react";
import { extractDrawing, stepToGlbUrl, type ExtractResult } from "./api";

// Der Extraktor läuft serverseitig im Threadpool; zwei parallel halten die Wartezeit kurz,
// ohne den Container zu überlasten
const PARALLEL_UPLOADS = 2;

export type ModelState =
  | { state: "idle" }
  | { state: "run"; name: string }
  | { state: "done"; name: string; url: string }
  | { state: "error"; name: string; error: string };

export interface Job {
  id: number;
  name: string;
  file: File | null; // nur bis zum Lesen, PDF nicht länger als nötig im Speicher halten
  state: "wait" | "run" | "done" | "error";
  result: ExtractResult | null;
  error: string | null;
  seconds: string;
  doneAt: string;
  model: ModelState;
}

export type JobStatus = "wait" | "run" | "done" | "flag" | "error";

export function jobStatus(job: Job): [JobStatus, string] {
  if (job.state === "wait") return ["wait", "wartet"];
  if (job.state === "run") return ["run", "liest"];
  if (job.state === "error" || !job.result) return ["error", "Fehler"];
  const n = job.result.review.length;
  return n ? ["flag", `${n} prüfen`] : ["done", "fertig"];
}

let nextId = 1;

export function useJobs(onFinished: (job: Job) => void) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const started = useRef(new Set<number>());
  const finished = useRef(onFinished);
  useEffect(() => { finished.current = onFinished; }, [onFinished]);

  const patch = useCallback((id: number, change: Partial<Job>) => {
    setJobs((all) => all.map((j) => (j.id === id ? { ...j, ...change } : j)));
  }, []);

  const addFiles = useCallback((files: File[]) => {
    const fresh = files.map<Job>((file) => ({
      id: nextId++, name: file.name, file, state: "wait", result: null, error: null,
      seconds: "", doneAt: "", model: { state: "idle" },
    }));
    setJobs((all) => [...all, ...fresh]);
  }, []);

  useEffect(() => {
    let free = PARALLEL_UPLOADS - jobs.filter((j) => j.state === "run").length;
    for (const job of jobs) {
      if (free <= 0) break;
      if (job.state !== "wait" || started.current.has(job.id)) continue;
      started.current.add(job.id);
      free -= 1;
      patch(job.id, { state: "run" });
      void read(job);
    }

    async function read(job: Job) {
      const t0 = performance.now();
      let done: Job;
      try {
        const result = await extractDrawing(job.file!);
        done = {
          ...job, file: null, state: "done", result,
          seconds: ((performance.now() - t0) / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 }),
          doneAt: new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }),
        };
      } catch (err) {
        done = { ...job, file: null, state: "error", error: (err as Error).message };
      }
      patch(job.id, done);
      finished.current(done);
    }
  }, [jobs, patch]);

  /** STEP aus der Pipeline zu einer Zeichnung laden; der Server wandelt es in GLB. */
  const loadModel = useCallback(async (id: number, step: File) => {
    const name = step.name;
    setJobs((all) => all.map((j) => {
      if (j.id !== id) return j;
      if (j.model.state === "done") URL.revokeObjectURL(j.model.url);
      return { ...j, model: { state: "run", name } };
    }));
    try {
      patch(id, { model: { state: "done", name, url: await stepToGlbUrl(step) } });
    } catch (err) {
      patch(id, { model: { state: "error", name, error: (err as Error).message } });
    }
  }, [patch]);

  /** Remove all jobs from the list. The sidebar enables this only when no job is waiting or running. */
  const clear = useCallback(() => {
    setJobs((all) => {
      for (const j of all) if (j.model.state === "done") URL.revokeObjectURL(j.model.url);
      return [];
    });
  }, []);

  return { jobs, addFiles, loadModel, clear };
}
