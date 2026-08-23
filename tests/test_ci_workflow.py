"""CI workflow integrity: valid YAML, required steps, zero version literals."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-and-package.yml"


def _workflow() -> dict:
    text = WORKFLOW.read_text(encoding="utf-8")
    return yaml.safe_load(text)


def test_workflow_yaml_parses_with_required_triggers():
    data = _workflow()
    assert "build-and-package" in data["jobs"]
    # PyYAML renders the `on:` key as boolean True (YAML 1.1 quirk).
    triggers_block = data.get(True, data.get("on", {}))
    triggers = set(triggers_block.keys())
    assert {"push", "pull_request"} <= triggers


def test_workflow_runs_tests_before_packaging():
    data = _workflow()
    steps = data["jobs"]["build-and-package"]["steps"]
    names = [step.get("name", "") for step in steps]
    assert any("Test Suite" in name for name in names), names
    test_index = next(i for i, n in enumerate(names) if "Test Suite" in n)
    build_names = [n for n in names[test_index + 1 :]]
    assert any("Build Executable" in n for n in build_names)
    assert any("Installer" in n for n in build_names)


def test_workflow_invokes_plain_iscc_without_version_override():
    """ISPP owns versioning; CI must not inject or duplicate it."""
    data = _workflow()
    steps = data["jobs"]["build-and-package"]["steps"]
    iscc_steps = [
        step for step in steps if "iscc" in str(step.get("run", "")).lower()
    ]
    assert len(iscc_steps) == 1
    run_cmd = iscc_steps[0]["run"]
    assert "installer" in run_cmd.lower()
    assert not re.search(r"\d+\.\d+\.\d+", run_cmd)


def test_workflow_installs_project_extras_not_ghost_requirements():
    data = _workflow()
    joined = "\n".join(
        str(step.get("run", "")) for step in data["jobs"]["build-and-package"]["steps"]
    )
    assert 'pip install -e ".[dev]"' in joined
    assert "requirements.txt" not in joined
