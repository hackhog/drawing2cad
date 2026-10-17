import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props { title: ReactNode; subtitle: ReactNode; live?: boolean; actions?: ReactNode }

export function PageHeader({ title, subtitle, live = false, actions }: Props) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-2.5">
      <div className="min-w-0">
        <h1 className="m-0 text-xl font-bold tracking-tight text-card-foreground">{title}</h1>
        <p className={cn("mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground",
          live && "before:size-[7px] before:rounded-full before:bg-good before:content-['']")}>{subtitle}</p>
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}
