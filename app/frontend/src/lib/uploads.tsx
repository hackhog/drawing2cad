// Batch upload (ADR 0007): each PDF passes wait → send → read → done | error, with at most
// PARALLEL_UPLOADS at the same time. A finished upload becomes a source in the sources query.
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { useApi } from "./apiContext";
import { ApiFailure, recoveryFor } from "./errors";
import { LOCALE, partName } from "./format";
import { analysisQuery, capabilitiesQuery, keys } from "./queries";

// The service analyzes in a thread pool; two parallel uploads keep the wait short without overloading it.
const PARALLEL_UPLOADS = 2;

export interface Upload {
  id: number;
  name: string;
  state: "wait" | "send" | "read" | "error";
  progress: number;
  error: string | null;
}

interface UploadContext {
  uploads: Upload[];
  addFiles: (files: File[]) => void;
  dismiss: (id: number) => void;
}

const Context = createContext<UploadContext | null>(null);
let nextId = 1;

export function UploadProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [uploads, setUploads] = useState<Upload[]>([]);
  // Keep the PDF bytes out of React state and release them when the upload ends.
  const files = useRef(new Map<number, File>());

  const patch = useCallback((id: number, change: Partial<Upload>) => {
    setUploads((all) => all.map((u) => (u.id === id ? { ...u, ...change } : u)));
  }, []);

  const addFiles = useCallback((picked: File[]) => {
    const fresh = picked.map<Upload>((file) => {
      const id = nextId++;
      files.current.set(id, file);
      return { id, name: file.name, state: "wait", progress: 0, error: null };
    });
    setUploads((all) => [...all, ...fresh]);
  }, []);

  const dismiss = useCallback((id: number) => setUploads((all) => all.filter((u) => u.id !== id)), []);

  useEffect(() => {
    let free = PARALLEL_UPLOADS - uploads.filter((u) => u.state === "send" || u.state === "read").length;
    for (const upload of uploads) {
      if (free <= 0) break;
      const file = files.current.get(upload.id);
      if (upload.state !== "wait" || !file) continue;
      files.current.delete(upload.id);
      free -= 1;
      patch(upload.id, { state: "send" });
      void send(upload, file);
    }

    async function send(upload: Upload, file: File) {
      const t0 = performance.now();
      try {
        // Reject an oversized file before the transfer; the service checks the limit again.
        const { max_pdf_bytes: limit } = await queryClient.fetchQuery(capabilitiesQuery(api));
        if (file.size > limit) {
          throw new ApiFailure({ code: "UPLOAD_TOO_LARGE", field: "file", message: `PDF larger than ${Math.floor(limit / 1024 / 1024)} MB.` }, 413);
        }
        const source = await api.uploadSource(file, (progress) => patch(upload.id, { progress, state: progress < 1 ? "send" : "read" }));
        const analysis = await queryClient.fetchQuery(analysisQuery(api, source.source_id));
        await queryClient.invalidateQueries({ queryKey: keys.sources });
        dismiss(upload.id);
        const seconds = ((performance.now() - t0) / 1000).toLocaleString(LOCALE, { maximumFractionDigits: 1 });
        const flags = analysis.review.length;
        const notify = flags ? toast.warning : toast.success;
        notify(`${partName(file.name)} read`, { description: flags ? `${flags} spot(s) to review · ${seconds} s` : `Everything explained · ${seconds} s` });
      } catch (err) {
        patch(upload.id, { state: "error", error: (err as Error).message });
        toast.error(`${partName(file.name)} unreadable`, { description: `${(err as Error).message} ${recoveryFor(err)}` });
      }
    }
  }, [uploads, api, queryClient, patch, dismiss]);

  return <Context.Provider value={{ uploads, addFiles, dismiss }}>{children}</Context.Provider>;
}

export function useUploads(): UploadContext {
  const context = useContext(Context);
  if (!context) throw new Error("useUploads requires an UploadProvider.");
  return context;
}

export const isPdf = (f: File) => /\.pdf$/i.test(f.name) || f.type === "application/pdf";
