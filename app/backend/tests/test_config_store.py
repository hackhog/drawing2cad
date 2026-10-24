"""The SQLite configuration store with encrypted API keys and run limits for each profile (ADR 0028)."""

import base64
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from drawing_demo import api
from drawing_demo.agent import config_store
from drawing_demo.agent import runner as runner_module
from drawing_demo.agent.config_store import ConfigStore, MasterKey, SecretKeyError
from drawing_demo.service import ServiceError
from drawing_demo.agent.profiles import DEFAULT_LIMITS, DEFAULT_MAXIMUMS, ProfileStore
from test_agent_runs import TEST_MASTER_KEY, environment, upload, with_model_endpoint  # noqa: F401 (fixture)

OTHER_MASTER_KEY = base64.b64encode(b"z" * 32).decode()
OPENROUTER = {"provider": "openrouter", "model": "vendor/m"}


def database(tmp_path):
    return tmp_path / "data" / "config.sqlite"


def no_submit(monkeypatch, submitted):
    monkeypatch.setattr(runner_module.AgentRunner, "submit", lambda self, run_id, settings: submitted.append(run_id))


def test_a_stored_key_is_encrypted_and_never_returned(environment, tmp_path):
    with TestClient(api.create_app()) as client:
        res = client.put("/api/agent/profiles/OpenRouter", json={**OPENROUTER, "api_key": "or-secret-value"})
        assert res.status_code == 200 and "or-secret-value" not in res.text
        assert "or-secret-value" not in client.get("/api/agent/profiles").text
        assert client.app.state.services.runner.settings.api_key == "or-secret-value"
    for path in database(tmp_path).parent.glob("config.sqlite*"):
        assert b"or-secret-value" not in path.read_bytes()
    with sqlite3.connect(database(tmp_path)) as db:
        row = db.execute("SELECT key_ciphertext, key_nonce, key_version FROM profiles").fetchone()
    assert row[0] and len(row[1]) == 12 and row[2] == MasterKey.from_text(TEST_MASTER_KEY).version


def test_a_ciphertext_does_not_decrypt_in_another_profile(environment, tmp_path):
    with TestClient(api.create_app()) as client:
        for name in ("A", "B"):
            client.put(f"/api/agent/profiles/{name}", json={**OPENROUTER, "api_key": f"key-{name}"})
    with sqlite3.connect(database(tmp_path)) as db:
        ciphertext, nonce = db.execute("SELECT key_ciphertext, key_nonce FROM profiles WHERE name = 'A'").fetchone()
        db.execute("UPDATE profiles SET key_ciphertext = ?, key_nonce = ? WHERE name = 'B'", (ciphertext, nonce))
    with TestClient(api.create_app()) as client:
        store = client.app.state.services.runner.profiles
        assert store.get("A").api_key == "key-A" and store.get("B") is None
        with pytest.raises(ServiceError) as raised:
            store.run_profile("B")
        assert raised.value.detail["code"] == "PROFILE_KEY_LOCKED"


def test_without_a_master_key_keys_cannot_be_saved_and_environment_profiles_still_run(environment):
    environment.delenv("DRAWING2CAD_SECRET_KEY")
    with_model_endpoint(environment)
    submitted = []
    no_submit(environment, submitted)
    with TestClient(api.create_app()) as client:
        res = client.put("/api/agent/profiles/OpenRouter", json={**OPENROUTER, "api_key": "k"})
        assert res.status_code == 503
        detail = res.json()["detail"]
        assert detail["code"] == "SECRET_KEY_MISSING" and detail["field"] == "api_key"
        assert "DRAWING2CAD_SECRET_KEY" in detail["recovery"]
        assert client.get("/api/agent/profiles").json()["master_key_set"] is False
        source = upload(client)
        assert client.post(f"/api/sources/{source['source_id']}/runs").status_code == 201 and len(submitted) == 1


