// Dialog of "Start run": choose the model profile for one run. The active profile of the settings does not change.
import { Play } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { AgentProfile } from "@/lib/contract";
import { PROVIDER_LABEL, unusableReason } from "@/lib/runStart";
import { cn } from "@/lib/utils";

const ROW = "flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 has-[:checked]:border-primary has-[:checked]:bg-highlight-bg has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60";

export function RunStartDialog({ open, onOpenChange, profiles, active, selected, onSelect, canStart, pending, onStart }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  profiles: AgentProfile[];
  active: string | null;
  selected: string | null;
  onSelect: (name: string) => void;
  canStart: boolean;
  pending: boolean;
  onStart: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Start a CAD run</DialogTitle>
          <DialogDescription>
            Choose the model for this run. The default profile in the settings does not change.
          </DialogDescription>
        </DialogHeader>
        <fieldset className="grid gap-2" disabled={pending}>
          <legend className="sr-only">Model profile for the run</legend>
          {profiles.map((profile) => {
            const reason = unusableReason(profile);
            return (
              <label key={profile.name} className={ROW}>
                <input type="radio" name="run-profile" className="mt-1 accent-primary" value={profile.name}
                  checked={selected === profile.name} disabled={!!reason} onChange={() => onSelect(profile.name)} />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
                    {profile.name}
                    <Badge variant="outline" className="text-[10.5px] font-medium">{PROVIDER_LABEL[profile.provider]}</Badge>
                    {profile.name === active && <Badge variant="secondary" className="text-[10.5px] font-medium">Default</Badge>}
                  </span>
                  <span className="block font-mono text-xs [overflow-wrap:anywhere] text-muted-foreground">
                    {profile.model}{profile.reasoning_effort ? ` · reasoning ${profile.reasoning_effort}` : ""}
                  </span>
                  {reason && <span className={cn("block text-xs text-flag")}>{reason}</span>}
                </span>
              </label>
            );
          })}
        </fieldset>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="ghost" size="sm" disabled={pending}>Cancel</Button>
          </DialogClose>
          <Button type="button" size="sm" disabled={!canStart || pending} onClick={onStart}>
            <Play className="size-3" />{pending ? "Starting …" : "Start run"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
