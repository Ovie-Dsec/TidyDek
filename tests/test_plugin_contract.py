"""Phase 19.3: PluginContract isolation + structural conformance."""

import ast
import dataclasses
from pathlib import Path
from types import MappingProxyType

from src.core.config_schema import ScanRules
from src.core.plugin_contract import (
    PLUGIN_API_VERSION,
    FileEvent,
    PluginContext,
    ScanSummary,
)

MODULE = Path(__file__).resolve().parents[1] / "src" / "core" / "plugin_contract.py"


# ------------------------------------------------------------- isolation
def test_module_imports_are_pure_headless():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    allowed = {"__future__", "dataclasses", "typing"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    assert found <= allowed, f"contract imported outside whitelist: {found}"
    banned = found & {"tkinter", "customtkinter", "ctypes"}
    assert not banned, f"OS/UI leakage in contract: {banned}"


def test_no_integrations_or_gui_references_anywhere_in_source():
    source = MODULE.read_text(encoding="utf-8")
    for needle in ("src.integrations", "src.gui", "tkinter", "ctypes"):
        assert needle not in source, f"forbidden reference: {needle}"


def test_api_version_is_pinned():
    assert PLUGIN_API_VERSION == "1"


# ----------------------------------------------------------- conformance
class _DummyPlugin:
    """Satisfies the Protocol structurally with read-only internals."""

    def __init__(self):
        self.scan_rules = MappingProxyType(
            ScanRules(exclude_patterns=["*.tmp"]).model_dump()
        )
        self.logs = []
        self.files = []

    def emit_log(self, level: str, message: str) -> None:
        self.logs.append((level, message))

    def on_file(self, event: FileEvent) -> None:
        self.files.append(event.path)

    def on_scan_complete(self, summary: ScanSummary) -> None:
        self.emit_log("INFO", f"done {summary.files_scanned}")


def test_conforming_plugin_passes_runtime_check():
    plugin = _DummyPlugin()
    assert isinstance(plugin, PluginContext)


def test_nonconforming_object_fails_runtime_check():
    class Incomplete:
        scan_rules = {}

    assert not isinstance(Incomplete(), PluginContext)


def test_file_event_is_immutable():
    event = FileEvent(path="C:/x.txt", name="x.txt", extension=".txt", size=1)
    try:
        event.size = 99  # type: ignore[misc] - deliberate violation under test
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised, "FileEvent must be frozen (read-only contract)"


def test_scan_rules_view_is_read_only():
    plugin = _DummyPlugin()
    try:
        plugin.scan_rules["max_depth"] = 999  # type: ignore[index]
        raised = False
    except TypeError:
        raised = True
    assert raised, "rule mapping must reject mutation"
    assert plugin.scan_rules["exclude_patterns"] == ["*.tmp"]


def test_summary_round_trip_through_plugin_callbacks(tmp_path=None):
    plugin = _DummyPlugin()
    assert isinstance(plugin, PluginContext)
    plugin.on_file(FileEvent("C:/a.txt", "a.txt", ".txt", 5))
    plugin.on_scan_complete(ScanSummary(root="C:/", files_scanned=1,
                                        cancelled=False))
    assert plugin.files == ["C:/a.txt"]
    assert plugin.logs[-1] == ("INFO", "done 1")
