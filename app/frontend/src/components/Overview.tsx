// Seite „Übersicht“: Kennzahlen über den ganzen Stapel, eine Zeile je Zeichnung (ADR 0008)
import { useState, type DragEvent } from "react";
import { explainedShare, fmt, partName, pct } from "../lib/format";
import { jobStatus, type Job } from "../lib/jobs";
import { GaugeIcon } from "./Icons";

type Tone = "" | "good" | "bad";
const Sub = ({ text, tone }: { text: string; tone: Tone }) => <p className={tone ? `delta ${tone}` : undefined}>{text}</p>;

interface Props {
  jobs: Job[];
  onShow: (job: Job) => void;
  drop: { onDragOver: (e: DragEvent) => void; onDragLeave: () => void; onDrop: (e: DragEvent) => void };
}

export function Overview({ jobs, onShow, drop }: Props) {
  const [mode, setMode] = useState<"number" | "gauge">("number");
  const done = jobs.filter((j) => j.state === "done" && j.result);
  const busy = jobs.filter((j) => j.state === "wait" || j.state === "run").length;
  const failed = jobs.filter((j) => j.state === "error").length;

  const jobsSub: [string, Tone] = busy ? [`${busy} in Arbeit`, ""]
    : failed ? [`${failed} nicht lesbar`, "bad"]
    : jobs.length ? ["alle gelesen, lokal und ohne KI", "good"] : ["gelesen, lokal und ohne KI", ""];

  const shares = done.map((j) => explainedShare(j.result!));
  const total = shares.reduce((a, s) => a + s.total, 0);
  const explained = shares.reduce((a, s) => a + s.explained, 0);
  const share = total ? explained / total : 0;

  const texts = done.flatMap((j) => j.result!.drawing.text_blocks);
  const unsure = texts.filter((t) => t.text.includes("?")).length;
  const flags = done.reduce((a, j) => a + j.result!.review.length, 0);

  return (
    <section className="overview" aria-label="Übersicht">
      <section className="tiles" aria-label="Kennzahlen">
        <article className="tile">
          <header><h3>Zeichnungen</h3></header>
          <div className="value"><strong>{jobs.length ? fmt(done.length) : "–"}</strong></div>
          <Sub text={jobsSub[0]} tone={jobsSub[1]} />
        </article>
        <article className="tile" data-mode={mode}>
          <header>
            <h3>Erklärt</h3>
            <div className="tile-mode" role="radiogroup" aria-label="Darstellung">
              <button type="button" role="radio" aria-checked={mode === "number"} title="Zahl" onClick={() => setMode("number")}>#</button>
              <button type="button" role="radio" aria-checked={mode === "gauge"} title="Tacho" onClick={() => setMode("gauge")}><GaugeIcon /></button>
            </div>
          </header>
          <div className="value">
            <svg className="gauge" viewBox="0 0 100 56" aria-hidden="true">
              <path className="track" d="M8 50a42 42 0 0 1 84 0" />
              <path className="fill" d="M8 50a42 42 0 0 1 84 0" pathLength={100} style={{ strokeDasharray: `${share * 100} 100` }} />
            </svg>
            <strong>{total ? pct(share) : "–"}</strong>
          </div>
          <p>{total ? `${fmt(explained)} von ${fmt(total)} Strichen zugeordnet` : "Anteil der Striche mit sicherer Bedeutung"}</p>
        </article>
        <article className="tile">
          <header><h3>Texte gelesen</h3></header>
          <div className="value"><strong>{done.length ? fmt(texts.length) : "–"}</strong></div>
          {done.length
            ? <Sub text={unsure ? `${unsure} nicht sicher gelesen` : "alle sicher gelesen"} tone={unsure ? "bad" : "good"} />
            : <p>Maße, Schnitte, Hinweise</p>}
        </article>
        <article className={`tile${flags > 0 ? " warn" : ""}`}>
          <header><h3>Zu prüfen</h3></header>
          <div className="value"><strong>{done.length ? fmt(flags) : "–"}</strong></div>
          {done.length
            ? <Sub text={flags === 1 ? "Stelle markiert statt geraten" : flags ? "Stellen markiert statt geraten" : "nichts offen"} tone={flags ? "bad" : "good"} />
            : <p>Markiert statt geraten</p>}
        </article>
      </section>

      <article className="card table-card" {...drop}>
        <header className="card-head">
          <h2>Zeichnungen</h2>
          <span className="pill">Tabelle</span>
        </header>
        <p className="empty-drop">Alte Zeichnungen als PDF hierher ziehen, gern mehrere auf einmal</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Zeichnung</th><th>Status</th><th className="num">Erklärt</th><th className="num">Ansichten</th>
                <th className="num">Texte</th><th className="num">Zu prüfen</th><th className="num">Dauer</th>
              </tr>
            </thead>
            <tbody>{jobs.map((job) => <JobRow key={job.id} job={job} onShow={onShow} />)}</tbody>
          </table>
        </div>
      </article>
    </section>
  );
}

function JobRow({ job, onShow }: { job: Job; onShow: (job: Job) => void }) {
  const [state, label] = jobStatus(job);
  const status = <td><span className={`status ${state}`} title={job.error ?? ""}>{label}</span></td>;
  if (job.state !== "done" || !job.result) {
    return (
      <tr data-state={state}>
        <td className="name">{partName(job.name)}</td>{status}
        {Array.from({ length: 5 }, (_, i) => <td key={i} className="num">–</td>)}
      </tr>
    );
  }
  const d = job.result.drawing;
  return (
    <tr data-state={state} tabIndex={0} onClick={() => onShow(job)} onKeyDown={(e) => e.key === "Enter" && onShow(job)}>
      <td className="name">{partName(job.name)}</td>{status}
      <td className="num">{pct(explainedShare(job.result).share)}</td>
      <td className="num">{fmt(d.views.length)}</td>
      <td className="num">{fmt(d.text_blocks.length)}</td>
      <td className="num">{fmt(job.result.review.length)}</td>
      <td className="num">{job.seconds} s</td>
    </tr>
  );
}
