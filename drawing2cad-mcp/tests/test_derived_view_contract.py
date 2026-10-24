"""View-kind contracts through runtime, MCP, and the local model adapter. No CAD execution."""

from copy import deepcopy
import json

from jsonschema import Draft202012Validator
from mcp.types import CallToolRequestParams
import pytest

from drawing2cad_mcp.config import Settings
from drawing2cad_mcp.derived_views import normalize_requests
from drawing2cad_mcp.domain_service import DomainService
from drawing2cad_mcp.domain_store import DomainError
from drawing2cad_mcp.domain_tools import DOMAIN_SCHEMAS
from drawing2cad_mcp.local_model_client import Trace, decode_json_text_arguments, drive, tool_catalog
from drawing2cad_mcp.server import Application

TOP = {"id": "top", "kind": "orthographic", "view_direction": [0, 0, 1], "up": [0, 1, 0]}
ISO = {"id": "iso", "kind": "isometric", "view_direction": [1, -1, 1], "up": [0, 0, 1]}
SECTION = {"id": "section_a", "kind": "section", "up": [0, 0, 1],
           "cutting_plane": {"letter": "A", "origin": [0, 0, 0], "normal": [0, -1, 0],
                             "viewing_side": "positive_normal", "source_view_id": "top"}}
PRIVATE = "/srv/private-customer/secret-drawing.pdf"


def arguments(view):
    views = [TOP, view] if view["kind"] == "section" else [view]
    return {"run_id": "localtest-a", "expected_revision": 1, "views": deepcopy(views)}


@pytest.fixture
def app(tmp_path):
    value = Application(Settings.model_validate({
        "pdf": {"allowed_roots": [str(tmp_path)], "output_root": str(tmp_path / "output")},
        "domain": {"enabled": True}, "cad": {"enabled": True}}))
    yield value
    value.domain.close()



@pytest.mark.parametrize("view", [TOP, ISO, SECTION], ids=["orthographic", "isometric", "section"])
@pytest.mark.parametrize("explicit", [False, True], ids=["defaults", "explicit-options"])
def test_valid_forms_preserve_defaults_and_supported_options(view, explicit):
    request = arguments(view)
    if explicit:
        request["views"][-1].update(projection_type="parallel", hidden_lines=True,
                                    scale_convention="isometric_projection" if view["kind"] == "isometric" else "true_size")
    Draft202012Validator(DOMAIN_SCHEMAS["drawing_derive_views"]).validate(request)
    normalized = normalize_requests(request["views"])[-1]
    assert normalized["kind"] == view["kind"]
    assert normalized["hidden_lines"] == (True if explicit else view["kind"] == "orthographic")
    expected = "isometric_projection" if explicit else "isometric_drawing"
    assert normalized["projection"]["scale_convention"] == (expected if view["kind"] == "isometric" else "true_size")


def invalid_views():
    for view in (TOP, ISO, SECTION):
        needed = "cutting_plane" if view["kind"] == "section" else "view_direction"
        forbidden = "view_direction" if view["kind"] == "section" else "cutting_plane"
        missing = deepcopy(view)
        del missing[needed]
        yield pytest.param(missing, needed, forbidden, id=view["kind"] + "-missing")
        for value, name in ((None, "null"), (SECTION["cutting_plane"] if forbidden == "cutting_plane" else [0, -1, 0], "value")):
            yield pytest.param({**view, forbidden: value}, needed, forbidden, id=view["kind"] + "-forbidden-" + name)
        yield pytest.param({**view, needed: None}, needed, forbidden, id=view["kind"] + "-required-null")


