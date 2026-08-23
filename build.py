#!/usr/bin/env python
"""TidyDek build automation.

Pipeline (each step skippable via flags):
    1. unit tests            pytest -q
    2. EXE                   PyInstaller --onefile --windowed -> dist/TidyDek.exe
    3. installer             ISCC installer/TidyDek.iss (needs Inno Setup 6)
    4. verification          artifact existence + SHA256 report

Usage:
    py build.py                 full pipeline
    py build.py --skip-tests    fast iteration
    py build.py --only-version  print the SSOT version and exit

Notes:
- The version comes exclusively from src/version.py (SSOT).
- Missing Inno Setup is reported as a skipped step, not a failure, so the
  script stays usable on machines without ISCC; CI images should provide it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence, Union

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.version import APP_NAME, VERSION  # noqa: E402  (path bootstrap above)

DIST = ROOT / "dist"
ASSETS = ROOT / "assets"
ICON = ASSETS / "icon.ico"
MANIFEST = ASSETS / "app.manifest"
INSTALLER_SCRIPT = ROOT / "installer" / "TidyDek.iss"
INSTALLER_OUTPUT = ROOT / "installer" / "Output"

# Generated each build so the SSOT version flows into the embedded
# application manifest without any version literal living in the repo.
MANIFEST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="{name}" version="{version}.0" processorArchitecture="*"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">True/PM</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </windowsSettings>
  </application>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <!-- Windows 10 and 11 -->
      <supportedOS Id="{{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}}"/>
      <!-- Windows 8.1 -->
      <supportedOS Id="{{1f676c76-80e1-4239-95bb-83d0f6d0da78}}"/>
    </application>
  </compatibility>
</assembly>
"""


def ensure_assets() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        MANIFEST_TEMPLATE.format(name=APP_NAME, version=VERSION),
        encoding="utf-8",
    )
    if not ICON.is_file():
        raise SystemExit(
            f"missing {ICON}; run 'py build_assets.py' first "
            "(asset pipeline is deterministic, never hand-edited)"
        )


def find_mt_exe() -> Path | None:
    """Locate mt.exe from the newest installed Windows SDK."""
    kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    bin_root = kits / "Windows Kits" / "10" / "bin"
    if not bin_root.is_dir():
        return None
    candidates = sorted(bin_root.glob("*/*/x64/mt.exe"), reverse=True)
    return candidates[0] if candidates else None


def embed_manifest(exe_path: Path) -> None:
    mt = find_mt_exe()
    if mt is None:
        print("[MANIFEST] Windows SDK mt.exe not found; skipping embedding. "
              "Runtime per-monitor DPI call still guarantees correct scaling.")
        return
    run([mt, "-nologo", "-manifest", MANIFEST,
         "-outputresource", f"{exe_path};1"])


