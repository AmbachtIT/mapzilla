"""Build the Mapzilla terrain generators from the stock ones.

A terrain generator is a `.gen.lua` (name, climate, sliders) pointing at a
`.tree.lua` node graph. We never write a graph from scratch: each of ours is a
stock graph, read straight out of the game's `climates.zip`, with extra nodes
spliced in. Everything stock stays byte-for-byte as shipped apart from line
endings, so a game patch that retunes a climate is picked up by rebuilding.

Generators built - see GENERATORS at the bottom:

  mapzilla_temperate_river_sea
                          One river from mountains to a sea, ending in a delta:
                          our river plus a map-wide layout. See the splice.
  mapzilla_river_a        PROBE. The temperate graph with its river layout
                          taken from our own scripted node (content/mapzilla/)
                          instead of the stock one. The "_a" is a leftover of
                          the naming test and stays for now: see GENERATORS.

  mapzilla_temperate_mesas  the worked example of a regional stamp: the
                          desert's mesas confined to regions picked by
                          low-frequency noise. Confirmed in the game.

Mistakes in a node graph take the game down from the new game dialog with a
message that names no node, so every tree is validated against the stock trees
before it is written - see `validate`. Nothing is written if validation fails.

Usage:  python tools/build.py [--game <install dir>] [--content <content dir>]
"""
import argparse
import collections
import io
import math
import os
import re
import sys
import zipfile

DEFAULT_GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Transport Fever 3"
DEFAULT_CONTENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "mod", "mapzilla_1", "content")

CLIMATES = ("temperate", "dry", "subarctic", "tropical")

PREFIX = "mz_"  # namespace so our nodes can never collide with stock names

REMAP = "gui/node_editor/remap_number.node"
COMBINE_POINT = "gui/node_editor/combine_point.node"
RANDOM_QUADS = "gui/node_editor/random_quads.node"

# A node's output is looked up by key and not every type calls it "out". The
# rest are learned from the stock trees; these are the ones we emit ourselves.
OUTPUT_KEY = {
    REMAP: "output",
    COMBINE_POINT: "point",
}

# Our own scripted nodes, defined by content/mapzilla/<name>.node.lua. The
# validator cannot learn these from the stock trees, so what each needs and
# publishes is stated here and must be kept in step with the .node.lua.
CUSTOM_NODES = {
    "river": {
        # "seed" is not declared in the .node.lua: every scripted node gets one
        # unless it says withSeed = false.
        "inputs": {"boundsMin", "boundsMax", "amount", "lakes", "layout", "coast",
                   "islands", "axis", "seed"},
        # Optional in the .node.lua, so a tree may leave the wire off. The
        # engine then reads the value from the node's param of the same name -
        # as stock does for every random_quads, none of which wires atlasSize.
        "optional": {"amount", "lakes", "layout", "coast", "islands", "axis"},
        "params": {"amount", "lakes", "layout", "coast", "islands", "axis", "seed"},
        "outputs": {"points", "widths", "depthsTangent", "tangents", "widthTangents",
                    "layoutVertices", "layoutTexCoords",
                    "roughVertices", "roughTexCoords",
                    "islandVertices", "islandTexCoords"},
    },
}

# The five point clouds river_map reads, from either the stock or our node.
RIVER_MAP_INPUTS = ("points", "widths", "depthsTangent", "tangents", "widthTangents")


# --- stock files --------------------------------------------------------------

class Stock:
    """The four stock climates, read from the game's climates.zip."""

    def __init__(self, game_dir):
        path = os.path.join(game_dir, "base", "content", "climates.zip")
        if not os.path.exists(path):
            raise SystemExit("stock climates not found: " + path)
        self.zip = zipfile.ZipFile(path)

    def read(self, climate, suffix):
        name = "climates/%s/%s%s" % (climate, climate, suffix)
        raw = self.zip.read(name).decode("utf-8", errors="surrogateescape")
        # Stock files are CRLF; the repository is LF throughout.
        return raw.replace("\r\n", "\n")

    def tree(self, climate):
        return self.read(climate, "_gen.tree.lua")

    def gen(self, climate):
        return self.read(climate, ".gen.lua")


# --- reading a tree -----------------------------------------------------------
#
# Regexes rather than a Lua parser: the node editor writes these files in one
# rigid layout, and matching that layout is also what lets a splice leave every
# stock byte alone.

NODE_RE = re.compile(r"\n\t\t\t\{ \n.*?\n\t\t\t\},", re.S)
INPUT_RE = re.compile(
    r'\n\t\t\t\t\t(\w+) = \{ \n\s*key = "([^"]*)",\s*\n\s*nodeName = "([^"]*)",')
PARAMS_RE = re.compile(r"\n\t\t\t\tparams = \{ \n(.*?)\n\t\t\t\t\},", re.S)
PARAM_KEY_RE = re.compile(r"^\t\t\t\t\t(\w+) = ", re.M)


def parse(text):
    """Return the nodes of a tree as dicts: name, layerType, inputs, params."""
    nodes = []
    for match in NODE_RE.finditer(text):
        block = match.group(0)
        layer = re.search(r'\n\t\t\t\tlayerType = "([^"]+)"', block)
        name = re.search(r'\n\t\t\t\tname = "([^"]*)"', block)
        if not layer or not name:
            continue
        params = PARAMS_RE.search(block)
        nodes.append({
            "name": name.group(1),
            "layerType": layer.group(1),
            # input name -> (producing node, output key read from it)
            "inputs": {m.group(1): (m.group(3), m.group(2))
                       for m in INPUT_RE.finditer(block)},
            "params": set(PARAM_KEY_RE.findall(params.group(1))) if params else set(),
            "block": block,
        })
    return nodes


# --- writing nodes ------------------------------------------------------------

_next_x = [-0.5]


