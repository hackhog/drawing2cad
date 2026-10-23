"""Durable, principal-scoped source and artifact storage.

Adapters must construct AccessContext from a verified server identity. A tool
argument must never supply that identity. Public results contain no local paths.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from uuid import uuid4

class DomainError(Exception):
    """A transport-independent error with a stable code."""

    def __init__(self, code: str, message: str, target: str | None = None,
                 next_action: str | None = None, defects: list[dict] | None = None):
        super().__init__(message)
        self.code, self.message = code, message
        self.target, self.next_action, self.defects = target, next_action, defects

    def to_dict(self) -> dict:
        result = {"code": self.code, "message": self.message}
        if self.target is not None:
            result["target"] = self.target
        if self.next_action is not None:
            result["next_action"] = self.next_action
        if self.defects:
            result["defects"] = self.defects
        return result

    as_dict = to_dict


@dataclass(frozen=True)
class AccessContext:
    """A server-verified principal. Do not deserialize this from tool input."""

    subject: str

    def __post_init__(self):
        if (not isinstance(self.subject, str) or not self.subject.strip()
                or len(self.subject) > 256 or any(ord(c) < 32 for c in self.subject)):
            raise DomainError("INVALID_IDENTITY", "A valid server identity is required.")
        try:
            self.subject.encode("utf-8")
        except UnicodeError:
            raise DomainError("INVALID_IDENTITY", "A valid server identity is required.") from None


def _integer(value: int, minimum: int, maximum: int, target: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainError("INVALID_ARGUMENT", f"{target} is outside the permitted range.", target)
    return value


def _filename(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 255
            or value in {".", ".."} or any(c in value for c in "/\\")
            or any(ord(c) < 32 for c in value)):
        raise DomainError("INVALID_ARGUMENT", "Use a filename without a directory.", "filename")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise DomainError("INVALID_ARGUMENT", "The filename must use valid Unicode.", "filename") from None
    return value


class DomainStore:
    """Keep metadata in SQLite and immutable bytes in private namespaces."""

    def __init__(self, root: Path | str, max_source_bytes: int = 20 * 1024 * 1024,
                 max_chunk_bytes: int = 512 * 1024):
        self.root = Path(os.path.abspath(root))
        self.max_source_bytes = _integer(max_source_bytes, 1, 256 * 1024 * 1024, "max_source_bytes")
        self.max_chunk_bytes = _integer(max_chunk_bytes, 1, 4 * 1024 * 1024, "max_chunk_bytes")
        self._check_path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "metadata.sqlite3"
        self._check_path(self.db_path)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY, subject TEXT NOT NULL, filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, offset INTEGER NOT NULL,
                    status TEXT NOT NULL, source_id TEXT, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, subject TEXT NOT NULL, filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, subject TEXT NOT NULL, filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, role TEXT NOT NULL,
                    run_id TEXT NOT NULL, revision INTEGER NOT NULL, media_type TEXT NOT NULL,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (
                    subject TEXT NOT NULL, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    text TEXT NOT NULL, PRIMARY KEY(subject, run_id));
                CREATE TABLE IF NOT EXISTS flag_decisions (
                    subject TEXT NOT NULL, source_id TEXT NOT NULL, page INTEGER NOT NULL,
                    flag_id TEXT NOT NULL, decision TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(subject, source_id, page, flag_id));
                CREATE TABLE IF NOT EXISTS upload_chunks (
                    upload_id TEXT NOT NULL, offset INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
                    PRIMARY KEY(upload_id, offset));
                CREATE INDEX IF NOT EXISTS sources_owner ON sources(subject, id);
                CREATE INDEX IF NOT EXISTS artifacts_owner ON artifacts(subject, id);
            """)

    @staticmethod
    def _check_path(path: Path) -> None:
        # Check every existing ancestor. resolve() alone hides links.
        for component in (path, *path.parents):
            if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
                raise DomainError("UNSAFE_PATH", "A storage path contains a link.")

    @contextmanager
    def _db(self):
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = self.db_path.with_name(self.db_path.name + suffix)
            self._check_path(path)
            try:
                metadata = path.stat()
            except FileNotFoundError:
                continue
            # A link count of 0 occurs while SQLite deletes a sidecar file in another thread.
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink > 1:
                raise DomainError("UNSAFE_PATH", "Metadata must use regular files without extra links.")
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def namespace_root(self, ctx: AccessContext) -> Path:
        if not isinstance(ctx, AccessContext):
            raise DomainError("INVALID_IDENTITY", "A server identity is required.")
        digest = hashlib.sha256(ctx.subject.encode("utf-8")).hexdigest()
        path = self.root / "principals" / digest
        self._check_path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, ctx: AccessContext, area: str, object_id: str) -> Path:
        if not re.fullmatch(r"[a-z]+_[0-9a-f]{32}", object_id):
            raise DomainError("NOT_FOUND", "The requested object does not exist.")
        parent = self.namespace_root(ctx) / area
        self._check_path(parent)
        parent.mkdir(exist_ok=True)
        path = parent / (object_id + ".pdf" if area == "sources" else object_id)
        self._check_path(path)
        return path

    @staticmethod
    def _row(db, table: str, ctx: AccessContext, object_id: str):
        row = db.execute(f"SELECT * FROM {table} WHERE id=? AND subject=?",
                         (object_id, ctx.subject)).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "The requested object does not exist.")
        return row

    @staticmethod
    def _public(row, kind: str) -> dict:
        result = dict(row)
        result.pop("subject", None)
        result[f"{kind}_id"] = result.pop("id")
        if kind == "source":
            result.update(status="uploaded", pdf_validation="not_tested", media_type="application/pdf")
        return result

    @staticmethod
    def _sync_directory(path: Path):
        if os.name != "nt":
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def upload_begin(self, ctx: AccessContext, filename: str, size_bytes: int, sha256: str) -> dict:
        filename = _filename(filename)
        _integer(size_bytes, 1, self.max_source_bytes, "size_bytes")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            raise DomainError("INVALID_ARGUMENT", "Expected SHA-256 must have 64 hexadecimal digits.", "sha256")
        object_id = "upl_" + uuid4().hex
        path = self._path(ctx, "uploads", object_id)
        with self._db() as db:
            with path.open("xb") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            self._sync_directory(path.parent)
            db.execute("INSERT INTO uploads VALUES (?,?,?,?,?,?,?,?,?)",
                       (object_id, ctx.subject, filename, size_bytes, sha256.lower(), 0,
                        "uploading", None, time.time()))
            return self._public(self._row(db, "uploads", ctx, object_id), "upload")

    def upload_get(self, ctx: AccessContext, upload_id: str) -> dict:
        with self._db() as db:
            return self._public(self._row(db, "uploads", ctx, upload_id), "upload")

    def upload_chunk(self, ctx: AccessContext, upload_id: str, offset: int, data_base64: str) -> dict:
        _integer(offset, 0, self.max_source_bytes, "offset")
        with self._db() as db:
            row = self._row(db, "uploads", ctx, upload_id)
            if row["status"] != "uploading":
                raise DomainError("INVALID_STATE", "The upload is not open.", upload_id)
            if (not isinstance(data_base64, str)
                    or len(data_base64) > 4 * ((self.max_chunk_bytes + 2) // 3)):
                raise DomainError("LIMIT_EXCEEDED", "The upload chunk is too large.")
            try:
                data = base64.b64decode(data_base64, validate=True)
            except (ValueError, binascii.Error):
                raise DomainError("INVALID_ARGUMENT", "The chunk must use valid base64.") from None
            _integer(len(data), 1, self.max_chunk_bytes, "chunk_bytes")
            if offset + len(data) > row["size_bytes"]:
                raise DomainError("LIMIT_EXCEEDED", "The chunk exceeds the declared file size.")
            path = self._path(ctx, "uploads", upload_id)
            if not path.is_file():
                raise DomainError("INTEGRITY_ERROR", "The upload data is missing.")
            with path.open("r+b") as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise DomainError("UNSAFE_PATH", "Upload data must be a regular file without extra links.")
                if metadata.st_size < row["offset"]:
                    raise DomainError("INTEGRITY_ERROR", "The upload data is incomplete.")
                stream.truncate(row["offset"])
                if offset < row["offset"]:
                    committed = db.execute("SELECT * FROM upload_chunks WHERE upload_id=? AND offset=?",
                                           (upload_id, offset)).fetchone()
                    stream.seek(offset)
                    if (committed is None or committed["size_bytes"] != len(data)
                            or committed["sha256"] != hashlib.sha256(data).hexdigest()
                            or stream.read(len(data)) != data):
                        raise DomainError("REVISION_CONFLICT", "Retry bytes differ from the stored chunk.")
                elif offset == row["offset"]:
                    stream.seek(offset)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    db.execute("INSERT INTO upload_chunks VALUES (?,?,?,?)",
                               (upload_id, offset, len(data), hashlib.sha256(data).hexdigest()))
                    db.execute("UPDATE uploads SET offset=? WHERE id=?", (offset + len(data), upload_id))
                else:
                    raise DomainError("REVISION_CONFLICT", "Resume at the committed upload offset.")
            return self._public(self._row(db, "uploads", ctx, upload_id), "upload")

    @staticmethod
    def _verify(path: Path, size_bytes: int, digest: str) -> None:
        DomainStore._check_path(path)
        try:
            metadata = path.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise DomainError("UNSAFE_PATH", "Stored files must be regular files without extra links.")
            if metadata.st_size != size_bytes:
                raise DomainError("INTEGRITY_ERROR", "Stored file size does not match metadata.")
            actual = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    actual.update(chunk)
            if actual.hexdigest() != digest:
                raise DomainError("INTEGRITY_ERROR", "Stored file hash does not match metadata.")
        except OSError:
            raise DomainError("INTEGRITY_ERROR", "Stored file is unavailable.") from None

    @staticmethod
    def _verify_pdf(path: Path):
        # This checks the file envelope only. Run structural parsing in the
        # bounded PDF preparation process, not in the upload service.
        with path.open("rb") as stream:
            header = stream.read(8)
            stream.seek(max(0, path.stat().st_size - 1024))
            trailer = stream.read(1024)
        if not re.match(rb"%PDF-[12]\.[0-9]", header) or b"%%EOF" not in trailer:
            raise DomainError("INVALID_PDF", "The file does not have a PDF header and trailer.")

    def upload_complete(self, ctx: AccessContext, upload_id: str) -> dict:
        with self._db() as db:
            row = self._row(db, "uploads", ctx, upload_id)
            if row["status"] == "complete":
                source = self._row(db, "sources", ctx, row["source_id"])
                path = self._path(ctx, "sources", source["id"])
                self._verify(path, source["size_bytes"], source["sha256"])
                return self._public(source, "source")
            if row["status"] != "uploading" or row["offset"] != row["size_bytes"]:
                raise DomainError("INVALID_STATE", "Complete all upload chunks before finalization.")
            source_id = "src_" + upload_id[4:]
            pending = self._path(ctx, "uploads", upload_id)
            destination = self._path(ctx, "sources", source_id)
            # A file rename can complete before the metadata transaction commits.
            path = destination if destination.exists() else pending
            self._verify(path, row["size_bytes"], row["sha256"])
            self._verify_pdf(path)
            if path == pending:
                os.replace(pending, destination)
                self._sync_directory(destination.parent)
                self._sync_directory(pending.parent)
            db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?)",
                       (source_id, ctx.subject, row["filename"], row["size_bytes"], row["sha256"], time.time()))
            db.execute("UPDATE uploads SET status='complete',source_id=? WHERE id=?", (source_id, upload_id))
            return self._public(self._row(db, "sources", ctx, source_id), "source")

    def upload_abort(self, ctx: AccessContext, upload_id: str) -> dict:
        with self._db() as db:
            row = self._row(db, "uploads", ctx, upload_id)
            if row["status"] == "complete":
                raise DomainError("INVALID_STATE", "A completed upload cannot be aborted.")
            self._path(ctx, "uploads", upload_id).unlink(missing_ok=True)
            self._path(ctx, "sources", "src_" + upload_id[4:]).unlink(missing_ok=True)
            db.execute("UPDATE uploads SET status='aborted' WHERE id=?", (upload_id,))
            return self._public(self._row(db, "uploads", ctx, upload_id), "upload")

    def source_get(self, ctx: AccessContext, source_id: str) -> dict:
        with self._db() as db:
            return self._public(self._row(db, "sources", ctx, source_id), "source")

    def source_delete(self, ctx: AccessContext, source_id: str) -> dict:
        """Remove a source and its PDF bytes. Artifacts of earlier runs stay immutable."""
        with self._db() as db:
            row = self._row(db, "sources", ctx, source_id)
            self._path(ctx, "sources", source_id).unlink(missing_ok=True)
            db.execute("DELETE FROM sources WHERE id=?", (source_id,))
            db.execute("DELETE FROM flag_decisions WHERE subject=? AND source_id=?", (ctx.subject, source_id))
            return self._public(row, "source")

    def source_path(self, ctx: AccessContext, source_id: str) -> Path:
        with self._db() as db:
            row = self._row(db, "sources", ctx, source_id)
            path = self._path(ctx, "sources", source_id)
            self._verify(path, row["size_bytes"], row["sha256"])
            return path

    def _list(self, ctx: AccessContext, table: str, kind: str, limit: int, cursor: str | None,
              run_id: str | None = None) -> dict:
        _integer(limit, 1, 100, "limit")
        if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r"[a-z]+_[0-9a-f]{32}", cursor)):
            raise DomainError("INVALID_ARGUMENT", "The page cursor is invalid.", "cursor")
        query = f"SELECT * FROM {table} WHERE subject=? AND id>?"
        values = [ctx.subject, cursor or ""]
        if run_id is not None:
            query += " AND run_id=?"
            values.append(run_id)
        with self._db() as db:
            rows = db.execute(query + " ORDER BY id LIMIT ?", (*values, limit + 1)).fetchall()
        return {"items": [self._public(row, kind) for row in rows[:limit]],
                "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None}

    def source_list(self, ctx: AccessContext, limit: int = 50, cursor: str | None = None) -> dict:
        return self._list(ctx, "sources", "source", limit, cursor)

    def artifact_register(self, ctx: AccessContext, path: Path | str, role: str, run_id: str,
                          revision: int, media_type: str, filename: str) -> dict:
        filename = _filename(filename)
        _integer(revision, 0, 2**31 - 1, "revision")
        for target, value in (("role", role), ("run_id", run_id), ("media_type", media_type)):
            if not isinstance(value, str) or not value or len(value) > 256 or any(ord(c) < 32 for c in value):
                raise DomainError("INVALID_ARGUMENT", f"{target} is invalid.", target)
        path = Path(os.path.abspath(path))
        self._check_path(path)
        if not path.is_relative_to(self.namespace_root(ctx)) or not path.is_file():
            raise DomainError("UNSAFE_PATH", "An artifact must be a file in the private namespace.")
        if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1:
            raise DomainError("UNSAFE_PATH", "An artifact must be a regular file without extra links.")
        object_id = "art_" + uuid4().hex
        destination = self._path(ctx, "artifacts", object_id)
        digest, size = hashlib.sha256(), 0
        try:
            with path.open("rb") as source, destination.open("xb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > 256 * 1024 * 1024:
                        raise DomainError("LIMIT_EXCEEDED", "The artifact exceeds 256 MiB.")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            self._sync_directory(destination.parent)
            with self._db() as db:
                db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (object_id, ctx.subject, filename, size, digest.hexdigest(), role,
                            run_id, revision, media_type, time.time()))
                return self._public(self._row(db, "artifacts", ctx, object_id), "artifact")
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def artifact_get(self, ctx: AccessContext, artifact_id: str) -> dict:
        with self._db() as db:
            return self._public(self._row(db, "artifacts", ctx, artifact_id), "artifact")

    def artifact_list(self, ctx: AccessContext, run_id: str | None = None,
                      limit: int = 50, cursor: str | None = None) -> dict:
        return self._list(ctx, "artifacts", "artifact", limit, cursor, run_id)

    def artifact_read(self, ctx: AccessContext, artifact_id: str, offset: int = 0,
                      length: int | None = None) -> dict:
        _integer(offset, 0, 256 * 1024 * 1024, "offset")
        length = self.max_chunk_bytes if length is None else length
        _integer(length, 1, self.max_chunk_bytes, "length")
        with self._db() as db:
            row = self._row(db, "artifacts", ctx, artifact_id)
            if offset > row["size_bytes"]:
                raise DomainError("INVALID_ARGUMENT", "The offset exceeds the artifact size.", "offset")
            path = self._path(ctx, "artifacts", artifact_id)
            self._verify(path, row["size_bytes"], row["sha256"])
            with path.open("rb") as stream:
                stream.seek(offset)
                data = stream.read(length)
            return {"artifact_id": artifact_id, "offset": offset, "length": len(data),
                    "data_base64": base64.b64encode(data).decode("ascii"),
                    "eof": offset + len(data) == row["size_bytes"], "sha256": row["sha256"]}

    def notes_read(self, ctx: AccessContext, run_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT revision,text FROM notes WHERE subject=? AND run_id=?",
                             (ctx.subject, run_id)).fetchone()
            if row is None:
                raise DomainError("NOT_FOUND", "The requested run notes do not exist.")
            return {"run_id": run_id, **dict(row)}

    def notes_update(self, ctx: AccessContext, run_id: str, expected_revision: int, text: str) -> dict:
        _integer(expected_revision, 0, 2**31 - 1, "expected_revision")
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
            raise DomainError("INVALID_ARGUMENT", "The run identifier is invalid.", "run_id")
        if not isinstance(text, str):
            raise DomainError("INVALID_ARGUMENT", "Run notes must contain text.", "text")
        try:
            encoded_size = len(text.encode("utf-8"))
        except UnicodeError:
            raise DomainError("INVALID_ARGUMENT", "Run notes must use valid Unicode.", "text") from None
        if encoded_size > 64 * 1024:
            raise DomainError("LIMIT_EXCEEDED", "Run notes must not exceed 64 KiB.")
        with self._db() as db:
            row = db.execute("SELECT revision FROM notes WHERE subject=? AND run_id=?",
                             (ctx.subject, run_id)).fetchone()
            current = row["revision"] if row else 0
            if current != expected_revision:
                raise DomainError("REVISION_CONFLICT", "The note revision changed. Read the notes and retry.")
            db.execute("INSERT INTO notes VALUES (?,?,?,?) ON CONFLICT(subject,run_id) "
                       "DO UPDATE SET revision=excluded.revision,text=excluded.text",
                       (ctx.subject, run_id, current + 1, text))
            return {"run_id": run_id, "revision": current + 1, "text": text}

    def flag_decisions(self, ctx: AccessContext, source_id: str | None = None, page: int | None = None,
                       limit: int = 1000) -> list[dict]:
        """Decisions of this principal, oldest first: of one source page, or of all sources."""
        query, values = "SELECT * FROM flag_decisions WHERE subject=?", [ctx.subject]
        if source_id is not None:
            query += " AND source_id=? AND page=?"
            values += [source_id, page]
        with self._db() as db:
            rows = db.execute(query + " ORDER BY created, flag_id LIMIT ?", (*values, limit)).fetchall()
        return [{"source_id": row["source_id"], "page": row["page"], "flag_id": row["flag_id"],
                 **json.loads(row["decision"])} for row in rows]

    def flag_decision_set(self, ctx: AccessContext, source_id: str, page: int, flag_id: str,
                          decision: dict | None) -> None:
        """Store or, with None, remove the decision on one flag. The source must exist."""
        with self._db() as db:
            self._row(db, "sources", ctx, source_id)
            db.execute("DELETE FROM flag_decisions WHERE subject=? AND source_id=? AND page=? AND flag_id=?",
                       (ctx.subject, source_id, page, flag_id))
            if decision is not None:
                db.execute("INSERT INTO flag_decisions VALUES (?,?,?,?,?,?)",
                           (ctx.subject, source_id, page, flag_id, json.dumps(decision, ensure_ascii=False), time.time()))
