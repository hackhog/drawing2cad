"""Browser tests: the built UI against the real web backend, its domain service, and its mounted MCP endpoint.

A scripted model replaces the model endpoint, as in test_agent_runs.py. It creates a part but does not build it, so
these tests cover no released STEP or drawing download. The tests need the UI build (`npm run build` in
app/frontend) and an installed Google Chrome; without them they are skipped.
"""

from pathlib import Path
import re
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from drawing_demo import api
from drawing_demo.agent import runner as runner_module
from test_agent_runs import Server, environment, pdf_bytes, scripted_model, with_model_endpoint  # noqa: F401 (fixture)

playwright = pytest.importorskip("playwright.sync_api")
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
TIMEOUT_MS = 30_000

pytestmark = pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="UI build missing: run npm run build in app/frontend")


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
        server = Server(uvicorn.Config(with_ui(api.create_app()), log_config=None, access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            yield f"http://127.0.0.1:{port}"
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
