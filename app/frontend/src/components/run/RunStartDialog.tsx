// Dialog of "Start run": choose the model profile for one run. The active profile of the settings does not change.
import { Play } from "lucide-react";
import type { RefObject } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { AgentProfile } from "@/lib/contract";
import { PROVIDER_LABEL, unusableReason } from "@/lib/runStart";

const ROW = "flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 has-[:checked]:border-primary has-[:checked]:bg-highlight-bg has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60";

/** The profiles as one radio group. A profile without a usable key is disabled and names the reason. */
export function RunProfileOptions({ profiles, active, selected, onSelect, disabled }: {
  profiles: AgentProfile[];
  active: string | null;
  selected: string | null;
  onSelect: (name: string) => void;
  disabled: boolean;
}) {
  return (
    <fieldset className="grid gap-2" disabled={disabled}>
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
              {reason && <span className="block text-xs text-flag">{reason}</span>}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

export function RunStartDialog({ open, onOpenChange, profiles, active, selected, onSelect, canStart, pending, onStart, returnFocus }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  profiles: AgentProfile[];
  active: string | null;
  selected: string | null;
  onSelect: (name: string) => void;
  canStart: boolean;
  pending: boolean;
  onStart: () => void;
  /** The button that opened the dialog. A controlled dialog has no trigger, so it returns the focus here. */
  returnFocus: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg"
        onCloseAutoFocus={(event) => { event.preventDefault(); returnFocus.current?.focus(); }}>
        <DialogHeader>
          <DialogTitle>Start a CAD run</DialogTitle>
          <DialogDescription>
            Choose the model for this run. The default profile in the settings does not change.
          </DialogDescription>
        </DialogHeader>
        <RunProfileOptions profiles={profiles} active={active} selected={selected} onSelect={onSelect} disabled={pending} />
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
