export interface Toast { id: number; title: string; detail: string; tone: "good" | "warn" | "bad"; out: boolean }

export function Toasts({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.tone}${t.out ? " out" : ""}`}>
          <strong>{t.title}</strong><span>{t.detail}</span>
        </div>
      ))}
    </div>
  );
}
