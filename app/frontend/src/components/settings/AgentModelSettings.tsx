// Settings section "KI-Modell": select the profile for new runs, and create, change, check, or delete profiles.
// A key goes to the server only when a profile is saved. The server never sends it back, and the browser does not store it.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, Pencil, Plus, Plug, Trash2 } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApi } from "@/lib/apiContext";
import type { AgentApi, AgentProfile, AgentProfileInput, AgentProfiles, AgentProvider, ConnectionCheck } from "@/lib/contract";
import { recoveryFor } from "@/lib/errors";
import { agentProfilesQuery, capabilitiesQuery, keys } from "@/lib/queries";
import { cn } from "@/lib/utils";

interface ProviderText {
  label: string;
  endpoint?: { label: string; placeholder: string; hint: string };
  model: { label: string; placeholder: string };
  key: string;
}

const PROVIDERS: Record<AgentProvider, ProviderText> = {
  openrouter: {
    label: "OpenRouter",
    model: { label: "Modell", placeholder: "anthropic/claude-sonnet-5.5" },
    key: "API-Key von openrouter.ai/keys. Das Modell muss Tool-Aufrufe und Bilder unterstützen.",
  },
  azure: {
    label: "Azure AI Foundry",
    endpoint: {
      label: "Endpunkt der Ressource", placeholder: "https://<ressource>.openai.azure.com",
      hint: "Jede URL der Ressource genügt, auch die Ziel-URI aus dem Portal. Der Server nutzt https://<ressource>/openai/v1.",
    },
    model: { label: "Deployment-Name", placeholder: "gpt-6.1-sol" },
    key: "Schlüssel 1 oder 2 der Ressource (Azure-Portal → Schlüssel und Endpunkt).",
  },
  openai: {
    label: "OpenAI-kompatibel",
    endpoint: { label: "Basis-URL", placeholder: "https://api.openai.com/v1", hint: "Der Server hängt /chat/completions oder /responses an." },
    model: { label: "Modell", placeholder: "gpt-5.6" },
    key: "Wird als Authorization: Bearer gesendet.",
  },
};
const API_LABEL: Record<AgentApi, string> = { chat: "Chat Completions", responses: "Responses API" };
const EFFORTS = ["", "none", "minimal", "low", "medium", "high"];
const NO_AGENT = "Lokal, ohne KI";
const ROW = "flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border px-3 py-2.5 has-[:checked]:border-primary has-[:checked]:bg-highlight-bg";
const SELECT = "h-9 w-full rounded-md border border-input bg-transparent px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50";

type Editing = { name: string | null } | null;

export function AgentModelSettings() {
  const api = useApi();
  const queryClient = useQueryClient();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const profiles = useQuery(agentProfilesQuery(api));
  const [editing, setEditing] = useState<Editing>(null);

  const apply = async (data: AgentProfiles) => {
    queryClient.setQueryData(keys.agentProfiles, data);
    await queryClient.invalidateQueries({ queryKey: keys.capabilities });
  };
  const select = useMutation({
    mutationFn: (name: string | null) => api.selectAgentProfile(name),
    onSuccess: apply,
    onError: (err) => toast.error("Modellprofil nicht gewählt", { description: `${err.message} ${recoveryFor(err)}` }),
  });
  const remove = useMutation({
    mutationFn: (name: string) => api.deleteAgentProfile(name),
    onSuccess: apply,
    onError: (err) => toast.error("Profil nicht gelöscht", { description: `${err.message} ${recoveryFor(err)}` }),
  });

  if (caps?.simulated) return <p className="text-sm">Simulierter Dienst: Läufe nutzen kein Modell.</p>;
  if (profiles.isError) return <p className="text-sm text-flag">Modellprofile nicht geladen. {recoveryFor(profiles.error)}</p>;
  const data = profiles.data;
  const active = select.isPending ? select.variables : data?.active ?? null;
  const edited = editing?.name ? data?.profiles.find((p) => p.name === editing.name) : undefined;

  return (
    <div className="grid max-w-3xl gap-3">
      <Card className="gap-3 rounded-xl px-4 py-3.5 shadow-none">
        <CardHeader className="flex flex-row items-center justify-between px-0">
          <CardTitle className="text-sm font-bold">Profil für neue Läufe</CardTitle>
          <Button size="sm" variant="outline" className="h-7" disabled={!data || editing !== null} onClick={() => setEditing({ name: null })}>
            <Plus className="size-3.5" />Profil hinzufügen
          </Button>
        </CardHeader>
        <CardContent className="px-0">
          <fieldset className="grid gap-2" disabled={!data || select.isPending}>
            <legend className="sr-only">Aktives Modellprofil</legend>
            {data?.profiles.map((profile) => (
              <ProfileRow key={profile.name} profile={profile} checked={active === profile.name}
                onSelect={() => select.mutate(profile.name)} onEdit={() => setEditing({ name: profile.name })}
                onDelete={() => remove.mutate(profile.name)} editing={editing !== null} />
            ))}
            <label className={ROW}>
              <input type="radio" name="agent-profile" className="accent-primary" checked={!!data && active === null}
                onChange={() => select.mutate(null)} />
              <span className="flex-1 text-sm font-semibold">{NO_AGENT}</span>
              <small className="text-[11px] text-muted-foreground">Keine Läufe, nur Zeichnungsanalyse</small>
            </label>
          </fieldset>
          <p className="mt-2.5 text-xs text-muted-foreground">
            Wartende und laufende Läufe behalten ihr Profil. Keys bleiben auf dem Server und werden nie wieder angezeigt.
          </p>
        </CardContent>
      </Card>

      {editing && (
        <ProfileForm key={editing.name ?? "new"} profile={edited} taken={data?.profiles.map((p) => p.name) ?? []}
          onDone={async (result) => { if (result) await apply(result); setEditing(null); }} />
      )}
    </div>
  );
}

