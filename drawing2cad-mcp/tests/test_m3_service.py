"""Test M3 service gates with fake workers. These are not CAD acceptance tests."""

from copy import deepcopy
import hashlib
from uuid import uuid4

import pytest

from drawing2cad_mcp.cad_service import CadError
from drawing2cad_mcp.domain_store import DomainError
from test_cad_service import FakeRunner, setup_service, create, coverage
from test_domain_service import CTX, OTHER, domain


class ReplayRunner(FakeRunner):
    def __init__(self, storage, description):
        super().__init__(storage)
        self.description = description
        self.bad_hash = False
        self.bad_replay = False
        self.bad_analysis = False
        self.bad_analysis_hash = False
        self.requests = []

    def run(self, operation, *, description=None, input_step=None, **kwargs):
        self.requests.append((operation, deepcopy(description), deepcopy(kwargs)))
        if operation == "analyze_ap242":
            self.calls.append(operation)
            return {"status": "fail" if self.bad_analysis else "pass", "analyzer": "STEPcode",
                    "pmi_inventory": [], "pmi_inventory_complete": True, "entity_counts": {},
                    "input_sha256": "0" * 64 if self.bad_analysis_hash else hashlib.sha256(input_step.read_bytes()).hexdigest(),
                    "checks": [{"check": "independent_ap242_schema_read", "status": "pass"}],
                    "worker": {"worker_id": uuid4().hex}}
        if operation != "reconstruct_step":
            result = super().run(operation, description=description, input_step=input_step, **kwargs)
            if operation == "validate" and result.get("status") == "pass":
                result["step"]["schemas"] = ["AP242_MANAGED_MODEL_BASED_3D_ENGINEERING"]
            return result
        self.calls.append(operation)
        directory = self.storage / uuid4().hex
        directory.mkdir(parents=True)
        candidate = directory / "candidate.step"
        candidate.write_bytes(b"ISO-10303-21; synthetic replay placeholder")
        return {"status": "fail" if self.bad_replay else "pass", "candidate_step": str(candidate),
                "description": deepcopy(self.description),
                "input_sha256": "0" * 64 if self.bad_hash else hashlib.sha256(input_step.read_bytes()).hexdigest(),
                "construction": {"original_agreement": "pass"},
                "worker": {"worker_id": directory.name, "work_dir": str(directory)},
                "measured": {"volume_mm3": 1000, "bbox_min": [0, 0, 0], "bbox_max": [20, 10, 5]}}


def test_pmi_rejects_default_ap214_profile(setup_service):
    service, runner, _, _ = setup_service
    create(setup_service)
    with pytest.raises(CadError) as failure:
        service.build_from_description(run_id="example", expected_revision=1, pmi={})
    assert failure.value.code == "PMI_PROFILE_REQUIRED"
    assert runner.calls == []


@pytest.mark.parametrize("bad_hash,bad_replay", [(False, False), (True, False), (False, True)])
def test_ap242_build_requires_fresh_step_only_replay(setup_service, bad_hash, bad_replay):
    service, _, description, _ = setup_service
    create(setup_service)
    runner = ReplayRunner(service.runner.storage, description)
    runner.bad_hash, runner.bad_replay = bad_hash, bad_replay
    service.runner = runner
    result = service.build_from_description(run_id="example", expected_revision=1, export_profile="ap242")
    assert result["status"] == ("fail" if bad_hash or bad_replay else "pass")
    assert runner.calls == ["build", "validate", "reconstruct_step", "analyze_ap242"]
    assert runner.requests[-1][1] is None
    assert result["released"] is False


@pytest.mark.parametrize("bad_status,bad_hash", [(True, False), (False, True)])
def test_ap242_build_rejects_failed_or_unbound_independent_analysis(setup_service, bad_status, bad_hash):
    service, _, description, _ = setup_service
    create(setup_service)
    runner = ReplayRunner(service.runner.storage, description)
    runner.bad_analysis, runner.bad_analysis_hash = bad_status, bad_hash
    service.runner = runner
    result = service.build_from_description(run_id="example", expected_revision=1, export_profile="ap242")
    assert result["status"] == "fail" and result["released"] is False
    assert result["build"]["independent_analysis"]["input_sha256"] == (
        "0" * 64 if bad_hash else result["build"]["candidate_sha256"])


@pytest.mark.parametrize("mutation", ["remove", "hash", "missing_check"])
def test_ap242_release_requires_current_independent_evidence(setup_service, mutation):
    service, _, description, source = setup_service
    create(setup_service)
    service.runner = ReplayRunner(service.runner.storage, description)
    assert service.build_from_description(run_id="example", expected_revision=1,
                                          export_profile="ap242")["status"] == "pass"
    with service._lock("example") as directory:
        state = service._load(directory)
        if mutation == "remove":
            del state["build"]["independent_analysis"]
        elif mutation == "hash":
            state["build"]["independent_analysis"]["input_sha256"] = "0" * 64
        else:
            state["build"]["independent_analysis"]["checks"] = []
        service._save(directory, state)
    with pytest.raises(CadError) as failure:
        service.export_step(run_id="example", expected_revision=1, coverage=coverage(source))
    assert failure.value.code == "INDEPENDENT_ANALYSIS_REQUIRED"
    assert service.part_read(run_id="example")["part"]["release"] is None


def prepare_artifact(domain):
    service, _, description, _, _ = domain
    cad = service._backend(CTX)[0]
    cad.runner = ReplayRunner(cad.runner.storage, description)
    source = service.store.namespace_root(CTX) / "synthetic.step"
    source.write_bytes(b"ISO-10303-21; synthetic input placeholder")
    artifact = service.store.artifact_register(CTX, source, "released_step", "plate", 1,
                                               "model/step", "part.step")
    return service, cad.runner, artifact


def test_remote_replay_is_owner_bound_and_hash_bound(domain):
    service, runner, artifact = prepare_artifact(domain)
    args = {"artifact_id": artifact["artifact_id"], "expected_sha256": artifact["sha256"]}
    with pytest.raises(DomainError):
        service.call(OTHER, "step_reconstruct", args)
    with pytest.raises(DomainError) as failure:
        service.call(CTX, "step_reconstruct", {**args, "expected_sha256": "0" * 64})
    assert failure.value.code == "ARTIFACT_HASH_MISMATCH"
    assert runner.calls == []


def test_remote_replay_returns_unreleased_separate_artifacts(domain):
    service, runner, artifact = prepare_artifact(domain)
    result = service.call(CTX, "step_reconstruct", {"artifact_id": artifact["artifact_id"],
                          "expected_sha256": artifact["sha256"], "parameter_changes": {"length": 25}})
    assert result["status"] == "pass"
    assert result["released"] is False
    assert result["replay_id"] != "plate"
    assert len(result["artifacts"]) == 3
    assert all(item["revision"] == 0 and item["run_id"] == result["replay_id"] for item in result["artifacts"])
    assert runner.calls == ["reconstruct_step", "validate"]
    assert runner.requests[0][1] is None
    assert runner.requests[0][2]["parameter_changes"] == {"length": 25}
    state = service.call(CTX, "part_read", {"run_id": "plate"})["part"]
    assert state["revision"] == 1 and state["release"] is None


def test_replay_failed_validation_does_not_publish_candidate(domain):
    service, runner, artifact = prepare_artifact(domain)
    runner.fail_operation = "validate"
    result = service.call(CTX, "step_reconstruct", {"artifact_id": artifact["artifact_id"],
                          "expected_sha256": artifact["sha256"]})
    assert result["status"] == "fail" and result["released"] is False
    assert "artifacts" not in result
