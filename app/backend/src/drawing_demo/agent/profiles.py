"""Model profiles of the agent runner and the active profile (ADR 0020).

Profiles come from the server environment (read-only) or from the web UI. The store keeps UI profiles and the active
selection in one JSON file in the data directory, with owner-only permissions. API keys go from the browser to the
server only when a profile is saved; no response contains a key.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Literal
from urllib.parse import urlsplit

from ..service import ServiceError
from .model import ModelSettings, profiles_from_env

Provider = Literal["openrouter", "azure", "openai"]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# A UI name is a path segment and a label; environment names have the stricter rule of model.PROFILE_NAME.
PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}")
REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high"}


@dataclass(frozen=True)
class Profile:
    settings: ModelSettings
    provider: Provider
    # "env" profiles come from DRAWING2CAD_AGENT_*; only "ui" profiles can change.
    origin: Literal["env", "ui"]

    def view(self, name: str) -> dict[str, Any]:
        """The profile for the browser: everything except the key."""
        s = self.settings
        return {"name": name, "provider": self.provider, "origin": self.origin, "base_url": s.base_url, "model": s.model,
                "api": s.api, "reasoning_effort": s.reasoning_effort, "key_set": bool(s.api_key)}


def provider_of(settings: ModelSettings) -> Provider:
    host = urlsplit(settings.base_url).hostname or ""
    if host == "openrouter.ai":
        return "openrouter"
    if host.endswith(".azure.com") or settings.api_key_header.lower() == "api-key":
        return "azure"
    return "openai"


def endpoint_for(provider: Provider, endpoint: str) -> str:
    """The OpenAI-compatible base URL for the endpoint that a user enters.

    Azure AI Foundry: any URL of the resource (for example the target URI from the portal) becomes
    `https://<resource>.../openai/v1`. OpenRouter has one fixed endpoint.
    """
    if provider == "openrouter":
        return OPENROUTER_BASE_URL
    parts = urlsplit(endpoint.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise ServiceError(422, "INVALID_PROFILE", "Der Endpunkt muss eine https-URL sein.", field="endpoint",
                           recovery="Die URL der Ressource eintragen, zum Beispiel https://<ressource>.openai.azure.com.")
    if provider == "azure":
        return f"https://{parts.netloc}/openai/v1"
    return f"https://{parts.netloc}{parts.path}".rstrip("/")


class ProfileStore:
    """Environment profiles, UI profiles, and the active profile. Safe for use from several threads."""

    def __init__(self, path: Path, env_profiles: dict[str, ModelSettings] | None = None):
        self.path = path
        self._lock = threading.Lock()
        env = profiles_from_env() if env_profiles is None else env_profiles
        self._profiles: dict[str, Profile] = {name: Profile(s, provider_of(s), "env") for name, s in env.items()}
        stored = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        for name, data in stored.get("profiles", {}).items():
            if name not in self._profiles:
                self._profiles[name] = Profile(ModelSettings(**data["settings"]), data["provider"], "ui")
        # Without a stored selection, the first profile is active. A stored null means "no agent".
        active = stored["active"] if "active" in stored else next(iter(self._profiles), None)
        self._active: str | None = active if active in self._profiles else next(iter(self._profiles), None)

    @property
    def active(self) -> str | None:
        return self._active

    def get(self, name: str | None) -> ModelSettings | None:
        with self._lock:
            profile = self._profiles.get(name) if name is not None else None
            return profile.settings if profile else None

    def view(self) -> dict[str, Any]:
        with self._lock:
            return {"active": self._active, "profiles": [p.view(n) for n, p in self._profiles.items()]}

    def select(self, name: str | None) -> None:
        with self._lock:
            if name is not None and name not in self._profiles:
                raise ServiceError(422, "UNKNOWN_PROFILE", f"Unbekanntes Modellprofil: {name}", field="name",
                                   recovery="Ein Profil aus der Liste der Einstellungen wählen.")
            self._active = name
            self._save()

    def save(self, name: str, provider: Provider, endpoint: str, model: str, api: str, api_key: str | None,
             reasoning_effort: str | None) -> None:
        """Create or change a UI profile. Without `api_key`, a changed profile keeps its key."""
        if not PROFILE_NAME.fullmatch(name):
            raise ServiceError(422, "INVALID_PROFILE", "Der Name braucht 1 bis 40 Zeichen: Buchstaben, Ziffern, Leerzeichen, . _ -.",
                               field="name")
        if not model.strip():
            raise ServiceError(422, "INVALID_PROFILE", "Das Modell fehlt.", field="model",
                               recovery="Bei Azure AI Foundry den Namen des Deployments eintragen.")
        if api not in ("chat", "responses"):
            raise ServiceError(422, "INVALID_PROFILE", "Die Schnittstelle muss chat oder responses sein.", field="api")
        if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
            raise ServiceError(422, "INVALID_PROFILE", "Unbekannter Reasoning-Aufwand.", field="reasoning_effort")
        base_url = endpoint_for(provider, endpoint)
        with self._lock:
            current = self._profiles.get(name)
            if current and current.origin == "env":
                raise ServiceError(409, "PROFILE_READ_ONLY", f"Das Profil {name} kommt aus der Server-Konfiguration.",
                                   field="name", recovery="Einen anderen Namen wählen oder die .env des Servers ändern.")
            key = (api_key or "").strip() or (current.settings.api_key if current else "")
            if not key:
                raise ServiceError(422, "INVALID_PROFILE", "Der API-Key fehlt.", field="api_key")
            header = "api-key" if provider == "azure" else "Authorization"
            settings = ModelSettings(base_url, model.strip(), key, header, reasoning_effort, api)
            self._profiles[name] = Profile(settings, provider, "ui")
            if self._active is None and len(self._profiles) == 1:
                self._active = name
            self._save()

    def delete(self, name: str) -> None:
        with self._lock:
            profile = self._profiles.get(name)
            if profile is None:
                raise ServiceError(404, "NOT_FOUND", f"Unbekanntes Modellprofil: {name}")
            if profile.origin == "env":
                raise ServiceError(409, "PROFILE_READ_ONLY", f"Das Profil {name} kommt aus der Server-Konfiguration.",
                                   recovery="Das Profil in der .env des Servers entfernen.")
            del self._profiles[name]
            if self._active == name:
                self._active = next(iter(self._profiles), None)
            self._save()

    def _save(self) -> None:
        """Write UI profiles and the selection atomically. Only the owner can read the file, because it holds keys."""
        data = {"active": self._active, "profiles": {
            name: {"provider": p.provider, "settings": asdict(p.settings)}
            for name, p in self._profiles.items() if p.origin == "ui"}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, self.path)
