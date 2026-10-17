// Deletes a drawing after a second click, so that one stray click removes nothing.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/apiContext";
import type { Source } from "@/lib/contract";
import { recoveryFor } from "@/lib/errors";
import { partName } from "@/lib/format";
import { keys } from "@/lib/queries";
import { cn } from "@/lib/utils";

interface Props {
  source: Source;
  /** "row": icon in a table row; "header": labeled button in a page header. */
  variant?: "row" | "header";
  /** Runs after the deletion and before the cache cleanup, e.g. to leave the page of the deleted drawing. */
  onDeleted?: () => Promise<void> | void;
}

export function DeleteSourceButton({ source, variant = "row", onDeleted }: Props) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [armed, setArmed] = useState(false);
  const name = partName(source.filename);
  const remove = useMutation({
    mutationFn: () => api.deleteSource(source.source_id),
    onSuccess: async () => {
      await onDeleted?.();
      // Refresh the list first: its rows observe the analysis, which would otherwise be read again and fail.
      await queryClient.invalidateQueries({ queryKey: keys.sources, exact: true });
      for (const key of [keys.source(source.source_id), keys.analysis(source.source_id), keys.runs(source.source_id)]) {
        queryClient.removeQueries({ queryKey: key });
      }
      toast.success(`${name} gelöscht`);
    },
    onError: (err) => toast.error(`${name} nicht gelöscht`, { description: `${err.message} ${recoveryFor(err)}` }),
    onSettled: () => setArmed(false),
  });
  const row = variant === "row";
  // A table row opens the drawing on click and Enter; the button handles its own events.
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  return (
    <span onClick={stop} onKeyDown={stop}>
      {armed ? (
        <Button variant="destructive" size={row ? "xs" : "sm"} className={cn(!row && "rounded-full")} autoFocus disabled={remove.isPending}
          onBlur={() => !remove.isPending && setArmed(false)} onClick={() => remove.mutate()}>
          {row ? "Löschen" : <><Trash2 />Wirklich löschen</>}
        </Button>
      ) : row ? (
        <Button variant="ghost" size="icon" className="size-7 text-muted-foreground" aria-label={`${name} löschen`} title="Zeichnung löschen"
          onClick={() => setArmed(true)}>
          <Trash2 className="size-3.5" />
        </Button>
      ) : (
        <Button variant="outline" size="sm" className="rounded-full" onClick={() => setArmed(true)}>
          <Trash2 />Löschen
        </Button>
      )}
    </span>
  );
}
