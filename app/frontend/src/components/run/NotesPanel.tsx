// The revisioned note of a run. The agent writes its report there; users can add review information.
// A save replaces the note against the revision that the user edited.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useApi } from "@/lib/apiContext";
import type { Run, RunNote } from "@/lib/contract";
import { errorCode, recoveryFor } from "@/lib/errors";
import { capabilitiesQuery, keys, noteQuery } from "@/lib/queries";
import { isActive } from "@/lib/release";

export function NotesPanel({ run }: { run: Run }) {
  const api = useApi();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  if (!caps?.notes) return <p className="text-muted-foreground">The connected service does not store notes.</p>;
  if (!run.part) {
    return <p className="text-muted-foreground">{isActive(run) ? "The note is available once the run has finished."
      : "Notes belong to the part. This run created no part."}</p>;
  }
  return <Note run={run} />;
}

function Note({ run }: { run: Run }) {
  const api = useApi();
  const note = useQuery(noteQuery(api, run.run_id));
  if (note.isError) return <ErrorState title="Note not loaded" error={note.error} onRetry={() => void note.refetch()} />;
  if (!note.data) return <p className="text-muted-foreground">Loading note …</p>;
  // A new revision from the service resets the editor to the stored text.
  return <NoteEditor key={note.data.revision} run={run} note={note.data} />;
}

function NoteEditor({ run, note }: { run: Run; note: RunNote }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [text, setText] = useState(note.text);
  const active = isActive(run);
  const save = useMutation({
    mutationFn: () => api.saveNote(run.run_id, note.revision, text),
    onSuccess: (saved) => queryClient.setQueryData(keys.note(run.run_id), saved),
  });
  const conflict = errorCode(save.error) === "REVISION_CONFLICT";

  return (
    <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <div className="flex items-baseline justify-between">
        <Label htmlFor="note">Run note</Label>
        <span className="text-[11px] text-muted-foreground">{note.revision ? `Revision ${note.revision}` : "No note yet"}</span>
      </div>
      <Textarea id="note" value={text} onChange={(e) => setText(e.target.value)} rows={12} disabled={active}
        placeholder="Review note, question for design, decision …" />
      {save.error && (
        <Alert variant="destructive">
          <AlertDescription>
            <p>{save.error.message} {recoveryFor(save.error)}</p>
            {conflict && (
              <Button type="button" variant="outline" size="sm" className="mt-1"
                onClick={() => { save.reset(); void queryClient.invalidateQueries({ queryKey: keys.note(run.run_id) }); }}>
                Reload
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {active ? "While the run is active, the agent writes its report into the note." : "The agent report stays in the Review tab."}
        </p>
        <Button type="submit" size="sm" className="rounded-full" disabled={active || text === note.text || save.isPending}>
          Save note
        </Button>
      </div>
    </form>
  );
}
