"""Native tool contracts and full client-to-server stdio round trips."""

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolRequestParams
from PIL import Image
import pytest
import drawing2cad_mcp
from pydantic import ValidationError

from drawing2cad_mcp.config import PdfSettings, ServerSettings, Settings
from drawing2cad_mcp.server import LOCAL_TOOLS, STROKE_KINDS, Application
from drawing2cad_mcp.vector import Kind
from test_pdf import make_pdf
from test_part_schema import sample_description

SAMPLE = Path(__file__).resolve().parents[2] / "resources" / "Drawing2CAD" / "Maschinenteil" / "Maschinenteil_dwg.pdf"


@pytest.fixture
def app(tmp_path):
    return Application(Settings(pdf=PdfSettings(allowed_roots=[tmp_path], output_root=tmp_path / "out",
                                               pdftoppm=os.environ.get("DRAWING2CAD_PDFTOPPM")),
                                server=ServerSettings(preview_max_pixels=1000)))


async def invoke(app, name, **args):
    return await app.on_call_tool(None, CallToolRequestParams(name=name, arguments=args))


async def test_status_and_pdf_use_native_tools(app, tmp_path):
    source = make_pdf(tmp_path / "test.pdf")
    result = await invoke(app, "pdf_info", path=str(source))
    assert not result.is_error
    assert result.structured_content["page_count"] == 2
    assert json.loads(result.content[0].text) == result.structured_content
    status = await invoke(app, "drawing2cad_status")
    assert "freecad" not in status.structured_content
    assert "development_proxy" not in status.structured_content["capabilities"]
    assert not hasattr(app, "proxy")
    listed = [tool.name for tool in (await app.on_list_tools(None)).tools]
    # build_code is disabled by default and is therefore not offered.
    assert "build_code" not in listed and len(listed) == len(LOCAL_TOOLS) - 1


@pytest.mark.parametrize("removed", ['[freecad]\nenabled=false\n', '[server]\nexpose_freecad_proxy=false\n'])
def test_removed_proxy_configuration_is_rejected(tmp_path, removed):
    config = tmp_path / "removed.toml"
    config.write_text('[pdf]\nallowed_roots=["sources"]\noutput_root="out"\n' + removed, encoding="utf-8")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Settings.load(config)


def test_removed_application_proxy_argument_is_rejected(tmp_path):
    settings = Settings(pdf=PdfSettings(allowed_roots=[tmp_path], output_root=tmp_path / "out"))
    with pytest.raises(TypeError, match="proxy"):
        Application(settings, proxy=object())


@pytest.mark.parametrize("name,args", [
    ("pdf_info", {"path": "a.pdf", "arbitrary": True}),
    ("pdf_render_page", {"path": "a.pdf", "page": 0}),
    ("pdf_render_page", {"path": "a.pdf", "page": True}),
    ("pdf_crop_region", {"path": "a.pdf", "page": 1, "bbox": [0, 1, 2]}),
    ("drawing_extract", {"path": "a.pdf", "stroke_kinds": ["contour"]}),
    ("drawing_extract", {"path": "a.pdf", "include_strokes": True, "stroke_kinds": ["bogus"]}),
    ("drawing_extract", {"path": "a.pdf", "include_strokes": True, "stroke_kinds": []}),
    ("drawing2cad_status", {"refresh_freecad": True}),
])
async def test_local_schema_validation(app, name, args):
    result = await invoke(app, name, **args)
    assert result.is_error
    assert result.structured_content["error"]["code"] == "INVALID_ARGUMENTS"


async def test_unknown_removed_and_outside_root_errors(app):
    assert (await invoke(app, "missing")).structured_content["error"]["code"] == "UNKNOWN_TOOL"
    assert (await invoke(app, "freecad_echo")).structured_content["error"]["code"] == "UNKNOWN_TOOL"
    assert app.get_schema("freecad_echo") is None
    failure = await invoke(app, "pdf_info", path=str(Path(sys.executable).with_suffix(".pdf")))
    assert failure.is_error
    assert "outside" in failure.structured_content["error"]["message"]
    failure = await invoke(app, "drawing_extract", path=str(Path(sys.executable).with_suffix(".pdf")))
    assert failure.structured_content["error"]["code"] == "PDF_PREPARATION_FAILED"
    assert "outside" in failure.structured_content["error"]["message"]


async def test_drawing_analysis_is_built_in(app, tmp_path):
    result = await invoke(app, "drawing_extract", path=str(make_pdf(tmp_path / "test.pdf")))
    assert not result.is_error, result
    assert result.structured_content["provenance"]["engine"] == "drawing2cad_mcp.vector"
    status = (await invoke(app, "drawing2cad_status")).structured_content
    assert status["drawing_analysis"]["available"]
    assert status["drawing_analysis"]["execution"] == "isolated_process"


def test_stroke_kinds_schema_matches_vector_engine():
    assert STROKE_KINDS == [kind.value for kind in Kind]


