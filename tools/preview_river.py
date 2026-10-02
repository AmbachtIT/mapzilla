"""Draw what the river node lays out, without starting the game.

Runs content/mapzilla/nodes.script.lua through tools/run_river.js for a few
seeds and draws each result: rivers at their real widths (exaggerated, or the
small ones would vanish), the layout quad's direction, and where the coast
will be. It shows the river tree only - not terrain, which is the node
graph's doing and exists only in the game.

Needs Node with fengari (see run_river.js) and Pillow.

Usage:  python tools/preview_river.py [--size 16000] [--height 16000] [--amount 0.5]
                                      [--seeds 1 2 3 4 5 6] [--out preview.png]
"""
import argparse
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
TILE = 520          # pixels along the longer side of a map
WIDTH_SCALE = 1.6   # rivers are drawn this much wider than true scale
COAST = 0.80        # RIVER_TO_SEA["coast"] in build.py
MARGIN = 0.1        # LAYOUT_MARGIN


def run(seed, width, height, amount, lakes):
    out = subprocess.run(
        ["node", os.path.join(HERE, "run_river.js"), str(seed), str(width), str(height),
         str(amount), str(lakes)],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("river script failed for seed %s:\n%s" % (seed, out.stderr))
    return json.loads(out.stdout)


def split_rivers(points, widths, tangents):
    """Undo the join: rivers are separated by a repeated point."""
    rivers, current = [], []
    for i, p in enumerate(points):
        if current and i + 1 < len(points) and p == points[i - 1] and current[-1][0] == p:
            rivers.append(current)
            current = []
            continue
        current.append((p, widths[i], tangents[i]))
    if current:
        rivers.append(current)
    return rivers


def hermite(p0, m0, p1, m1, steps=14):
    """The curve between two river points, as river_map is assumed to draw it:
    a cubic hermite through the points with the node's tangents."""
    out = []
    for k in range(steps + 1):
        t = k / steps
        h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
        h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
        out.append((h00 * p0[0] + h10 * m0[0] + h01 * p1[0] + h11 * m1[0],
                    h00 * p0[1] + h10 * m0[1] + h01 * p1[1] + h11 * m1[1]))
    return out


def draw(result, width, height):
    points, widths, _depths, tangents, _wt, quad, tex = result
    scale = TILE / max(width, height)
    img = Image.new("RGB", (round(width * scale), round(height * scale)), (74, 107, 82))
    d = ImageDraw.Draw(img)

    def px(p):
        return ((p[0] + width / 2) * scale, (height / 2 - p[1]) * scale)

    # The layout quad gives the frame: texture s = 0 is the far mountain edge
    # of the overhanging quad, s = 1 the far sea edge.
    origin, along, across = quad[0], quad[1], quad[5]

    def frame(u, v):
        s = (u + MARGIN) / (1 + 2 * MARGIN)
        t = (v + MARGIN) / (1 + 2 * MARGIN)
        return (origin[0] + (along[0] - origin[0]) * s + (across[0] - origin[0]) * t,
                origin[1] + (along[1] - origin[1]) * s + (across[1] - origin[1]) * t)

    d.polygon([px(frame(COAST, 0)), px(frame(1, 0)), px(frame(1, 1)), px(frame(COAST, 1))],
              fill=(43, 90, 115))

    rivers = split_rivers(points, widths, tangents)
    for river in rivers:
        for (a, wa, ta), (b, wb, tb) in zip(river, river[1:]):
            w = max(wa[0] + wa[1], wb[0] + wb[1]) * scale * WIDTH_SCALE
            d.line([px(q) for q in hermite(a, ta, b, tb)], fill=(120, 190, 225),
                   width=max(1, round(w)), joint="curve")
    d.text((6, 4), "%d rivers" % len(rivers), fill=(246, 243, 236))
    return img, len(rivers)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--size", type=float, default=16000, help="map width in metres")
    parser.add_argument("--height", type=float, help="map height in metres (default: square)")
    parser.add_argument("--amount", type=float, default=0.5, help="Rivers slider, 0..1")
    parser.add_argument("--lakes", type=float, default=0.5, help="Lakes slider, 0..1")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--out", default="preview.png")
    args = parser.parse_args()

    width, height = args.size, args.height or args.size
    cols = min(3, len(args.seeds))
    rows = (len(args.seeds) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TILE + (cols + 1) * 8, rows * TILE + (rows + 1) * 8), (14, 23, 18))
    for i, seed in enumerate(args.seeds):
        img, count = draw(run(seed, width, height, args.amount, args.lakes), width, height)
        sheet.paste(img, (8 + (i % cols) * (TILE + 8), 8 + (i // cols) * (TILE + 8)))
        print("seed %d: %d rivers" % (seed, count))
    sheet.save(args.out)
    print("wrote " + args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
