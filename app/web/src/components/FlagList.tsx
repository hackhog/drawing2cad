import type { ReviewFlag } from "../lib/api";
import { FLAG_KIND } from "../lib/kinds";

interface Props { flags: ReviewFlag[]; active: ReviewFlag | null; onSelect: (flag: ReviewFlag) => void }

/** Prüfliste im Stil einer Änderungsliste: Klick zoomt das Blatt auf die Stelle. */
export function FlagList({ flags, active, onSelect }: Props) {
  return (
    <article className="card flags-card">
      <header className="card-head">
        <h2>Prüfen <span className="count">{flags.length || ""}</span></h2>
        <span className="pill">Liste</span>
      </header>
      <ul className="list">
        {!flags.length && <li className="ok">Nichts zu prüfen.</li>}
        {flags.map((f, i) => f.bbox ? (
          <li key={i} className={f === active ? "active" : undefined} onClick={() => onSelect(f)}>
            <i className={`dot ${f.kind}`} />
            <div className="item"><strong>{f.message}</strong><span>{FLAG_KIND[f.kind] ?? f.kind}</span></div>
            <time>x {Math.round(f.bbox[0])} · y {Math.round(f.bbox[1])}</time>
          </li>
        ) : <li key={i} className="ok">{f.message}</li>)}
      </ul>
    </article>
  );
}
