// Status colors of the established UI: wait, run, done, flag (to review), error.
import type { Tone } from "@/lib/status";
import { cn } from "@/lib/utils";

const BADGE: Record<Tone, string> = {
  wait: "bg-muted text-muted-foreground",
  run: "bg-run-bg text-run",
  done: "bg-good-bg text-good",
  flag: "bg-warn-bg text-bad",
  error: "bg-flag-bg text-flag",
};
const DOT: Record<Tone, string> = {
  wait: "bg-faint", run: "bg-run dot-run", done: "bg-good", flag: "bg-highlight", error: "bg-flag",
};

export const StatusDot = ({ tone, className }: { tone: Tone; className?: string }) =>
  <span aria-hidden="true" className={cn("size-[7px] flex-none rounded-full", DOT[tone], className)} />;

export function StatusBadge({ tone, children, title }: { tone: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold whitespace-nowrap", BADGE[tone])}>
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />{children}
    </span>
  );
}
