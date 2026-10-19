"""Runtime configuration of the web app in SQLite, with encrypted API keys (ADR 0028).

The store holds the model profiles of the web UI, the active profile, and an audit of changes. It encrypts each API key
with AES-256-GCM and a master key from the deployment configuration. The master key is never in the database.
Run `python -m drawing_demo.agent.config_store rotate --help` to encrypt all keys with a new master key.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SECRET_KEY_ENV = "DRAWING2CAD_SECRET_KEY"
SECRET_KEY_FILE_ENV = "DRAWING2CAD_SECRET_KEY_FILE"
NONCE_BYTES = 12
KEY_FIELD = "api_key"

# Each migration runs once, in order. Add new migrations at the end; never change an applied one.
MIGRATIONS = (
    """
    CREATE TABLE profiles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        provider TEXT NOT NULL,
        base_url TEXT NOT NULL,
        model TEXT NOT NULL,
        api TEXT NOT NULL,
        reasoning_effort TEXT,
        key_header TEXT NOT NULL,
        key_ciphertext BLOB,
        key_nonce BLOB,
        key_version TEXT,
        limits_json TEXT NOT NULL DEFAULT '{}',
        revision INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        revision INTEGER NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE config_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT
    );
    """,
)


class SecretKeyError(ValueError):
    """The master key is missing, invalid, or does not decrypt a stored key."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MasterKey:
    """The 32-byte master key. Its version is a short hash, so that a stored key names the master key it needs."""

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise SecretKeyError("The master key must be 32 bytes, Base64-encoded.")
        self._aead = AESGCM(key)
        self.version = hashlib.sha256(b"drawing2cad-master-key\0" + key).hexdigest()[:16]

    @classmethod
    def from_text(cls, text: str) -> "MasterKey":
        try:
            return cls(base64.b64decode(text.strip(), validate=True))
        except (binascii.Error, ValueError) as error:
            raise SecretKeyError("The master key must be 32 bytes, Base64-encoded.") from error

    @classmethod
    def from_env(cls) -> "MasterKey | None":
        """The master key from DRAWING2CAD_SECRET_KEY_FILE (for example a Docker secret) or DRAWING2CAD_SECRET_KEY."""
        path = os.environ.get(SECRET_KEY_FILE_ENV, "").strip()
        if path:
            try:
                return cls.from_text(Path(path).read_text(encoding="ascii"))
            except OSError as error:
                raise SecretKeyError(f"Cannot read the master key file in {SECRET_KEY_FILE_ENV}.") from error
        text = os.environ.get(SECRET_KEY_ENV, "").strip()
        return cls.from_text(text) if text else None

    @staticmethod
    def _associated_data(profile_id: str) -> bytes:
        # A ciphertext is bound to its profile and field, so it cannot be moved to another profile.
        return f"profile:{profile_id}:{KEY_FIELD}".encode("utf-8")

    def encrypt(self, profile_id: str, secret: str) -> tuple[bytes, bytes]:
        nonce = os.urandom(NONCE_BYTES)
        return self._aead.encrypt(nonce, secret.encode("utf-8"), self._associated_data(profile_id)), nonce

    def decrypt(self, profile_id: str, ciphertext: bytes, nonce: bytes) -> str:
        try:
            return self._aead.decrypt(nonce, ciphertext, self._associated_data(profile_id)).decode("utf-8")
        except InvalidTag as error:
            raise SecretKeyError("The master key does not decrypt the stored key.") from error


class RevisionConflict(Exception):
    """The expected revision differs from the stored revision."""

    def __init__(self, target: str, stored: int | None):
        super().__init__(target)
        self.target = target
        self.stored = stored


