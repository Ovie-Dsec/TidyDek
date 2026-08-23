"""Architecture purity enforcement (operational constraint #4).

Parsed with ``ast`` (not regex) so comments and string literals cannot fool
the checks:

- ``src/core/**`` and ``src/viewmodels/**`` must not import GUI toolkits.
- ``src/gui/**`` must not import ``src.core`` directly; it goes through
  ``src.viewmodels`` only.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
GUI_TOOLKITS = {"tkinter", "customtkinter"}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _python_files(*subdirs: str):
    base = SRC.joinpath(*subdirs)
    yield from sorted(base.rglob("*.py"))


def test_core_and_viewmodels_import_no_gui_toolkits():
    offenders = [
        str(f)
        for sub in ("core", "viewmodels")
        for f in _python_files(sub)
        if any(m.split(".")[0] in GUI_TOOLKITS for m in _imported_modules(f))
    ]
    assert offenders == [], f"GUI imports leaked into headless layers: {offenders}"


def test_gui_never_imports_core_directly():
    offenders = [
        str(f)
        for f in _python_files("gui")
        if any(
            m == "src.core" or m.startswith("src.core.")
            for m in _imported_modules(f)
        )
    ]
    assert offenders == [], f"View bypasses ViewModel layer: {offenders}"


WIN32_BOUNDARY_MODULE = {"src.integrations.win32_api"}


def test_ctypes_confined_to_win32_api_module():
    """Raw FFI may appear ONLY in src/integrations/win32_api.py."""
    offenders = []
    for sub in ("core", "viewmodels", "gui"):
        for f in _python_files(sub):
            heads = {m.split(".")[0] for m in _imported_modules(f)}
            if "ctypes" in heads or any(m.startswith("src.integrations") for m in _imported_modules(f)):
                offenders.append(str(f))
    for f in _python_files("integrations"):
        if f.name != "win32_api.py" and "ctypes" in {
            m.split(".")[0] for m in _imported_modules(f)
        }:
            offenders.append(str(f))
    assert offenders == [], f"ctypes used outside win32_api boundary: {offenders}"


def test_core_and_viewmodels_do_not_touch_integrations():
    """Business/presentation layers must stay OS-agnostic."""
    offenders = [
        str(f)
        for sub in ("core", "viewmodels")
        for f in _python_files(sub)
        if any(m == "src.integrations" or m.startswith("src.integrations.")
               for m in _imported_modules(f))
    ]
    assert offenders == [], f"OS integration leaked into headless layers: {offenders}"
