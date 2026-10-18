import { Link } from "@tanstack/react-router";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { errorCode, recoveryFor } from "@/lib/errors";

interface Props { title: string; error?: unknown; onRetry?: () => void }

/** Actionable error message: what failed, the stable code, and what the user can do. */
export function ErrorState({ title, error, onRetry }: Props) {
  const message = error instanceof Error ? error.message : null;
  return (
    <div role="alert" className="mx-auto mt-16 flex max-w-md flex-col items-center gap-3 text-center">
      <span className="grid size-10 place-items-center rounded-lg bg-flag-bg text-flag"><AlertTriangle className="size-5" /></span>
      <h2 className="text-base font-bold text-card-foreground">{title}</h2>
      {message && <p className="text-muted-foreground">{message}</p>}
      <p className="text-sm">{error ? recoveryFor(error) : "The address is unknown."}</p>
      {error !== undefined && <code className="rounded bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{errorCode(error)}</code>}
      <div className="flex gap-2">
        {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>Try again</Button>}
        <Button size="sm" asChild><Link to="/">To overview</Link></Button>
      </div>
    </div>
  );
}
