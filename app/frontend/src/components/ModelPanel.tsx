// Reiter 4: STEP aus der Pipeline laden (Server wandelt in GLB) und als 3D-Modell zeigen
import { lazy, Suspense, useState } from "react";
import { dropTarget } from "../lib/drop";
import type { ModelState } from "../lib/jobs";

const ModelViewer = lazy(() => import("./ModelViewer"));

const isStep = (f: File) => /\.(stp|step)$/i.test(f.name);

export function ModelPanel({ model, onStep }: { model: ModelState; onStep: (step: File) => void }) {
  const [over, setOver] = useState(false);
  const take = (files: File[]) => { const step = files.find(isStep); if (step) onStep(step); };

  return (
    <div className="viewer" {...dropTarget(take, setOver)}>
      {model.state === "done" ? (
        <>
          <Suspense fallback={<p className="model-drop">3D-Ansicht wird geladen …</p>}>
            <ModelViewer url={model.url} />
          </Suspense>
          <span className="model-name">{model.name}</span>
        </>
      ) : (
        <label className={`model-drop${over ? " drag" : ""}`}>
          {model.state === "run" ? <span>{model.name} wird umgewandelt …</span> : <span>STEP-Datei des Modells hierher ziehen oder klicken</span>}
          {model.state === "error" && <span className="error">{model.name}: {model.error}</span>}
          <small>Ergebnis der Pipeline (drawing2cad-mcp + FreeCAD). Der Server vernetzt es zu GLB, gespeichert wird nichts.</small>
          <input
            type="file" accept=".stp,.step" hidden
            onChange={(e) => { take([...(e.target.files ?? [])]); e.target.value = ""; }}
          />
        </label>
      )}
    </div>
  );
}
