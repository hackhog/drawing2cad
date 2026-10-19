"""Model profiles of the agent runner, the active profile, and run limits (ADR 0020, ADR 0028).

Profiles come from the server environment (read-only) or from the web UI. The SQLite configuration store keeps the UI
profiles, their run limits, and the active selection. It encrypts each API key with the master key of the deployment.
API keys go from the browser to the server only when a profile is saved; no response contains a key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Literal
from urllib.parse import urlsplit

from ..service import ServiceError
from .config_store import ConfigStore, MasterKey, MasterKeyChanged, RevisionConflict, SecretKeyError
from .model import DEFAULT_PROFILE, ENV_PREFIX, ModelSettings, profiles_from_env

Provider = Literal["openrouter", "azure", "openai"]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# A UI name is a path segment and a label; environment names have the stricter rule of model.PROFILE_NAME.
PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}")
REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high"}
ACTIVE_SETTING = "active_profile"
ACTOR = "web-ui"

# Run limits of the agent loop. A profile can set each one; an unset limit uses the default.
DEFAULT_LIMITS = {"step_budget": 45, "max_turns": 60, "model_timeout_seconds": 300, "call_timeout_seconds": 240,
                  "total_timeout_seconds": 2400, "max_tool_text_chars": 80000}
# The deployment can change each maximum with DRAWING2CAD_RUN_MAX_<LIMIT>, for example DRAWING2CAD_RUN_MAX_STEP_BUDGET.
DEFAULT_MAXIMUMS = {"step_budget": 100, "max_turns": 150, "model_timeout_seconds": 1800, "call_timeout_seconds": 900,
                    "total_timeout_seconds": 14400, "max_tool_text_chars": 400000}
MAXIMUM_PREFIX = "DRAWING2CAD_RUN_MAX_"


def _positive_int(text: str, variable: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"{variable} must be a positive integer.") from None
    if value < 1:
        raise ValueError(f"{variable} must be a positive integer.")
    return value


def maximums_from_env() -> dict[str, int]:
    maximums = dict(DEFAULT_MAXIMUMS)
    for name in maximums:
        variable = MAXIMUM_PREFIX + name.upper()
        text = os.environ.get(variable, "").strip()
        if text:
            maximums[name] = _positive_int(text, variable)
    return maximums


def check_limits(limits: dict[str, Any], maximums: dict[str, int], source: str = "limits") -> dict[str, int]:
    """Only known limits, each an integer from 1 to its maximum. Raise a ServiceError that names the field."""
    checked = {}
    for name, value in limits.items():
        if value is None:
            continue
        if name not in DEFAULT_LIMITS:
            raise ServiceError(422, "INVALID_PROFILE", f"Unknown run limit: {name}.", field=f"{source}.{name}")
        if type(value) is not int or not 1 <= value <= maximums[name]:
            raise ServiceError(422, "INVALID_PROFILE", f"{name} must be an integer from 1 to {maximums[name]}.",
                               field=f"{source}.{name}", recovery="Use a smaller value or ask the operator to change "
                               f"{MAXIMUM_PREFIX}{name.upper()}.")
        checked[name] = value
    return checked


def env_profile_limits(names: list[str], maximums: dict[str, int]) -> dict[str, dict[str, int]]:
    """Run limits of the environment profiles from DRAWING2CAD_AGENT[_<NAME>]_<LIMIT>.

    Example: DRAWING2CAD_AGENT_LITELLM_STEP_BUDGET. Without DRAWING2CAD_AGENT_PROFILES, the unprefixed variables apply.
    """
    listed = bool(os.environ.get(ENV_PREFIX + "PROFILES", "").strip())
    result = {}
    for name in names:
        prefix = f"{ENV_PREFIX}{name.upper()}_" if listed or name != DEFAULT_PROFILE else ENV_PREFIX
        limits = {}
        for limit in DEFAULT_LIMITS:
            text = os.environ.get(prefix + limit.upper(), "").strip()
            if text:
                limits[limit] = _positive_int(text, prefix + limit.upper())
        try:
            result[name] = check_limits(limits, maximums, prefix.rstrip("_"))
        except ServiceError as error:
            raise ValueError(f"{error.detail['message']} ({error.detail['field']})") from None
    return result


@dataclass(frozen=True)
class Profile:
    """A profile. `settings` is None when the profile has no usable key, for example a locked key."""
    settings: ModelSettings | None
    provider: Provider
    # "env" profiles come from DRAWING2CAD_AGENT_*; only "ui" profiles can change.
    origin: Literal["env", "ui"]
    base_url: str
    model: str
    api: str
    reasoning_effort: str | None
    key_set: bool
    key_locked: bool = False
    limits: dict[str, int] = field(default_factory=dict)
    revision: int | None = None

    def view(self, name: str) -> dict[str, Any]:
        """The profile for the browser: everything except the key."""
        return {"name": name, "provider": self.provider, "origin": self.origin, "base_url": self.base_url,
                "model": self.model, "api": self.api, "reasoning_effort": self.reasoning_effort,
                "key_set": self.key_set, "key_locked": self.key_locked, "limits": dict(self.limits),
                "revision": self.revision}


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
        raise ServiceError(422, "INVALID_PROFILE", "The endpoint must be an https URL.", field="endpoint",
                           recovery="Enter the URL of the resource, for example https://<resource>.openai.azure.com.")
    if provider == "azure":
        return f"https://{parts.netloc}/openai/v1"
    return f"https://{parts.netloc}{parts.path}".rstrip("/")


class ProfileStore:
    """Environment profiles, UI profiles in the configuration store, and the active profile. Safe for several threads.

    `master` is the master key for API keys; "env" reads it from DRAWING2CAD_SECRET_KEY_FILE or DRAWING2CAD_SECRET_KEY.
    """

    def __init__(self, path: Path, env_profiles: dict[str, ModelSettings] | None = None,
                 master: MasterKey | None | Literal["env"] = "env", env_limits: dict[str, dict[str, int]] | None = None,
                 maximums: dict[str, int] | None = None):
        self._lock = threading.Lock()
        self.maximums = maximums_from_env() if maximums is None else maximums
        self.master = MasterKey.from_env() if master == "env" else master
        self.store = ConfigStore(path)
        env = profiles_from_env() if env_profiles is None else env_profiles
        limits = env_profile_limits(list(env), self.maximums) if env_limits is None else env_limits
        self._env = {name: Profile(s, provider_of(s), "env", s.base_url, s.model, s.api, s.reasoning_effort,
                                   bool(s.api_key), limits=limits.get(name, {})) for name, s in env.items()}

    # Reading. Metadata reads never decrypt a key; only get(), require(), and run_profile() decrypt one selected key.

    def _ui_profile(self, row: dict[str, Any], decrypt: bool) -> Profile:
        has_key = row["key_ciphertext"] is not None
        # Without decryption, a key is locked when no master key or another master key encrypted it.
        locked = has_key and (self.master is None or row["key_version"] != self.master.version)
        settings = None
        if decrypt and has_key and not locked:
            try:
                key = self.store.secret(row, self.master)
                settings = ModelSettings(row["base_url"], row["model"], key, row["key_header"], row["reasoning_effort"],
                                         row["api"])
            except SecretKeyError:
                locked = True  # For example a ciphertext of another profile.
        return Profile(settings, row["provider"], "ui", row["base_url"], row["model"], row["api"], row["reasoning_effort"],
                       has_key, locked, json.loads(row["limits_json"]), row["revision"])

    def _profiles(self, decrypt: str | None = None) -> dict[str, Profile]:
        """Environment profiles first, then UI profiles. A UI profile cannot use the name of an environment profile.

        Only the profile named in `decrypt` gets its decrypted key.
        """
        profiles = dict(self._env)
        for row in self.store.profiles():
            profiles.setdefault(row["name"], self._ui_profile(row, row["name"] == decrypt))
        return profiles

    def _active(self, profiles: dict[str, Profile]) -> tuple[str | None, int]:
        stored = self.store.setting(ACTIVE_SETTING)
        if stored is None:
            # Without a stored selection, the first profile is active. A stored null means "no agent".
            return next(iter(profiles), None), 0
        name, revision = stored[0]["name"], stored[1]
        if name is None:
            return None, revision
        return (name if name in profiles else next(iter(profiles), None)), revision

    def _effective_limits(self, profile: Profile | None) -> dict[str, int]:
        own = profile.limits if profile else {}
        return {key: min(own.get(key, default), self.maximums[key]) for key, default in DEFAULT_LIMITS.items()}

    @property
    def active(self) -> str | None:
        with self._lock:
            return self._active(self._profiles())[0]

    def usable(self, name: str | None) -> bool:
        """True if the profile exists and has a key that the current master key encrypted. It decrypts no key."""
        with self._lock:
            profile = self._profiles().get(name) if name is not None else None
        return bool(profile and profile.key_set and not profile.key_locked)

    def model(self, name: str | None) -> str | None:
        with self._lock:
            profile = self._profiles().get(name) if name is not None else None
        return profile.model if profile else None

    def get(self, name: str | None) -> ModelSettings | None:
        """The endpoint of a profile with its decrypted key, or None if it does not exist or has no usable key."""
        with self._lock:
            profile = self._profiles(decrypt=name).get(name) if name is not None else None
        return profile.settings if profile else None

    def limits(self, name: str | None) -> dict[str, int]:
        """The effective run limits of a profile: its own limits over the defaults, never above the maximums."""
        with self._lock:
            profile = self._profiles().get(name) if name is not None else None
        return self._effective_limits(profile)

    @staticmethod
    def _checked(name: str, profile: Profile | None) -> ModelSettings:
        if profile is None:
            raise ServiceError(422, "UNKNOWN_PROFILE", f"Unknown model profile: {name}", field="name",
                               recovery="Choose a profile from the list in the settings.")
        if profile.key_locked:
            raise ServiceError(409, "PROFILE_KEY_LOCKED", f"The stored API key of the profile {name} cannot be decrypted.",
                               field="api_key", recovery="Enter the API key of the profile again in the settings, "
                               "or start the backend with the master key that encrypted it.")
        if profile.settings is None:
            raise ServiceError(409, "PROFILE_KEY_MISSING", f"The profile {name} has no API key.", field="api_key",
                               recovery="Enter the API key of the profile in the settings.")
        return profile.settings

    def require(self, name: str) -> ModelSettings:
        """The endpoint of a profile with its decrypted key. A locked or missing key fails with an actionable error."""
        with self._lock:
            profile = self._profiles(decrypt=name).get(name)
        return self._checked(name, profile)

    def run_profile(self, name: str) -> tuple[ModelSettings, dict[str, int]]:
        """The endpoint and the effective limits of a profile, read together, so that a change cannot mix them."""
        with self._lock:
            profile = self._profiles(decrypt=name).get(name)
        return self._checked(name, profile), self._effective_limits(profile)

    def view(self) -> dict[str, Any]:
        with self._lock:
            profiles = self._profiles()
            active, revision = self._active(profiles)
        return {"active": active, "active_revision": revision,
                "profiles": [p.view(n) for n, p in profiles.items()], "master_key_set": self.master is not None,
                "limits": {"defaults": dict(DEFAULT_LIMITS), "maximums": dict(self.maximums)}}

    # Changes

    @staticmethod
    def _conflict(error: RevisionConflict) -> ServiceError:
        return ServiceError(409, "REVISION_CONFLICT", f"{error.target} was changed in the meantime (revision {error.stored}).",
                            field="revision", recovery="Reload the settings and apply your change again.")

    def select(self, name: str | None, expected_revision: int | None = None) -> None:
        with self._lock:
            if name is not None and name not in self._profiles():
                raise ServiceError(422, "UNKNOWN_PROFILE", f"Unknown model profile: {name}", field="name",
                                   recovery="Choose a profile from the list in the settings.")
            try:
                self.store.set_setting(ACTIVE_SETTING, {"name": name}, expected_revision, ACTOR)
            except RevisionConflict as error:
                raise self._conflict(error) from None

    def save(self, name: str, provider: Provider, endpoint: str, model: str, api: str, api_key: str | None,
             reasoning_effort: str | None, limits: dict[str, Any] | None = None,
             expected_revision: int | None = None) -> None:
        """Create or change a UI profile. Without `api_key`, a changed profile keeps its key."""
        if not PROFILE_NAME.fullmatch(name):
            raise ServiceError(422, "INVALID_PROFILE", "The name needs 1 to 40 characters: letters, digits, spaces, . _ -.",
                               field="name")
        if not model.strip():
            raise ServiceError(422, "INVALID_PROFILE", "The model is missing.", field="model",
                               recovery="For Azure AI Foundry, enter the name of the deployment.")
        if api not in ("chat", "responses"):
            raise ServiceError(422, "INVALID_PROFILE", "The interface must be chat or responses.", field="api")
        if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
            raise ServiceError(422, "INVALID_PROFILE", "Unknown reasoning effort.", field="reasoning_effort")
        checked = check_limits(limits or {}, self.maximums)
        base_url = endpoint_for(provider, endpoint)
        key = (api_key or "").strip() or None
        with self._lock:
            if name in self._env:
                raise ServiceError(409, "PROFILE_READ_ONLY", f"The profile {name} comes from the server configuration.",
                                   field="name", recovery="Choose a different name or change the server .env.")
            current = self.store.profile(name)
            stored_revision = current["revision"] if current else None
            if expected_revision is not None and expected_revision != (stored_revision or 0):
                # For example an edit of a profile that another browser deleted.
                raise self._conflict(RevisionConflict(name, stored_revision))
            # The active name and its selection revision come from one read, so that a later check is consistent.
            before, selection = self._active(self._profiles())
            if key is None and (current is None or current["key_ciphertext"] is None):
                raise ServiceError(422, "INVALID_PROFILE", "The API key is missing.", field="api_key")
            if key is not None and self.master is None:
                raise ServiceError(503, "SECRET_KEY_MISSING", "The server has no master key to encrypt API keys.",
                                   field="api_key", recovery="Set DRAWING2CAD_SECRET_KEY_FILE or DRAWING2CAD_SECRET_KEY "
                                   "on the server and restart the backend.")
            fields = {"provider": provider, "base_url": base_url, "model": model.strip(), "api": api,
                      "reasoning_effort": reasoning_effort,
                      "key_header": "api-key" if provider == "azure" else "Authorization", "limits_json": checked}
            try:
                self.store.save_profile(name, fields, key, self.master, expected_revision, ACTOR)
            except RevisionConflict as error:
                raise self._conflict(error) from None
            except MasterKeyChanged:
                raise ServiceError(409, "MASTER_KEY_CHANGED", "A rotation changed the master key of the stored API keys.",
                                   field="api_key", recovery="Restart the backend with the new master key, then save "
                                   "the profile again.") from None
            stored = self.store.setting(ACTIVE_SETTING)
            if stored is not None and stored[0]["name"] is None and len(self._profiles()) == 1:
                self._adjust_selection(name, selection)
            elif stored is None and self._active(self._profiles())[0] != before:
                # The first profile became active by default. Store the selection, so that its revision changes.
                self._adjust_selection(name, selection)

    def delete(self, name: str, expected_revision: int | None = None) -> None:
        with self._lock:
            if name in self._env:
                raise ServiceError(409, "PROFILE_READ_ONLY", f"The profile {name} comes from the server configuration.",
                                   recovery="Remove the profile from the server .env.")
            active, selection = self._active(self._profiles())
            try:
                deleted = self.store.delete_profile(name, expected_revision, ACTOR)
            except RevisionConflict as error:
                raise self._conflict(error) from None
            if not deleted:
                raise ServiceError(404, "NOT_FOUND", f"Unknown model profile: {name}")
            if active == name:
                self._adjust_selection(next(iter(self._profiles()), None), selection)

    def _adjust_selection(self, name: str | None, read_revision: int) -> None:
        """Store an automatic change of the active profile, only if no other selection was stored since it was read."""
        try:
            self.store.set_setting(ACTIVE_SETTING, {"name": name}, read_revision, ACTOR)
        except RevisionConflict:
            pass  # Another client selected a profile in the meantime; its selection stays.

    def close(self) -> None:
        self.store.close()
