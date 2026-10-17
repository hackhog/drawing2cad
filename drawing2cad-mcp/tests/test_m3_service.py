"""Test M3 service gates with fake workers. These are not CAD acceptance tests."""

from copy import deepcopy
import hashlib
from uuid import uuid4

import pytest

from drawing2cad_mcp.cad_service import CadError
from drawing2cad_mcp.domain_store import DomainError
from test_cad_service import FakeRunner, setup_service, create
from test_domain_service import CTX, OTHER, domain


class ReplayRunner(FakeRunner):
    def __init__(self, storage, description):
        super().__init__(storage)
        self.description = description
        self.bad_hash = False
        self.bad_replay = False
        self.requests = []

    def run(self, operation, *, description=None, input_step=None, **kwargs):
        self.requests.append((operation, deepcopy(description), deepcopy(kwargs)))
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
    assert runner.calls == ["build", "validate", "reconstruct_step"]
    assert runner.requests[-1][1] is None
    assert result["released"] is False


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
