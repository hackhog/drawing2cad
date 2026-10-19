// Settings section "AI model": select the profile for new runs, and create, change, check, or delete profiles.
// A key goes to the server only when a profile is saved. The server encrypts it, never sends it back, and the browser
// does not store it. Each change sends the revision that the browser read, so a stale change fails (ADR 0028).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, CircleCheck, CircleX, LockKeyhole, Pencil, Plus, Plug, Trash2 } from "lucide-react";
import { useState, type ComponentProps, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApi } from "@/lib/apiContext";
import type {
  AgentApi, AgentLimitName, AgentLimits, AgentProfile, AgentProfileInput, AgentProfiles, AgentProvider, ConnectionCheck,
} from "@/lib/contract";
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
    model: { label: "Model", placeholder: "openai/gpt-6.1-sol" },
    key: "API key from openrouter.ai/keys. The model must support tool calls and images.",
  },
  azure: {
    label: "Azure AI Foundry",
    endpoint: {
      label: "Resource endpoint", placeholder: "https://<resource>.openai.azure.com",
      hint: "Any URL of the resource works, including the target URI from the portal. The server uses https://<resource>/openai/v1.",
    },
    model: { label: "Deployment-Name", placeholder: "gpt-6.1-sol" },
    key: "Key 1 or 2 of the resource (Azure portal → Keys and Endpoint).",
  },
  openai: {
    label: "OpenAI-compatible",
    endpoint: { label: "Base URL", placeholder: "https://api.openai.com/v1", hint: "The server appends /chat/completions or /responses." },
    model: { label: "Model", placeholder: "gpt-5.6" },
    key: "Sent as Authorization: Bearer.",
  },
};
const API_LABEL: Record<AgentApi, string> = { chat: "Chat Completions", responses: "Responses API" };
const LIMIT_LABEL: Record<AgentLimitName, string> = {
  step_budget: "Tool requests", max_turns: "Model turns", model_timeout_seconds: "Model call (s)",
  call_timeout_seconds: "Tool call (s)", total_timeout_seconds: "Run (s)", max_tool_text_chars: "Tool result (characters)",
};
const EFFORTS = ["", "none", "minimal", "low", "medium", "high"];
const NO_AGENT = "Local, no AI";
const ROW = "flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border px-3 py-2.5 has-[:checked]:border-primary has-[:checked]:bg-highlight-bg";
// Same height, border, and focus ring as Input; the own chevron replaces the native arrow of each browser.
const SELECT = "h-9 w-full appearance-none rounded-md border border-input bg-transparent pr-9 pl-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50";

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
    mutationFn: (name: string | null) => api.selectAgentProfile(name, profiles.data?.active_revision),
    onSuccess: apply,
    onError: (err) => toast.error("Model profile not selected", { description: `${err.message} ${recoveryFor(err)}` }),
  });
  const remove = useMutation({
    mutationFn: (profile: AgentProfile) => api.deleteAgentProfile(profile.name, profile.revision),
    onSuccess: apply,
    onError: (err) => toast.error("Profile not deleted", { description: `${err.message} ${recoveryFor(err)}` }),
  });

  if (caps?.simulated) return <p className="text-sm">Simulated service: runs use no model.</p>;
  if (profiles.isError) return <p className="text-sm text-flag">Model profiles not loaded. {recoveryFor(profiles.error)}</p>;
  const data = profiles.data;
  const active = select.isPending ? select.variables : data?.active ?? null;
  const edited = editing?.name ? data?.profiles.find((p) => p.name === editing.name) : undefined;
  // Older servers do not report the master key; they store keys without it.
  const canStoreKeys = data?.master_key_set !== false;

  return (
    <div className="grid max-w-3xl gap-3">
      <Card className="gap-3 rounded-xl px-4 py-3.5 shadow-none">
        <CardHeader className="flex flex-row items-center justify-between px-0">
          <CardTitle className="text-sm font-bold">Profile for new runs</CardTitle>
          <Button size="sm" variant="outline" className="h-7" disabled={!data || editing !== null || !canStoreKeys}
            title={canStoreKeys ? undefined : "The server has no master key for API keys"} onClick={() => setEditing({ name: null })}>
            <Plus className="size-3.5" />Add profile
          </Button>
        </CardHeader>
        <CardContent className="px-0">
          <fieldset className="grid gap-2" disabled={!data || select.isPending}>
            <legend className="sr-only">Active model profile</legend>
            {data?.profiles.map((profile) => (
              <ProfileRow key={profile.name} profile={profile} checked={active === profile.name}
                onSelect={() => select.mutate(profile.name)} onEdit={() => setEditing({ name: profile.name })}
                onDelete={() => remove.mutate(profile)} editing={editing !== null} />
            ))}
            <label className={ROW}>
              <input type="radio" name="agent-profile" className="accent-primary" checked={!!data && active === null}
                onChange={() => select.mutate(null)} />
              <span className="flex-1 text-sm font-semibold">{NO_AGENT}</span>
              <small className="text-[11px] text-muted-foreground">No runs, drawing analysis only</small>
            </label>
          </fieldset>
          <p className="mt-2.5 text-xs text-muted-foreground">
            Queued and running runs keep their profile. Keys stay encrypted on the server and are never shown again.
          </p>
          {!canStoreKeys && (
            <p role="status" className="mt-1.5 text-xs text-flag">
              The server has no master key, so it cannot store API keys from this page. Profiles from the server
              configuration still work. Set DRAWING2CAD_SECRET_KEY_FILE or DRAWING2CAD_SECRET_KEY on the server and restart it.
            </p>
          )}
        </CardContent>
      </Card>

      {editing && (
        <ProfileForm key={editing.name ?? "new"} profile={edited} taken={data?.profiles.map((p) => p.name) ?? []}
          limits={data?.limits}
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
            {profile.origin === "env" && <Badge variant="secondary" className="text-[10.5px] font-medium" title="From the server configuration (.env), cannot be changed here">Server</Badge>}
            {profile.key_locked && (
              <Badge variant="outline" className="border-flag text-[10.5px] font-medium text-flag"
                title="The server cannot decrypt the stored key, for example after a change of its master key. Enter the key again.">
                <LockKeyhole className="size-3" />Key locked
              </Badge>
            )}
          </span>
          <small className="block truncate font-mono text-[11px] text-muted-foreground" title={profile.base_url}>
            {profile.model} · {API_LABEL[profile.api]}{profile.reasoning_effort ? ` · reasoning ${profile.reasoning_effort}` : ""}
            {Object.keys(profile.limits ?? {}).length > 0 ? " · own limits" : ""}
          </small>
        </span>
        <span className="flex gap-1">
          <Button type="button" size="xs" variant="ghost" disabled={check.isPending} onClick={() => check.mutate()}
            title="Send a short request with one tool to the endpoint (a few tokens)">
            <Plug />{check.isPending ? "Checking …" : "Test"}
          </Button>
          {profile.origin === "ui" && (
            <>
              <Button type="button" size="xs" variant="ghost" disabled={editing} onClick={onEdit}><Pencil />Edit</Button>
              <Button type="button" size="xs" variant="ghost" className={cn(confirm && "text-flag")}
                onClick={() => (confirm ? onDelete() : setConfirm(true))} onBlur={() => setConfirm(false)}>
                <Trash2 />{confirm ? "Really delete?" : "Delete"}
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
      {result.ok ? `Connection OK (${result.latency_ms} ms). Response: ${result.message || "(empty)"}` : result.message}
    </p>
  );
}

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    // content-start: fields in one row keep their label and input at the same height, also when only one has a hint.
    <div className="grid content-start gap-1.5">
      <Label htmlFor={id} className="text-xs font-semibold">{label}</Label>
      {children}
      {hint && <small className="text-[11px] text-muted-foreground">{hint}</small>}
    </div>
  );
}

function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <div className="relative">
      <select className={cn(SELECT, className)} {...props} />
      <ChevronDown aria-hidden="true" className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}

