"""Review measurements of the web adapter: the time that a person used to review a drawing, and the estimated time of
a manual rebuild of the part.

The overview compares these values with the run time to show the benefit. Measurements are web-adapter data and
not domain data, so they stay out of the domain service. Each source has one file with a list of measurements.
"""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .jobs import write_json, now
from .service import checked_id

# One day of review is a forgotten stopwatch, not a review.
MAX_REVIEW_SECONDS = 24 * 3600
MAX_MANUAL_HOURS = 1000


class MeasurementInput(BaseModel):
    """One review of one drawing. The estimate is optional: a person can stop the stopwatch without one."""

    review_seconds: float = Field(gt=0, le=MAX_REVIEW_SECONDS)
    manual_hours: float | None = Field(default=None, gt=0, le=MAX_MANUAL_HOURS)
    estimator: Literal["drafter", "guest", "team"] | None = None


class MeasurementStore:
    """Measurement files below one directory. Source IDs are checked and never select another path."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, source_id: str) -> Path:
        return self.root / f"{checked_id(source_id, 'src')}.json"

    def _read(self, path: Path) -> list[dict[str, Any]]:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def add(self, source_id: str, measurement: MeasurementInput) -> dict[str, Any]:
        record = {"measurement_id": "msr_" + uuid4().hex, "source_id": source_id, **measurement.model_dump(),
                  "recorded_at": now()}
        with self._lock:
            path = self._path(source_id)
            write_json(path, [*self._read(path), record])
        return record

    def list(self) -> list[dict[str, Any]]:
        records = [m for path in self.root.glob("src_*.json") for m in self._read(path)]
        return sorted(records, key=lambda m: m["recorded_at"])

    def remove(self, source_id: str) -> None:
        with self._lock:
            self._path(source_id).unlink(missing_ok=True)
