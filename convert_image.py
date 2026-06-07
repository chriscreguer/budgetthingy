"""Convert a 792x272 PNG into the raw 2-bit packed .bin the 5.79" (G) panel expects.

The e-paper is a 4-color (Black/White/Yellow/Red) panel. Each pixel is encoded
as a 2-bit color code; 4 pixels are packed into one byte, MSB first. A full frame
is (792 / 4) * 272 = 53,856 bytes.

This produces a plain row-major buffer (198 bytes per row). The on-device driver
(epd5in79g.cpp) is responsible for the panel-specific dual-controller / mirrored
streaming order -- this script does NOT do any reordering.

Usage:
    python convert_image.py input.png output.bin

Or call convert(png_path, bin_path) directly from budget_pace.py.
"""

import sys

from PIL import Image

WIDTH = 792
HEIGHT = 272
BYTES_PER_ROW = WIDTH // 4          # 198
EXPECTED_BYTES = BYTES_PER_ROW * HEIGHT  # 53,856

# 2-bit color codes for the 5.79" (G) panel, matching EPD_5in79g.h:
#   BLACK=0x0, WHITE=0x1, YELLOW=0x2, RED=0x3
# NOTE: some 5.79g panel revisions ship with red/yellow swapped. If colors come
# out wrong on the first hardware test, swap the codes for (255,255,0) and
# (255,0,0) below -- it's a one-line fix.
COLOR_MAP: dict[tuple[int, int, int], int] = {
    (0, 0, 0): 0b00,        # black
    (255, 255, 255): 0b01,  # white
    (255, 255, 0): 0b10,    # yellow
    (255, 0, 0): 0b11,      # red
}

_PALETTE = list(COLOR_MAP.items())
_cache: dict[tuple[int, int, int], int] = {}


def _nearest_code(rgb: tuple[int, int, int]) -> int:
    """Nearest of the 4 panel colors by squared Euclidean distance in RGB."""
    code = _cache.get(rgb)
    if code is not None:
        return code
    r, g, b = rgb
    best_code = 0
    best_dist = None
    for (cr, cg, cb), c in _PALETTE:
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if best_dist is None or d < best_dist:
            best_dist = d
            best_code = c
    _cache[rgb] = best_code
    return best_code


def convert(png_path: str, bin_path: str) -> int:
    """Convert a 792x272 PNG to a packed .bin. Returns the number of bytes written."""
    img = Image.open(png_path).convert("RGB")
    if img.size != (WIDTH, HEIGHT):
        raise ValueError(
            f"Expected a {WIDTH}x{HEIGHT} image, got {img.size[0]}x{img.size[1]}"
        )

    px = img.load()
    out = bytearray(EXPECTED_BYTES)
    idx = 0
    for y in range(HEIGHT):
        for x in range(0, WIDTH, 4):
            byte = 0
            for k in range(4):
                # pixel 0 -> bits 7-6, pixel 1 -> bits 5-4, ...
                byte |= _nearest_code(px[x + k, y]) << (6 - 2 * k)
            out[idx] = byte
            idx += 1

    if idx != EXPECTED_BYTES:
        raise AssertionError(f"Packed {idx} bytes, expected {EXPECTED_BYTES}")

    with open(bin_path, "wb") as f:
        f.write(out)
    return len(out)


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python convert_image.py input.png output.bin", file=sys.stderr)
        sys.exit(1)
    n = convert(sys.argv[1], sys.argv[2])
    print(f"Wrote {n} bytes to {sys.argv[2]}")


if __name__ == "__main__":
    main()