@pytest.mark.parametrize("change", [{"DRAWING2CAD_SECRET_KEY": OTHER_MASTER_KEY}, {"DRAWING2CAD_SECRET_KEY": None}])
def test_a_key_that_does_not_decrypt_is_locked_and_a_run_fails_at_start(environment, change):
    with TestClient(api.create_app()) as client:
        client.put("/api/agent/profiles/OpenRouter", json={**OPENROUTER, "api_key": "k"})
    for name, value in change.items():
        environment.delenv(name) if value is None else environment.setenv(name, value)
    submitted = []
    no_submit(environment, submitted)
    with TestClient(api.create_app()) as client:
        view = client.get("/api/agent/profiles").json()
        assert view["active"] == "OpenRouter" and view["profiles"][0]["key_locked"] is True
        source = upload(client)
        res = client.post(f"/api/sources/{source['source_id']}/runs")
        assert res.status_code == 409 and res.json()["detail"]["code"] == "PROFILE_KEY_LOCKED" and submitted == []
        assert "again" in res.json()["detail"]["recovery"]
        # Entering the key again unlocks the profile.
        client.put("/api/agent/profiles/OpenRouter", json={**OPENROUTER, "api_key": "k2"})
        if change["DRAWING2CAD_SECRET_KEY"] is not None:
            assert client.get("/api/agent/profiles").json()["profiles"][0]["key_locked"] is False


def test_rotation_encrypts_all_keys_with_the_new_master_key(environment, tmp_path, capsys):
    with TestClient(api.create_app()) as client:
        for name in ("A", "B"):
            client.put(f"/api/agent/profiles/{name}", json={**OPENROUTER, "api_key": f"key-{name}"})
    old, new = tmp_path / "old.key", tmp_path / "new.key"
    old.write_text(TEST_MASTER_KEY, encoding="ascii")
    new.write_text(OTHER_MASTER_KEY, encoding="ascii")
    config_store.main(["rotate", "--database", str(database(tmp_path)), "--old-key-file", str(old), "--new-key-file", str(new)])
    assert "Encrypted 2 stored API keys" in capsys.readouterr().out
    environment.setenv("DRAWING2CAD_SECRET_KEY", OTHER_MASTER_KEY)
    with TestClient(api.create_app()) as client:
        profiles = client.app.state.services.runner.profiles
        assert [profiles.get(name).api_key for name in ("A", "B")] == ["key-A", "key-B"]
    # A wrong old key changes nothing.
    with pytest.raises(SystemExit, match="no key changed"):
        config_store.main(["rotate", "--database", str(database(tmp_path)), "--old-key-file", str(old),
                           "--new-key-file", str(new)])


def test_a_stale_revision_is_a_conflict(environment):
    with TestClient(api.create_app()) as client:
        view = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k"}).json()
        revision = view["profiles"][0]["revision"]
        assert client.put("/api/agent/profiles/P", json={**OPENROUTER, "model": "vendor/n", "revision": revision}).status_code == 200
        res = client.put("/api/agent/profiles/P", json={**OPENROUTER, "model": "vendor/o", "revision": revision})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "REVISION_CONFLICT"
        assert client.delete("/api/agent/profiles/P", params={"revision": revision}).status_code == 409
        active_revision = client.get("/api/agent/profiles").json()["active_revision"]
        assert client.put("/api/agent/active", json={"name": None, "revision": active_revision}).status_code == 200
        res = client.put("/api/agent/active", json={"name": "P", "revision": active_revision})
        assert res.status_code == 409 and res.json()["detail"]["field"] == "revision"


@pytest.mark.parametrize("limits, field", [
    ({"step_budget": DEFAULT_MAXIMUMS["step_budget"] + 1}, "limits.step_budget"),
    ({"total_timeout_seconds": 0}, "limits.total_timeout_seconds"),
    ({"unknown_limit": 5}, "limits.unknown_limit"),
])
def test_limits_outside_their_range_are_rejected(environment, limits, field):
    with TestClient(api.create_app()) as client:
        res = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k", "limits": limits})
        assert res.status_code == 422 and res.json()["detail"]["field"] == field