@pytest.mark.parametrize("view,needed,forbidden", list(invalid_views()))
async def test_invalid_forms_fail_with_actionable_private_feedback(app, view, needed, forbidden):
    request = arguments(view)
    validator = Draft202012Validator(DOMAIN_SCHEMAS["drawing_derive_views"])
    assert not validator.is_valid(request)
    with pytest.raises(ValueError) as runtime:
        normalize_requests(request["views"])
    assert PRIVATE not in str(runtime.value)
    with pytest.raises(DomainError) as domain:
        DomainService._validate("drawing_derive_views", request)
    result = await app.on_call_tool(None, CallToolRequestParams(name="drawing_derive_views", arguments=request))
    assert result.is_error
    for error in (domain.value.to_dict(), result.structured_content["error"]):
        text = json.dumps(error)
        assert "supply " + needed in text and "omit " + forbidden in text
        assert "Remove a forbidden field; do not set it to null" in text
        assert PRIVATE not in text


async def test_published_catalog_survives_local_provider_adapter_and_nested_decoding(app):
    catalog = (await app.on_list_tools(None)).model_dump(mode="json", by_alias=True)["tools"]
    item = next(item for item in catalog if item["name"] == "drawing_derive_views")
    schema = item["inputSchema"]
    assert schema == app.get_schema("drawing_derive_views") == DOMAIN_SCHEMAS["drawing_derive_views"]
    adapted = next(item for item in tool_catalog(catalog) if item["function"]["name"] == "drawing_derive_views")
    assert json.loads(json.dumps(adapted["function"]["parameters"])) == schema
    forms = schema["properties"]["views"]["items"]
    assert len(forms["anyOf"]) == 2 and "oneOf" not in forms
    for view in forms["examples"]:
        request = arguments(view)
        nested = request["views"][-1]
        nested["up"] = json.dumps(nested["up"])
        if view["kind"] == "section":
            nested["cutting_plane"]["origin"] = json.dumps(nested["cutting_plane"]["origin"])
            nested["cutting_plane"] = json.dumps(nested["cutting_plane"])
        else:
            nested["view_direction"] = json.dumps(nested["view_direction"])
        request["views"] = json.dumps(request["views"])
        decoded, records = decode_json_text_arguments(request, adapted["function"]["parameters"])
        Draft202012Validator(schema).validate(decoded)
        assert normalize_requests(decoded["views"])[-1]["kind"] == view["kind"]
        assert len(records) == (4 if view["kind"] == "section" else 3)


async def test_live_contract_error_reaches_model_and_keeps_repeat_guard(app, tmp_path):
    catalog = (await app.on_list_tools(None)).model_dump(mode="json", by_alias=True)["tools"]
    invalid = arguments({**TOP, "cutting_plane": None})
    payloads = []

    def model(plan, payload, timeout):
        payloads.append(deepcopy(payload))
        return {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "drawing_derive_views", "arguments": invalid}}]}}

    class Session:
        calls = 0

        async def call_tool(self, name, arguments):
            self.calls += 1
            return await app.on_call_tool(None, CallToolRequestParams(name=name, arguments=arguments))

    session = Session()
    result = await drive(session, catalog, {"model": "scripted-local-provider", "source_id": "src_" + "a" * 32,
        "source_sha256": "b" * 64, "run_prefix": "localtest", "step_budget": 4}, "Synthetic test", Trace(tmp_path), model_call=model)
    assert result["status"] == "no_progress" and session.calls == 1
    assert result["blocked_requests"] == 1 and result["no_progress"]["repeat_count"] == 2
    published = next(item for item in payloads[0]["tools"] if item["function"]["name"] == "drawing_derive_views")
    assert published["function"]["parameters"] == app.get_schema("drawing_derive_views")
    feedback = json.dumps(payloads[1]["messages"])
    assert "supply view_direction and omit cutting_plane" in feedback
    assert "do not set it to null" in feedback


@pytest.mark.parametrize("private_field", [False, True])
def test_private_values_and_unknown_keys_do_not_leak(private_field):
    view = {**TOP, PRIVATE: 1} if private_field else {**TOP, "view_direction": PRIVATE}
    with pytest.raises(ValueError) as runtime:
        normalize_requests([view])
    assert "secret" not in str(runtime.value)
    with pytest.raises(DomainError) as domain:
        DomainService._validate("drawing_derive_views", arguments(view))
    assert "secret" not in json.dumps(domain.value.to_dict())
