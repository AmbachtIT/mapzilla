"""Draw what the river node lays out, without starting the game.

Runs content/mapzilla/nodes.script.lua through tools/run_river.js for a few
seeds and draws each result: the layout the script chose, shaded the way the
node graph will read it - sea, plains, hills, highland - with the rivers at
their real widths (exaggerated, or the small ones would vanish) on top. It
shows the river tree and the layout field, not the terrain, which is the rest
of the node graph's doing and exists only in the game.

The shading is build.py's own layout_u, read through the tile the script asked
for, so a river laid out in a frame that does not match the field it is told to
follow shows up here as a river in the sea - and in the checks each tile prints.

Needs Node with fengari (see run_river.js) and Pillow.

Usage:  python tools/preview_river.py [--size 16000] [--height 16000] [--amount 0.5]
                                      [--layout island] [--coast 0.5] [--islands 0.5]
                                      [--axis 0.5]
                                      [--seeds 1 2 3] [--out preview.png]
"""
import argparse
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw

import build

HERE = os.path.dirname(os.path.abspath(__file__))
TILE = 520          # pixels along the longer side of a map
WIDTH_SCALE = 1.6   # rivers are drawn this much wider than true scale
SHADE = 4           # the field is shaded in blocks this many pixels across
COAST = build.RIVER_TO_SEA["coast"]
MARGIN = build.LAYOUT_MARGIN

# The relief the graph builds from u, by the thresholds the stock biome
# selector splits it at - see RIVER_TO_SEA["profile"].
BANDS = ((0.24, (108, 104, 96)),     # highland, with the alpine stamps on top
         (0.56, (92, 118, 84)),      # upland
         (0.75, (116, 142, 92)),     # rolling hills
         (COAST, (150, 170, 112)),   # plains
         (1.01, (43, 90, 115)))      # sea


