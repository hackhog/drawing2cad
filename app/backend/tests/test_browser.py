"""Browser tests: the built UI against the real web backend, its domain service, and its mounted MCP endpoint.

A scripted model replaces the model endpoint, as in test_agent_runs.py. Synthetic workers also test unreleased
artifact downloads after a failed drawing verification; these are not CAD acceptance tests. The tests need the UI build (`npm run build` in
app/frontend) and an installed Google Chrome; without them they are skipped.
"""

from pathlib import Path
import hashlib
import io
import json
import re
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from PIL import Image, ImageDraw
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from drawing_demo import api
from drawing_demo.agent import runner as runner_module
from test_agent_runs import Server, environment, pdf_bytes, scripted_model, seed_failed_verification, with_model_endpoint  # noqa: F401 (fixture)

playwright = pytest.importorskip("playwright.sync_api")
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
TIMEOUT_MS = 30_000

pytestmark = pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="UI build missing: run npm run build in app/frontend")


class RunningSite(str):
    """A test URL with access to the same backend domain service."""

    def __new__(cls, url, services):
        value = super().__new__(cls, url)
        value.services = services
        return value


def with_ui(backend):
    """Serve the UI build like nginx in Compose: /api and /mcp go to the backend, other paths to the single-page app."""
    static = StaticFiles(directory=DIST)
    index = HTMLResponse((DIST / "index.html").read_bytes())

    async def app(scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or path.startswith(("/api/", "/mcp")):
            await backend(scope, receive, send)
        elif path != "/" and (DIST / path.lstrip("/")).is_file():
            await static(scope, receive, send)
        else:
            await index(scope, receive, send)
    return app


@pytest.fixture
def site(environment):
    with_model_endpoint(environment)
    environment.setattr(runner_module, "make_model_call", lambda settings: scripted_model)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        environment.setenv("DRAWING2CAD_MCP_URL", f"http://127.0.0.1:{port}/mcp")
        backend = api.create_app()
        server = Server(uvicorn.Config(with_ui(backend), log_config=None, access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            yield RunningSite(f"http://127.0.0.1:{port}", backend.state.services)
        finally:
            server.should_exit = True
            thread.join(10)


@pytest.fixture
def page():
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except playwright.Error as error:
            pytest.skip(f"Google Chrome not available: {error.message.splitlines()[0]}")
        context = browser.new_context(accept_downloads=True)
        context.set_default_timeout(TIMEOUT_MS)
        playwright.expect.set_options(timeout=TIMEOUT_MS)
        yield context.new_page()
        browser.close()


def upload(page, name, data, mime="application/pdf"):
    page.locator("input[type=file]").first.set_input_files({"name": name, "mimeType": mime, "buffer": data})


def test_upload_run_review_note_and_run_files(site, page, tmp_path):
    expect = playwright.expect
    page.goto(site)
    upload(page, "Plate_dwg.pdf", pdf_bytes())
    expect(page.get_by_text("Plate read")).to_be_visible()
    page.get_by_role("cell", name="Plate", exact=True).click()

    page.get_by_role("button", name="Start run").click()
    # The button opens the run start dialog. Its own button starts the run.
    dialog = page.get_by_role("dialog", name="Start a CAD run")
    dialog.get_by_role("button", name="Start run").click()
    expect(page).to_have_url(re.compile(r"/runs/run_[0-9a-f]{32}"))
    run_id = page.url.split("/runs/")[1].split("?")[0]
    # The scripted model creates a part without a build; the run ends as failed in the modeling phase.
    expect(page.get_by_text("The agent built no valid model", exact=False)).to_be_visible()

    # The run page opens the timeline: the end of the loop, the four layers, and each step with its details.
    expect(page.get_by_role("tab", name="Timeline")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_text("The model ended the conversation without a release.")).to_be_visible()
    expect(page.get_by_text("How a run works")).to_be_visible()
    steps = page.get_by_role("navigation", name="Steps")
    steps.get_by_role("button", name=re.compile("part_create")).click()
    expect(page.get_by_role("heading", name="part_create")).to_be_visible()
    expect(page.get_by_text("Answer of the MCP server")).to_be_visible()

    page.get_by_role("tab", name="Parameter").click()
    expect(page.get_by_label("length")).to_have_value("10")
    expect(page.get_by_label("length")).to_be_disabled()
    expect(page.get_by_text("The connected service does not allow parameter changes.")).to_be_visible()

    page.get_by_role("tab", name="Review").click()
    expect(page.get_by_text("Report: part created, not built.")).to_be_visible()
    projection = page.get_by_role("region", name="Does the model match the drawing?")
    expect(projection).to_be_visible()
    expect(projection.get_by_text("not tested", exact=True)).to_be_visible()
    expect(page.get_by_label("Source drawing agreement")).to_contain_text("not tested")

    # The note starts with the agent report as rendered Markdown and keeps the report in the review tab after a change.
    page.get_by_role("tab", name="Notes").click()
    notes = page.get_by_role("tabpanel")
    expect(notes.get_by_text("Report: part created, not built.")).to_be_visible()
    page.get_by_role("button", name="Edit").click()
    note = page.get_by_label("Run note")
    expect(note).to_have_value("Report: part created, not built.")
    note.fill("Clarify the edge radius with design.")
    page.get_by_role("button", name="Save note").click()
    expect(page.get_by_text("Revision 2")).to_be_visible()
    expect(notes.get_by_text("Clarify the edge radius with design.")).to_be_visible()

    # A change from elsewhere makes the edited revision stale: the UI shows the conflict and reloads the newer note.
    with httpx2.Client(base_url=site, trust_env=False) as client:
        assert client.put(f"/api/runs/{run_id}/note", json={"expected_revision": 2, "text": "From elsewhere."}).status_code == 200
    page.get_by_role("button", name="Edit").click()
    note.fill("My change")
    page.get_by_role("button", name="Save note").click()
    expect(page.get_by_text("Revision has changed", exact=False).or_(page.get_by_text("A newer state exists", exact=False))).to_be_visible()
    page.get_by_role("button", name="Reload").click()
    expect(notes.get_by_text("From elsewhere.")).to_be_visible()
    page.get_by_role("tab", name="Review").click()
    expect(page.get_by_text("Report: part created, not built.")).to_be_visible()

    page.get_by_role("button", name="Open run files").click()
    with page.expect_download() as download:
        page.get_by_role("link", name=re.compile("All as ZIP")).click()
    target = tmp_path / "run.zip"
    download.value.save_as(target)
    assert target.read_bytes().startswith(b"PK")


def test_failures_show_a_message_with_recovery(site, page):
    expect = playwright.expect
    page.goto(site)
    upload(page, "Notes.pdf", b"not a pdf")
    expect(page.get_by_text("Notes unreadable")).to_be_visible()
    expect(page.get_by_text("Not a PDF file", exact=False).first).to_be_visible()

    page.goto(f"{site}/runs/run_{'0' * 32}")
    expect(page.get_by_text("Not found")).to_be_visible()
    page.get_by_role("link", name="To overview").click()
    expect(page).to_have_url(f"{site}/")


def test_projection_overlay_and_limits_in_the_review_tab(site, page, tmp_path):
    """The browser receives a simulated projection report and PNG through its usual API paths."""
    expect = playwright.expect
    page.goto(site)
    upload(page, "Plate_dwg.pdf", pdf_bytes())
    expect(page.get_by_text("Plate read")).to_be_visible()
    page.get_by_role("cell", name="Plate", exact=True).click()
    page.get_by_role("button", name="Start run").click()
    page.get_by_role("dialog", name="Start a CAD run").get_by_role("button", name="Start run").click()
    expect(page.get_by_text("The agent built no valid model", exact=False)).to_be_visible()
    run_id = page.url.split("/runs/")[1].split("?")[0]
    with httpx2.Client(base_url=site, trust_env=False) as client:
        value = client.get(f"/api/runs/{run_id}").json()
    overlay_id = "art_" + "f" * 32
    value["simulated"] = True
    value["projection"] = {
        "status": "deviates", "revision": 1, "simulated": True, "reason": None, "page": 1,
        "overlay_artifact_id": overlay_id, "report_artifact_id": None, "sheet_size_mm": [297, 210],
        "views": [{"view_id": "front", "status": "fail", "reason": None, "region_sheet_mm": [20, 20, 200, 140],
                   "metrics": {"p95_mm": 0.49, "max_mm": 0.8, "coverage": 0.98},
                   "limits": {"p95_mm": 0.3, "max_mm": 1, "coverage_min": 0.85},
                   "checks": {"p95": "fail", "max": "pass", "coverage": "pass"}, "max_capped": False}],
    }
    image = Image.new("RGB", (594, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 120, 340, 230), outline="grey", width=4)
    draw.rectangle((82, 120, 342, 230), outline="blue", width=2)
    draw.ellipse((336, 114, 348, 126), outline="red", width=2)
    content = io.BytesIO()
    image.save(content, format="PNG")
    page.route(f"**/api/runs/{run_id}", lambda route: route.fulfill(content_type="application/json", body=json.dumps(value)))
    page.route(f"**/api/artifacts/{overlay_id}/content", lambda route: route.fulfill(content_type="image/png", body=content.getvalue()))
    page.goto(f"{site}/runs/{run_id}?tab=review")
    section = page.get_by_role("region", name="Does the model match the drawing?")
    expect(section.get_by_role("img", name="Source and model overlay for front")).to_be_visible()
    expect(section.get_by_text("0.490 mm", exact=True)).to_be_visible()
    expect(section.get_by_text("Minimum 85.0%", exact=True)).to_be_visible()
    expect(section.get_by_text("Simulated projection data", exact=False)).to_be_visible()
    expect(page.get_by_label("Source drawing agreement")).to_contain_text("deviates")
    section.screenshot(path=str(tmp_path / "projection-review.png"))


def test_failed_verification_last_results_downloads(site, page, environment, tmp_path):
    """Test real candidate preview with permitted sample STEP bytes and fake CAD checks; no CAD acceptance is claimed."""
    sample = Path(__file__).resolve().parents[3] / "resources" / "Drawing2CAD" / "Splint" / "Splint.stp"
    assert sample.is_file(), "The permitted STEP preview fixture is missing."
    run_id = seed_failed_verification(site.services, environment, preview_step=sample.read_bytes())
    with httpx2.Client(base_url=site, trust_env=False) as client:
        value = client.get(f"/api/runs/{run_id}").json()
    selected = [a for a in value["artifacts"] if a["artifact_id"] in value["last_results"]["artifact_ids"]]
    assert {a["role"] for a in selected} == {"step_candidate", "drawing_pdf", "drawing_dxf", "verification_report", "verification_preview"}
    assert all(a["released"] is False for a in selected)
    expect = playwright.expect
    # The sample replaces fake worker bytes before registration. The stored hash and the converted bytes must agree.
    with page.expect_response(lambda response: response.url.endswith("/api/model")) as converted:
        page.goto(f"{site}/runs/{run_id}?tab=results")
    assert converted.value.status == 200
    assert converted.value.body().startswith(b"glTF")
    section = page.get_by_role("region", name="Last results (not released)")
    expect(section).to_be_visible()
    expect(section.get_by_text("Failed phase: creating drawing", exact=True)).to_be_visible()
    expect(section.get_by_text("AGENT_TIME_BUDGET", exact=False).first).to_be_visible()
    blocking = section.get_by_role("list", name="Blocking findings")
    expect(blocking.get_by_text("DIM-06", exact=True)).to_be_visible()
    expect(blocking.get_by_text("FEAT-02", exact=True)).to_be_visible()
    expect(section.get_by_text("Candidate model · Rev. 1 · not released", exact=True)).to_be_visible()
    candidate = next(a for a in selected if a["role"] == "step_candidate")
    expect(section.get_by_text(candidate["filename"] + " · not released", exact=True)).to_be_visible()
    canvas = section.locator("canvas")
    expect(canvas).to_be_visible()
    # A blank canvas has one background color. Wait until the model and its edges produce rendered pixels.
    deadline = time.monotonic() + 15
    while True:
        rendered = Image.open(io.BytesIO(canvas.screenshot())).convert("RGB")
        colors = rendered.getcolors(maxcolors=256)
        if colors is None or len(colors) > 10:
            break
        assert time.monotonic() < deadline, "The candidate model did not render in the 3D viewer."
        page.wait_for_timeout(100)
    expect(section.get_by_text("3D view not possible.", exact=False)).to_have_count(0)
    rows = section.get_by_role("list", name="Last result files").get_by_role("listitem")
    expect(rows).to_have_count(5)
    expect(section.get_by_text("released", exact=True)).to_have_count(0)
    for index, artifact in enumerate(selected):
        button = section.get_by_role("button", name=f"Download {artifact['filename']}", exact=True)
        expect(button).to_be_enabled()
        with page.expect_download() as download:
            button.click()
        target = tmp_path / f"result-{index}"
        download.value.save_as(target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == artifact["sha256"]


def test_failed_before_build_shows_no_step_result(site, page):
    expect = playwright.expect
    page.goto(site)
    upload(page, "NoBuild_dwg.pdf", pdf_bytes())
    expect(page.get_by_text("NoBuild read")).to_be_visible()
    page.get_by_role("cell", name="NoBuild", exact=True).click()
    page.get_by_role("button", name="Start run").click()
    page.get_by_role("dialog", name="Start a CAD run").get_by_role("button", name="Start run").click()
    expect(page.get_by_text("The agent built no valid model", exact=False)).to_be_visible()
    page.get_by_role("tab", name="Results", exact=True).click()
    section = page.get_by_role("region", name="Last results (not released)")
    expect(section.get_by_text("No STEP model is available:", exact=False)).to_be_visible()
    expect(section.get_by_role("list", name="Last result files").get_by_role("listitem")).to_have_count(0)
