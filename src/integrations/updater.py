"""Secure autonomous update pipeline.

Security boundary, enforced in order:
1. The manifest URL and the resolved installer URL MUST be https; any
   redirect that downgrades to http aborts the fetch.
2. Manifest fields are strictly validated (missing/empty -> UpdateError).
3. The installer is streamed to a temp file while computing SHA256; the
   digest is compared against the manifest BEFORE anything is executed. On
   mismatch the file is overwritten with zeros and deleted.
4. Installation is a silent handoff: spawn the Inno Setup installer detached
   with /VERYSILENT flags; the caller exits immediately afterwards. Windows
   file locks make self-overwrite impossible, so we never try.

Network transport uses stdlib urllib only (no new dependencies).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.request import build_opener, Request

from src.core.logsetup import get_logger

_logger = get_logger("updater")

MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
SILENT_INSTALL_FLAGS = (
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/CLOSEAPPLICATIONS",
)


class UpdateError(RuntimeError):
    """Raised for any update-check/download/verify failure."""


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    min_required_version: str
    installer_url: str
    sha256: str
    release_notes: str


def version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.strip().split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            raise UpdateError(f"non-semantic version component: {version!r}")
        parts.append(int(digits))
    if not parts:
        raise UpdateError(f"invalid version: {version!r}")
    return tuple(parts)


def compare_versions(left: str, right: str) -> int:
    """-1 if left < right, 0 equal, +1 greater (padded numerically)."""
    a, b = version_tuple(left), version_tuple(right)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return (a > b) - (a < b)


def parse_manifest(raw: bytes) -> UpdateManifest:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise UpdateError("manifest exceeds size limit")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError(f"manifest is not valid JSON: {exc}") from exc
    required = ("version", "min_required_version", "installer_url",
                "sha256", "release_notes")
    missing = [field for field in required
               if not isinstance(data.get(field), str) or not data[field]]
    if missing:
        raise UpdateError(f"manifest missing fields: {', '.join(missing)}")
    url = data["installer_url"]
    if not url.lower().startswith("https://"):
        raise UpdateError("installer_url must be https")
    digest = data["sha256"].lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise UpdateError("sha256 must be a 64-char hex digest")
    return UpdateManifest(
        version=data["version"],
        min_required_version=data["min_required_version"],
        installer_url=url,
        sha256=digest,
        release_notes=data["release_notes"],
    )


def secure_delete(path: Path) -> None:
    """Best-effort destructive delete: zero-fill then unlink."""
    try:
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.seek(0)
            remaining = size
            while remaining > 0:
                block = min(remaining, 1024 * 1024)
                handle.write(b"\x00" * block)
                remaining -= block
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass


class Updater:
    def __init__(self, *, current_version: str, manifest_url: str) -> None:
        self.current_version = current_version
        self.manifest_url = manifest_url

    # ------------------------------------------------------------ transport
    def _fetch(self, url: str, max_bytes: int) -> bytes:
        request = Request(url, headers={"User-Agent": f"TidyDek-Updater"})
        opener = build_opener()
        try:
            response = opener.open(request, timeout=20)
        except OSError as exc:
            raise UpdateError(f"network error fetching update: {exc}") from exc
        if not str(response.geturl()).lower().startswith("https://"):
            raise UpdateError("redirected away from https; aborting")
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                block = response.read(1024 * 64)
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    raise UpdateError("download exceeds size limit")
                chunks.append(block)
        except OSError as exc:
            raise UpdateError(f"download interrupted: {exc}") from exc
        return b"".join(chunks)

    # ----------------------------------------------------------------- flow
    def check(self) -> tuple[bool, Optional[UpdateManifest], str]:
        raw = self._fetch(self.manifest_url, MAX_MANIFEST_BYTES)
        manifest = parse_manifest(raw)

        comparison = compare_versions(manifest.version, self.current_version)
        if comparison <= 0:
            return False, manifest, "You are running the latest version."

        forced = compare_versions(
            self.current_version, manifest.min_required_version
        ) < 0
        reason = (
            f"Mandatory security update to {manifest.version}."
            if forced
            else f"Version {manifest.version} is available."
        )
        _logger.info("update available: %s", manifest.version)
        return True, manifest, reason

    def download(self, manifest: UpdateManifest,
                 destination: Optional[Path] = None) -> Path:
        target = destination or Path(tempfile.gettempdir()) / (
            f"TidyDek-setup-{manifest.version}.exe"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._fetch(manifest.installer_url, MAX_INSTALLER_BYTES)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != manifest.sha256:
            target.write_bytes(payload[:0])  # ensure file exists for deletion
            secure_delete(target)
            _logger.error("installer hash mismatch: %s != %s",
                          digest, manifest.sha256)
            raise UpdateError(
                "Integrity check failed; the download was discarded."
            )
        target.write_bytes(payload)
        _logger.info("installer verified (%d bytes)", len(payload))
        return target

    def install(
        self,
        installer_path: Path,
        popen: Callable[..., object] = subprocess.Popen,
    ) -> object:
        """Detached silent handoff; caller exits right after this returns."""
        if not installer_path.is_file():
            raise UpdateError(f"installer missing: {installer_path}")
        creation_flags = 0x00000008  # DETACHED_PROCESS on Windows
        return popen(
            [str(installer_path), *SILENT_INSTALL_FLAGS],
            creationflags=creation_flags,
            close_fds=True,
        )