def test_a_run_records_the_limits_of_its_profile(environment):
    submitted = []
    no_submit(environment, submitted)
    with TestClient(api.create_app()) as client:
        client.put("/api/agent/profiles/Local", json={**OPENROUTER, "api_key": "k",
                                                      "limits": {"step_budget": 20, "model_timeout_seconds": 900}})
        view = client.get("/api/agent/profiles").json()
        assert view["profiles"][0]["limits"] == {"step_budget": 20, "model_timeout_seconds": 900}
        assert view["limits"] == {"defaults": DEFAULT_LIMITS, "maximums": DEFAULT_MAXIMUMS}
        source = upload(client)
        run = client.post(f"/api/sources/{source['source_id']}/runs").json()
        assert run["agent"]["limits"] == {**DEFAULT_LIMITS, "step_budget": 20, "model_timeout_seconds": 900}
        assert runner_module.run_limits(run) == run["agent"]["limits"]


def test_environment_profiles_read_their_limits_and_the_maximums_come_from_the_deployment(environment):
    with_model_endpoint(environment)
    environment.setenv("DRAWING2CAD_AGENT_STEP_BUDGET", "12")
    environment.setenv("DRAWING2CAD_RUN_MAX_MODEL_TIMEOUT_SECONDS", "200")
    with TestClient(api.create_app()) as client:
        profiles = client.app.state.services.runner.profiles
        assert profiles.limits("Standard") == {**DEFAULT_LIMITS, "step_budget": 12, "model_timeout_seconds": 200}
    environment.setenv("DRAWING2CAD_AGENT_STEP_BUDGET", "0")
    with pytest.raises(ValueError, match="DRAWING2CAD_AGENT_STEP_BUDGET"):
        api.create_app()


def test_the_former_profile_file_is_not_read(environment, tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "agent-profiles.json").write_text(json.dumps({"active": "Old", "profiles": {"Old": {"provider": "openrouter", "settings": {
        "base_url": "https://openrouter.ai/api/v1", "model": "vendor/old", "api_key": "old-key"}}}}))
    with TestClient(api.create_app()) as client:
        view = client.get("/api/agent/profiles").json()
        assert view["profiles"] == [] and view["active"] is None


def test_an_invalid_master_key_stops_the_start(environment):
    environment.setenv("DRAWING2CAD_SECRET_KEY", "not base64 and too short")
    with pytest.raises(SecretKeyError):
        api.create_app()


def test_migrations_run_once_and_record_their_version(tmp_path):
    store = ConfigStore(tmp_path / "config.sqlite")
    assert store.schema_version() == len(config_store.MIGRATIONS)
    store.close()
    store = ConfigStore(tmp_path / "config.sqlite")
    assert store.schema_version() == len(config_store.MIGRATIONS)
    store.close()


def test_the_audit_records_changes_without_values(tmp_path):
    profiles = ProfileStore(tmp_path / "config.sqlite", env_profiles={}, master=MasterKey.from_text(TEST_MASTER_KEY))
    profiles.save("P", "openrouter", "", "vendor/m", "chat", "audit-secret", None)
    profiles.select("P")
    profiles.delete("P")
    events = profiles.store.events()
    profiles.close()
    # The first profile becomes active by default, and the store records this selection too.
    assert [(e["actor"], e["action"], e["target"]) for e in events] == [
        ("web-ui", "profile_create", "P"), ("web-ui", "setting_update", "active_profile"),
        ("web-ui", "setting_update", "active_profile"), ("web-ui", "profile_delete", "P"),
        ("web-ui", "setting_update", "active_profile")]
    assert "audit-secret" not in json.dumps(events)


def test_metadata_reads_decrypt_no_key(environment, monkeypatch):
    with TestClient(api.create_app()) as client:
        for name in ("A", "B"):
            client.put(f"/api/agent/profiles/{name}", json={**OPENROUTER, "api_key": f"key-{name}"})
        calls = []
        original = MasterKey.decrypt
        monkeypatch.setattr(MasterKey, "decrypt", lambda self, *args: calls.append(args[0]) or original(self, *args))
        client.get("/api/agent/profiles")
        client.get("/api/capabilities")
        client.put("/api/agent/profiles/B", json={**OPENROUTER, "model": "vendor/n"})
        assert calls == []
        # A run decrypts only the key of its own profile.
        submitted = []
        no_submit(monkeypatch, submitted)
        source = upload(client)
        assert client.post(f"/api/sources/{source['source_id']}/runs").status_code == 201
        assert len(calls) == 1


