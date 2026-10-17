"""Bounded file access for STEP inspection and application metadata adapters."""

from __future__ import annotations

from collections import Counter
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

from .adapters import identity
from .adapters.p21 import sth_p21_parse, sth_p21_validate_refs
from .adapters.pmi import read_step_pmi_extended
from .adapters.procedural import decode_procedural
from .adapters.review import append_adapter_properties, read_adapter_properties
from .step_tools import REVIEW_SCHEMAS, STEP_DESCRIPTIONS, STEP_SCHEMAS


class StepError(ValueError):
    """A structured failure with a target and a corrective action."""

    def __init__(self, code: str, message: str, target: str = "source", next_action: str = "Inspect the source and call the tool again."):
        super().__init__(message)
        self.code, self.message, self.target, self.next_action = code, message, target, next_action

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "target": self.target, "next_action": self.next_action}


class StepService:
    """Inspect permitted STEP inputs and publish separate metadata candidates."""

    def __init__(self, allowed_roots: list[Path], output_root: Path, max_step_bytes: int = 33554432):
        if not allowed_roots:
            raise ValueError("At least one STEP allowed root is required")
        if isinstance(max_step_bytes, bool) or not isinstance(max_step_bytes, int) or max_step_bytes <= 0:
            raise ValueError("max_step_bytes must be a positive integer")
        self.output_root = Path(output_root).expanduser().resolve()
        self.allowed_roots = [Path(p).expanduser().resolve() for p in allowed_roots] + [self.output_root]
        self.max_step_bytes = max_step_bytes
        self._output_identity = self._directory_identity(self.output_root)

    def _arguments(self, name: str, arguments: dict[str, Any]) -> None:
        if name not in STEP_SCHEMAS:
            raise StepError("UNKNOWN_STEP_TOOL", "Unknown STEP tool: " + name, "tool", "Use a tool in the STEP catalog.")
        if not isinstance(arguments, dict):
            raise StepError("INVALID_ARGUMENTS", "Tool arguments must be an object", "arguments")
        contract = STEP_SCHEMAS[name]
        if set(arguments) - set(contract["properties"]) or set(contract["required"]) - set(arguments):
            raise StepError("INVALID_ARGUMENTS", "Missing or unexpected tool argument", "arguments", "Use the tool input schema.")
        if not isinstance(arguments["path"], str) or not arguments["path"]:
            raise StepError("INVALID_ARGUMENTS", "path must be a nonempty string", "path")
        expected = arguments["expected_sha256"]
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise StepError("INVALID_ARGUMENTS", "expected_sha256 must contain 64 hexadecimal characters", "expected_sha256")
        if "expected_count" in arguments:
            count = arguments["expected_count"]
            if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100000:
                raise StepError("INVALID_ARGUMENTS", "expected_count must be an integer from 0 through 100000", "expected_count")
        for field in ("expected_schemas", "properties"):
            if field not in arguments:
                continue
            entries = arguments[field]
            if not isinstance(entries, dict) or not entries or set(entries) - set(REVIEW_SCHEMAS):
                raise StepError("INVALID_ARGUMENTS", "Use the supported review property names", field)
            for prop, value in entries.items():
                if field == "properties" and not isinstance(value, dict):
                    raise StepError("INVALID_ARGUMENTS", "Each review property must be a JSON object", field)
                actual = value.get("schema") if field == "properties" else value
                if actual != REVIEW_SCHEMAS[prop]:
                    raise StepError("UNSUPPORTED_REVIEW_SCHEMA", "Unsupported review schema for " + prop, field,
                                    "Supply the schema identifier in the tool catalog.")
        if "output_name" in arguments:
            value = arguments["output_name"]
            if (not isinstance(value, str) or len(value) > 128 or
                    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:step|stp)", value) or ".." in value or
                    value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *["COM" + str(i) for i in range(1, 10)], *["LPT" + str(i) for i in range(1, 10)]}):
                raise StepError("INVALID_ARGUMENTS", "output_name must be a safe STEP basename", "output_name")

    def _read(self, value: str, expected: str) -> tuple[Path, bytes, str]:
        try:
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise StepError("STEP_PATH_NOT_ALLOWED", "STEP path must be absolute", "path", "Supply an absolute path inside an allowed root.")
            path = path.resolve()
        except (OSError, ValueError) as error:
            if isinstance(error, StepError):
                raise
            raise StepError("INVALID_STEP_FILE", "Cannot resolve the STEP path", "path", "Supply a valid absolute STEP file path.") from error
        if not any(path.is_relative_to(root) for root in self.allowed_roots):
            raise StepError("STEP_PATH_NOT_ALLOWED", "STEP path is outside the allowed roots", "path", "Use an authorized file inside a configured allowed root.")
        if path.suffix.lower() not in {".step", ".stp"}:
            raise StepError("INVALID_STEP_FILE", "Expected a .step or .stp file", "path")
        try:
            with path.open("rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise StepError("INVALID_STEP_FILE", "STEP input must be a regular file", "path")
                if info.st_size > self.max_step_bytes:
                    raise StepError("STEP_SIZE_LIMIT", "STEP input exceeds the configured byte limit", "path", "Use a supported bounded STEP file.")
                raw = stream.read(self.max_step_bytes + 1)
        except OSError as error:
            raise StepError("STEP_READ_FAILED", str(error), "path", "Make the authorized STEP file readable.") from error
        if len(raw) > self.max_step_bytes:
            raise StepError("STEP_SIZE_LIMIT", "STEP input exceeds the configured byte limit", "path")
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected.lower():
            raise StepError("SOURCE_HASH_MISMATCH", "STEP source SHA-256 differs from expected_sha256", "expected_sha256",
                            "Verify the authorized source revision and supply its exact byte hash.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise StepError("INVALID_STEP_ENCODING", "STEP input must use UTF-8 or ASCII", "path") from error
        if not re.match(r"\s*ISO-10303-21\s*;", text, re.I) or not re.search(r"END-ISO-10303-21\s*;\s*$", text, re.I):
            raise StepError("INVALID_STEP_FILE", "STEP exchange structure is incomplete", "path")
        return path, raw, text

    @staticmethod
    def _directory_identity(path):
        if path.is_dir():
            info=path.stat()
            return info.st_dev,info.st_ino
        return None

    def _output_path(self):
        try:
            if self.output_root.resolve() != self.output_root or self.output_root.is_symlink():
                raise StepError("STEP_OUTPUT_ROOT_CHANGED", "The output root changed its resolved location", "output_root", "Restore the configured output directory before publishing.")
            current=self._directory_identity(self.output_root)
            if self._output_identity is not None and current != self._output_identity:
                raise StepError("STEP_OUTPUT_ROOT_CHANGED", "The output directory was replaced", "output_root", "Restore the configured output directory before publishing.")
            return self.output_root
        except OSError as error:
            raise StepError("STEP_OUTPUT_ROOT_CHANGED", "Cannot verify the configured output root", "output_root") from error

    def _publish(self, output_name: str, raw: bytes) -> Path:
        if len(raw) > self.max_step_bytes:
            raise StepError("STEP_SIZE_LIMIT", "Metadata candidate exceeds the configured byte limit", "properties")
        target = self._output_path() / output_name
        temporary = None
        try:
            try:
                self.output_root.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise StepError("STEP_WRITE_FAILED", str(error), "output_root", "Use a writable output directory.") from error
            self._output_path()
            if self._output_identity is None:
                self._output_identity=self._directory_identity(self.output_root)
            # Link a complete temporary file to the new name. A hard link never replaces a target.
            fd, temporary = tempfile.mkstemp(prefix=".step-candidate-", suffix=".tmp", dir=self.output_root)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._output_path()
            os.link(temporary, target)
        except FileExistsError as error:
            raise StepError("STEP_OUTPUT_EXISTS", "Candidate output already exists", "output_name", "Choose a new candidate output name.") from error
        except OSError as error:
            raise StepError("STEP_WRITE_FAILED", str(error), "output_name", "Use a writable output root that supports atomic hard links.") from error
        finally:
            if temporary is not None:
                # Do not follow a redirected directory to delete an unrelated file.
                try:
                    self._output_path()
                except StepError:
                    pass
                else:
                    Path(temporary).unlink(missing_ok=True)
        return target

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call one bounded adapter and return JSON-compatible source evidence."""
        self._arguments(name, arguments)
        path, raw, text = self._read(arguments["path"], arguments["expected_sha256"])
        result = {"source": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)},
                  "adapter": identity()}
        try:
            records = sth_p21_parse(text, max_bytes=self.max_step_bytes, exchange=True)
            sth_p21_validate_refs(records)
            if name == "step_inspect":
                counts = Counter(t for t, _ in records.values())
                result["inspection"] = {"entity_count": len(records), "entity_types": dict(sorted(counts.items())[:128]),
                                        "entity_type_count": len(counts), "entity_types_truncated": len(counts) > 128,
                                        "all_references_resolve": True,
                                        "procedural_representations": counts["PROCEDURAL_SHAPE_REPRESENTATION"],
                                        "syntax_profile": "header-and-single-data-section", "express_validated": False}
            elif name == "step_read_procedural":
                decoded = decode_procedural(text, records)
                result["procedural"] = {k: v for k, v in decoded.items() if k not in {"text", "records", "sha256"}}
            elif name == "step_read_pmi":
                result["pmi"] = read_step_pmi_extended(text, arguments.get("expected_count"), records)
            elif name == "step_read_review_properties":
                result["properties"] = read_adapter_properties(text, arguments["expected_schemas"], records)
            elif name == "step_append_review_properties":
                # Serialization validates JSON types, finite numbers, and payload size before any output is created.
                candidate, preservation = append_adapter_properties(text, arguments["properties"])
                new_bytes = candidate.encode("utf-8")
                if raw.startswith(b"\xef\xbb\xbf"):
                    new_bytes = b"\xef\xbb\xbf" + new_bytes
                # The original byte prefix and suffix surround the inserted entities without normalization.
                at = text.rfind("ENDSEC;")
                if not candidate.startswith(text[:at]) or not candidate.endswith(text[at:]):
                    raise ValueError("Original STEP byte regions changed")
                target = self._publish(arguments["output_name"], new_bytes)
                result["artifact"] = {"path": str(target), "sha256": hashlib.sha256(new_bytes).hexdigest(), "size_bytes": len(new_bytes)}
                result["preservation"] = {k: v for k, v in preservation.items() if k not in {"source_sha256", "output_sha256"}}
                result["metadata_only"] = True
            return result
        except StepError:
            raise
        except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError, AttributeError) as error:
            raise StepError("STEP_PROFILE_UNSUPPORTED", str(error), name,
                            "Use the documented adapter subset or an explicitly supported fallback. No CAD validity is implied.") from error