class ConfigStore:
    """The SQLite configuration database. One connection with a lock: one writer, WAL mode."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        if new:
            os.chmod(self.path, 0o600)  # SQLite creates its WAL and shared-memory files with the same mode.
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _migrate(self) -> None:
        self._db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied = {row[0] for row in self._db.execute("SELECT version FROM schema_migrations")}
        for version, script in enumerate(MIGRATIONS, start=1):
            if version in applied:
                continue
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for statement in filter(str.strip, script.split(";")):
                    self._db.execute(statement)
                self._db.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (version, _now()))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def schema_version(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]

    # Profiles

    def profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._db.execute("SELECT * FROM profiles ORDER BY created_at, name")]

    def profile(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM profiles WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

    def save_profile(self, name: str, fields: dict[str, Any], secret: str | None, master: MasterKey | None,
                     expected_revision: int | None, actor: str) -> dict[str, Any]:
        """Create or change a profile. `secret` None keeps the stored key. The caller checks the field values."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                current = self._db.execute("SELECT * FROM profiles WHERE name = ?", (name,)).fetchone()
                stored = current["revision"] if current else None
                if expected_revision is not None and expected_revision != (stored or 0):
                    raise RevisionConflict(name, stored)
                profile_id = current["id"] if current else uuid.uuid4().hex
                values = {**fields, "limits_json": json.dumps(fields.get("limits_json") or {}, sort_keys=True)}
                if secret is not None:
                    if master is None:
                        raise SecretKeyError("No master key is configured.")
                    ciphertext, nonce = master.encrypt(profile_id, secret)
                    values.update(key_ciphertext=ciphertext, key_nonce=nonce, key_version=master.version)
                now = _now()
                if current:
                    assignments = ", ".join(f"{column} = ?" for column in values)
                    self._db.execute(f"UPDATE profiles SET {assignments}, revision = revision + 1, updated_at = ? WHERE id = ?",
                                     (*values.values(), now, profile_id))
                else:
                    columns = ["id", "name", *values, "revision", "created_at", "updated_at"]
                    self._db.execute(f"INSERT INTO profiles ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                                     (profile_id, name, *values.values(), 1, now, now))
                self._event(actor, "profile_update" if current else "profile_create", name)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            return dict(self._db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone())

    def delete_profile(self, name: str, expected_revision: int | None, actor: str) -> bool:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                current = self._db.execute("SELECT revision FROM profiles WHERE name = ?", (name,)).fetchone()
                if current is None:
                    self._db.execute("ROLLBACK")
                    return False
                if expected_revision is not None and expected_revision != current["revision"]:
                    raise RevisionConflict(name, current["revision"])
                self._db.execute("DELETE FROM profiles WHERE name = ?", (name,))
                self._event(actor, "profile_delete", name)
                self._db.execute("COMMIT")
                return True
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def secret(self, row: dict[str, Any], master: MasterKey | None) -> str | None:
        """The decrypted key of a profile row, or None if the row has no key. Fails if the key cannot be decrypted."""
        if row.get("key_ciphertext") is None:
            return None
        if master is None:
            raise SecretKeyError("No master key is configured.")
        return master.decrypt(row["id"], row["key_ciphertext"], row["key_nonce"])

    # Settings

    def setting(self, key: str) -> tuple[Any, int] | None:
        with self._lock:
            row = self._db.execute("SELECT value_json, revision FROM settings WHERE key = ?", (key,)).fetchone()
            return (json.loads(row["value_json"]), row["revision"]) if row else None

    def set_setting(self, key: str, value: Any, expected_revision: int | None, actor: str) -> int:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT revision FROM settings WHERE key = ?", (key,)).fetchone()
                stored = row["revision"] if row else None
                if expected_revision is not None and expected_revision != (stored or 0):
                    raise RevisionConflict(key, stored)
                revision = (stored or 0) + 1
                self._db.execute("INSERT INTO settings (key, value_json, revision, updated_at) VALUES (?, ?, ?, ?) "
                                 "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                                 "revision = excluded.revision, updated_at = excluded.updated_at",
                                 (key, json.dumps(value), revision, _now()))
                self._event(actor, "setting_update", key)
                self._db.execute("COMMIT")
                return revision
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    # Audit and rotation

    def _event(self, actor: str, action: str, target: str | None) -> None:
        self._db.execute("INSERT INTO config_events (at, actor, action, target) VALUES (?, ?, ?, ?)",
                         (_now(), actor, action, target))

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._db.execute("SELECT * FROM config_events ORDER BY id")]

    def rotate(self, old: MasterKey, new: MasterKey, actor: str = "rotate-command") -> int:
        """Encrypt all stored keys with the new master key in one transaction. Returns the number of keys."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                rows = self._db.execute("SELECT id, name, key_ciphertext, key_nonce FROM profiles "
                                        "WHERE key_ciphertext IS NOT NULL").fetchall()
                for row in rows:
                    secret = old.decrypt(row["id"], row["key_ciphertext"], row["key_nonce"])
                    ciphertext, nonce = new.encrypt(row["id"], secret)
                    self._db.execute("UPDATE profiles SET key_ciphertext = ?, key_nonce = ?, key_version = ?, "
                                     "revision = revision + 1, updated_at = ? WHERE id = ?",
                                     (ciphertext, nonce, new.version, _now(), row["id"]))
                self._event(actor, "keys_rotate", None)
                self._db.execute("COMMIT")
                return len(rows)
            except Exception:
                self._db.execute("ROLLBACK")
                raise


def _read_key(path: str) -> MasterKey:
    return MasterKey.from_text(Path(path).read_text(encoding="ascii"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage the configuration database of the drawing2cad web backend.")
    commands = parser.add_subparsers(dest="command", required=True)
    rotate = commands.add_parser("rotate", help="Encrypt all stored API keys with a new master key.")
    rotate.add_argument("--database", type=Path,
                        default=Path(os.environ.get("DRAWING2CAD_DATA_DIR", ".data")) / "config.sqlite")
    # The keys come from files, so that they do not appear in the process list or the shell history.
    rotate.add_argument("--old-key-file", required=True)
    rotate.add_argument("--new-key-file", required=True)
    arguments = parser.parse_args(argv)
    if not arguments.database.is_file():
        raise SystemExit(f"No configuration database at {arguments.database}.")
    store = ConfigStore(arguments.database)
    try:
        count = store.rotate(_read_key(arguments.old_key_file), _read_key(arguments.new_key_file))
    except SecretKeyError as error:
        raise SystemExit(f"Rotation failed, no key changed: {error}") from None
    finally:
        store.close()
    print(f"Encrypted {count} stored API keys with the new master key. Set the new key in the deployment and restart.")


if __name__ == "__main__":
    main()
