import { jobStatus, type Job } from "../lib/jobs";
import { partName } from "../lib/format";
import { GridIcon, LogoIcon } from "./Icons";

interface Props {
  jobs: Job[];
  shownId: number | null; // nur gesetzt, wenn die Seite „Zeichnung“ offen ist
  onOverview: () => void;
  onShow: (job: Job) => void;
  onClear: () => void;
}

export function Sidebar({ jobs, shownId, onOverview, onShow, onClear }: Props) {
  // Clear only when nothing is in progress, so no running request writes into an empty list
  const busy = jobs.some((j) => j.state === "wait" || j.state === "run");
  return (
    <aside className="nav">
      <div className="brand">
        <span className="logo" aria-hidden="true"><LogoIcon /></span>
        Drawing2CAD
      </div>

      <button type="button" className="nav-item" aria-current={shownId === null} onClick={onOverview}>
        <GridIcon />Übersicht
      </button>

      <p className="nav-label">Zeichnungen</p>
      <ul className="batch" aria-label="Hochgeladene Zeichnungen">
        {jobs.map((job) => {
          const [state, label] = jobStatus(job);
          return (
            <li key={job.id}>
              <button
                type="button" data-state={state} disabled={job.state !== "done"} title={job.error ?? job.name}
                aria-current={job.id === shownId} onClick={() => onShow(job)}
              >
                <span>{partName(job.name)}</span><small>{label}</small>
              </button>
            </li>
          );
        })}
      </ul>

      <footer className="nav-foot">
        <div className="nav-status">
          <span>Lokal, ohne KI</span>
          <button type="button" disabled={!jobs.length || busy} onClick={onClear} title="Alle Zeichnungen aus der Liste entfernen">
            Leeren
          </button>
        </div>
        <div className="profile">
          <span className="avatar" aria-hidden="true">KO</span>
          <div><strong>Konstruktion</strong><small>Demo-Arbeitsplatz</small></div>
        </div>
      </footer>
    </aside>
  );
}
