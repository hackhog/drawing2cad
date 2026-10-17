// Revisioned run notes. A note is stored against the latest note revision that the user saw.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useApi } from "@/lib/apiContext";
import type { Run } from "@/lib/contract";
import { errorCode, recoveryFor } from "@/lib/errors";
import { time } from "@/lib/format";
import { capabilitiesQuery, keys, notesQuery } from "@/lib/queries";

export function NotesPanel({ run }: { run: Run }) {
  const api = useApi();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  if (!caps?.notes) return <p className="text-muted-foreground">Der verbundene Dienst speichert keine Notizen.</p>;
  return <Notes run={run} />;
}

function Notes({ run }: { run: Run }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const notes = useQuery(notesQuery(api, run.run_id));
  const [text, setText] = useState("");
  const revision = notes.data?.at(-1)?.revision ?? 0;
  const add = useMutation({
    mutationFn: () => api.addNote(run.run_id, revision, text),
    onSuccess: async () => {
      setText("");
      await queryClient.invalidateQueries({ queryKey: keys.notes(run.run_id) });
    },
    onError: async (err) => {
      // Load the newer notes, so the user can see them before saving again. The draft stays.
      if (errorCode(err) === "REVISION_CONFLICT") await queryClient.invalidateQueries({ queryKey: keys.notes(run.run_id) });
    },
  });

  if (notes.isError) return <ErrorState title="Notizen nicht geladen" error={notes.error} onRetry={() => void notes.refetch()} />;
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-2">
        {notes.data?.length === 0 && <li className="text-muted-foreground">Noch keine Notizen.</li>}
        {notes.data?.map((n) => (
          <li key={n.note_id} className="rounded-md border px-3 py-2">
            <div className="mb-0.5 flex justify-between text-[11px] text-muted-foreground">
              <span>{n.author} · Rev. {n.revision}</span><time>{time(n.created_at)}</time>
            </div>
            <p className="whitespace-pre-wrap text-card-foreground">{n.text}</p>
          </li>
        ))}
      </ul>
      <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate(); }}>
        <Label htmlFor="note">Neue Notiz</Label>
        <Textarea id="note" value={text} onChange={(e) => setText(e.target.value)} rows={3}
          placeholder="Prüfhinweis, Rückfrage an die Konstruktion, Entscheidung …" />
        {add.error && (
          <Alert variant="destructive"><AlertDescription>{add.error.message} {recoveryFor(add.error)}</AlertDescription></Alert>
        )}
        <Button type="submit" size="sm" className="self-end rounded-full" disabled={!text.trim() || add.isPending}>Notiz speichern</Button>
      </form>
    </div>
  );
}
