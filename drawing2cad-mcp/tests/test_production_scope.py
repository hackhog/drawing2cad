"""The documentation gate covers maintained texts and preserves historical evidence."""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "check_production_scope.py"


@pytest.mark.parametrize("relative", [
    "AGENTS.md", "app/AGENTS.md", "skills/drawing2cad/SKILL.md",
    "skills/drawing2cad/references/validation.md", "drawing2cad-mcp/README.md",
    "drawing2cad-mcp/src/drawing2cad_mcp/domain_tools.py",
    "app/backend/src/drawing_demo/agent/runner.py", "app/frontend/src/components/ArtifactsPanel.tsx",
])
def test_retired_scope_in_maintained_text_fails(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Use the HaCkAtHoN metric.\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert f"{relative}:1:" in result.stdout


@pytest.mark.parametrize("text", ["Minimum path for the metric", "M1 prototype delivery", "A complete metric pass"])
def test_retired_scope_without_its_original_event_name_fails(tmp_path, text):
    path = tmp_path / "AGENTS.md"
    path.write_text(text, encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1


def test_compatibility_identifiers_and_geometry_terms_remain_permitted(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "Legacy validated_prototype_step and metric_acceptance stay readable. Metric units and geometric checks remain supported.",
        encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0


def test_historical_and_generated_evidence_is_not_rewritten(tmp_path):
    for relative in ("docs/adr/0014-history.md", "resources/source.txt", "output/run/report.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Historical hackathon result.\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0


def test_maintained_service_texts_pass():
    result = subprocess.run([sys.executable, str(SCRIPT), str(ROOT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