def run(cmd: Sequence[Union[str, Path]], *, cwd: Path = ROOT) -> None:
    printable = " ".join(str(part) for part in cmd)
    print(f"\n>>> {printable}")
    result = subprocess.run(
        [str(part) for part in cmd], cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        raise SystemExit(f"step failed ({result.returncode}): {printable}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Code signing (Phase 9). Fully opt-in: signing runs only when BOTH
# TIDYDEK_SIGN_SUBJECT and a signtool location are provided. Otherwise the
# step is skipped loudly so unsigned local builds never fail, while CI or a
# release machine with credentials gets signed artifacts automatically.
#   TIDYDEK_SIGN_SUBJECT   certificate subject name (CN) to select
#   SIGNTOOL_PATH          full path to signtool.exe (or on PATH as signtool)
#   TIDYDEK_TIMESTAMP_URL  optional RFC3161 server (default DigiCert)
# EV certificates behind a cloud HSM: extend _sign_cmd() with the provider's
# required arguments (e.g. /csp /kc for KeyLocker, Azure Trusted Signing dlib).
# --------------------------------------------------------------------------
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


def find_sigtool() -> Path | None:
    override = os.environ.get("SIGNTOOL_PATH")
    if override and Path(override).is_file():
        return Path(override)
    on_path = shutil.which("signtool")
    return Path(on_path) if on_path else None


def sign_artifact(artifact: Path) -> bool:
    subject = os.environ.get("TIDYDEK_SIGN_SUBJECT")
    signtool = find_sigtool()
    if not subject or not signtool:
        print(f"\n[SIGN] Skipped {artifact.name} "
              "(set TIDYDEK_SIGN_SUBJECT and SIGNTOOL_PATH to enable).")
        return False
    timestamp_url = os.environ.get("TIDYDEK_TIMESTAMP_URL", DEFAULT_TIMESTAMP_URL)
    cmd = [
        str(signtool), "sign",
        "/fd", "SHA256",
        "/tr", timestamp_url,
        "/td", "SHA256",
        "/n", subject,
        str(artifact),
    ]
    run(cmd)
    print(f"[SIGN] Signed {artifact.name}")
    return True


def find_iscc() -> Path | None:
    """Locate Inno Setup's command-line compiler."""
    candidate = os.environ.get("ISCC_PATH")
    if candidate and Path(candidate).is_file():
        return Path(candidate)
    on_path = shutil.which("iscc")
    if on_path:
        return Path(on_path)
    program_dirs = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    )
    for base in program_dirs:
        probe = base / "Inno Setup 6" / "ISCC.exe"
        if probe.is_file():
            return probe
    return None


def build_exe() -> Path:
    ensure_assets()
    kill_running_instance()
    run([sys.executable, "-m", "PyInstaller",
         "--noconfirm", "--clean",
         "--onefile", "--windowed",
         "--icon", ICON,
         "--add-data", f"{ASSETS};assets",
         "--name", APP_NAME,
         str(ROOT / "main.py")])
    artifact = DIST / f"{APP_NAME}.exe"
    if not artifact.is_file():
        raise SystemExit(f"expected EXE missing: {artifact}")
    embed_manifest(artifact)
    return artifact


def kill_running_instance() -> None:
    """Phase 13.4: a running TidyDek locks dist/TidyDek.exe (WinError 5)."""
    result = subprocess.run(
        ["taskkill", "/F", "/IM", f"{APP_NAME}.exe"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if result.returncode == 0:
        print("[PRE-BUILD] terminated lingering TidyDek.exe")


def build_installer() -> Path | None:
    iscc = find_iscc()
    if iscc is None:
        print("\n[SKIP] Inno Setup 6 (ISCC) not found; "
              "set ISCC_PATH or install Inno Setup to produce the setup EXE.")
        return None
    run([iscc, INSTALLER_SCRIPT])
    expected = INSTALLER_OUTPUT / f"{APP_NAME}-setup-{VERSION}.exe"
    if not expected.is_file():
        raise SystemExit(f"expected installer missing: {expected}")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME} {VERSION}")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-exe", action="store_true")
    parser.add_argument("--skip-installer", action="store_true")
    parser.add_argument("--only-version", action="store_true")
    args = parser.parse_args()

    if args.only_version:
        print(f"{APP_NAME} {VERSION}")
        return

    print(f"Building {APP_NAME} v{VERSION} (SSOT: src/version.py)")

    if not args.skip_tests:
        run([sys.executable, "-m", "pytest", "-q"])

    artifacts: list[Path] = []
    if not args.skip_exe:
        exe = build_exe()
        sign_artifact(exe)
        artifacts.append(exe)
    if not args.skip_installer:
        installer = build_installer()
        if installer is not None:
            sign_artifact(installer)
            artifacts.append(installer)

    print("\n=== Artifacts ===")
    if not artifacts:
        print("(none produced)")
    for artifact in artifacts:
        size_mb = artifact.stat().st_size / (1024 * 1024)
        print(f"{artifact.name}  [{size_mb:.1f} MiB]  sha256={sha256_of(artifact)}")
    print(f"\nDone: {APP_NAME} v{VERSION}")


if __name__ == "__main__":
    main()
