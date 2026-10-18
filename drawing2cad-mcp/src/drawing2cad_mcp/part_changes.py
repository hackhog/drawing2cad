"""Report construction changes against a retained validated build."""

from copy import deepcopy

from .part_schema import _references


def _items(description, key, identifier):
    return {item[identifier]: item for item in description.get(key, [])}


def baseline(description, revision, digest, build):
    """Keep bounded inputs and results needed for a later comparison."""
    return {
        "revision": revision,
        "description_sha256": digest,
        "parameters": deepcopy(description.get("parameters", [])),
        "features": deepcopy(description["features"]),
        "build": {
            "candidate_sha256": build.get("candidate_sha256"),
            "feature_results": deepcopy(build.get("build", {}).get("feature_results", [])),
            "measured": deepcopy(build.get("validation", {}).get("measured", {})),
            "checks": deepcopy(build.get("validation", {}).get("checks", [])),
        } if build and build.get("status") == "pass" else None,
    }


def proposed_change(base, description, revision):
    old = _items(base, "parameters", "name")
    new = _items(description, "parameters", "name")
    changes = []
    for name in sorted(old.keys() | new.keys()):
        before, after = old.get(name), new.get(name)
        if before == after:
            continue
        paths = []
        for index, feature in enumerate(description["features"]):
            paths.extend({"feature_id": feature["id"], "path": f"/features/{index}" + path}
                         for reference, path in _references(feature) if reference == name)
        changes.append({"name": name,
                        "before": {key: before[key] for key in ("value", "unit") if key in before} if before else None,
                        "after": {key: after[key] for key in ("value", "unit") if key in after} if after else None,
                        "value_or_unit_changed": (before or {}).get("value") != (after or {}).get("value")
                                                 or (before or {}).get("unit") != (after or {}).get("unit"),
                        "metadata_changed": {key: value for key, value in (before or {}).items() if key not in {"value", "unit"}}
                                            != {key: value for key, value in (after or {}).items() if key not in {"value", "unit"}},
                        "direct_references": paths})
    old_features = _items(base, "features", "id")
    new_features = _items(description, "features", "id")
    changed_defs = sorted(identifier for identifier in old_features.keys() | new_features.keys()
                          if old_features.get(identifier) != new_features.get(identifier))
    old_order = [feature["id"] for feature in base["features"]]
    order = [feature["id"] for feature in description["features"]]
    if old_order != order:
        changed_defs = sorted(set(changed_defs) | {identifier for index, identifier in enumerate(order)
                                                   if index >= len(old_order) or old_order[index] != identifier})
    direct = {path["feature_id"] for change in changes for path in change["direct_references"]}
    direct.update(changed_defs)
    downstream = {identifier for item in direct for sequence in (old_order, order) if item in sequence
                  for identifier in sequence[sequence.index(item) + 1:]}
    downstream &= set(order)
    return {"status": "pending_rebuild", "baseline": deepcopy(base), "target_revision": revision,
            "parameter_changes": changes, "changed_feature_definitions": changed_defs,
            "direct_features": sorted(direct), "potentially_affected_downstream_features": sorted(downstream),
            "actual_effect": {"status": "not_tested"}}


def _numeric_delta(before, after):
    if type(before) in (int, float) and type(after) in (int, float):
        return after - before
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        if all(type(item) in (int, float) for item in before + after):
            return [right - left for left, right in zip(before, after)]
    return None


def built_effect(report, build):
    """Record measured deltas without interpreting equal volume as unchanged shape."""
    report = deepcopy(report)
    old = report["baseline"]["build"]
    if not old:
        report["status"] = "no_validated_baseline"
        return report
    if not build or build.get("status") != "pass":
        report["status"] = "rebuild_failed"
        checks = deepcopy((build or {}).get("validation", {}).get("checks", []))
        report["actual_effect"] = {"status": "fail", "checks": checks,
                                   "fresh_worker_reimport": next((item.get("status") for item in checks
                                                                  if item.get("check") == "fresh_worker_reimport"), "not_tested"),
                                   "build_import_agreement": deepcopy((build or {}).get("agreement", {"status": "not_tested"}))}
        return report
    previous = {item["feature_id"]: item for item in old["feature_results"]}
    current = {item["feature_id"]: item for item in build.get("build", {}).get("feature_results", [])}
    feature_effects = []
    for identifier in sorted(previous.keys() | current.keys()):
        before, after = previous.get(identifier), current.get(identifier)
        feature_effects.append({"feature_id": identifier,
                                "before_volume_mm3": before.get("volume_after_mm3") if before else None,
                                "after_volume_mm3": after.get("volume_after_mm3") if after else None,
                                "volume_delta_mm3": _numeric_delta(before.get("volume_after_mm3"), after.get("volume_after_mm3")) if before and after else None})
    before_measured = old["measured"]
    after_measured = build.get("validation", {}).get("measured", {})
    geometry = {key: {"before": before_measured.get(key), "after": after_measured.get(key),
                      "delta": _numeric_delta(before_measured.get(key), after_measured.get(key))}
                for key in ("volume_mm3", "bbox_min", "bbox_max")}
    report["status"] = "validated_rebuild"
    report["actual_effect"] = {
        "status": "pass", "candidate_sha256": build.get("candidate_sha256"),
        "feature_operation_volumes": feature_effects, "aggregate_geometry": geometry,
        "local_checks": {"before": deepcopy(old["checks"]),
                         "after": deepcopy(build.get("validation", {}).get("checks", []))},
        "fresh_worker_reimport": next((item.get("status") for item in build.get("validation", {}).get("checks", [])
                                       if item.get("check") == "fresh_worker_reimport"), "not_tested"),
        "build_import_agreement": deepcopy(build.get("agreement", {"status": "not_tested"})),
    }
    return report
