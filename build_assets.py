#!/usr/bin/env python
"""Deterministic asset pipeline: brand logo -> multi-resolution Windows .ico.

Source selection order:
    1. ``TIDYDEK_LOGO`` environment variable (explicit override)
    2. ``assets/logo_source.png``   <- committed copy of the provided logo

Micro-glyph strategy (Phase 14): a 256px logo downscaled to 16px turns into
an unrecognizable smudge. If ``assets/logo_micro.png`` exists it is used
EXCLUSIVELY for the 16px and 32px frames; everything else comes from the
full logo. When no hand-tuned micro file exists, one is DERIVED once from
the master by tight center-cropping (62%) so primary shapes stay legible at
tiny sizes; a derived file is written only if absent and is never
overwritten, so artists can drop in a refined version later.

The .ico container is assembled manually because Pillow's ``sizes=`` API can
only downscale from ONE base image. Frames are classic 32-bit BMP-DIB entries
(bottom-up BGRA + empty AND mask), which every Windows Explorer generation
renders correctly.

Usage:
    py build_assets.py            # regenerate assets/icon.ico from the logo
    py build_assets.py --check    # verify the .ico exists and list frames
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
MASTER_OUT = ASSETS / "icon_master.png"
MICRO_OUT = ASSETS / "logo_micro.png"
ICO = ASSETS / "icon.ico"

STANDARD_SIZES = [16, 32, 48, 64, 128, 256]
MICRO_SIZES = {16, 32}
MAX_ICON_SIZE = 256


# ------------------------------------------------------------ source loading
def locate_source() -> Path:
    override = os.environ.get("TIDYDEK_LOGO")
    candidates = []
    if override:
        candidates.append(Path(override))
    candidates.append(ASSETS / "logo_source.png")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "no logo source found; set TIDYDEK_LOGO or add assets/logo_source.png"
    )


def load_rgba(path: Path) -> Image.Image:
    try:
        image = Image.open(path)
        return image.convert("RGBA")
    except OSError as exc:
        raise SystemExit(f"unreadable image {path}: {exc}") from exc


def square_padded(image: Image.Image) -> Image.Image:
    """Center on a transparent square canvas; never stretch."""
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    offset = ((side - image.width) // 2, (side - image.height) // 2)
    canvas.paste(image, offset)
    return canvas


# ------------------------------------------------------------- frame planning
def plan_frames(
    master: Image.Image, micro: Image.Image | None
) -> dict[int, Image.Image]:
    """Map each .ico size to its designated source image (LANCZOS resample)."""
    frames: dict[int, Image.Image] = {}
    capped = [s for s in STANDARD_SIZES if s <= min(MAX_ICON_SIZE, master.size[0])]
    for size in capped:
        if size in MICRO_SIZES and micro is not None:
            source = micro
        else:
            source = master
        frames[size] = source.resize((size, size), Image.LANCZOS)
    return frames


def derive_micro(master: Image.Image) -> Image.Image:
    """Tight center crop (62%) keeps primary shapes legible at tiny sizes."""
    side = master.size[0]
    crop_side = int(side * 0.62)
    left = (side - crop_side) // 2
    top = (side - crop_side) // 2
    cropped = master.crop((left, top, left + crop_side, top + crop_side))
    return cropped.resize((32, 32), Image.LANCZOS)


# --------------------------------------------------------------- ICO assembly
def _frame_to_bmp(frame: Image.Image) -> bytes:
    """32-bit BITMAPINFOHEADER + bottom-up BGRA pixels + empty AND mask."""
    width, height = frame.size
    rgba = frame.tobytes("raw", "BGRA")

    row_size = width * 4
    mask_row_size = ((width + 31) // 32) * 4
    pixel_data = bytearray()
    for y in range(height - 1, -1, -1):          # bottom-up
        start = y * row_size
        pixel_data += rgba[start:start + row_size]
    mask_data = b"\x00" * (mask_row_size * height)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,             # biSize
        width,
        height * 2,     # XOR + AND heights
        1,              # biPlanes
        32,             # biBitCount
        0,              # BI_RGB
        len(pixel_data) + len(mask_data),
        0,              # biXPelsPerMeter
        0,              # biYPelsPerMeter
        0,              # biClrUsed
        0,              # biClrImportant
    )
    return header + bytes(pixel_data) + mask_data


def write_ico(frames: dict[int, Image.Image], path: Path) -> None:
    ordered = sorted(frames.items())
    count = len(ordered)

    header = struct.pack("<HHH", 0, 1, count)    # reserved, type=icon, count
    entries = b""
    blobs = b""
    offset = 6 + 16 * count
    for size, image in ordered:
        blob = _frame_to_bmp(image)
        byte_size = size % 256                   # 256 is encoded as 0
        entries += struct.pack(
            "<BBBBHHII",
            byte_size, byte_size,
            0,           # palette colors
            0,           # reserved
            1,           # planes
            32,          # bits per pixel
            len(blob),
            offset,
        )
        blobs += blob
        offset += len(blob)

    path.write_bytes(header + entries + blobs)


# --------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate TidyDek icons")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        if not ICO.is_file():
            raise SystemExit("icon.ico missing; run build_assets.py")
        with Image.open(ICO) as ico:
            sizes = sorted({size for size, _ in ico.info.get("sizes", set())})
        print(f"OK {ICO} frames={len(sizes)}: {sizes}")
        return

    source = locate_source()
    ASSETS.mkdir(parents=True, exist_ok=True)

    master = square_padded(load_rgba(source))
    master.save(MASTER_OUT)

    if MICRO_OUT.is_file():
        micro = load_rgba(MICRO_OUT)
        micro_origin = "committed"
    else:
        micro = derive_micro(master)
        micro.save(MICRO_OUT)
        micro_origin = "auto-derived"

    frames = plan_frames(master, micro)
    write_ico(frames, ICO)

    print(f"source : {source} ({master.size[0]}x{master.size[1]})")
    print(f"micro  : {MICRO_OUT} ({micro_origin}, drives 16/32px frames)")
    print(f"wrote  : {MASTER_OUT}")
    print(f"wrote  : {ICO} sizes={sorted(frames)}")


if __name__ == "__main__":
    sys.exit(main())
