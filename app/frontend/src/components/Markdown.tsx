// Read-only Markdown view for agent reports and notes (ADR 0023). GitHub Markdown adds tables and task lists.
// Raw HTML in the text stays escaped, so a note cannot inject markup into the page.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("markdown", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
