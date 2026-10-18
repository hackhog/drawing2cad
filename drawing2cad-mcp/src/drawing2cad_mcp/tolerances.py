"""Conservative tolerance candidates from native text or supplied transcriptions."""

from __future__ import annotations

import re
from typing import Any


_NUM = r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)"
_UNIT = r"(?:\s*(mm|deg|°))?"
_PLUS_MINUS = re.compile(rf"^\s*(?:[⌀ØR]?\s*)?({_NUM})\s*(?:±|\+/-)\s*({_NUM}){_UNIT}\s*$", re.I)
_DEVIATIONS = re.compile(rf"^\s*(?:[⌀ØR]?\s*)?({_NUM})\s+([+-](?:\d+(?:[.,]\d*)?|[.,]\d+))\s*(?:/|\s)\s*([+-](?:\d+(?:[.,]\d*)?|[.,]\d+)){_UNIT}\s*$", re.I)
_LIMITS = re.compile(rf"^\s*(?:LIMITS?\s*[:=]?\s*)?({_NUM})\s*(?:\.\.|TO)\s*({_NUM}){_UNIT}\s*$", re.I)
_STACKED_LIMITS = re.compile(rf"^\s*({_NUM})\s*\n\s*({_NUM}){_UNIT}\s*$", re.I)
_FIT = re.compile(r"^\s*(?:[⌀Ø]?\s*)?(?:(\d+(?:[.,]\d+)?)\s*)?([A-Za-z]{1,3}\d{1,2})\s*$")
_GENERAL = re.compile(r"\b(?:ISO\s*2768(?:\s*[-–]\s*[A-Za-z0-9-]+)?|GENERAL\s+TOLERANCES?\s*[:=]?\s*[^\n]{1,100})\b", re.I)


def _unit(value: str | None) -> str | None:
    if value is None:
        return None
    return "deg" if value.lower() in {"deg", "°"} else value.lower()


def _number(value: str) -> float:
    return float(value.replace(",", "."))


def parse_tolerance(raw_text: str, *, unit: str | None = None, notation_hint: str | None = None) -> dict[str, Any] | None:
    """Parse one literal. Do not infer a unit or a fit table value."""
    text = raw_text.strip()
    if not text:
        return None
    match = _PLUS_MINUS.fullmatch(text)
    if match:
        nominal, magnitude, printed_unit = match.groups()
        value = _number(magnitude)
        if value < 0:
            return {"kind": "unclear", "reason": "The tolerance magnitude is negative."}
        result = {"kind": "deviation", "printed_nominal": _number(nominal),
                  "lower_deviation": -value, "upper_deviation": value}
        result["unit"] = _unit(printed_unit or unit)
        return result
    match = _DEVIATIONS.fullmatch(text)
    if match:
        nominal, first, second, printed_unit = match.groups()
        lower, upper = sorted((_number(first), _number(second)))
        return {"kind": "deviation", "printed_nominal": _number(nominal),
                "lower_deviation": lower, "upper_deviation": upper, "unit": _unit(printed_unit or unit)}
    stacked = _STACKED_LIMITS.fullmatch(text) if notation_hint == "limits" else None
    match = _LIMITS.fullmatch(text) or stacked
    if match and (notation_hint == "limits" or text.upper().startswith("LIMIT")):
        first, second, printed_unit = match.groups()
        lower, upper = (_number(second), _number(first)) if match is stacked else (_number(first), _number(second))
        if lower > upper:
            return {"kind": "unclear", "reason": "The printed limits are not ordered."}
        return {"kind": "limits", "lower_limit": lower, "upper_limit": upper,
                "unit": _unit(printed_unit or unit)}
    match = _FIT.fullmatch(text)
    if match and (match.group(2).lower().rstrip("0123456789") in {"h", "g", "f", "js"} or notation_hint == "fit"):
        nominal, designation = match.groups()
        result = {"kind": "fit", "designation": designation}
        if nominal is not None:
            result["printed_nominal"] = _number(nominal)
        return result
    match = _GENERAL.search(text)
    if match:
        return {"kind": "general", "designation": match.group(0).strip()}
    if notation_hint in {"deviation", "limits", "fit", "general", "unclear"} or any(mark in text for mark in ("±", "+/-", "⌀", "Ø")):
        return {"kind": "unclear", "reason": "Tolerance notation needs source review."}
    return None


def candidate(raw_text: str, *, source: dict[str, Any], provenance: str,
              unit: str | None = None, confidence: float = 0.5,
              notation_hint: str | None = None) -> dict[str, Any] | None:
    """Return a source-linked candidate with explicit review state."""
    parsed = parse_tolerance(raw_text, unit=unit, notation_hint=notation_hint)
    if parsed is None:
        return None
    resolved = parsed["kind"] != "unclear" and parsed.get("unit") is not None
    if parsed["kind"] in {"fit", "general"}:
        resolved = True
    return {**parsed, "raw_text": raw_text, "confidence": confidence,
            "resolution": "resolved" if resolved else "review_required",
            "scope": "unassigned", "source": source, "provenance": provenance}
