"""Exercise AP242 and bounded replay through a real remote MCP connection."""

from drawing2cad_mcp.drawing_contract import description_digest
from test_drafting import drawing_fixture
from test_http import running_server
from test_remote_delivery import (delivery_app, delivery_session, call, upload,
    source_pdf_bytes, coverage, download, expect_error)


async def test_remote_ap242_drawing_release_and_step_only_replay(delivery_app):
    async with running_server(delivery_app) as url:
        async with delivery_session(url) as session:
            source = await upload(session, source_pdf_bytes())
            description, drawing = drawing_fixture()
            description["evidence"][0]["source"].update(source_id=source["source_id"], source_sha256=source["sha256"])
            drawing["description_sha256"] = description_digest(description)
            await call(session, "part_create", run_id="ap242_remote", description=description,
                sources=[{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}])
            schema = await call(session, "pmi_schema")
            assert schema["schema"]["additionalProperties"] is False
            pmi = {"schema_version": "drawing2cad.pmi/1", "dimensions": [{
                "id": "bore_diameter", "kind": "diameter", "feature_id": "hole",
                "evidence_ids": ["drawing"], "value": 8,
                "targets": [{"surface": "cylinder", "axis": "Z", "origin": [30, 15, 0], "radius": 4}],
                "annotation": {"origin": [45, 25, 15], "normal": "Z", "x_axis": "X", "text_height": 2.5}}]}
            args = {"run_id": "ap242_remote", "expected_revision": 1}
            built = await call(session, "build_from_description", **args, export_profile="ap242", pmi=pmi)
            assert built["status"] == "pass", built
            replay = built["build"]["step_only_reconstruction"]
            assert replay["status"] == "pass"
            assert replay["input_sha256"] == built["build"]["candidate_sha256"]
            assert replay["construction"]["original_agreement"] == "pass"
            analysis = built["build"]["independent_analysis"]
            assert analysis["status"] == "pass" and analysis["analyzer"] == "STEPcode"
            assert analysis["input_sha256"] == built["build"]["candidate_sha256"]
            assert analysis["worker"]["worker_id"] != replay["worker"]["worker_id"]
            assert analysis["nominal_pmi"]["status"] == "pass", analysis
            assert analysis["nominal_pmi"]["dimensions"][0]["value"] == 8
            assert "pmi_inventory" not in analysis
            visual = await call(session, "part_render_pmi", **args)
            assert visual["status"] == "pass" and visual["released"] is False
            assert visual["source_sha256"] == built["build"]["candidate_sha256"]
            assert visual["inspection"]["dimensions"][0]["value"] == 8
            assert visual["inspection"]["visual_review"] == "not_tested"
            for output in visual["artifacts"]:
                await download(session, output)
            rendered = await call(session, "drawing_render", **args, drawing_spec=drawing)
            await call(session, "drawing_review", **args, drawing_sha256=rendered["drawing"]["drawing_sha256"],
                reviewer="Synthetic M3 integration reviewer", reason="Synthetic geometry and drawing contract test.",
                source_hashes=[source["sha256"]], decision="accepted")
            released = await call(session, "export_step", **args, coverage=coverage(source))
            assert released["release"]["export_profile"] == "ap242"
            artifact = released["release"]["artifact"]
            raw = await download(session, artifact)
            assert b"AP242_MANAGED_MODEL_BASED_3D_ENGINEERING" in raw
            assert b"DIMENSIONAL_SIZE" in raw and b"drawing2cad.construction.v1" in raw
            visual = await call(session, "step_render_pmi", artifact_id=artifact["artifact_id"],
                                expected_sha256=artifact["sha256"])
            assert visual["status"] == "pass" and visual["source_artifact_id"] == artifact["artifact_id"]
            assert visual["source_sha256"] == artifact["sha256"]
            reconstructed = await call(session, "step_reconstruct", artifact_id=artifact["artifact_id"],
                                        expected_sha256=artifact["sha256"])
            assert reconstructed["status"] == "pass", reconstructed
            assert reconstructed["released"] is False
            assert reconstructed["replay_id"] != "ap242_remote"
            for output in reconstructed["artifacts"]:
                await download(session, output)
            # A reconstruction cannot change or approve the original run.
            state = await call(session, "part_read", run_id="ap242_remote")
            assert state["part"]["revision"] == 1
            await call(session, "build_from_description", **args)
            # A rebuild clears the drawing review. The release states that the drawing is unreviewed.
            rereleased = await call(session, "export_step", **args, coverage=coverage(source))
            assert rereleased["release"]["drawing"]["status"] == "unreviewed"
