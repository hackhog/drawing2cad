// Display a STEP file that the user supplies, after server conversion to GLB. Display only, no CAD result.
import { Component, lazy, Suspense, useState, type ReactNode } from "react";
import { dropTarget } from "@/lib/drop";
import type { ModelState } from "@/lib/stepPreviews";
import { cn } from "@/lib/utils";
import { VIEWER_FRAME } from "./viewerFrame";

const ModelViewer = lazy(() => import("./ModelViewer"));

const isStep = (f: File) => /\.(stp|step)$/i.test(f.name);

const CENTER = "absolute inset-0 grid place-items-center content-center gap-2.5 p-6 text-center text-sm font-medium text-muted-foreground";

/** Keep a failed 3D view (for example, no WebGL in the browser) inside its frame. */
class ViewerBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(error: Error) { return { error: error.message }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <p className={CENTER}>
        3D-Ansicht nicht möglich. Der Browser stellt kein WebGL bereit.
        <small className="text-xs font-normal text-faint">{this.state.error}</small>
      </p>
    );
  }
}

/** 3D view of a GLB URL, with a name label. */
export function ModelFrame({ url, name }: { url: string; name: string }) {
  return (
    <div className={VIEWER_FRAME}>
      <ViewerBoundary>
        <Suspense fallback={<p className={CENTER}>3D-Ansicht wird geladen …</p>}>
          <ModelViewer url={url} />
        </Suspense>
      </ViewerBoundary>
      <span className="absolute top-2.5 left-2.5 rounded-full bg-info-bg px-2.5 py-0.5 text-[11px] font-semibold text-info">{name}</span>
    </div>
  );
}

/** Drop or select a STEP file. A dropped file also replaces a model that is already shown. */
export function ModelPanel({ model, onStep }: { model: ModelState; onStep: (step: File) => void }) {
  const [over, setOver] = useState(false);
  const take = (files: File[]) => { const step = files.find(isStep); if (step) onStep(step); };

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", over && "[&>div]:ring-4 [&>div]:ring-highlight-bg")} {...dropTarget(take, setOver)}>
      {model.state === "done" ? <ModelFrame url={model.url} name={model.name} /> : (
        <div className={VIEWER_FRAME}>
          <label className={cn(CENTER, "cursor-pointer", over && "bg-highlight-bg")}>
            {model.state === "run" ? <span>{model.name} wird umgewandelt …</span> : <span>STEP-Datei des Modells hierher ziehen oder klicken</span>}
            {model.state === "error" && <span className="text-flag">{model.name}: {model.error}</span>}
            <small className="max-w-[420px] text-xs font-normal text-faint">
              STEP-Datei zur 3D-Vorschau. Der Server wandelt sie in GLB um; die Datei wird nicht dauerhaft gespeichert.
            </small>
            <input type="file" accept=".stp,.step" hidden onChange={(e) => { take([...(e.target.files ?? [])]); e.target.value = ""; }} />
          </label>
        </div>
      )}
    </div>
  );
}