async def test_drawing_extract_on_sample(tmp_path):
    if not SAMPLE.is_file():
        pytest.skip("Sample drawing is missing")
    app = Application(Settings(pdf=PdfSettings(allowed_roots=[SAMPLE.parent], output_root=tmp_path / "out")))
    plain = (await invoke(app, "drawing_extract", path=str(SAMPLE))).structured_content
    assert plain["source"]["sha256"] == (await invoke(app, "pdf_info", path=str(SAMPLE))).structured_content["source"]["sha256"]
    assert plain["summary"]["views"] == len(plain["views"]) > 0
    assert plain["summary"]["text_blocks"] == len(plain["text_blocks"]) > 0
    assert "strokes" not in plain
    assert all("stroke_ids" not in view and view["stroke_count"] > 0 for view in plain["views"])
    full = (await invoke(app, "drawing_extract", path=str(SAMPLE), include_strokes=True)).structured_content
    assert len(full["strokes"]) == plain["summary"]["strokes"]
    assert [len(view["stroke_ids"]) for view in full["views"]] == [view["stroke_count"] for view in plain["views"]]
    contours = (await invoke(app, "drawing_extract", path=str(SAMPLE), include_strokes=True,
                             stroke_kinds=["contour"])).structured_content["strokes"]
    assert len(contours) == plain["summary"]["by_kind"]["contour"]
    assert {stroke["kind"] for stroke in contours} == {"contour"}
    assert not list((tmp_path / "out").iterdir())  # The snapshot is removed.


async def test_inline_preview_and_full_resolution_artifact(app, tmp_path):
    if not os.environ.get("DRAWING2CAD_PDFTOPPM"):
        pytest.skip("Poppler is required for the facade rendering integration test")
    source = make_pdf(tmp_path / "test.pdf")
    result = await invoke(app, "pdf_render_page", path=str(source), page=1, dpi=72)
    assert not result.is_error, result
    metadata = result.structured_content
    with Image.open(metadata["artifact"]["path"]) as artifact:
        assert artifact.size == (144, 216)
    with Image.open(BytesIO(base64.b64decode(result.content[1].data))) as preview:
        assert preview.width * preview.height <= 1000
        assert metadata["preview"]["resized"]
    without_image = await invoke(app, "pdf_crop_region", path=str(source), page=1,
                                 bbox=[0, 0, 0.5, 0.5], dpi=72, include_image=False)
    assert not without_image.is_error
    assert len(without_image.content) == 1
    assert "preview" not in without_image.structured_content


def test_config_resolves_paths_relative_to_file(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[pdf]\nallowed_roots=["sources"]\noutput_root="out"\n', encoding="utf8")
    settings = Settings.load(config)
    assert settings.pdf.allowed_roots == [tmp_path / "sources"]
    assert settings.pdf.output_root == tmp_path / "out"


async def test_full_stdio_server_exposes_native_part_and_pdf_tools(tmp_path):
    source = make_pdf(tmp_path / "test.pdf")
    config = tmp_path / "config.toml"
    quote = json.dumps
    config.write_text(
        f'[pdf]\nallowed_roots=[{quote(str(tmp_path))}]\noutput_root={quote(str(tmp_path / "out"))}\n', encoding="utf8")
    parameters = StdioServerParameters(command=sys.executable,
                                      args=["-m", "drawing2cad_mcp", "--config", str(config)],
                                      env={"PYTHONPATH": str(Path(drawing2cad_mcp.__file__).resolve().parents[1])})
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            catalog = (await session.list_tools()).tools
            assert len(catalog) == len(LOCAL_TOOLS) - 1  # build_code is disabled by default.
            assert not any(tool.name.startswith("freecad_") or tool.name == "build_code" for tool in catalog)
            capabilities = await session.call_tool("cad_capabilities", {})
            assert not capabilities.structured_content["workflow"]["available"]
            assert capabilities.structured_content["cad"]["backend"] == "build123d"
            assert "development_proxy" not in capabilities.structured_content
            schema = await session.call_tool("part_schema", {})
            assert not schema.is_error
            assert schema.structured_content["schema"]["additionalProperties"] is False
            validated = await session.call_tool("part_validate", {"description": sample_description()})
            assert validated.structured_content["status"] == "pass"
            removed = await session.call_tool("freecad_execute_code", {"code": "raise AssertionError()"})
            assert removed.is_error and removed.structured_content["error"]["code"] == "UNKNOWN_TOOL"
            status = await session.call_tool("drawing2cad_status", {})
            assert "freecad" not in status.structured_content
            assert "development_proxy" not in status.structured_content["capabilities"]
            pdf = await session.call_tool("pdf_info", {"path": str(source)})
            assert pdf.structured_content["page_count"] == 2
            text = await session.call_tool("pdf_read_text", {"path": str(source)})
            assert text.structured_content["source"] == pdf.structured_content["source"]
            assert "Dimension 42 mm" in text.structured_content["pages"][0]["text"]


async def test_invalid_argument_error_does_not_repeat_the_input_value(app, tmp_path):
    private = "/srv/private-customer/secret-drawing.pdf"
    source = make_pdf(tmp_path / "test.pdf")
    result = await invoke(app, "pdf_read_text", path=str(source), pages=private)
    assert result.is_error
    error = result.structured_content["error"]
    assert error["code"] == "INVALID_ARGUMENTS" and error["target"] == "/pages"
    assert "secret" not in json.dumps(result.structured_content)


async def test_stdio_transport_does_not_repeat_invalid_input_values(tmp_path):
    """The complete MCP stdio path returns the field and the rule, not the private value."""
    private = "/srv/private-customer/secret-drawing.pdf"
    source = make_pdf(tmp_path / "test.pdf")
    config = tmp_path / "config.toml"
    quote = json.dumps
    config.write_text(
        f'[pdf]\nallowed_roots=[{quote(str(tmp_path))}]\noutput_root={quote(str(tmp_path / "out"))}\n', encoding="utf8")
    parameters = StdioServerParameters(command=sys.executable,
                                      args=["-m", "drawing2cad_mcp", "--config", str(config)],
                                      env={"PYTHONPATH": str(Path(drawing2cad_mcp.__file__).resolve().parents[1])})
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool("pdf_read_text", {"path": str(source), "pages": private})
            assert result.is_error
            assert "secret" not in json.dumps(result.model_dump(mode="json"))