function ProfileForm({ profile, taken, limits, onDone }: {
  profile?: AgentProfile; taken: string[]; limits?: AgentProfiles["limits"]; onDone: (result: AgentProfiles | null) => Promise<void>;
}) {
  const api = useApi();
  const [name, setName] = useState(profile?.name ?? "");
  const [form, setForm] = useState<AgentProfileInput>({
    provider: profile?.provider ?? "openrouter", endpoint: profile?.provider === "openrouter" ? "" : profile?.base_url ?? "",
    model: profile?.model ?? "", api: profile?.api ?? "chat", api_key: "", reasoning_effort: profile?.reasoning_effort ?? null,
    limits: { ...profile?.limits }, revision: profile?.revision ?? null,
  });
  const save = useMutation({
    mutationFn: () => api.saveAgentProfile(name.trim(), form),
    onSuccess: (result) => { toast.success(`Profile “${name.trim()}” saved`); void onDone(result); },
    onError: (err) => toast.error("Profile not saved", { description: `${err.message} ${recoveryFor(err)}` }),
  });
  const text = PROVIDERS[form.provider];
  const set = (change: Partial<AgentProfileInput>) => setForm((current) => ({ ...current, ...change }));
  const duplicate = !profile && taken.includes(name.trim());
  const submit = (evt: FormEvent) => { evt.preventDefault(); save.mutate(); };

  return (
    <Card className="gap-3 rounded-xl px-4 py-3.5 shadow-none">
      <CardHeader className="px-0">
        <CardTitle className="text-sm font-bold">{profile ? `Edit profile “${profile.name}”` : "New profile"}</CardTitle>
      </CardHeader>
      <CardContent className="px-0">
        <form className="grid gap-3.5" onSubmit={submit} autoComplete="off">
          <fieldset className="grid gap-1.5">
            <legend className="mb-1.5 text-xs font-semibold">Provider</legend>
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
            <Field id="profile-name" label="Name" hint={duplicate ? "This name already exists." : "Shown in the sidebar and in the run."}>
              <Input id="profile-name" value={name} required maxLength={40} disabled={!!profile} aria-invalid={duplicate}
                placeholder={text.label} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field id="profile-model" label={text.model.label}>
              <Input id="profile-model" value={form.model} required placeholder={text.model.placeholder}
                onChange={(e) => set({ model: e.target.value })} />
            </Field>
          </div>
          {text.endpoint && (
            <Field id="profile-endpoint" label={text.endpoint.label} hint={text.endpoint.hint}>
              <Input id="profile-endpoint" type="url" value={form.endpoint} required placeholder={text.endpoint.placeholder}
                onChange={(e) => set({ endpoint: e.target.value })} />
            </Field>
          )}
          <Field id="profile-key" label="API-Key" hint={profile?.key_locked ? "The stored key is locked. Enter it again." : text.key}>
            <Input id="profile-key" type="password" value={form.api_key} required={!profile?.key_set || !!profile.key_locked}
              autoComplete="new-password" placeholder={profile?.key_set && !profile.key_locked ? "Saved – leave empty to keep it" : ""}
              onChange={(e) => set({ api_key: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3 max-[700px]:grid-cols-1">
            {form.provider !== "openrouter" && (
              <Field id="profile-api" label="Interface" hint="Some models (for example gpt-6.1-sol) use tools only through the Responses API.">
                <Select id="profile-api" value={form.api} onChange={(e) => set({ api: e.target.value as AgentApi })}>
                  {(Object.keys(API_LABEL) as AgentApi[]).map((value) => <option key={value} value={value}>{API_LABEL[value]}</option>)}
                </Select>
              </Field>
            )}
            <Field id="profile-effort" label="Reasoning effort" hint="Optional. Empty sends no value. “Test” checks it together with a tool.">
              <Select id="profile-effort" value={form.reasoning_effort ?? ""}
                onChange={(e) => set({ reasoning_effort: e.target.value || null })}>
                {EFFORTS.map((value) => <option key={value} value={value}>{value || "—"}</option>)}
              </Select>
            </Field>
          </div>
          {limits && <LimitFields limits={limits} value={form.limits ?? {}} onChange={(value) => set({ limits: value })} />}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={save.isPending || duplicate}>{save.isPending ? "Saving …" : "Save"}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => void onDone(null)}>Cancel</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function LimitFields({ limits, value, onChange }: {
  limits: NonNullable<AgentProfiles["limits"]>; value: AgentLimits; onChange: (value: AgentLimits) => void;
}) {
  const names = Object.keys(LIMIT_LABEL) as AgentLimitName[];
  return (
    <details className="rounded-lg border px-3 py-2" open={names.some((name) => value[name] != null)}>
      <summary className="cursor-pointer text-xs font-semibold">Run limits</summary>
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        Empty uses the server default. A small local model can need fewer tool requests and longer model calls.
      </p>
      <div className="mt-2 grid grid-cols-3 gap-3 max-[700px]:grid-cols-1">
        {names.map((name) => (
          <Field key={name} id={`limit-${name}`} label={LIMIT_LABEL[name]} hint={`Default ${limits.defaults[name]}, max. ${limits.maximums[name]}`}>
            <Input id={`limit-${name}`} type="number" inputMode="numeric" min={1} max={limits.maximums[name]} step={1}
              value={value[name] ?? ""} placeholder={String(limits.defaults[name])}
              onChange={(e) => onChange({ ...value, [name]: e.target.value === "" ? null : Number(e.target.value) })} />
          </Field>
        ))}
      </div>
    </details>
  );
}
