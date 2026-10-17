import { Plus } from "lucide-react";
import { useState } from "react";
import { dropTarget } from "@/lib/drop";
import { isPdf, useUploads } from "@/lib/uploads";
import { cn } from "@/lib/utils";

/** Select or drop several PDFs. Uploads start at once and show their progress in the overview. */
export function UploadButton({ label }: { label: string }) {
  const { addFiles } = useUploads();
  const [over, setOver] = useState(false);
  const take = (files: File[]) => addFiles(files.filter(isPdf));
  return (
    <label
      {...dropTarget(take, setOver)}
      className={cn("relative inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full bg-primary px-3.5 text-[12.5px] font-semibold text-primary-foreground hover:bg-primary/90",
        "focus-within:ring-[3px] focus-within:ring-ring/50", over && "ring-4 ring-primary/15")}
    >
      <input
        type="file" accept="application/pdf,.pdf" multiple className="absolute inset-0 cursor-pointer opacity-0"
        onChange={(e) => { take([...(e.target.files ?? [])]); e.target.value = ""; }}
      />
      <Plus className="size-3.5" />{label}
    </label>
  );
}
