// Oberfläche der Demo: lädt Zeichnungs-PDFs hoch (auch mehrere auf einmal) und zeigt das Extraktor-Ergebnis,
// geführt in Schritten: Zeichnung → Erkannt → Prüfen → 3D-Modell. Zwei Seiten: „Übersicht“ mit Kennzahlen und
// Tabelle über den ganzen Stapel, „Zeichnung“ mit dem Blatt und der Prüfliste. Fertige Zeichnungen melden sich per Toast.
import { useCallback, useState } from "react";
import type { ReviewFlag } from "./lib/api";
import { dropTarget } from "./lib/drop";
import { explainedShare, partName, pct } from "./lib/format";
import { useJobs, type Job } from "./lib/jobs";
import { FlagList } from "./components/FlagList";
import { FitIcon } from "./components/Icons";
import { ModelPanel } from "./components/ModelPanel";
import { Overview } from "./components/Overview";
import { SheetViewer } from "./components/SheetViewer";
import { Sidebar } from "./components/Sidebar";
import { Toasts, type Toast } from "./components/Toasts";

type Step = 1 | 2 | 3 | 4;
const STEPS: [Step, string][] = [[1, "Zeichnung"], [2, "Erkannt"], [3, "Prüfen"], [4, "3D-Modell"]];

let toastId = 0;

export function App() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toast = useCallback((title: string, detail: string, tone: Toast["tone"]) => {
    const id = ++toastId;
    setToasts((all) => [...all, { id, title, detail, tone, out: false }]);
    setTimeout(() => setToasts((all) => all.map((t) => (t.id === id ? { ...t, out: true } : t))), 4500);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), 5000);
  }, []);

  const onFinished = useCallback((job: Job) => {
    if (job.state === "done" && job.result) {
      const n = job.result.review.length;
      toast(`${partName(job.name)} gelesen`, n ? `${n} Stelle(n) zu prüfen · ${job.seconds} s` : `Alles erklärt · ${job.seconds} s`, n ? "warn" : "good");
    } else {
      toast(`${partName(job.name)} nicht lesbar`, job.error ?? "", "bad");
    }
  }, [toast]);

  const { jobs, addFiles, loadModel } = useJobs(onFinished);
  const [shownId, setShownId] = useState<number | null>(null); // null = Seite „Übersicht“
  const [step, setStepState] = useState<Step>(1);
  const [focus, setFocus] = useState<ReviewFlag | null>(null);
  const [fitKey, setFitKey] = useState(0);
  const [over, setOver] = useState(false);

  const shown = jobs.find((j) => j.id === shownId && j.result) ?? null;
  const current = shown?.result ?? null;

  const pdfs = (files: File[]) => addFiles(files.filter((f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf"));
  const drop = dropTarget(pdfs, setOver);

  // Schritt 3 springt auf das erste Flag mit Ort; sonst ganzes Blatt. Der Schritt bleibt beim Wechsel der Zeichnung erhalten.
  function setStep(next: Step, job: Job | null = shown) {
    setStepState(next);
    setFocus(next === 3 ? job?.result?.review.find((f) => f.bbox) ?? null : null);
    setFitKey((k) => k + 1);
  }

  function show(job: Job) {
    setShownId(job.id);
    setStep(step, job);
  }

  const story = current && {
    1: `Eine Zeichnung ohne 3D-Modell: ${current.drawing.sheet_size_mm[0]} × ${current.drawing.sheet_size_mm[1]} mm, keine Textebene, nur Striche.`,
    2: `${current.drawing.summary.strokes.toLocaleString("de-DE")} Striche klassifiziert, ${current.drawing.summary.views} Ansichten gefunden, ${current.drawing.summary.text_blocks} Maße und Texte gelesen. Ohne KI, nachvollziehbar.`,
    3: current.review.length ? `${current.review.length} Stelle(n) ohne sichere Bedeutung: markiert statt geraten.` : "Keine unklaren Stellen: alles erklärt.",
    4: "Aus der geprüften Zeichnung baut die Pipeline ein parametrisches Modell und exportiert STEP.",
  }[step];

  const done = jobs.filter((j) => j.state === "done").length;
  let title = "Übersicht";
  let updated = jobs.length ? `${done} von ${jobs.length} Zeichnungen gelesen` : "Noch keine Zeichnung hochgeladen";
  let live = done > 0;
  if (shown && current) {
    title = partName(shown.name);
    updated = `Gelesen ${shown.doneAt} · ${shown.seconds} s · ${pct(explainedShare(current).share)} erklärt · lokal, ohne KI`;
    live = true;
  }

  return (
    <div className="shell" data-view={shown ? "drawing" : "overview"} data-step={step} data-has-jobs={jobs.length ? "" : undefined}>
      <div className="window">
        <div className="window-bar" aria-hidden="true"><i /><i /><i /></div>

        <div className="app">
          <Sidebar jobs={jobs} shownId={shown?.id ?? null} onOverview={() => setShownId(null)} onShow={show} />

          <main className="main">
            <header className="head">
              <div>
                <h1>{title}</h1>
                <p className={`updated${live ? " live" : ""}`}>{updated}</p>
              </div>
              <div className="actions">
                {shown && step < 4 && (
                  <button type="button" className="btn ghost" onClick={() => { setFocus(null); setFitKey((k) => k + 1); }}>
                    <FitIcon />Ganzes Blatt
                  </button>
                )}
                <label className={`btn dark upload${over ? " drag" : ""}`} {...drop}>
                  <input
                    type="file" accept="application/pdf,.pdf" multiple
                    onChange={(e) => { pdfs([...(e.target.files ?? [])]); e.target.value = ""; }}
                  />
                  <span>{jobs.length ? "+ Weitere PDFs" : "+ PDFs hochladen"}</span>
                </label>
              </div>
            </header>

            {!shown || !current ? (
              <Overview jobs={jobs} onShow={show} drop={drop} />
            ) : (
              <section className="board" aria-label="Zeichnung">
                <article className="card sheet-card">
                  <header className="card-head">
                    <nav className="steps" aria-label="Ablauf">
                      {STEPS.map(([n, label]) => (
                        <button key={n} type="button" aria-current={n === step ? "step" : "false"} onClick={() => setStep(n)}>
                          <b>{n}</b>{label}
                        </button>
                      ))}
                    </nav>
                  </header>
                  {step === 4
                    ? <ModelPanel model={shown.model} onStep={(f) => void loadModel(shown.id, f)} />
                    : <SheetViewer key={shown.id} result={current} focus={focus} fitKey={fitKey} dropProps={drop} />}
                  <footer className="story">
                    <p>{story}</p>
                    {step < 4 && <button type="button" className="btn dark" onClick={() => setStep((step + 1) as Step)}>Weiter</button>}
                  </footer>
                </article>

                <FlagList flags={current.review} active={focus} onSelect={(f) => { if (step !== 3) setStepState(3); setFocus(f); }} />
              </section>
            )}
          </main>
        </div>
      </div>

      <Toasts toasts={toasts} />
    </div>
  );
}
