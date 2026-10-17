// Named parameters and ordered operations. A change creates a new revision through the shared revision API;
// the service rejects a wrong expected revision with REVISION_CONFLICT.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/apiContext";
import type { Run, ValueOrigin } from "@/lib/contract";
import { ApiFailure, errorCode, recoveryFor } from "@/lib/errors";
import { capabilitiesQuery, keys } from "@/lib/queries";
import { isActive } from "@/lib/release";
import type { ParameterChange } from "@/lib/webApi";

export const ORIGIN: Record<ValueOrigin, [string, string]> = {
  source: ["Zeichnung", "bg-info-bg text-info"],
  assumed: ["Annahme", "bg-warn-bg text-bad"],
  user: ["Nutzer", "bg-good-bg text-good"],
};

export function ParametersPanel({ run }: { run: Run }) {
  const part = run.part;
  if (!part) return <p className="text-muted-foreground">Noch keine Teilebeschreibung.</p>;
  // A new revision resets the form to the stored values.
  return <ParameterForm key={part.revision} run={run} />;
}

function ParameterForm({ run }: { run: Run }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const part = run.part!;
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const editable = caps?.parameter_edit === true && part.capabilities.parameter_edit && !isActive(run);

  const changes: ParameterChange[] = Object.entries(drafts)
    .filter(([name, text]) => text !== String(part.parameters.find((p) => p.name === name)?.value))
    .map(([name, text]) => ({ name, value: Number(text.replace(",", ".")) }));

  const change = useMutation({
    mutationFn: () => api.changeParameters(run.run_id, part.revision, changes),
    onSuccess: async (next) => {
      queryClient.setQueryData(keys.run(run.run_id), next);
      await queryClient.invalidateQueries({ queryKey: keys.runs(run.source_id) });
    },
  });
  const conflict = errorCode(change.error) === "REVISION_CONFLICT";
  const badField = change.error instanceof ApiFailure ? change.error.field : null;

  return (
    <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); if (changes.length) change.mutate(); }}>
      <Table>
        <TableHeader>
          <TableRow><TableHead>Parameter</TableHead><TableHead>Merkmal</TableHead><TableHead>Wert</TableHead><TableHead>Herkunft</TableHead></TableRow>
        </TableHeader>
        <TableBody>
          {part.parameters.map((p) => {
            const [origin, tone] = ORIGIN[p.origin];
            return (
              <TableRow key={p.name}>
                <TableCell className="font-mono text-xs">{p.name}</TableCell>
                <TableCell className="text-muted-foreground">{p.feature}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <Input
                      aria-label={p.name} inputMode="decimal" className="h-7 w-24 text-right tabular-nums"
                      disabled={!editable || !p.editable} aria-invalid={badField === p.name}
                      value={drafts[p.name] ?? String(p.value)}
                      onChange={(e) => setDrafts((all) => ({ ...all, [p.name]: e.target.value }))}
                    />
                    <span className="text-xs text-muted-foreground">{p.unit}</span>
                  </div>
                </TableCell>
                <TableCell><Badge variant="secondary" className={tone}>{origin}</Badge></TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      {change.error && (
        <Alert variant="destructive">
          <AlertTitle>{conflict ? "Revision hat sich geändert" : "Änderung abgelehnt"}</AlertTitle>
          <AlertDescription>
            <p>{change.error.message} {recoveryFor(change.error)}</p>
            {conflict && (
              <Button type="button" variant="outline" size="sm" className="mt-1"
                onClick={() => { change.reset(); void queryClient.invalidateQueries({ queryKey: keys.run(run.run_id) }); }}>
                Neu laden
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {!caps?.parameter_edit ? "Der verbundene Dienst erlaubt keine Parameteränderung."
            : isActive(run) ? "Während der Auftrag läuft, sind Änderungen gesperrt."
            : `Änderungen erzeugen Revision ${part.revision + 1}. Bisherige Ergebnisse werden als veraltet markiert.`}
        </p>
        <Button type="submit" size="sm" className="rounded-full" disabled={!editable || !changes.length || change.isPending}>
          Neue Revision erzeugen
        </Button>
      </div>

      <section>
        <h3 className="mb-1.5 text-xs font-semibold tracking-[.06em] text-faint uppercase">Operationen in Reihenfolge</h3>
        <ol className="flex flex-col gap-1">
          {part.operations.map((op) => (
            <li key={op.index} className="flex items-baseline gap-2.5 rounded-md border px-2.5 py-1.5">
              <b className="tabular-nums text-muted-foreground">{op.index}</b>
              <span className="flex-1 font-medium text-card-foreground">{op.label}</span>
              <code className="text-[11px] text-muted-foreground">{op.kind}({op.parameters.join(", ")})</code>
            </li>
          ))}
        </ol>
      </section>
    </form>
  );
}
