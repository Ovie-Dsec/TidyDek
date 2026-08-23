"""Secure updater: manifest validation, version math, hash gate, handoff."""

import hashlib
import json
from pathlib import Path

import pytest

from src.integrations.updater import (
    UpdateError,
    UpdateManifest,
    Updater,
    compare_versions,
    parse_manifest,
    secure_delete,
    version_tuple,
)

GOOD_MANIFEST = {
    "version": "0.3.0",
    "min_required_version": "0.2.0",
    "installer_url": "https://cdn.tidydek.com/releases/TidyDek-setup-0.3.0.exe",
    "sha256": "a" * 64,
    "release_notes": "https://tidydek.com/changelog#0-3-0",
}


# ------------------------------------------------------------------ versions
def test_version_tuple_and_comparison():
    assert version_tuple("0.10.2") == (0, 10, 2)
    assert compare_versions("0.3.0", "0.2.9") == 1
    assert compare_versions("1.0", "1.0.0") == 0  # zero-padded
    assert compare_versions("0.2.0", "0.10.0") == -1


def test_version_tuple_rejects_garbage():
    with pytest.raises(UpdateError):
        version_tuple("abc")


# ------------------------------------------------------------------ manifest
def test_parse_manifest_happy_path():
    manifest = parse_manifest(json.dumps(GOOD_MANIFEST).encode())
    assert manifest.version == "0.3.0"
    assert manifest.sha256 == "a" * 64


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.pop("version"),
        lambda d: d.update(installer_url="http://cdn.example.com/x.exe"),
        lambda d: d.update(sha256="zz" * 32),
        lambda d: d.update(sha256="aabb"),
        lambda d: d.update(release_notes=""),
    ],
)
def test_parse_manifest_rejects_invalid_payloads(mutation):
    import json

    payload = dict(GOOD_MANIFEST)
    mutation(payload)
    with pytest.raises(UpdateError):
        parse_manifest(json.dumps(payload).encode())


def test_parse_manifest_rejects_truncated_json():
    with pytest.raises(UpdateError):
        parse_manifest(b'{"version": "0')


# ------------------------------------------------------------------- hashing
def _manifest_with_digest(digest: str) -> UpdateManifest:
    return UpdateManifest(
        version="9.9.9",
        min_required_version="0.2.0",
        installer_url="https://cdn.example.com/x.exe",
        sha256=digest,
        release_notes="https://example.com/notes",
    )


def test_download_verifies_hash_before_use(tmp_path, monkeypatch):
    payload = b"MZfake-installer-bytes"
    good_digest = hashlib.sha256(payload).hexdigest()
    updater = Updater(current_version="0.1.0", manifest_url="https://x/latest.json")

    monkeypatch.setattr(updater, "_fetch", lambda url, cap: payload)
    destination = tmp_path / "setup.exe"
    result = updater.download(_manifest_with_digest(good_digest), destination)
    assert result.read_bytes() == payload


def test_download_hash_mismatch_destroys_file(tmp_path, monkeypatch):
    payload = b"tampered-payload"
    updater = Updater(current_version="0.1.0", manifest_url="https://x/latest.json")
    monkeypatch.setattr(updater, "_fetch", lambda url, cap: payload)

    destination = tmp_path / "setup.exe"
    with pytest.raises(UpdateError, match="[Ii]ntegrity"):
        updater.download(_manifest_with_digest("b" * 64), destination)
    assert not destination.exists(), "mismatched installer must be destroyed"


def test_secure_delete_zeroes_then_removes(tmp_path):
    target = tmp_path / "secret.bin"
    target.write_bytes(b"\xde\xad" * 100)
    secure_delete(target)
    assert not target.exists()


# -------------------------------------------------------------------- handoff
def test_install_spawns_silent_flags_detached(tmp_path, monkeypatch):
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return "POPN-HANDLE"

    installer = tmp_path / "TidyDek-setup-9.9.9.exe"
    installer.write_bytes(b"MZ")
    updater = Updater(current_version="0.1.0", manifest_url="https://x/l.json")

    handle = updater.install(installer, popen=fake_popen)
    assert handle == "POPN-HANDLE"
    cmd = captured["cmd"]
    for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                 "/CLOSEAPPLICATIONS"):
        assert flag in cmd
    assert captured["kwargs"].get("creationflags", 0) != 0  # DETACHED_PROCESS


def test_install_missing_installer_raises(tmp_path):
    updater = Updater(current_version="0.1.0", manifest_url="https://x/l.json")
    with pytest.raises(UpdateError):
        updater.install(tmp_path / "ghost.exe", popen=lambda *a, **k: None)


# --------------------------------------------------------------- check logic
def test_check_reports_no_update_when_current_is_newest(monkeypatch):
    import json

    updater = Updater(current_version="9.9.9", manifest_url="https://x/l.json")
    monkeypatch.setattr(
        updater, "_fetch", lambda url, cap: json.dumps(GOOD_MANIFEST).encode()
    )
    available, manifest, message = updater.check()
    assert available is False
    assert "latest" in message.lower()


def test_check_marks_mandatory_when_below_min_required(monkeypatch):
    import json

    updater = Updater(current_version="0.1.0", manifest_url="https://x/l.json")
    monkeypatch.setattr(
        updater, "_fetch", lambda url, cap: json.dumps(GOOD_MANIFEST).encode()
    )
    available, manifest, message = updater.check()
    assert available is True
    assert "Mandatory" in message