def lua(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        # Must be quoted: `key = cluster.count` is valid Lua that reads as
        # indexing a global.
        return '"%s"' % value
    return repr(value) if isinstance(value, float) else str(value)


def node(name, layer_type, inputs=None, params=None):
    """Emit one node block in exactly the layout the stock trees use.

    Our nodes are laid out in a row below the stock graph, so they are easy to
    find in the in-game node editor.
    """
    _next_x[0] += 0.012
    position = (round(_next_x[0], 4), -0.06)
    out = ["\t\t\t{ ", "\t\t\t\tcolor = { 0.9, 0.45, 0.1, 0.6, },"]
    if inputs:
        out.append("\t\t\t\tinputs = { ")
        for key in sorted(inputs):
            src_node, src_key = inputs[key]
            out.append("\t\t\t\t\t%s = { " % key)
            out.append('\t\t\t\t\t\tkey = "%s",' % src_key)
            out.append('\t\t\t\t\t\tnodeName = "%s",' % src_node)
            out.append("\t\t\t\t\t},")
        out.append("\t\t\t\t},")
    else:
        out.append("\t\t\t\tinputs = { },")
    out.append('\t\t\t\tlayerType = "%s",' % layer_type)
    out.append('\t\t\t\tname = "%s",' % name)
    if params:
        out.append("\t\t\t\tparams = { ")
        for key in sorted(params):
            value = params[key]
            if isinstance(value, list):
                # A point cloud: the only list-valued param the trees use.
                out.append("\t\t\t\t\t%s = {" % key)
                for point in value:
                    out.append("\t\t\t\t\t\t{ %s, }," % ", ".join(lua(v) for v in point))
                out.append("\t\t\t\t\t},")
            else:
                out.append("\t\t\t\t\t%s = %s," % (key, lua(value)))
        out.append("\t\t\t\t},")
    else:
        out.append("\t\t\t\tparams = { },")
    out.append("\t\t\t\tposition = { %s, %s, }," % position)
    out.append("\t\t\t},")
    return "\n".join(out)


def remap_map(name, source, lo_in, hi_in, lo_out, hi_out, clamp=True):
    """map_clamp_map: the input interval [lo_in, hi_in] onto [lo_out, hi_out].

    `from` and `to` are intervals, not points - stock inverts a mask with
    from = (0, 1), to = (1, 0).
    """
    return node(name, "map_clamp_map", inputs={"in1": source},
                params={"clamp": clamp, "from_x": lo_in, "from_y": hi_in,
                        "to_x": lo_out, "to_y": hi_out})


# --- splicing -----------------------------------------------------------------

class Tree:
    def __init__(self, text):
        self.text = text
        self.nodes = parse(text)
        self.by_name = {n["name"]: n for n in self.nodes}
        self.added = []

    def need(self, name, layer_type):
        """A stock node we wire into, by name. A patch may rename it."""
        found = self.by_name.get(name)
        if found is None or found["layerType"] != layer_type:
            raise SystemExit("stock node %r <%s> not found - has the game "
                             "changed its tree?" % (name, layer_type))
        return name

    def land(self):
        """Return (node to rewire, input name, node currently feeding it).

        Every stock tree ends in add_map(land, river) -> height_map_output.
        Adding to that *sum* would put our relief on top of carved riverbeds
        and fill them in. Splicing into the land side leaves the river term to
        be applied after us, so rivers still cut down through whatever we add.
        """
        outputs = [n for n in self.nodes if n["layerType"] == "height_map_output"]
        if len(outputs) != 1:
            raise SystemExit("expected exactly one height_map_output")
        final = self.by_name[outputs[0]["inputs"]["in1"][0]]
        if final["layerType"] != "add_map" or "in1" not in final["inputs"]:
            raise SystemExit("height output is no longer fed by add_map(land, river)")
        return final["name"], "in1", final["inputs"]["in1"][0]

    def add(self, block):
        self.added.append(block)

    def consumers(self, source):
        """Every (node, input name) of the stock tree that reads `source`."""
        return [(n["name"], key) for n in self.nodes
                for key, (src, _) in sorted(n["inputs"].items()) if src == source]

    def rewire(self, name, input_name, old_source, new_source):
        block = self.by_name[name]["block"]
        pattern = re.compile(
            r'(\n\t\t\t\t\t%s = \{ \n\s*key = "[^"]*",\s*\n\s*nodeName = ")%s(",)'
            % (re.escape(input_name), re.escape(old_source)))
        patched, count = pattern.subn(lambda m: m.group(1) + new_source + m.group(2), block)
        if count != 1:
            raise SystemExit("failed to rewire %s.%s" % (name, input_name))
        if self.text.count(block) != 1:
            raise SystemExit("node block for %s not found exactly once" % name)
        self.text = self.text.replace(block, patched, 1)
        # Keep the stored block current, or a second rewire of the same node
        # would look for text that is no longer there and silently do nothing.
        self.by_name[name]["block"] = patched

    def render(self):
        anchor = "\t\tnodes = {\n"
        if self.text.count(anchor) != 1:
            raise SystemExit("could not find the nodes array")
        return self.text.replace(anchor, anchor + "\n".join(self.added) + "\n", 1)


# --- the mesa splice ----------------------------------------------------------
#
# Lifted from the desert tree, where a mesa is: random quads -> rasterise the
# plateau atlas -> scale to metres -> MAX with the ground. The numbers marked
# "desert" below are that tree's own.

MESAS = {
    # Slow field deciding where mesa country is. Frequency is per metre, so
    # this is one swing every ~12km: a couple of regions on a medium map.
    # fractal_noise_map is used because its frequency cannot be wired, which
    # also means region size does not yet scale with the map.
    "region_frequency": 0.00008,
    "region_octaves": 2,
    # The noise is roughly symmetric about 0, so this window makes about half
    # the map mesa country, with a hard-ish edge.
    "region_from": -0.05,
    "region_to": 0.05,
    # Attempts per square kilometre of map; only quads whose centre lands in
    # allowed country are kept, so this is also the density there. Each atlas
    # tile is one mesa about a third of the quad wide - roughly 450m across at
    # these sizes - so anything near 1 per km2 makes them overlap, and the Max
    # blend then merges them into one ragged plateau instead of separate
    # mesas. The first build used the desert's ~4 and got exactly that: half
    # the map turned into noise. This leaves about 1.8km between neighbours.
    "attempts_per_km2": 0.3,
    "sizes": [[1200, 0], [1500, 0], [1200, 0], [1500, 0]],      # desert
    "atlas": "::/climates/gen/tex/dry_mesa_plateau_01.png",     # desert, 2x2
    "atlas_white": 0.8738,                                      # desert
    "height": 170,                                              # desert, metres
    # Mesas fade out over this band of the stock river-distance map, so valleys
    # stay open. That map is not in metres: stock stretches distance 0..3000
    # onto 0..7745 and adds +-50 of noise, so this is roughly 100..400 distance
    # units. Temperate fades its own mountains over 0..1500 of the same map,
    # which would turn a mesa into a ramp; a mesa wants a short band.
    "river_from": 250,
    "river_to": 1000,
}


def splice_mesas(tree, cfg=MESAS):
    # Stock temperate nodes we read from.
    seed = tree.need("Data", "input_data")
    bounds = tree.need("New Map data #300", "input_data")
    map_km2 = tree.need("Calc map size", "mul_number")
    biome1 = tree.need("Mask Biome 1", "mask_map")      # plains, 0..4m
    biome2 = tree.need("Mask Biome 2", "mask_map")      # low hills, 5..120m
    lakes = tree.need("Sea Rasterization", "rasterizer_map")
    river_dist = tree.need("New Add maps #329", "add_map")  # scaled distance to a river

    target, target_input, land = tree.land()

    name = {key: PREFIX + key for key in (
        "region_noise", "region", "lowland", "not_lake", "region_lowland",
        "allowed", "blocked", "per_km2", "quantity", "sizes", "quads", "raster",
        "mesa_height", "zero", "land_pos", "land_neg", "mesa_over", "mesa_rel",
        "river_cut", "mesa_cut", "land")}

    def ref(key):
        return (name[key], "out")

    for block in (
        # 1 inside mesa country, 0 outside.
        node(name["region_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["region_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": cfg["region_octaves"]}),
        remap_map(name["region"], ref("region_noise"),
                  cfg["region_from"], cfg["region_to"], 0, 1),

        # Mesas belong on the plains and low hills. On the higher ground they
        # would barely clear it - see the lift below.
        node(name["lowland"], "compare_map",
             inputs={"in1": (biome1, "out"), "in2": (biome2, "out")},
             params={"op": "MAX"}),
        remap_map(name["not_lake"], (lakes, "out"), 0, 1, 1, 0),
        node(name["region_lowland"], "mul_map",
             inputs={"in1": ref("region"), "in2": ref("lowland")}),
        node(name["allowed"], "mul_map",
             inputs={"in1": ref("region_lowland"), "in2": ref("not_lake")}),
        # random_quads keeps a quad where its mask is 0, hence the inversion -
        # stock feeds it "invert ... formation mask" nodes the same way.
        remap_map(name["blocked"], ref("allowed"), 0, 1, 1, 0),

        # How many to try, scaled by map area like every stock stamp.
        node(name["per_km2"], "constant_number",
             params={"value": cfg["attempts_per_km2"]}),
        node(name["quantity"], "mul_number",
             inputs={"in1": (map_km2, "out"), "in2": ref("per_km2")},
             params={"in2": 0}),
        node(name["sizes"], "constant_pointcloud",
             params={"values": cfg["sizes"]}),
        node(name["quads"], RANDOM_QUADS,
             inputs={"mask": ref("blocked"),
                     "max": (bounds, "mapBoundsMax"),
                     "min": (bounds, "mapBoundsMin"),
                     "numQuads": ref("quantity"),
                     "sizeAndScale": ref("sizes")},
             params={"atlasSize_x": 2, "atlasSize_y": 2, "centerCheck": True,
                     "max_x": 0, "max_y": 0, "min_x": 0, "min_y": 0,
                     "numQuads": 800}),
        node(name["raster"], "rasterizer_map",
             inputs={"texCoords": (name["quads"], "texCoords"),
                     "vertices": (name["quads"], "vertices")},
             params={"op": "Max", "tex": cfg["atlas"],
                     "wrapS": "REPEAT", "wrapT": "REPEAT"}),
        remap_map(name["mesa_height"], ref("raster"),
                  0, cfg["atlas_white"], 0, cfg["height"], clamp=False),

        # The desert takes MAX(mesa, ground), which is what keeps a mesa's top
        # flat. Here the ground includes lakes at -100m, and a MAX against the
        # mesa map's zeroes would fill every one of them in. So compute only
        # the lift - how far the mesa stands above the ground, never negative -
        # and add that:  lift = max(0, mesa - max(0, land)).
        node(name["zero"], "constant_map", params={"value": 0}),
        node(name["land_pos"], "compare_map",
             inputs={"in1": (land, "out"), "in2": ref("zero")},
             params={"op": "MAX"}),
        remap_map(name["land_neg"], ref("land_pos"), 0, 1, 0, -1, clamp=False),
        node(name["mesa_over"], "add_map",
             inputs={"in1": ref("mesa_height"), "in2": ref("land_neg")}),
        node(name["mesa_rel"], "compare_map",
             inputs={"in1": ref("mesa_over"), "in2": ref("zero")},
             params={"op": "MAX"}),

        # Keep river valleys open, then hand the result on as the new land.
        remap_map(name["river_cut"], (river_dist, "out"),
                  cfg["river_from"], cfg["river_to"], 0, 1),
        node(name["mesa_cut"], "mul_map",
             inputs={"in1": ref("mesa_rel"), "in2": ref("river_cut")}),
        node(name["land"], "add_map",
             inputs={"in1": (land, "out"), "in2": ref("mesa_cut")}),
    ):
        tree.add(block)

    tree.rewire(target, target_input, land, name["land"])


# --- the river splice ---------------------------------------------------------

def splice_river(layer_type, layout=None):
    """Swap the stock river layout for the one from our scripted river node.

    The stock tree feeds river_map from river_points.node, a scripted random
    walk. Ours publishes the same five point clouds, so only the wires move:
    river_map and everything downstream of it - the carved bed, the valley the
    land is flattened into - stay stock. The stock node is left in place,
    unconnected.

    `layer_type` is the name the tree uses for our node. `layout` is which
    layout the script is to lay the river out for: a layout key to fix one, or
    None to let the generator's Layout dropdown choose - see LAYOUTS.
    """
    def splice(tree):
        rivers = [n for n in tree.nodes if n["layerType"] == "river_map"]
        if len(rivers) != 1:
            raise SystemExit("expected exactly one river_map")
        river = rivers[0]
        stock_points = river["inputs"]["points"][0]
        stock = tree.by_name[stock_points]
        if stock["layerType"] != "gui/node_editor/river_points.node":
            raise SystemExit("river_map is no longer fed by river_points.node")

        # The stock Rivers slider, already remapped to (0, 1] for the stock
        # node. Ours reads it as how densely tributaries join.
        amount = stock["inputs"]["riverAmountFactor"]
        # The stock Lakes slider, raw 0..1 ("oceans" is its key in temperate).
        # Ours reads it as how many lakes lie along the rivers.
        lakes = (tree.need("Ocean Amount", "param_number"), "out")

        name = PREFIX + "river_data"
        inputs = {"boundsMin": stock["inputs"]["boundsMin"],
                  "boundsMax": stock["inputs"]["boundsMax"],
                  "amount": amount,
                  "lakes": lakes,
                  "seed": stock["inputs"]["seed"]}
        params = {"amount": 0.5, "lakes": 0.5, "seed": 0, "coast": 0.5,
                  "islands": 0.5, "axis": 0.5,
                  "layout": layout_value(layout) if layout else 0}
        if layout is None:
            # Our own params, which build_gen adds to the generator, each with
            # what a param_number is to fall back on where the key is not set.
            # For the layout that is 0, the dropdown's own "Random"; for the
            # coastline it is the middle setting, because there 0 is the first
            # setting and not an absence. Either way a generator that never got
            # the param still makes a map.
            for key, wire, dummy in ((LAYOUT_KEY, "layout", 0), (COAST_KEY, "coast", 0.5),
                                     (ISLANDS_KEY, "islands", 0.5),
                                     (AXIS_KEY, "axis", 0.5)):
                param = PREFIX + wire + "_param"
                tree.add(node(param, "param_number",
                              params={"dummy": dummy, "key": key}))
                inputs[wire] = (param, "out")
        tree.add(node(name, layer_type, inputs=inputs, params=params))
        for key in RIVER_MAP_INPUTS:
            tree.rewire(river["name"], key, stock_points, name)
    return splice


# --- the layouts --------------------------------------------------------------
#
# Where the mountains and the sea are. The river-to-sea splice below hangs
# everything - the coastline, the relief, the lakes, the islands - off one
# field u, which is 0 deep in the mountains and 1 out at sea. So a layout need
# be nothing but a different u, and all of that follows it.
#
# A layout is a distance measured in the map frame - `a` along the map's longer
# side, `b` across it, both 0..1 - and the two distances at which u is 0 and 1:
#
#   along   the distance is `a`: u runs from one end of the map to the other,
#           which is the coast the mod started with
#   across  |2b - 1|, the distance from the map's centre line: a fold, with the
#           same land mirrored on both sides of it
#   radial  the distance from the centre of the map, 1 at the middle of an edge
#           and 1.41 in a corner
#
# Either end may sit off the map (a distance above 1), and that is how a layout
# gets a broad band of mountains along an edge instead of a thin rim: the map
# edge then lies partway up the ramp rather than at its end.
#
# Two layouts need a second term for their flanks, read from |2b - 1| as well:
# "sea" raises u towards both long edges (a max, so the sea wraps round), while
# "mountains" holds it down there (a min, so the flanks stay high).
#
# The numbers come from the relief profile in RIVER_TO_SEA, which reads u as
# highland below 0.24, hills to 0.68, plains to the coast at 0.80 and sea
# beyond. So the distance at which u is 0.24 is where the mountains begin and
# the one at 0.80 is where the water does; the tables below are worked back
# from where those two belong in each layout. On a 16km map:
#
#   shore       as before: highland the first 3.8km, sea the last 3.2km
#   island      a massif 1.9km across in the middle, the coast 80% of the way
#               out, so half the map is the sea around it
#   inland_sea  a sea 7.5km across in the middle, plains and hills around it,
#               mountains from 7.2km out to the edge and the corners
#   isthmus     a range 4km wide down the middle, 2.4km of sea along each side
#   strait      a channel 4km wide down the middle, mountains from 2km in
#   peninsula   mountains across the near end, sea beyond 80% of the length
#               and 1.2km of it along each flank
#   bay         mountains across the near end and 1km along each flank, the
#               sea a lobe in the far end 60% of the map wide
LAYOUT_KEY = "mz_layout"               # the generator param, read by param_number
COAST_KEY = "mz_coast"                 # the Coastline param, likewise
ISLANDS_KEY = "mz_islands"             # the Islands param
AXIS_KEY = "mz_axis"                   # and the Orientation param
# The Coastline slider's labels. What each one does is the script's business -
# ROUGHNESS in nodes.script.lua - because it is the script that hands the
# amplitude to the graph, as a map; see the roughness quad below.
COASTLINES = (("Straight",), ("Gentle",), ("Medium",), ("Rugged",), ("Wild",))
# The Islands slider's labels, and what each does to the island threshold -
# see "island_bias" in RIVER_TO_SEA, which is this curve. The first setting
# takes the island noise out of the picture altogether; it is called Few and
# not None because a coastline rough enough to wander will still strand the
# odd piece of shelf offshore, and that is the coast's doing, not this.
ISLANDS = (("Few",), ("Scattered",), ("Medium",), ("Dense",), ("Packed",))
# The Orientation dropdown: which side of the map a layout runs along. Index 1
# is Random, so 0 - what a param_number falls back on where the key is unset -
# would be Random too; the dummy is the long side instead, which is what every
# map did before the param existed.
AXES = (("Random",), ("Long side",), ("Short side",))
LAYOUT_TEX = "mapzilla_1::/mapzilla/tex/layouts.tga"
LAYOUT_TILE = 256                      # pixels per layout in the atlas

# key, kind, d0, d1, spread and band must match LAYOUTS in
# content/mapzilla/nodes.script.lua, which lays the river out in the frame the
# same numbers describe; check_layouts() refuses to build if the two drift
# apart. `flank` and `name` are ours alone - the script needs neither.
LAYOUTS = (
    dict(key="shore", name="Single shore", kind="along", d0=0.00, d1=1.00,
         spread=1.00, band=1.00),
    dict(key="island", name="Island", kind="radial", d0=0.00, d1=1.00,
         spread=1.00, band=1.00),
    dict(key="inland_sea", name="Inland sea", kind="radial", d0=1.09, d1=0.31,
         spread=1.00, band=1.00),
    dict(key="isthmus", name="Isthmus", kind="across", d0=0.06, d1=0.86,
         spread=1.00, band=1.00),
    dict(key="strait", name="Strait", kind="across", d0=0.96, d1=0.07,
         spread=1.00, band=1.00),
    # The flanks are sea the whole way down, so the rivers keep to the middle.
    dict(key="peninsula", name="Peninsula", kind="along", d0=0.00, d1=1.00,
         spread=1.00, band=0.45, flank=("sea", 0.45, 0.95)),
    # The delta is capped to the lobe between the flanking ridges, or its
    # outer channels would run up into them.
    dict(key="bay", name="Bay", kind="along", d0=0.00, d1=1.00,
         spread=0.25, band=0.50, flank=("mountains", 0.00, 0.50)),
)


# The script reads a number back out of the first tile - see the roughness
# quad in nodes.script.lua - so that tile has to stay the plain ramp whose
# value is the map coordinate it stands for.
assert LAYOUTS[0]["kind"] == "along" and (LAYOUTS[0]["d0"], LAYOUTS[0]["d1"]) == (0.0, 1.0) \
    and "flank" not in LAYOUTS[0], "the first layout must be the plain ramp"


def ramp(x, lo, hi):
    """x from lo..hi onto 0..1, clamped. hi may lie below lo."""
    return min(1.0, max(0.0, (x - lo) / float(hi - lo)))


def layout_u(spec, a, b):
    """The field a layout stamps, at (a, b) in the map frame."""
    if spec["kind"] == "along":
        distance = a
    elif spec["kind"] == "across":
        distance = abs(2 * b - 1)
    else:
        distance = math.hypot(2 * a - 1, 2 * b - 1)
    u = ramp(distance, spec["d0"], spec["d1"])
    flank = spec.get("flank")
    if flank:
        kind, lo, hi = flank
        side = ramp(abs(2 * b - 1) if kind == "sea" else 1 - abs(2 * b - 1), lo, hi)
        # A plain max (or min) would meet the end ramp at a right angle and
        # leave the map with square corners. Taking the two terms in quadrature
        # rounds them off instead, and still leaves the centre line - where the
        # flank term is out of the way - exactly u, which is where the river is
        # laid out and the only place the two have to agree.
        if kind == "sea":
            u = min(1.0, math.hypot(u, side))
        else:
            u = 1 - min(1.0, math.hypot(1 - u, 1 - side))
    return u


def layout_value(key):
    """What param_number gives for the layout param when `key` is chosen.

    A param's value is its place on the dropdown mapped onto 0..1 -
    (index - 1) / (count - 1) - and index 1 is "Random", so the first layout
    lands one step above 0. Inferred, not documented: every stock slider is
    read through a remap_number over 0..1, and the dummy a param_number falls
    back on is 0.5 where the slider's default is the middle of five values.
    """
    keys = [spec["key"] for spec in LAYOUTS]
    return round((keys.index(key) + 1) / float(len(LAYOUTS)), 6)


def write_layout_atlas(path, tile=LAYOUT_TILE):
    """The layouts as one row of tiles: an 8-bit greyscale TGA, the format of
    the stock stamps (climates/gen/tex/ridge.tga is 1024x256 of the same).

    A tile covers the layout quad, which overhangs the map by LAYOUT_MARGIN on
    every side, so the map is the middle of the tile and the tile's edges -
    where a texture filters against its neighbour - are never sampled. One row
    of tiles, not a grid, because how a row offset reaches the texture is
    plain and how a column offset does is guesswork. Every field is
    symmetrical across the map's centre line, so which way up the rows are
    read does not matter either.
    """
    width, height = tile * len(LAYOUTS), tile
    header = bytes([0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    width & 255, width >> 8, height & 255, height >> 8, 8, 8])
    lo, span = -LAYOUT_MARGIN, 1 + 2 * LAYOUT_MARGIN
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(header)
        for j in range(height):
            b = lo + span * (j + 0.5) / height
            row = bytearray()
            for spec in LAYOUTS:
                for i in range(tile):
                    a = lo + span * (i + 0.5) / tile
                    row.append(int(round(255 * layout_u(spec, a, b))))
            f.write(bytes(row))


LAYOUT_LUA_RE = re.compile(
    r'\{ key = "(\w+)",\s+kind = "(\w+)",\s+d0 = ([\d.]+), d1 = ([\d.]+),'
    r'\s+spread = ([\d.]+), band = ([\d.]+) \},')


def check_layouts(script_path):
    """The script lays the river out in the frame these numbers describe and
    build.py bakes the field from them, in two languages. Rather than leave a
    comment to keep them in step, read the script's table back and compare."""
    text = io.open(script_path, encoding="utf-8").read()
    found = [(key, kind, float(d0), float(d1), float(spread), float(band))
             for key, kind, d0, d1, spread, band in LAYOUT_LUA_RE.findall(text)]
    want = [(s["key"], s["kind"], s["d0"], s["d1"], s["spread"], s["band"])
            for s in LAYOUTS]
    if found != want:
        return ["LAYOUTS in %s does not match the table in build.py:"
                "\n    script: %s\n     build: %s"
                % (os.path.basename(script_path), found, want)]
    return []


# --- the river-to-sea splice --------------------------------------------------
#
# On top of our river: mountains at its source and a sea at its mouth.
#
# The river node also publishes a quad covering the map. Rasterised with the
# layout atlas, that is a map of u - 0 deep in the mountains, 1 out at sea -
# which no stock node can provide, since nothing in the graph knows which way
# our script turned the river or which layout it chose. Everything else hangs
# off u:
#
#   sea        where u (plus a wobble) passes the coast, the map is declared
#              lake. Stock already knows what a lake is: it becomes biome 0,
#              -100m deep, with a soft shore and the right ground textures.
#   relief     the stock selector that sorts land into plains / hills /
#              highland is replaced by a profile along u, so the land steps
#              down from highland at the source, through a zone of rolling
#              hills, to flat plains at the coast. The stock noise keeps a
#              say, so the zones have ragged, interlocking edges.
#   valleys    stock pulls the land down to every river in proportion to its
#              height. We keep that but reshape the fall: a flat floor along
#              every river in the highland, a long gentle slope in the hills.
#   shores     the same for lakes and the sea, which stock stamps through the
#              finished land: ours come down to the water the way they come
#              down to a river, so a lake lies in a basin.
#   islands    noise peaks out at sea are left as land, and lifted into hills.

LAYOUT_MARGIN = 0.1     # must match LAYOUT_MARGIN in content/mapzilla/nodes.script.lua

RIVER_TO_SEA = {
    # Where the coast is, in u, for every layout. The river script opens its
    # delta at 0.66.
    "coast": 0.80,
    # The coastline wanders either way on a noise of about one swing per 3km,
    # so it is not a ruled line. How far is the Coastline param's business: the
    # river node works it out - it is the only thing that knows how much of the
    # map the layout squeezes u into - and hands it over as a map, by way of a
    # quad pointing at one texel of the ramp. See ROUGHNESS in the script.
    "coast_frequency": 0.0003,
    # A second, finer octave - one swing per 1.1km, and half that again within
    # it - is what turns a wandering coastline into a ragged one: bays get
    # headlands, headlands get coves. It takes a share of the wobble rather
    # than adding to it, so the two together never reach further than the
    # ceiling the script holds them to, and what changes with the setting is
    # the character of the coast rather than only its reach.
    #
    # The share is read off how far the coast wanders at all, which is the
    # Coastline setting by another name - it is the one number in the graph
    # that follows it. So: nothing at Straight, and at Wild a coast that is
    # two fifths fine detail. A layout that folds the map reaches a given
    # wander at a lower setting, and gets the matching detail there too.
    "coast_fine_frequency": 0.0009,
    "coast_fine_share": [[0, 0], [0.012, 0], [0.028, 0.06], [0.05, 0.14],
                         [0.10, 0.28], [0.18, 0.40]],
    # The land selector runs 0..1, higher meaning higher ground. At the default
    # Mountains setting stock reads it as: below 0.56 plains (0-4m), to 0.75
    # rolling hills (5-120m), to 0.83 upland (80-140m), above that highland
    # (100-160m, plus alpine stamps). Ours is a profile along u - three level
    # stretches with short slopes between them - so each kind of land gets a
    # zone of its own:
    #     u 0.00-0.24   0.86   highland, with upland where the noise dips
    #     u 0.34-0.58   0.66   rolling hills
    #     u 0.68-1.00   0.25   plains, down to the coast
    # A plain ramp was tried first. It crosses the narrow 0.56-0.75 window
    # quickly, so the hills were a thin band nobody noticed.
    "profile": [[0, 0.86], [0.24, 0.86], [0.34, 0.66], [0.58, 0.66], [0.68, 0.25], [1, 0.25]],
    # The stock selector noise moves the result by this much either way, which
    # is what makes the zone edges ragged. Kept under half the width of the
    # hills window so the hill zone stays hills.
    "noise_swing": 0.08,

    # How the land falls to a river, in units of the stock river-distance map
    # (not metres - stock stretches distance by roughly 2.6 and adds noise).
    # Stock multiplies each zone's height by a ramp that is 0 at the river and
    # 1 a set distance away: 500 for the hills, 1500 for upland and highland.
    #
    # Highland: the ramp starts only at the edge of a valley floor, so every
    # river in the mountains runs along a strip of flat ground - the buildable
    # land there. The climb beyond it is as steep as stock's.
    #
    # The floor's width is itself a map: a slow noise, one swing every 3km or
    # so, read through the curve below (noise value -> width). This one is a
    # straight line from no floor to 1140 across the range two octaves of
    # noise really cover, so along a river the valley narrows to a gorge and
    # widens to a basin by turns. A curve that kept most valleys shut and
    # opened a few into much bigger basins (up to 2600) was tried and looked
    # worse in the game; this is the shape that looked right.
    "valley_floor_frequency": 0.00035,
    # 820 is about 315m, and the noise spends most of its time well below the
    # top of the curve, so a floor averages nearer 160m a side. It was 1140
    # (440m): wide enough that a mountain valley read as a basin, and wide
    # enough that the flat ground went on long after the gravel band ended.
    # Narrowing it does not shrink that band - the band is measured from the
    # water and belongs to the river, not the floor - but it replaces flat
    # sandy ground with rising grassy ground, which is the point.
    "valley_floor_curve": [[-1, 0], [-0.55, 0], [0.55, 820], [1, 820]],
    # And the whole distribution is scaled by where on the map the river is.
    # One width for the entire course was the thing that read as wrong in the
    # mountains: a floor of 150 to 300m is a floodplain on a plain and a
    # basin in a gorge, and since the gravel band is 150m wide wherever it
    # falls, a mountain floor of that size is gravel from wall to wall. Down
    # on the plain the same band is a strip in a wide green field and nobody
    # looks twice. Mountain valleys are narrow in any case: that is what the
    # mountains did to them.
    #
    # Read over u, the same field everything else hangs off: highland at the
    # left, the coast at the right. Multiplying the width rather than
    # replacing it keeps the slow noise that makes a valley open and close
    # along its length, and just moves the whole distribution down where the
    # land is high.
    "floor_by_zone": [[0, 0.55], [0.24, 0.65], [0.45, 0.85], [0.68, 1.0], [1, 1.0]],
    # A valley floor, or any ground we flatten, is the land multiplied down to
    # nothing: height 0. The water level is 0 too. So the "flat land" in the
    # mountains was a film a centimetre above the water - it looks like land,
    # and no town will go on it. Stock plains are 0-4m up. All land is
    # therefore raised by this much, except within reach of water, where it
    # eases down to the bank: over bank_river (stock river-distance units)
    # beside a river, over bank_shore (metres) beside a lake or the sea.
    "ground_lift": 8,
    "bank_river": [60, 420],
    # The shore easing is stretched to match the taller lift, or a coastline
    # would come out of the water as a bluff rather than a beach.
    "bank_shore": [0, 220],
    # A valley floor pulled flat by the ramps above is a slab: the land is
    # multiplied to nothing, so only the lift holds it up and it is level to
    # the millimetre over hundreds of metres. Real floodplains are flat enough
    # to build on and nowhere near that flat. This is a slow noise - about one
    # swing per 1.2km - laid over the floor, worth this many metres at its
    # fullest, which is a grade of about one per cent: nothing a town placer
    # will notice, enough that the ground stops reading as poured concrete.
    # It is faded out as the land starts to climb, so the hills and the
    # mountains keep the shape the ramps give them, and faded to nothing at
    # the water's edge, so the river keeps clean banks.
    "floor_relief": 8,
    "floor_relief_frequency": 0.0008,
    # The relief gets its own, much shorter fades, and does not ride on `bank`
    # the way the lift does. `bank` is built to walk the ground gently down to
    # the water, over 162m from a river and 220m from a lake or the sea - and
    # multiplying the relief by it held the relief down over exactly the
    # ground that needed it: 50m from a lake shore it was worth 2m, where the
    # land has already been pulled flat by the shore ramps. Around a lake
    # sitting on a river, which can be 420m wide on its own, that left a
    # smooth featureless apron, inside the gravel band the whole way. The lift
    # still eases over the long ramp, so the ground still walks down to the
    # water; the relief comes in over a short one, so it varies while it does.
    "relief_bank": [60, 240],
    "relief_shore": [0, 100],
    # The broad relief above is faded in by `bank`, over 23 to 162m from the
    # river - which is precisely the band the gravel is laid on, so it leaves
    # that band as flat as it found it. A swing every 1.25km would be a tilt
    # across a 150m strip in any case. This is the one that does the work
    # there: a fine ripple, a swing every 250m, worth a couple of metres, held
    # off the channel only far enough to leave its banks clean. Two metres
    # over half a wavelength is a grade of about two per cent.
    "floor_ripple": 3.5,
    "floor_ripple_frequency": 0.004,
    "floor_ripple_bank": [20, 120],
    "floor_ripple_shore": [0, 60],
    # How far the highland takes to climb from a valley floor to its full
    # height, and the shape it climbs in. A straight ramp between two clamps
    # meets the floor at a corner and the ridge at another, and a corner where
    # a wide flat floor meets a mountainside is a wall - the wider the floor,
    # the more it reads as one. The curve is a smoothstep, so the ground leaves
    # the floor and arrives at full height tangentially, with the steepest part
    # in the middle where a valley side belongs.
    #
    # A smoothstep is half again as steep in the middle as the straight ramp it
    # replaces, so the climb is half again as long to keep the steepest part
    # exactly as steep as it was. The valleys get wider; the mountains between
    # them do not get any lower.
    "valley_climb": 2250,
    "valley_curve": [[round(i / 8.0, 4), round((i / 8.0) ** 2 * (3 - 2 * i / 8.0), 4)]
                     for i in range(9)],
    # Hills: stock's 500 puts a 60m bluff beside every river. A longer, later
    # ramp lets the hills roll down to the water instead.
    "hill_floor": 150,
    "hill_climb": 1700,

    # How the land falls to a lake or the sea, in metres from the water's
    # edge. Stock has nothing here: a lake is stamped through whatever is
    # there, and the ground only starts to drop inside the lake's outline - so
    # a lake in the mountains is a hole with 150m of hillside falling into it
    # in under a hundred metres. Ours treats still water the way stock treats
    # rivers: the land is multiplied by a ramp of distance to the shore, so a
    # lake sits in a basin the mountains and hills come down to. Each has a
    # short level shore first, then the climb.
    "shore_high_flat": 60,
    "shore_high_climb": 900,
    "shore_hill_flat": 20,
    "shore_hill_climb": 650,

    # Lakes. Most now lie on the rivers and are the river node's doing. The
    # stock ones - outlines stamped at random over the whole map - are kept
    # only as the odd isolated lake in the lowlands: their centres must fall
    # in this stretch of u (1 = allowed), which is the lower hills and the
    # plains short of the coast, and clear of any river by lake_river_clearance
    # (stock river-distance units). Stock tries a handful of positions per
    # map; with most of the map ruled out, few survive.
    "lake_zone": [[0, 0], [0.50, 0], [0.53, 1], [0.70, 1], [0.73, 0], [1, 0]],
    "lake_river_clearance": 1500,
    # Stock stamps its lake atlas 6000m wide, which suits a lake that is the
    # main feature of its region. An incidental one wants to be smaller.
    "lake_size": 3200,

    # Islands: patches of the sea that stay land. They are the high spots of a
    # noise of about one swing per 1.7km, wherever it passes island_threshold
    # (the noise runs roughly -1..1, so a higher threshold means fewer and
    # smaller islands), and only from island_offshore past the coast, in u -
    # nearer in, the same patch would just be a bump in the coastline. Inside
    # an island the land selector is raised by island_lift, from plains into
    # the hills band, or every island would be a flat shoal.
    "island_frequency": 0.0006,
    "island_threshold": 0.30,
    # The Islands slider, as a curve. The threshold above stays put and the
    # slider shifts the noise under it instead, which is the same thing and
    # keeps the soft edge the threshold gives an island's outline. The middle
    # setting moves nothing, so it is the islands the mod has always had; the
    # first drops the noise so far that the threshold is out of its reach
    # altogether, which is the only way to ask for no islands at all.
    "island_bias": [[0, -3.0], [0.25, -0.12], [0.5, 0.0], [0.75, 0.12], [1, 0.30]],
    "island_offshore": 0.035,
    "island_lift": 0.40,
    # Not every island is lifted. A second, slower noise - one swing per 3km
    # or so, slower than the islands are big, so it rarely changes within one
    # - decides: where it is above island_hilly_above the island is hills,
    # elsewhere it stays as flat as the coastal plain. 0 splits them about
    # evenly; raise it for more flat islands.
    "island_kind_frequency": 0.0003,
    "island_hilly_above": 0.0,
}


def splice_river_to_sea(tree, cfg=RIVER_TO_SEA):
    splice_river(RIVER_NODE)(tree)
    layout = PREFIX + "river_data"

    seed = tree.need("Data", "input_data")
    lakes = tree.need("Sea Rasterization", "rasterizer_map")
    selector = tree.need("New Normalize maps #13", "normalize_map")
    river_dist = tree.need("New Add maps #329", "add_map")
    hill_cut = tree.need("river_cut_02", "map_clamp_map")
    lake_quads = tree.need("Sea quad generator", RANDOM_QUADS)
    target, target_input, land = tree.land()
    biome_map = tree.need("New Remap Map #59", "map_clamp_map")
    biomes_out = tree.need("Biomes Output", "output_biomes")
    mountains_out = tree.need("mountains layer export", "output_biomes")
    mountains_raw = tree.need("mountain height", "map_clamp_map")
    mountains_cut = tree.need("mountains without river", "mul_map")
    lake_anywhere = tree.need("New Constant map #316", "constant_map")
    lake_sizes = tree.need("Atlas scales #0", "constant_pointcloud")
    high_cuts = [tree.need(n, "map_clamp_map")
                 for n in ("river_cut_03", "river cut 04", "river cut 04 #0")]

    name = {key: PREFIX + key for key in (
        "u_raster", "u", "coast_noise", "rough_raster", "rough", "coast_wobble",
        "fine_steps", "fine_share", "coarse_share", "coast_fine_noise",
        "fine_part", "coarse_part", "coast_mix",
        "u_coast", "sea", "water",
        "profile_steps", "profile", "selector_noise", "selector_raw", "selector",
        "floor_noise", "floor_neg", "floor_zone_steps", "floor_zone", "floor_scaled",
        "valley_dist", "valley_t", "valley_curve_steps",
        "valley_river", "hill_river",
        "dry_land", "shore_dist", "shore_high", "shore_hill", "valley", "hill_valley",
        "lake_zone_steps", "lake_zone", "lake_clear", "lake_allowed", "lake_blocked",
        "island_raster", "island_param", "island_bias_steps", "island_bias", "island_noisy",
        "lake_sizes", "floor_steps", "island_noise", "island_raw", "island_gate",
        "island", "not_island", "open_sea", "island_lift", "selector_lifted",
        "biome_cap", "biomes", "bank_river", "bank_shore", "bank", "ground", "land",
        "relief_noise", "relief_raw", "off_valley", "relief_zone", "relief", "ground_total",
        "ripple_noise", "ripple_raw", "ripple_bank", "ripple_near", "ripple", "relief_total",
        "relief_bank_river", "relief_bank_shore", "relief_fade",
        "ripple_bank_shore", "ripple_fade",
        "island_kind_noise", "island_hilly", "island_hills")}

    def ref(key):
        return (name[key], "out")

    for block in (
        # u, 0 deep in the mountains to 1 out at sea. The script points the
        # quad's texture coordinates at the tile of the layout it chose, and
        # the tile already allows for the quad's overhang, so nothing is left
        # for the graph to undo - the remap only clamps.
        node(name["u_raster"], "rasterizer_map",
             inputs={"texCoords": (layout, "layoutTexCoords"),
                     "vertices": (layout, "layoutVertices")},
             params={"op": "Max", "tex": LAYOUT_TEX,
                     "wrapS": "REPEAT", "wrapT": "REPEAT"}),
        remap_map(name["u"], ref("u_raster"), 0, 1, 0, 1),

        # Where a stock lake may be stamped: the lowland stretch, away from
        # rivers. random_quads keeps a quad whose centre reads 0, so the mask
        # is inverted at the end. The atlas is 4x4, one size per tile.
        node(name["lake_zone_steps"], "constant_pointcloud",
             params={"values": cfg["lake_zone"]}),
        node(name["lake_zone"], "pwlerp_map",
             inputs={"in1": ref("u"), "steps": ref("lake_zone_steps")}),
        remap_map(name["lake_clear"], (river_dist, "out"), cfg["lake_river_clearance"],
                  cfg["lake_river_clearance"] + 100, 0, 1),
        node(name["lake_allowed"], "mul_map",
             inputs={"in1": ref("lake_zone"), "in2": ref("lake_clear")}),
        remap_map(name["lake_blocked"], ref("lake_allowed"), 0, 1, 1, 0),
        node(name["lake_sizes"], "constant_pointcloud",
             params={"values": [[cfg["lake_size"], 0]] * 16}),

        # The sea: everything past a wobbly coastline, merged into the stock
        # lake map so every stock consumer treats it as water.
        node(name["coast_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["coast_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": 4}),
        # How far the coast wanders, as a map: one quad, every corner of it
        # pointing at the same texel, so the whole map reads that one value.
        node(name["rough_raster"], "rasterizer_map",
             inputs={"texCoords": (layout, "roughTexCoords"),
                     "vertices": (layout, "roughVertices")},
             params={"op": "Max", "tex": LAYOUT_TEX,
                     "wrapS": "REPEAT", "wrapT": "REPEAT"}),
        remap_map(name["rough"], ref("rough_raster"), 0, 1, 0, 1),
        # The fine octave's share of the wobble, and the coarse one's, which
        # is the rest of it.
        node(name["fine_steps"], "constant_pointcloud",
             params={"values": cfg["coast_fine_share"]}),
        node(name["fine_share"], "pwlerp_map",
             inputs={"in1": ref("rough"), "steps": ref("fine_steps")}),
        remap_map(name["coarse_share"], ref("fine_share"), 0, 1, 1, 0),
        node(name["coast_fine_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["coast_fine_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": 2}),
        node(name["fine_part"], "mul_map",
             inputs={"in1": ref("coast_fine_noise"), "in2": ref("fine_share")}),
        node(name["coarse_part"], "mul_map",
             inputs={"in1": ref("coast_noise"), "in2": ref("coarse_share")}),
        node(name["coast_mix"], "add_map",
             inputs={"in1": ref("coarse_part"), "in2": ref("fine_part")}),
        node(name["coast_wobble"], "mul_map",
             inputs={"in1": ref("coast_mix"), "in2": ref("rough")}),
        node(name["u_coast"], "add_map",
             inputs={"in1": ref("u"), "in2": ref("coast_wobble")}),
        remap_map(name["sea"], ref("u_coast"), cfg["coast"], cfg["coast"] + 0.005, 0, 1),

        # Islands: noise peaks, counted only well out to sea, taken back out
        # of the sea mask.
        node(name["island_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["island_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": 3}),
        # The Islands slider, which the river node hands over as a map in the
        # same way as the coastline's roughness, bent into island sizes here.
        node(name["island_raster"], "rasterizer_map",
             inputs={"texCoords": (layout, "islandTexCoords"),
                     "vertices": (layout, "islandVertices")},
             params={"op": "Max", "tex": LAYOUT_TEX,
                     "wrapS": "REPEAT", "wrapT": "REPEAT"}),
        remap_map(name["island_param"], ref("island_raster"), 0, 1, 0, 1),
        node(name["island_bias_steps"], "constant_pointcloud",
             params={"values": cfg["island_bias"]}),
        node(name["island_bias"], "pwlerp_map",
             inputs={"in1": ref("island_param"), "steps": ref("island_bias_steps")}),
        node(name["island_noisy"], "add_map",
             inputs={"in1": ref("island_noise"), "in2": ref("island_bias")}),
        remap_map(name["island_raw"], ref("island_noisy"),
                  cfg["island_threshold"], cfg["island_threshold"] + 0.04, 0, 1),
        remap_map(name["island_gate"], ref("u_coast"),
                  cfg["coast"] + cfg["island_offshore"],
                  cfg["coast"] + cfg["island_offshore"] + 0.02, 0, 1),
        node(name["island"], "mul_map",
             inputs={"in1": ref("island_raw"), "in2": ref("island_gate")}),
        remap_map(name["not_island"], ref("island"), 0, 1, 1, 0),
        node(name["open_sea"], "mul_map",
             inputs={"in1": ref("sea"), "in2": ref("not_island")}),

        node(name["water"], "compare_map",
             inputs={"in1": (lakes, "out"), "in2": ref("open_sea")},
             params={"op": "MAX"}),

        # The relief: a profile along u, roughened by the stock selector noise.
        node(name["profile_steps"], "constant_pointcloud",
             params={"values": cfg["profile"]}),
        node(name["profile"], "pwlerp_map",
             inputs={"in1": ref("u"), "steps": ref("profile_steps")}),
        remap_map(name["selector_noise"], (selector, "out"), 0, 1,
                  -cfg["noise_swing"], cfg["noise_swing"]),
        node(name["selector_raw"], "add_map",
             inputs={"in1": ref("profile"), "in2": ref("selector_noise")}),
        node(name["island_kind_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["island_kind_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": 2}),
        remap_map(name["island_hilly"], ref("island_kind_noise"),
                  cfg["island_hilly_above"] - 0.04, cfg["island_hilly_above"] + 0.04, 0, 1),
        node(name["island_hills"], "mul_map",
             inputs={"in1": ref("island"), "in2": ref("island_hilly")}),
        remap_map(name["island_lift"], ref("island_hills"), 0, 1, 0, cfg["island_lift"]),
        node(name["selector_lifted"], "add_map",
             inputs={"in1": ref("selector_raw"), "in2": ref("island_lift")}),
        remap_map(name["selector"], ref("selector_lifted"), 0, 1, 0, 1),

        # The valleys: our own ramps of distance to the nearest river, in
        # place of the stock ones.
        # The highland one is clamp((distance - floor) / climb) with a floor
        # that varies from place to place. There is no subtract node, so the
        # floor is made negative as it is scaled and then added.
        node(name["floor_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["valley_floor_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": 2}),
        node(name["floor_steps"], "constant_pointcloud",
             params={"values": [[x, -w] for x, w in cfg["valley_floor_curve"]]}),
        node(name["floor_neg"], "pwlerp_map",
             inputs={"in1": ref("floor_noise"), "steps": ref("floor_steps")}),
        node(name["floor_zone_steps"], "constant_pointcloud",
             params={"values": cfg["floor_by_zone"]}),
        node(name["floor_zone"], "pwlerp_map",
             inputs={"in1": ref("u"), "steps": ref("floor_zone_steps")}),
        node(name["floor_scaled"], "mul_map",
             inputs={"in1": ref("floor_neg"), "in2": ref("floor_zone")}),
        node(name["valley_dist"], "add_map",
             inputs={"in1": (river_dist, "out"), "in2": ref("floor_scaled")}),
        remap_map(name["valley_t"], ref("valley_dist"), 0, cfg["valley_climb"], 0, 1),
        node(name["valley_curve_steps"], "constant_pointcloud",
             params={"values": cfg["valley_curve"]}),
        node(name["valley_river"], "pwlerp_map",
             inputs={"in1": ref("valley_t"), "steps": ref("valley_curve_steps")}),
        remap_map(name["hill_river"], (river_dist, "out"), cfg["hill_floor"],
                  cfg["hill_floor"] + cfg["hill_climb"], 0, 1),

        # The shores: the same again for still water. distance_map gives, for
        # every pixel above its threshold, the distance to the nearest one at
        # or below it - so it wants a map that is 0 on water and 1 on land.
        # The lake atlas fades out at its edges; anything it touches at all
        # counts as water, so the distance is measured from the outline.
        remap_map(name["dry_land"], ref("water"), 0, 0.02, 1, 0),
        node(name["shore_dist"], "distance_map",
             inputs={"in1": ref("dry_land")}, params={"threshold": 0}),
        remap_map(name["shore_high"], ref("shore_dist"), cfg["shore_high_flat"],
                  cfg["shore_high_flat"] + cfg["shore_high_climb"], 0, 1),
        remap_map(name["shore_hill"], ref("shore_dist"), cfg["shore_hill_flat"],
                  cfg["shore_hill_flat"] + cfg["shore_hill_climb"], 0, 1),

        # Land is as high as both allow: low near a river, low near a shore.
        node(name["valley"], "mul_map",
             inputs={"in1": ref("valley_river"), "in2": ref("shore_high")}),
        node(name["hill_valley"], "mul_map",
             inputs={"in1": ref("hill_river"), "in2": ref("shore_hill")}),

        # Dry ground: lift all land clear of the water level, easing down to
        # the banks. Added on the land side, before the river is carved.
        remap_map(name["bank_river"], (river_dist, "out"),
                  cfg["bank_river"][0], cfg["bank_river"][1], 0, 1),
        remap_map(name["bank_shore"], ref("shore_dist"),
                  cfg["bank_shore"][0], cfg["bank_shore"][1], 0, 1),
        node(name["bank"], "mul_map",
             inputs={"in1": ref("bank_river"), "in2": ref("bank_shore")}),
        remap_map(name["ground"], ref("bank"), 0, 1, 0, cfg["ground_lift"]),
        # The floodplain's own relief, on the flat ground only.
        node(name["relief_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["floor_relief_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": 3}),
        remap_map(name["relief_raw"], ref("relief_noise"), -1, 1, 0, cfg["floor_relief"]),
        remap_map(name["off_valley"], ref("valley"), 0, 1, 1, 0),
        node(name["relief_zone"], "mul_map",
             inputs={"in1": ref("relief_raw"), "in2": ref("off_valley")}),
        remap_map(name["relief_bank_river"], (river_dist, "out"),
                  cfg["relief_bank"][0], cfg["relief_bank"][1], 0, 1),
        remap_map(name["relief_bank_shore"], ref("shore_dist"),
                  cfg["relief_shore"][0], cfg["relief_shore"][1], 0, 1),
        node(name["relief_fade"], "mul_map",
             inputs={"in1": ref("relief_bank_river"), "in2": ref("relief_bank_shore")}),
        node(name["relief"], "mul_map",
             inputs={"in1": ref("relief_zone"), "in2": ref("relief_fade")}),
        # The fine ripple, which reaches in close enough to break up the
        # gravel band itself.
        node(name["ripple_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["floor_ripple_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": 2}),
        remap_map(name["ripple_raw"], ref("ripple_noise"), -1, 1, 0, cfg["floor_ripple"]),
        remap_map(name["ripple_bank"], (river_dist, "out"),
                  cfg["floor_ripple_bank"][0], cfg["floor_ripple_bank"][1], 0, 1),
        remap_map(name["ripple_bank_shore"], ref("shore_dist"),
                  cfg["floor_ripple_shore"][0], cfg["floor_ripple_shore"][1], 0, 1),
        node(name["ripple_fade"], "mul_map",
             inputs={"in1": ref("ripple_bank"), "in2": ref("ripple_bank_shore")}),
        node(name["ripple_near"], "mul_map",
             inputs={"in1": ref("ripple_raw"), "in2": ref("ripple_fade")}),
        node(name["ripple"], "mul_map",
             inputs={"in1": ref("ripple_near"), "in2": ref("off_valley")}),
        node(name["relief_total"], "add_map",
             inputs={"in1": ref("relief"), "in2": ref("ripple")}),
        node(name["ground_total"], "add_map",
             inputs={"in1": ref("ground"), "in2": ref("relief_total")}),
        node(name["land"], "add_map",
             inputs={"in1": (land, "out"), "in2": ref("ground_total")}),

        # What the tree tells the rest of the game about the land. Stock
        # labels by zone alone, so a valley floor in the highland is still
        # reported as biome 3 or 4 and, under an alpine stamp, as "mountains"
        # - although we have flattened it. No towns appeared on those floors,
        # and the town placer is native code we cannot read, so the labels
        # are made to tell the truth: where the highland has been pulled all
        # the way down, the biome map says plains (biome 1 is 1.2 on its 0..4
        # scale) and the mountains layer, rewired below, is the stamp as cut
        # by the valleys rather than as stamped.
        remap_map(name["biome_cap"], ref("valley"), 0, 0.05, 1.2, 4),
        node(name["biomes"], "compare_map",
             inputs={"in1": (biome_map, "out"), "in2": ref("biome_cap")},
             params={"op": "MIN"}),
    ):
        tree.add(block)

    for consumer, input_name in tree.consumers(lakes):
        tree.rewire(consumer, input_name, lakes, name["water"])
    for consumer, input_name in tree.consumers(selector):
        tree.rewire(consumer, input_name, selector, name["selector"])
    tree.rewire(target, target_input, land, name["land"])
    tree.rewire(biomes_out, "output", biome_map, name["biomes"])
    tree.rewire(mountains_out, "output", mountains_raw, mountains_cut)
    tree.rewire(lake_quads, "mask", lake_anywhere, name["lake_blocked"])
    tree.rewire(lake_quads, "sizeAndScale", lake_sizes, name["lake_sizes"])
    for consumer, input_name in tree.consumers(hill_cut):
        tree.rewire(consumer, input_name, hill_cut, name["hill_valley"])
    for cut in high_cuts:
        for consumer, input_name in tree.consumers(cut):
            tree.rewire(consumer, input_name, cut, name["valley"])


# --- validation ---------------------------------------------------------------

def learn(stock, custom_layer_types):
    """What each layerType needs and publishes: stock ones from the stock
    trees, ours (layerType -> CUSTOM_NODES key) from CUSTOM_NODES."""
    inputs = collections.defaultdict(list)     # layerType -> input-name sets seen
    params = collections.defaultdict(list)     # layerType -> param-key sets seen
    out_keys = collections.defaultdict(set)    # layerType -> output keys read
    for climate in CLIMATES:
        nodes = parse(stock.tree(climate))
        kinds = {n["name"]: n["layerType"] for n in nodes}
        for n in nodes:
            inputs[n["layerType"]].append(set(n["inputs"]))
            params[n["layerType"]].append(n["params"])
            for src, key in n["inputs"].values():
                if src in kinds:
                    out_keys[kinds[src]].add(key)
    for layer_type, custom in custom_layer_types.items():
        spec = CUSTOM_NODES[custom]
        inputs[layer_type].append(set(spec["inputs"]))
        # A second observation without the optional inputs, so that what every
        # use of the type has in common - which is how validate() tells a
        # required input from an optional one in the stock types - comes out as
        # the required ones alone.
        inputs[layer_type].append(set(spec["inputs"]) - set(spec.get("optional", ())))
        params[layer_type].append(set(spec["params"]))
        out_keys[layer_type] |= spec["outputs"]
    return inputs, params, out_keys


def check_literals(text):
    """Catch unquoted string params, which load fine and then index a global."""
    ok = re.compile(r'^("|\{|\[\[|true$|false$|-?[\d.]+(e-?\d+)?$)')
    bad = []
    for i, line in enumerate(text.split("\n"), 1):
        m = re.match(r"\s*(\w+) = (.+?),?\s*$", line)
        if m and not ok.match(m.group(2).strip()):
            bad.append("line %d: %s = %s" % (i, m.group(1), m.group(2).strip()))
    return bad


def validate(text, knowledge):
    """Return a list of problems; empty means the game should accept the tree.

    Checks every node, stock ones included, for the failures that crash map
    generation without naming a node: a reference to a node that is not there,
    an output read by a key its type does not publish, a missing required
    input, and - for our own nodes - params the type has never been seen with.
    """
    inputs, params, out_keys = knowledge
    nodes = parse(text)
    by_name = {}
    problems = []
    for n in nodes:
        if n["name"] in by_name:
            problems.append("duplicate node name %r" % n["name"])
        by_name[n["name"]] = n

    for n in nodes:
        kind = n["layerType"]
        for key, (src, out_key) in n["inputs"].items():
            if src not in by_name:
                problems.append("%s.%s -> unknown node %r" % (n["name"], key, src))
                continue
            known = out_keys.get(by_name[src]["layerType"])
            if known and out_key not in known:
                problems.append("%s.%s reads %r from %s; stock only ever reads %s"
                                % (n["name"], key, out_key, src, sorted(known)))

        if kind not in inputs:
            problems.append("%s: layerType %r never used in stock trees" % (n["name"], kind))
            continue
        missing = set.intersection(*inputs[kind]) - set(n["inputs"])
        if missing:
            problems.append("%s (%s): missing required input(s) %s"
                            % (n["name"], kind, sorted(missing)))

        if n["name"].startswith(PREFIX):
            unknown = set(n["inputs"]) - set.union(*inputs[kind])
            if unknown:
                problems.append("%s (%s): input(s) %s never wired in stock"
                                % (n["name"], kind, sorted(unknown)))
            # A param may be left out only if a wire supplies it instead.
            absent = set.intersection(*params[kind]) - n["params"] - set(n["inputs"])
            extra = n["params"] - set.union(*params[kind])
            if absent:
                problems.append("%s (%s): missing param(s) %s"
                                % (n["name"], kind, sorted(absent)))
            if extra:
                problems.append("%s (%s): param(s) %s never used in stock"
                                % (n["name"], kind, sorted(extra)))

    # Our nodes must actually reach something the tree outputs - the height
    # map, or the biome and layer maps - or the splice is inert.
    reach = set()
    stack = [n["name"] for n in nodes
             if n["layerType"] in ("height_map_output", "output_biomes")]
    while stack:
        current = stack.pop()
        if current in reach or current not in by_name:
            continue
        reach.add(current)
        stack.extend(src for src, _ in by_name[current]["inputs"].values())
    for n in nodes:
        if n["name"].startswith(PREFIX) and n["name"] not in reach:
            problems.append("%s does not feed any output" % n["name"])

    return problems + ["odd literal - " + b for b in check_literals(text)]


# --- the .gen.lua ---------------------------------------------------------------

# Params of our own, which every stock generator does without: the dialog
# builds one UI element per param with no limit on the number
# (gui/menu/new_game_react_util.tl, addTerrainParameterSettingsEntry), and
# ComboBox is one of the five uiTypes it knows (api.type.enum.ScriptParamType).
# Both of ours read as "leave it alone" at the value a generator that never got
# them falls back on, so a dialog that turns out not to show a fourth and fifth
# param costs only the choice.
GEN_PARAM = """\t\t\t{
\t\t\t\tdefaultIndex = %(default)d,
\t\t\t\timages = { },
\t\t\t\tkey = "%(key)s",
\t\t\t\tname = _("%(name)s"),
\t\t\t\ttags = { },
\t\t\t\ttooltip = _("%(tooltip)s"),
\t\t\t\tuiType = "%(ui)s",
\t\t\t\tvalueIndices = { },
\t\t\t\tvalues = {
%(values)s
\t\t\t\t},
\t\t\t\tyearFrom = 0,
\t\t\t\tyearTo = 0,
\t\t\t},
"""


def gen_param(key, name, tooltip, ui, values, default):
    return GEN_PARAM % dict(
        key=key, name=name, tooltip=tooltip, ui=ui, default=default,
        values="\n".join('\t\t\t\t\t_("%s"),' % v for v in values))


def our_params():
    """The params Mountains to delta adds, in the order the dialog shows them:
    above the stock sliders, because they decide what those then adjust."""
    return (
        gen_param(LAYOUT_KEY, "Layout", "Where the mountains and the sea are.",
                  "ComboBox", ["Random"] + [spec["name"] for spec in LAYOUTS], 1)
        + gen_param(COAST_KEY, "Coastline",
                    "How far the coastline wanders in and out of a straight line.",
                    "Slider", [v[0] for v in COASTLINES], 3)
        + gen_param(ISLANDS_KEY, "Islands",
                    "How many islands lie off the coast.",
                    "Slider", [v[0] for v in ISLANDS], 3)
        + gen_param(AXIS_KEY, "Orientation",
                    "Which side of the map the layout runs along. "
                    "A square map looks the same either way.",
                    "ComboBox", [v[0] for v in AXES], 2))


HEADER = """-- %(display)s. GENERATED by tools/build.py - do not edit by hand.
--
-- The stock %(climate)s generator pointed at our own node tree: the stock graph
-- with %(what)s.
-- The stock sliders are untouched and still work.
"""


def build_gen(stock, climate, tree_res, label, what, layout_param_wanted=False):
    text = stock.gen(climate)
    for old, new in (
        ('nodeTree = "%s_gen.tree"' % climate, 'nodeTree = "%s"' % tree_res),
        # The generator moves out of the climate's own folder, so the climate
        # can no longer be named relative to it. This is also the id the new
        # game dialog compares against when listing generators for a climate.
        ('climate = "%s.clima"' % climate,
         'climate = "::/climates/%s/%s.clima"' % (climate, climate)),
    ):
        if text.count(old) != 1:
            raise SystemExit("expected exactly one %r in the stock generator" % old)
        text = text.replace(old, new)

    # The display name is not always the climate name - "dry" ships as
    # "Desert" - so take it from the desc block rather than guessing.
    found = {}

    def rename(match):
        # A label starting with "=" is the whole name; any other is appended
        # to the climate's, as in "Temperate + Mesas".
        if label.startswith("="):
            found["display"] = label[1:]
        else:
            found["display"] = "%s + %s" % (match.group(2), label)
        return match.group(1) + found["display"] + match.group(3)

    text, count = re.subn(r'(desc = \{.*?name = _\(")([^"]+)("\))', rename, text,
                          count=1, flags=re.S)
    if not count:
        raise SystemExit("could not find the display name in the stock generator")
    if layout_param_wanted:
        anchor = "\t\tparams = {\n"
        if text.count(anchor) != 1:
            raise SystemExit("could not find the generator's param list")
        text = text.replace(anchor, anchor + our_params(), 1)

    # After the stock entries, which are ordered 0..3.
    text, count = re.subn(r"order = \d+", "order = 90", text, count=1)
    if not count:
        raise SystemExit("could not find the order in the stock generator")
    header = HEADER % {"display": found["display"], "climate": climate, "what": what}
    return found["display"], header + text


# --- main ---------------------------------------------------------------------

# A tree names a scripted node by its path under content/, without ".lua" and
# without a mod prefix - the same form stock trees use for the stock nodes
# ("gui/node_editor/river_points.node"). Settled by probe: the prefixed form
# "mapzilla_1::/mapzilla/river.node" crashes generation, this one is found.
RIVER_NODE = "mapzilla/river.node"

# The game's settings.lua remembers the last generator used by resource name,
# and the new game dialog crashes on opening if that generator is gone. So a
# file base, once it has been selected in the game, is not free to rename or
# remove: pick another generator in the dialog first.
# What a published mod ships is what it must go on shipping: settings.lua
# remembers the last generator used by resource name, and the new game dialog
# crashes on opening if that generator has gone. The probes this one was built
# from - the river on stock terrain, the desert's mesas in noise-picked
# regions - are therefore not in the list. Their splices stay in this file, and
# putting either back is one line.
GENERATORS = (
    # (file base, stock climate, splice, label, description for the header,
    #  whether the generator gets the Layout dropdown)
    # The file base keeps its first name: it is what settings.lua remembers, so
    # it cannot follow the display name.
    ("mapzilla_temperate_river_sea", "temperate", splice_river_to_sea,
     "=Mapzilla - Mountains to delta",
     "one river laid out by our scripted node, with the mountains and the sea\n"
     "-- placed around it in the layout the Layout dropdown asks for", True),
)

CUSTOM_LAYER_TYPES = {RIVER_NODE: "river"}


def write(path, text):
    with io.open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write(text)


def write_content_list(content_dir):
    """_content.json lists every file under content/, generated or not."""
    files = []
    for root, _, names in os.walk(content_dir):
        for name in names:
            files.append(os.path.relpath(os.path.join(root, name), content_dir).replace(os.sep, "/"))
    lines = ",\n".join('        "%s"' % f for f in sorted(files))
    write(os.path.join(content_dir, "..", "_content.json"),
          '{\n    "archives": null,\n    "files": [\n%s\n    ]\n}\n' % lines)
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game", default=DEFAULT_GAME)
    parser.add_argument("--content", default=DEFAULT_CONTENT)
    args = parser.parse_args()

    stock = Stock(args.game)
    knowledge = learn(stock, CUSTOM_LAYER_TYPES)
    content_dir = os.path.abspath(args.content)
    out_dir = os.path.join(content_dir, "climates", "mapzilla")

    # The river script's own copy of the layout table, which build.py cannot
    # validate the way it validates a tree.
    script = os.path.join(content_dir, "mapzilla", "nodes.script.lua")
    drift = check_layouts(script)
    if drift:
        for problem in drift:
            print("  -", problem)
        return 1

    built = []
    for base, climate, splice, label, what, layout in GENERATORS:
        tree = Tree(stock.tree(climate))
        splice(tree)
        text = tree.render()
        problems = validate(text, knowledge)
        if problems:
            print("%s: NOT written" % base)
            for p in problems:
                print("  -", p)
            return 1
        display, gen = build_gen(stock, climate, base + ".tree", label, what, layout)
        built.append((base, display, len(tree.nodes), len(tree.added), text, gen))

    # Everything in the output folder is generated, so stale generators from an
    # earlier build must not linger and keep showing up in the game.
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, name))
    for base, display, stock_nodes, added, text, gen in built:
        write(os.path.join(out_dir, base + ".tree.lua"), text)
        write(os.path.join(out_dir, base + ".gen.lua"), gen)
        print("%-28s %d stock nodes + %d of ours, validated" % (display, stock_nodes, added))
    print("written to " + out_dir)
    tex = os.path.join(content_dir, "mapzilla", "tex")
    write_layout_atlas(os.path.join(tex, "layouts.tga"))
    print("%d layouts baked into tex/layouts.tga: %s"
          % (len(LAYOUTS), ", ".join(spec["key"] for spec in LAYOUTS)))
    # gradient.tga was the single left-to-right ramp the atlas replaced.
    stale = os.path.join(tex, "gradient.tga")
    if os.path.exists(stale):
        os.remove(stale)
    print("%d files listed in _content.json" % write_content_list(content_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