def run(seed, width, height, amount, lakes, layout, coast, islands, axis):
    out = subprocess.run(
        ["node", os.path.join(HERE, "run_river.js"), str(seed), str(width), str(height),
         str(amount), str(lakes), str(layout), str(coast), str(islands), str(axis)],
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


def map_frame(quad, tex):
    """The layout from the quad the script published: which tile of the atlas
    it points at, and how to read a map coordinate back as (a, b) in the map
    frame - which is what the rasteriser does with the quad in the game."""
    spec = build.LAYOUTS[int(round(tex[0][0] * len(build.LAYOUTS)))]
    span = 1 + 2 * MARGIN
    origin, along, across = quad[0], quad[1], quad[5]
    ax, ay = (along[0] - origin[0]) / span, (along[1] - origin[1]) / span
    bx, by = (across[0] - origin[0]) / span, (across[1] - origin[1]) / span
    ox, oy = origin[0] + MARGIN * (ax + bx), origin[1] + MARGIN * (ay + by)
    det = ax * by - ay * bx

    def ab(x, y):
        dx, dy = x - ox, y - oy
        return (dx * by - dy * bx) / det, (dy * ax - dx * ay) / det

    return spec, ab


def colour(u):
    for edge, rgb in BANDS:
        if u < edge:
            return rgb
    return BANDS[-1][1]


def read_value(tex):
    """A number the script sent as a map, read back out of the texture
    coordinate it used: one texel of the first tile, which is the plain ramp.
    Decoding it here is what checks the two ends of that trick agree."""
    tile = tex[0][0] * len(build.LAYOUTS)
    span = 1 + 2 * MARGIN
    return build.layout_u(build.LAYOUTS[0], -MARGIN + span * tile, 0.5)


def draw(result, width, height):
    (points, widths, _depths, tangents, _wt, quad, tex,
     _rv, rough_tex, _iv, island_tex) = result
    rough, islands = read_value(rough_tex), read_value(island_tex)
    scale = TILE / max(width, height)
    cols, rows = round(width * scale), round(height * scale)
    img = Image.new("RGB", (cols, rows))
    d = ImageDraw.Draw(img)
    spec, ab = map_frame(quad, tex)

    def px(p):
        return ((p[0] + width / 2) * scale, (height / 2 - p[1]) * scale)

    def metres(ix, iy):
        return ix / scale - width / 2, height / 2 - iy / scale

    def shade(u):
        # Where the coast noise can reach, drawn as its own band: the graph
        # adds that noise to u before deciding what is sea, so anywhere in
        # here may end up either.
        if COAST - rough < u < COAST + rough:
            return (84, 130, 126)
        return colour(u)

    # The layout, shaded in blocks: 17000 samples of the field rather than one
    # per pixel, which is quick and still shows every coastline.
    for iy in range(0, rows, SHADE):
        for ix in range(0, cols, SHADE):
            a, b = ab(*metres(ix + SHADE / 2, iy + SHADE / 2))
            d.rectangle([ix, iy, ix + SHADE, iy + SHADE],
                        fill=shade(build.layout_u(spec, a, b)))

    rivers = split_rivers(points, widths, tangents)
    for river in rivers:
        for (a, wa, ta), (b, wb, tb) in zip(river, river[1:]):
            w = max(wa[0] + wa[1], wb[0] + wb[1]) * scale * WIDTH_SCALE
            d.line([px(q) for q in hermite(a, ta, b, tb)], fill=(120, 190, 225),
                   width=max(1, round(w)), joint="curve")

    # The script lays its rivers out in a frame of its own, from u = 0.05 at a
    # source to 1.03 at a mouth, and the graph reads u off the tile instead.
    # The two agree only if the frame really does follow the field, so check
    # the ends against it. Not river by river: a river system in an outer lane
    # starts off the summit, and a tributary's first point is its confluence,
    # not a mouth. But something must reach the sea, and something must start
    # in the highland, or the frame is not the field after all.
    mouth = max(build.layout_u(spec, *ab(*river[0][0])) for river in rivers)
    source = min(build.layout_u(spec, *ab(*river[-1][0])) for river in rivers)
    notes = []
    if mouth <= COAST + rough:
        notes.append("nothing reaches the sea (highest mouth u %.2f)" % mouth)
    if source >= BANDS[0][0]:
        notes.append("nothing starts in the highland (lowest source u %.2f)" % source)

    d.text((6, 4), "%s - %d rivers - coast +/-%.2f - islands %.2f"
           % (spec["name"], len(rivers), rough, islands), fill=(246, 243, 236))
    return img, spec, len(rivers), mouth, source, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--size", type=float, default=16000, help="map width in metres")
    parser.add_argument("--height", type=float, help="map height in metres (default: square)")
    parser.add_argument("--amount", type=float, default=0.5, help="Rivers slider, 0..1")
    parser.add_argument("--lakes", type=float, default=0.5, help="Lakes slider, 0..1")
    parser.add_argument("--layout", default="",
                        help="one layout for every seed (%s); the default lets "
                             "the seed choose, as the game's Random setting does"
                             % ", ".join(s["key"] for s in build.LAYOUTS))
    parser.add_argument("--coast", type=float, default=0.5,
                        help="Coastline param, 0..1 in five steps (0 = the middle one)")
    parser.add_argument("--islands", type=float, default=0.5,
                        help="Islands param, 0..1 in five steps (0 = none)")
    parser.add_argument("--axis", type=float, default=0.5,
                        help="Orientation param: 0 random, 0.5 the map's long "
                             "side, 1 its short side")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--out", default="preview.png")
    args = parser.parse_args()

    keys = [spec["key"] for spec in build.LAYOUTS]
    if args.layout and args.layout not in keys:
        raise SystemExit("no such layout %r - one of %s"
                         % (args.layout, ", ".join(keys)))
    layout = build.layout_value(args.layout) if args.layout else 0
    width, height = args.size, args.height or args.size
    cols = min(3, len(args.seeds))
    rows = (len(args.seeds) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TILE + (cols + 1) * 8, rows * TILE + (rows + 1) * 8),
                      (14, 23, 18))
    bad = 0
    for i, seed in enumerate(args.seeds):
        img, spec, count, mouth, source, notes = draw(
            run(seed, width, height, args.amount, args.lakes, layout, args.coast,
                args.islands, args.axis),
            width, height)
        sheet.paste(img, (8 + (i % cols) * (TILE + 8), 8 + (i // cols) * (TILE + 8)))
        bad += len(notes)
        print("seed %-4d %-12s %2d rivers, lowest source u %.2f, highest mouth u %.2f%s"
              % (seed, spec["key"], count, source, mouth,
                 "  <- " + "; ".join(notes) if notes else ""))
    sheet.save(args.out)
    print("wrote " + args.out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
