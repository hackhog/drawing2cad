// Diagnostic files of a run: run record, model and tool trace, and MCP part state. Each file opens in a new browser tab.
import { useQuery } from "@tanstack/react-query";
import { Download, FileText, FolderOpen } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/apiContext";
import type { Run } from "@/lib/contract";
import { recoveryFor } from "@/lib/errors";
import { bytes } from "@/lib/format";
import { runFilesQuery } from "@/lib/queries";

export function RunFiles({ run }: { run: Run }) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const { data, error, isPending } = useQuery({ ...runFilesQuery(api, run.run_id), enabled: open });

  return (
    <div className="flex flex-col gap-2">
      <Button variant="outline" size="sm" className="justify-start" aria-expanded={open} onClick={() => setOpen(!open)}>
        <FolderOpen />{open ? "Hide run files" : "Open run files"}
      </Button>
      {open && (isPending ? <p className="text-xs text-muted-foreground">Loading files …</p>
        : error ? <p className="text-xs text-flag">{error.message} {recoveryFor(error)}</p>
        : data.files.length === 0 ? <p className="text-xs text-muted-foreground">No files for this run.</p>
        : (
          <>
            {data.archive_url && (
              <Button variant="secondary" size="sm" className="justify-start" asChild>
                <a href={data.archive_url} download><Download />All as ZIP ({data.files.length})</a>
              </Button>
            )}
            <ul className="max-h-80 overflow-y-auto rounded-md border text-[11px]">
              {data.files.map((file) => (
                <li key={file.path} className="border-b last:border-b-0">
                  <a href={file.url} target="_blank" rel="noreferrer" title={file.path}
                    className="flex items-center gap-1.5 px-2 py-1 hover:bg-muted">
                    <FileText className="size-3 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate font-mono">{file.path}</span>
                    <span className="shrink-0 text-muted-foreground">{bytes(file.byte_count)}</span>
                  </a>
                </li>
              ))}
            </ul>
          </>
        ))}
    </div>
  );
}
