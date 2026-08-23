"""SSOT enforcement: version lives ONLY in src/version.py."""

import re
import tomllib
from pathlib import Path

from src.version import APP_NAME, VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_semver_and_name_nonempty():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION
    assert APP_NAME.strip() != ""


def test_version_py_layout_contract_for_ispp():
    """ISPP consumes lines 1-2 verbatim; nothing may precede the markers."""
    lines = (ROOT / "src" / "version.py").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith('APP_NAME = "'), lines[0]
    assert lines[1].startswith('VERSION = "'), lines[1]
    # And the values must equal what a real import produces.
    assert APP_NAME in lines[0] and VERSION in lines[1]


def test_pyproject_derives_version_dynamically_from_version_module():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert "version" not in project, "pyproject must not hardcode a version"
    assert "version" in project.get("dynamic", [])
    attr = data["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "src.version.VERSION"


def test_installer_script_contains_no_version_literals():
    iss = (ROOT / "installer" / "TidyDek.iss").read_text(encoding="utf-8")
    # The script must reference the parsed defines...
    assert "AppVersion={#AppVersion}" in iss
    assert "AppName={#AppName}" in iss
    assert "#define AppVersionSrc" in iss
    # ...and must contain no hardcoded x.y.z literals anywhere.
    assert not re.search(r"\b\d+\.\d+\.\d+\b", iss), (
        "hardcoded version literal found in TidyDek.iss; use {#AppVersion}"
    )


def test_changelog_documents_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{VERSION}]" in changelog, (
        f"CHANGELOG.md is missing a section for {VERSION}"
    )
