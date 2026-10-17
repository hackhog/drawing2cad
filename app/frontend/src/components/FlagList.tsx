import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ReviewFlag } from "@/lib/drawing";
import { FLAG_KIND } from "@/lib/kinds";
import { cn } from "@/lib/utils";

interface Props { flags: ReviewFlag[]; active: ReviewFlag | null; highlight: boolean; onSelect: (flag: ReviewFlag) => void }

/** Review list in the style of a change list: a click zooms the sheet to the location. */
export function FlagList({ flags, active, highlight, onSelect }: Props) {
  return (
    <Card className={cn("min-h-0 gap-2.5 rounded-xl px-3.5 pt-3 pb-3.5 shadow-none transition-shadow", highlight && "border-warn-line ring-3 ring-warn-bg")}>
      <CardHeader className="flex flex-row items-center justify-between px-0">
        <CardTitle className="text-sm font-bold">
          Prüfen
          {flags.length > 0 && <span className="ml-1 rounded-full border border-warn-line bg-warn-bg px-1.5 py-px text-[11px] text-bad">{flags.length}</span>}
        </CardTitle>
        <span className="rounded-full bg-info-bg px-2.5 py-0.5 text-[11px] font-semibold text-info">Liste</span>
      </CardHeader>
      <CardContent className="overflow-y-auto px-0">
        <ul>
          {!flags.length && <li className="px-1.5 py-2 text-muted-foreground">Nichts zu prüfen.</li>}
          {flags.map((f, i) => f.bbox ? (
            <li key={i}>
              <button type="button" onClick={() => onSelect(f)} aria-pressed={f === active}
                className="flex w-full items-start gap-2.5 rounded-md border-b px-1.5 py-2 text-left last:border-b-0 hover:bg-accent aria-pressed:bg-[#fff1f0]">
                <i className={cn("mt-[5px] size-[7px] flex-none rounded-full", f.kind === "unreadable_text" ? "bg-run" : "bg-highlight")} />
                <span className="flex min-w-0 flex-1 flex-col">
                  <strong className="truncate font-semibold text-card-foreground">{f.message}</strong>
                  <span className="text-xs text-muted-foreground">{FLAG_KIND[f.kind] ?? f.kind}</span>
                </span>
                <time className="text-[11.5px] whitespace-nowrap text-muted-foreground">x {Math.round(f.bbox[0])} · y {Math.round(f.bbox[1])}</time>
              </button>
            </li>
          ) : <li key={i} className="px-1.5 py-2 text-muted-foreground">{f.message}</li>)}
        </ul>
      </CardContent>
    </Card>
  );
}
