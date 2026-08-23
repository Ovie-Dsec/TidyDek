"""Asset pipeline frame planning + ICO container integrity."""

from pathlib import Path

from PIL import Image

import build_assets as ba


def _solid(size: int, color) -> Image.Image:
    return Image.new("RGBA", (size, size), color)


def test_micro_drives_small_frames_master_drives_large():
    master = _solid(256, (255, 0, 0, 255))
    micro = _solid(32, (0, 255, 0, 255))
    frames = ba.plan_frames(master, micro)

    assert sorted(frames) == [16, 32, 48, 64, 128, 256]
    # 16/32 derive from the micro source (green), the rest from master (red).
    for size in (16, 32):
        assert frames[size].getpixel((size // 2, size // 2)) == (0, 255, 0, 255)
    for size in (48, 64, 128, 256):
        assert frames[size].getpixel((size // 2, size // 2)) == (255, 0, 0, 255)


def test_without_micro_all_frames_come_from_master():
    master = _solid(128, (10, 20, 30, 255))   # small source caps the set
    frames = ba.plan_frames(master, None)
    assert sorted(frames) == [16, 32, 48, 64, 128]  # capped at native width
    for frame in frames.values():
        assert frame.getpixel((1, 1)) == (10, 20, 30, 255)


def test_written_ico_round_trips_through_pillow(tmp_path):
    frames = {16: _solid(16, (1, 2, 3, 255)),
              48: _solid(48, (9, 8, 7, 255))}
    target = tmp_path / "out.ico"
    ba.write_ico(frames, target)

    with Image.open(target) as ico:
        embedded = sorted({s for s, _ in ico.info.get("sizes", set())})
    assert 16 in embedded and 48 in embedded


def test_derive_micro_is_tight_center_crop(tmp_path):
    master = _solid(256, (5, 6, 7, 255))
    micro = ba.derive_micro(master)
    assert micro.size == (32, 32)
    assert micro.getpixel((16, 16)) == (5, 6, 7, 255)