function ProfileRow({ profile, checked, editing, onSelect, onEdit, onDelete }: {
  profile: AgentProfile; checked: boolean; editing: boolean; onSelect: () => void; onEdit: () => void; onDelete: () => void;
}) {
  const api = useApi();
  const [confirm, setConfirm] = useState(false);
  const check = useMutation({ mutationFn: () => api.checkAgentProfile(profile.name) });
  return (
    <div className="grid gap-1.5">
      <label className={ROW}>
        <input type="radio" name="agent-profile" className="accent-primary" checked={checked} onChange={onSelect} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-sm font-semibold">
            {profile.name}
            <Badge variant="outline" className="text-[10.5px] font-medium">{PROVIDERS[profile.provider].label}</Badge>
            {profile.origin === "env" && <Badge variant="secondary" className="text-[10.5px] font-medium" title="Aus der Server-Konfiguration (.env), hier nicht änderbar">Server</Badge>}
          </span>
          <small className="block truncate font-mono text-[11px] text-muted-foreground" title={profile.base_url}>
            {profile.model} · {API_LABEL[profile.api]}{profile.reasoning_effort ? ` · reasoning ${profile.reasoning_effort}` : ""}
          </small>
        </span>
        <span className="flex gap-1">
          <Button type="button" size="xs" variant="ghost" disabled={check.isPending} onClick={() => check.mutate()}
            title="Eine kurze Anfrage ohne Werkzeuge an den Endpunkt senden (wenige Tokens)">
            <Plug />{check.isPending ? "Prüfe …" : "Testen"}
          </Button>
          {profile.origin === "ui" && (
            <>
              <Button type="button" size="xs" variant="ghost" disabled={editing} onClick={onEdit}><Pencil />Bearbeiten</Button>
              <Button type="button" size="xs" variant="ghost" className={cn(confirm && "text-flag")}
                onClick={() => (confirm ? onDelete() : setConfirm(true))} onBlur={() => setConfirm(false)}>
                <Trash2 />{confirm ? "Wirklich löschen?" : "Löschen"}
              </Button>
            </>
          )}
        </span>
      </label>
      {check.data && <CheckResult result={check.data} />}
      {check.isError && <CheckResult result={{ ok: false, message: `${check.error.message} ${recoveryFor(check.error)}` }} />}
    </div>
  );
}

function CheckResult({ result }: { result: ConnectionCheck }) {
  const Icon = result.ok ? CircleCheck : CircleX;
  return (
    <p role="status" className={cn("flex items-start gap-1.5 px-3 text-xs [overflow-wrap:anywhere]", result.ok ? "text-good" : "text-flag")}>
      <Icon className="mt-px size-3.5 flex-none" />
      {result.ok ? `Verbindung in Ordnung (${result.latency_ms} ms). Antwort: ${result.message || "(leer)"}` : result.message}
    </p>
  );
}

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="text-xs font-semibold">{label}</Label>
      {children}
      {hint && <small className="text-[11px] text-muted-foreground">{hint}</small>}
    </div>
  );
}