def test_creating_an_existing_profile_with_revision_zero_is_a_conflict(environment):
    with TestClient(api.create_app()) as client:
        assert client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k1", "revision": 0}).status_code == 200
        res = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k2", "revision": 0})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "REVISION_CONFLICT"
        assert client.app.state.services.runner.profiles.get("P").api_key == "k1"


def test_a_recreated_profile_has_a_new_revision(environment):
    with TestClient(api.create_app()) as client:
        old = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k1"}).json()["profiles"][0]["revision"]
        assert client.delete("/api/agent/profiles/P", params={"revision": old}).status_code == 200
        new = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k2", "revision": 0}).json()["profiles"][0]["revision"]
        assert new != old
        res = client.put("/api/agent/profiles/P", json={**OPENROUTER, "model": "vendor/x", "revision": old})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "REVISION_CONFLICT"
        assert client.delete("/api/agent/profiles/P", params={"revision": old}).status_code == 409


def test_a_backend_with_the_former_master_key_writes_no_key_after_a_rotation(environment, tmp_path):
    with TestClient(api.create_app()) as client:
        client.put("/api/agent/profiles/A", json={**OPENROUTER, "api_key": "key-A"})
        # The rotation runs while this backend still has the former master key.
        old, new = tmp_path / "old.key", tmp_path / "new.key"
        old.write_text(TEST_MASTER_KEY, encoding="ascii")
        new.write_text(OTHER_MASTER_KEY, encoding="ascii")
        config_store.main(["rotate", "--database", str(database(tmp_path)), "--old-key-file", str(old),
                           "--new-key-file", str(new)])
        res = client.put("/api/agent/profiles/B", json={**OPENROUTER, "api_key": "key-B"})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "MASTER_KEY_CHANGED"
        assert client.get("/api/agent/profiles").json()["profiles"][0]["key_locked"] is True
    environment.setenv("DRAWING2CAD_SECRET_KEY", OTHER_MASTER_KEY)
    with TestClient(api.create_app()) as client:
        assert client.put("/api/agent/profiles/B", json={**OPENROUTER, "api_key": "key-B"}).status_code == 200
        assert client.app.state.services.runner.profiles.get("A").api_key == "key-A"


def test_forget_keys_adopts_a_new_master_key_and_keeps_the_fence(environment, tmp_path, capsys):
    new = tmp_path / "new.key"
    new.write_text(OTHER_MASTER_KEY, encoding="ascii")
    with TestClient(api.create_app()) as client:
        client.put("/api/agent/profiles/A", json={**OPENROUTER, "api_key": "key-A"})
        with pytest.raises(SystemExit):
            config_store.main(["forget-keys", "--database", str(database(tmp_path)), "--new-key-file", str(new)])  # --yes.
        config_store.main(["forget-keys", "--database", str(database(tmp_path)), "--new-key-file", str(new), "--yes"])
        assert "Removed 1 stored API keys" in capsys.readouterr().out
        # This backend still has the former master key: it saves no key.
        res = client.put("/api/agent/profiles/A", json={**OPENROUTER, "api_key": "key-A2"})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "MASTER_KEY_CHANGED"
    environment.setenv("DRAWING2CAD_SECRET_KEY", OTHER_MASTER_KEY)
    with TestClient(api.create_app()) as client:
        profile = client.get("/api/agent/profiles").json()["profiles"][0]
        assert profile["key_set"] is False and profile["key_locked"] is False
        assert client.put("/api/agent/profiles/A", json={**OPENROUTER, "api_key": "key-A2"}).status_code == 200
        assert client.app.state.services.runner.profiles.get("A").api_key == "key-A2"


def test_the_first_profile_becomes_active_with_a_new_selection_revision(environment):
    with TestClient(api.create_app()) as client:
        before = client.get("/api/agent/profiles").json()
        assert before["active"] is None and before["active_revision"] == 0
        after = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k", "revision": 0}).json()
        assert after["active"] == "P" and after["active_revision"] > 0
        # A browser with the former selection cannot select "no agent" without a conflict.
        res = client.put("/api/agent/active", json={"name": None, "revision": before["active_revision"]})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "REVISION_CONFLICT"


