// Load an artifact preview by its opaque service ID. The 3D viewer stays lazy-loaded.
import { ModelFrame } from "@/components/ModelPanel";
import { useApi } from "@/lib/apiContext";
import { useArtifactUrl } from "@/lib/artifacts";
import type { Artifact } from "@/lib/contract";

export const Preview = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="flex min-h-[280px] flex-col gap-1.5">
    <h3 className="text-xs font-semibold tracking-[.06em] text-faint uppercase">{title}</h3>{children}
  </div>
);

export const Empty = ({ text }: { text: string }) => (
  <div className="grid flex-1 place-items-center rounded-lg border bg-viewer p-6 text-center text-xs text-muted-foreground">{text}</div>
);

export function BlobView({ artifact, kind, notReleased = false }: { artifact: Artifact; kind: "pdf" | "glb" | "png"; notReleased?: boolean }) {
  const { url, error } = useArtifactUrl(useApi(), artifact.artifact_id, kind === "glb" ? "glb" : "content");
  if (error) return <Empty text={error} />;
  if (!url) return <Empty text="Loading …" />;
  if (kind === "glb") return <ModelFrame url={url} name={`${artifact.filename}${notReleased ? " · not released" : ""}`} />;
  if (kind === "png") return <img src={url} alt={`${artifact.filename} · not released`} className="rounded-lg border object-contain" />;
  return <object data={url} type="application/pdf" aria-label={artifact.filename} className="min-h-[280px] flex-1 rounded-lg border" />;
}