function ProfileForm({ profile, taken, onDone }: {
  profile?: AgentProfile; taken: string[]; onDone: (result: AgentProfiles | null) => Promise<void>;
}) {
  const api = useApi();
  const [name, setName] = useState(profile?.name ?? "");
  const [form, setForm] = useState<AgentProfileInput>({
    provider: profile?.provider ?? "openrouter", endpoint: profile?.provider === "openrouter" ? "" : profile?.base_url ?? "",
    model: profile?.model ?? "", api: profile?.api ?? "chat", api_key: "", reasoning_effort: profile?.reasoning_effort ?? null,
  });
  const save = useMutation({
    mutationFn: () => api.saveAgentProfile(name.trim(), form),
    onSuccess: (result) => { toast.success(`Profil „${name.trim()}“ gespeichert`); void onDone(result); },
    onError: (err) => toast.error("Profil nicht gespeichert", { description: `${err.message} ${recoveryFor(err)}` }),
  });
  const text = PROVIDERS[form.provider];
  const set = (change: Partial<AgentProfileInput>) => setForm((current) => ({ ...current, ...change }));
  const duplicate = !profile && taken.includes(name.trim());
  const submit = (evt: FormEvent) => { evt.preventDefault(); save.mutate(); };

  return (
    <Card className="gap-3 rounded-xl px-4 py-3.5 shadow-none">
      <CardHeader className="px-0">
        <CardTitle className="text-sm font-bold">{profile ? `Profil „${profile.name}“ bearbeiten` : "Neues Profil"}</CardTitle>
      </CardHeader>
      <CardContent className="px-0">
        <form className="grid gap-3.5" onSubmit={submit} autoComplete="off">
          <fieldset className="grid gap-1.5">
            <legend className="mb-1.5 text-xs font-semibold">Anbieter</legend>
            <div className="flex flex-wrap gap-1.5">
              {(Object.keys(PROVIDERS) as AgentProvider[]).map((provider) => (
                <label key={provider} className="cursor-pointer rounded-full border px-3 py-1 text-xs font-medium has-[:checked]:border-primary has-[:checked]:bg-primary has-[:checked]:text-primary-foreground">
                  <input type="radio" name="provider" className="sr-only" checked={form.provider === provider}
                    onChange={() => set({ provider, api: provider === "openrouter" ? "chat" : form.api })} />
                  {PROVIDERS[provider].label}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="grid grid-cols-2 gap-3 max-[700px]:grid-cols-1">
            <Field id="profile-name" label="Name" hint={duplicate ? "Diesen Namen gibt es schon." : "Erscheint in der Seitenleiste und im Lauf."}>
              <Input id="profile-name" value={name} required maxLength={40} disabled={!!profile} aria-invalid={duplicate}
                placeholder={text.label} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field id="profile-model" label={text.model.label}>
              <Input id="profile-model" value={form.model} required placeholder={text.model.placeholder} className="font-mono"
                onChange={(e) => set({ model: e.target.value })} />
            </Field>
          </div>
          {text.endpoint && (
            <Field id="profile-endpoint" label={text.endpoint.label} hint={text.endpoint.hint}>
              <Input id="profile-endpoint" type="url" value={form.endpoint} required placeholder={text.endpoint.placeholder}
                className="font-mono" onChange={(e) => set({ endpoint: e.target.value })} />
            </Field>
          )}
          <Field id="profile-key" label="API-Key" hint={text.key}>
            <Input id="profile-key" type="password" value={form.api_key} required={!profile?.key_set} autoComplete="new-password"
              placeholder={profile?.key_set ? "Gespeichert – leer lassen, um ihn zu behalten" : ""} className="font-mono"
              onChange={(e) => set({ api_key: e.target.value })} />
          </Field>
          {form.provider !== "openrouter" && (
            <div className="grid grid-cols-2 gap-3 max-[700px]:grid-cols-1">
              <Field id="profile-api" label="Schnittstelle" hint="Manche Modelle (zum Beispiel gpt-6.1-sol) nutzen Werkzeuge nur über die Responses API.">
                <select id="profile-api" className={SELECT} value={form.api} onChange={(e) => set({ api: e.target.value as AgentApi })}>
                  {(Object.keys(API_LABEL) as AgentApi[]).map((value) => <option key={value} value={value}>{API_LABEL[value]}</option>)}
                </select>
              </Field>
              <Field id="profile-effort" label="Reasoning-Aufwand" hint="Optional. Leer sendet keinen Wert.">
                <select id="profile-effort" className={SELECT} value={form.reasoning_effort ?? ""}
                  onChange={(e) => set({ reasoning_effort: e.target.value || null })}>
                  {EFFORTS.map((value) => <option key={value} value={value}>{value || "—"}</option>)}
                </select>
              </Field>
            </div>
          )}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={save.isPending || duplicate}>{save.isPending ? "Speichere …" : "Speichern"}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => void onDone(null)}>Abbrechen</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
