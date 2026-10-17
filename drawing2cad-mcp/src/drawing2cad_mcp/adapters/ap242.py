"""Restricted-worker AP242 exchange with a bounded construction adapter."""

from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from .construction import MAX_STEP, PROFILE, change_parameters, embed_construction, read_construction
from ..cad_validation import measure_shape, step_metadata
from ..part_schema import parse_description


def export_ap242_candidate(shape, description: dict, output_dir: str | Path, *, pmi: dict | None = None) -> dict:
    """Export through OCCT. Attach declarative construction after CAD export."""
    from .semantic_pmi import export_ap242

    part = parse_description(description)
    measured = measure_shape(shape, part)
    if measured["status"] != "pass":
        return {**measured, "candidate_step": None}
    candidate = Path(output_dir) / "candidate.step"
    if candidate.exists():
        raise ValueError("The candidate path already exists. Use a fresh job directory.")
    report = export_ap242(shape, candidate, part.name, pmi=pmi, description=description)
    original = candidate.read_text(encoding="utf-8")
    combined, construction = embed_construction(original, description, pmi=pmi)
    candidate.write_text(combined, encoding="utf-8", newline="\n")
    if pmi is not None:
        from .semantic_pmi import verify_ap242_pmi
        report["readback"] = verify_ap242_pmi(candidate, pmi, description)
    metadata = step_metadata(candidate, part.name)
    checks = [*measured["checks"], *metadata["checks"],
              {"check": "fresh_worker_reimport", "status": "not_tested", "reason": "A separate restricted worker must import this candidate."}]
    return {"status": "fail" if any(item["status"] == "fail" for item in checks) else "pass",
            "candidate_step": str(candidate), "checks": checks, "measured": measured["measured"],
            "step": {key: value for key, value in metadata.items() if key != "checks"},
            "construction": construction, "pmi": report,
            "versions": {"build123d": version("build123d"), "ocp": version("cadquery-ocp-novtk")}}


def _agreement(original, rebuilt):
    """Compare occupied material in both directions, with bounded tolerances."""
    if not original.is_valid or not rebuilt.is_valid or len(original.solids()) != 1 or len(rebuilt.solids()) != 1:
        raise ValueError("STEP reconstruction requires one valid solid in each model.")
    scale = max(float(original.volume), float(rebuilt.volume), 1.0)
    volume_tolerance = max(1e-6, scale * 1e-8)
    original_only = float(original.cut(rebuilt).volume)
    rebuilt_only = float(rebuilt.cut(original).volume)
    first, second = original.bounding_box(), rebuilt.bounding_box()
    bbox_delta = max(abs(a - b) for a, b in zip([*first.min, *first.max], [*second.min, *second.max]))
    result = {"check": "construction_brep_agreement", "status": "pass" if original_only <= volume_tolerance and rebuilt_only <= volume_tolerance and bbox_delta <= 1e-6 else "fail",
              "method": "bidirectional_boolean_difference_and_bounding_box", "original_only_volume_mm3": original_only,
              "rebuilt_only_volume_mm3": rebuilt_only, "volume_tolerance_mm3": volume_tolerance,
              "bbox_max_delta_mm": bbox_delta, "bbox_tolerance_mm": 1e-6,
              "scope": "Numerical occupied-material comparison; not formal geometry or EXPRESS proof."}
    return result


def reconstruct_step(input_path: str | Path, output_dir: str | Path, parameter_changes: dict | None = None) -> dict:
    """Rebuild from STEP bytes only. Never load source paths from its payload."""
    from build123d import import_step
    from ..cad_kernel import build, build_shape

    path = Path(input_path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_STEP + 1)
    if len(raw) > MAX_STEP:
        raise ValueError("STEP input exceeds the supported size.")
    payload = read_construction(raw.decode("utf-8"))
    description = payload["description"]
    from .semantic_pmi import verify_ap242_pmi
    pmi_readback = verify_ap242_pmi(path, payload["pmi"] or {"schema_version": "drawing2cad.pmi/1", "dimensions": []}, description)
    metadata = step_metadata(path, description["name"])
    if any(item["status"] == "fail" for item in metadata["checks"]):
        return {"status": "fail", "candidate_step": None, "description": description,
                "input_sha256": sha256(raw).hexdigest(), "checks": metadata["checks"],
                "construction": {"profile": PROFILE, "original_agreement": "not_tested"}}
    original = import_step(path)
    rebuilt, feature_results = build_shape(description)
    agreement = _agreement(original, rebuilt)
    if agreement["status"] != "pass":
        return {"status": "fail", "candidate_step": None, "description": description,
                "input_sha256": sha256(raw).hexdigest(), "checks": [agreement],
                "construction": {"profile": PROFILE, "original_agreement": "fail"}}
    changed = change_parameters(description, parameter_changes or {})
    result = build(changed, output_dir, export_profile="ap242", pmi=payload["pmi"])
    result["description"] = changed
    result["input_sha256"] = sha256(raw).hexdigest()
    result["checks"] = [agreement, *result.get("checks", [])]
    result["construction"] = {**result.get("construction", {}), "profile": PROFILE,
                              "original_agreement": "pass", "original_feature_count": len(feature_results),
                              "input_pmi_readback": pmi_readback,
                              "parameter_changes": parameter_changes or {}, "input_description_sha256": payload["description_sha256"],
                              "scope": "Installed drawing2cad adapter; application-specific declarative construction only.",
                              "standard_procedural_history": "not_supported", "target_cad_native_history": "not_tested"}
    return result
