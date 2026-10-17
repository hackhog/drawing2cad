// Load artifact content by opaque ID into an object URL for the lifetime of a view.
import { useEffect, useState } from "react";
import { recoveryFor } from "./errors";
import type { WebApi } from "./webApi";

export function useArtifactUrl(api: WebApi, artifactId: string): { url: string | null; error: string | null } {
  const [state, setState] = useState<{ id: string; url: string | null; error: string | null }>({ id: artifactId, url: null, error: null });
  useEffect(() => {
    let live = true;
    let created: string | null = null;
    api.readArtifact(artifactId).then(
      (blob) => { if (!live) return; created = URL.createObjectURL(blob); setState({ id: artifactId, url: created, error: null }); },
      (err: Error) => { if (live) setState({ id: artifactId, url: null, error: `${err.message} ${recoveryFor(err)}` }); },
    );
    return () => { live = false; if (created) URL.revokeObjectURL(created); };
  }, [api, artifactId]);
  // A new ID shows the loading state until its own content arrives.
  return state.id === artifactId ? state : { url: null, error: null };
}