def test_saving_a_deleted_profile_is_a_conflict_not_a_missing_key(environment):
    with TestClient(api.create_app()) as client:
        revision = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k"}).json()["profiles"][0]["revision"]
        client.delete("/api/agent/profiles/P", params={"revision": revision})
        # The stale edit form sends no key, because it kept the stored key.
        res = client.put("/api/agent/profiles/P", json={**OPENROUTER, "model": "vendor/n", "revision": revision})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "REVISION_CONFLICT"


def test_two_stores_on_a_new_database_apply_each_migration_once(tmp_path):
    path = tmp_path / "config.sqlite"
    first, second = ConfigStore(path), ConfigStore(path)
    try:
        assert first.schema_version() == second.schema_version() == len(config_store.MIGRATIONS)
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(config_store.MIGRATIONS)
    finally:
        first.close()
        second.close()



def test_a_stale_delete_of_a_deleted_profile_is_a_conflict(environment):
    with TestClient(api.create_app()) as client:
        revision = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k"}).json()["profiles"][0]["revision"]
        assert client.delete("/api/agent/profiles/P", params={"revision": revision}).status_code == 200
        res = client.delete("/api/agent/profiles/P", params={"revision": revision})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "REVISION_CONFLICT"
        assert client.delete("/api/agent/profiles/P").status_code == 404


def test_an_automatic_selection_does_not_overwrite_a_selection_of_another_backend(tmp_path, monkeypatch):
    # Two stores on one database stand for two backends. While the first one deletes the active profile A, the
    # second one selects C. The automatic fallback of the first one must not overwrite that selection.
    master = MasterKey.from_text(TEST_MASTER_KEY)
    first = ProfileStore(tmp_path / "config.sqlite", env_profiles={}, master=master)
    second = ProfileStore(tmp_path / "config.sqlite", env_profiles={}, master=master)
    try:
        for name in ("A", "B", "C"):
            first.save(name, "openrouter", "", "vendor/m", "chat", f"key-{name}", None, expected_revision=0)
        first.select("A")
        original = first.store.delete_profile

        def delete_while_another_backend_selects(*args, **kwargs):
            second.select("C")
            return original(*args, **kwargs)

        monkeypatch.setattr(first.store, "delete_profile", delete_while_another_backend_selects)
        first.delete("A")
        assert first.active == "C" and second.active == "C"
    finally:
        first.close()
        second.close()


def test_the_first_profile_does_not_overwrite_a_selection_of_another_backend(tmp_path, monkeypatch):
    master = MasterKey.from_text(TEST_MASTER_KEY)
    first = ProfileStore(tmp_path / "config.sqlite", env_profiles={}, master=master)
    second = ProfileStore(tmp_path / "config.sqlite", env_profiles={}, master=master)
    try:
        original = first.store.save_profile

        def save_while_another_backend_selects(*args, **kwargs):
            second.select(None)
            return original(*args, **kwargs)

        monkeypatch.setattr(first.store, "save_profile", save_while_another_backend_selects)
        first.save("P", "openrouter", "", "vendor/m", "chat", "k", None, expected_revision=0)
        assert first.active is None and second.active is None
    finally:
        first.close()
        second.close()


def test_the_continuation_limit_is_a_run_limit_with_a_default_and_a_maximum(environment):
    assert DEFAULT_LIMITS["max_continuations"] == 3 and DEFAULT_MAXIMUMS["max_continuations"] == 10
    with TestClient(api.create_app()) as client:
        res = client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k", "limits": {"max_continuations": 11}})
        assert res.status_code == 422 and res.json()["detail"]["field"] == "limits.max_continuations"
        client.put("/api/agent/profiles/P", json={**OPENROUTER, "api_key": "k", "limits": {"max_continuations": 5}})
        view = client.get("/api/agent/profiles").json()
        assert view["profiles"][0]["limits"] == {"max_continuations": 5}
