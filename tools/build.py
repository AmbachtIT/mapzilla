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
        "inputs": {"boundsMin", "boundsMax", "amount", "lakes", "seed"},
        # "amount" and "lakes" are optional in the .node.lua. Stock gives an
        # optional input both a wire and a param of the same name, so we do too.
        "params": {"amount", "lakes", "seed"},
        "outputs": {"points", "widths", "depthsTangent", "tangents", "widthTangents",
                    "layoutVertices", "layoutTexCoords"},
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

def splice_river(layer_type):
    """Swap the stock river layout for the one from our scripted river node.

    The stock tree feeds river_map from river_points.node, a scripted random
    walk. Ours publishes the same five point clouds, so only the wires move:
    river_map and everything downstream of it - the carved bed, the valley the
    land is flattened into - stay stock. The stock node is left in place,
    unconnected.

    `layer_type` is the name the tree uses for our node.
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
        tree.add(node(name, layer_type,
                      inputs={"boundsMin": stock["inputs"]["boundsMin"],
                              "boundsMax": stock["inputs"]["boundsMax"],
                              "amount": amount,
                              "lakes": lakes,
                              "seed": stock["inputs"]["seed"]},
                      params={"amount": 0.5, "lakes": 0.5, "seed": 0}))
        for key in RIVER_MAP_INPUTS:
            tree.rewire(river["name"], key, stock_points, name)
    return splice


# --- the river-to-sea splice --------------------------------------------------
#
# On top of our river: mountains at its source and a sea at its mouth.
#
# The river node also publishes a quad covering the map. Rasterised with a
# gradient texture, that is a map of u - 0 at the mountain end, 1 at the sea
# end - which no stock node can provide, since nothing in the graph knows
# which way our script turned the river. Everything else hangs off u:
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
GRADIENT_TEX = "mapzilla_1::/mapzilla/tex/gradient.tga"

RIVER_TO_SEA = {
    # Where the coast is, in u. The river script opens its delta at 0.66.
    "coast": 0.80,
    # The coastline wanders by this much of the map either way, on a noise of
    # about one swing per 3km, so it is not a ruled line.
    "coast_wobble": 0.05,
    "coast_frequency": 0.0003,
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
    "valley_floor_curve": [[-1, 0], [-0.55, 0], [0.55, 1140], [1, 1140]],
    # A valley floor, or any ground we flatten, is the land multiplied down to
    # nothing: height 0. The water level is 0 too. So the "flat land" in the
    # mountains was a film a centimetre above the water - it looks like land,
    # and no town will go on it. Stock plains are 0-4m up. All land is
    # therefore raised by this much, except within reach of water, where it
    # eases down to the bank: over bank_river (stock river-distance units)
    # beside a river, over bank_shore (metres) beside a lake or the sea.
    "ground_lift": 4,
    "bank_river": [60, 420],
    "bank_shore": [0, 140],
    "valley_climb": 1500,
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
        "u_raster", "u", "coast_noise", "coast_wobble", "u_coast", "sea", "water",
        "profile_steps", "profile", "selector_noise", "selector_raw", "selector",
        "floor_noise", "floor_neg", "valley_dist", "valley_river", "hill_river",
        "dry_land", "shore_dist", "shore_high", "shore_hill", "valley", "hill_valley",
        "lake_zone_steps", "lake_zone", "lake_clear", "lake_allowed", "lake_blocked",
        "lake_sizes", "floor_steps", "island_noise", "island_raw", "island_gate",
        "island", "not_island", "open_sea", "island_lift", "selector_lifted",
        "biome_cap", "biomes", "bank_river", "bank_shore", "bank", "ground", "land",
        "island_kind_noise", "island_hilly", "island_hills")}

    def ref(key):
        return (name[key], "out")

    for block in (
        # u, 0 at the mountain end to 1 at the sea end. The quad overhangs the
        # map, so the map itself only spans the middle of the gradient.
        node(name["u_raster"], "rasterizer_map",
             inputs={"texCoords": (layout, "layoutTexCoords"),
                     "vertices": (layout, "layoutVertices")},
             params={"op": "Max", "tex": GRADIENT_TEX,
                     "wrapS": "REPEAT", "wrapT": "REPEAT"}),
        remap_map(name["u"], ref("u_raster"),
                  LAYOUT_MARGIN / (1 + 2 * LAYOUT_MARGIN),
                  (1 + LAYOUT_MARGIN) / (1 + 2 * LAYOUT_MARGIN), 0, 1),

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
        remap_map(name["coast_wobble"], ref("coast_noise"), -1, 1,
                  -cfg["coast_wobble"], cfg["coast_wobble"], clamp=False),
        node(name["u_coast"], "add_map",
             inputs={"in1": ref("u"), "in2": ref("coast_wobble")}),
        remap_map(name["sea"], ref("u_coast"), cfg["coast"], cfg["coast"] + 0.005, 0, 1),

        # Islands: noise peaks, counted only well out to sea, taken back out
        # of the sea mask.
        node(name["island_noise"], "fractal_noise_map",
             inputs={"seed": (seed, "seed")},
             params={"frequency": cfg["island_frequency"], "gain": 0.5,
                     "lacunarity": 2.0, "numOctaves": 3}),
        remap_map(name["island_raw"], ref("island_noise"),
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
        node(name["valley_dist"], "add_map",
             inputs={"in1": (river_dist, "out"), "in2": ref("floor_neg")}),
        remap_map(name["valley_river"], ref("valley_dist"), 0, cfg["valley_climb"], 0, 1),
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
        node(name["land"], "add_map",
             inputs={"in1": (land, "out"), "in2": ref("ground")}),

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


def write_gradient(path, width=256, height=8):
    """A left-to-right 0..255 ramp as an 8-bit greyscale TGA - the format of
    the stock stamps such as climates/gen/tex/volcano.tga."""
    header = bytes([0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    width & 255, width >> 8, height & 255, height >> 8, 8, 8])
    row = bytes(round(x * 255 / (width - 1)) for x in range(width))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(header + row * height)


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

HEADER = """-- %(display)s. GENERATED by tools/build.py - do not edit by hand.
--
-- The stock %(climate)s generator pointed at our own node tree: the stock graph
-- with %(what)s.
-- The stock sliders are untouched and still work.
"""


def build_gen(stock, climate, tree_res, label, what):
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
GENERATORS = (
    # (file base, stock climate, splice, label, description for the header)
    # Shown as "Mountains to delta". The file base keeps its first name: it
    # is what settings.lua remembers, so it cannot follow the display name.
    ("mapzilla_temperate_river_sea", "temperate", splice_river_to_sea, "=Mountains to delta",
     "one river laid out by our scripted node, mountains at its source and a sea at its mouth"),
    ("mapzilla_river_a", "temperate", splice_river(RIVER_NODE), "River probe",
     "the river layout taken from our scripted node"),
    ("mapzilla_temperate_mesas", "temperate", splice_mesas, "Mesas",
     "the desert's mesas, confined to noise-picked regions, spliced into the height chain"),
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

    built = []
    for base, climate, splice, label, what in GENERATORS:
        tree = Tree(stock.tree(climate))
        splice(tree)
        text = tree.render()
        problems = validate(text, knowledge)
        if problems:
            print("%s: NOT written" % base)
            for p in problems:
                print("  -", p)
            return 1
        display, gen = build_gen(stock, climate, base + ".tree", label, what)
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
    write_gradient(os.path.join(content_dir, "mapzilla", "tex", "gradient.tga"))
    print("%d files listed in _content.json" % write_content_list(content_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
