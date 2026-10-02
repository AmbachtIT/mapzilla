# Terrain generator notes

Reverse-engineered from the stock climates in `base/content/climates.zip` and
the game's GUI scripts. None of it is from documentation - treat it as
findings, and re-verify after game patches. The Town Clustering repository's
NOTES.md covers mod layout, Lua states and the node-graph crash modes; this
file adds what Mapzilla needed on top.

## Status

Confirmed in the game: a generator in `climates/mapzilla/` loads, its relative
`nodeTree` resolves, it appears in the Generator list for its climate, and the
preview generates without crashing. The region mask works - the splice changed
about half the map and left the rest stock temperate.

The mesa stamp was confirmed too. The first build stamped about 4 per km2, the
desert's density, and the affected half came out as noise at tens to hundreds
of metres - overlap, see Stamps below. At 0.3 per km2 separate mesas appear.
Their tops are not quite flat: the atlas blobs brighten toward the centre and
the desert's height mapping is unclamped. The mesa generator is no longer
built (mesas turned out not to be what the mod is for); `splice_mesas` stays in
`tools/build.py` as the worked example of a regional stamp.

A mod can supply its own **scripted node** - see below. The river probe
replaces the temperate river layout with one from
`content/mapzilla/nodes.script.lua`.

## Scripted nodes

The `gui/node_editor/*.node` layer types are not engine code. Each is a
`.node.lua` resource declaring inputs, outputs and an `applyScript`, and the
script is ordinary Teal in `gui/node_editor/layer_nodes.script.tl`. The engine
keeps them in a resource repository (`LayerGeneratorNodeRep`) like generators
and climates, which is why a mod should be able to add one.

An apply function is `fn(params, inputs, captureParams)`:

- `inputs.<key>` carries `.value`, `.point` (`.x`, `.y`), `.pointCloud` or
  `.map` according to the declared type. A map can be sampled anywhere:
  `inputs.mask.map:get(api.type.Vec2f.new(x, y))`, after checking
  `:isEmpty()` for an unwired optional input.
- It returns one `{ typeCode, value }` per declared output, in order:
  1 number, 2 point `{x, y}`, 3 point cloud `{ {x, y}, ... }`.
- A script **cannot return a map**. It influences height only through nodes
  that turn points into maps: `river_map`, `ridge_map`, `rasterizer_map`.
- `math.random` is seeded by the engine; nodes get a `seed` input unless the
  `.node.lua` says `withSeed = false`.

This matters most for rivers. The whole river layout - where rivers start,
how they wander, where tributaries join, lakes along them - is
`riverPoints.applyFn` plus `climates/gen/mapgenutil.tl`. `river_map` only
carves what it is given: points, hermite tangents, left/right widths, depth.
Several rivers travel as one list, separated by repeating the last point of
the previous river. So a mod that can ship a scripted node decides river
geometry completely.

Two limits that no script changes:

- **One water level.** `GameMap.waterLevel` is a single number. A river does
  not descend; it is a channel at sea level, and the land is pulled down to
  meet it (`river cut` multiplies the land by distance to the river). A river
  "from the mountains" is a valley cut through them.
- Stock rivers ignore the terrain. They are laid out first and the terrain is
  shaped around them, steered only by the `riverWeight` map.

Settled by probe:

- **A tree names a mod's node by bare content path**, without `.lua` and
  without a mod prefix: `content/mapzilla/river.node.lua` is
  `layerType = "mapzilla/river.node"`. The prefixed form
  `mapzilla_1::/mapzilla/river.node` crashes generation with
  `Assertion 'it != map.end()' failed` (`map_util.h:22`).
- **A mod's `applyScript` is loaded in the main menu.** The engine found
  `mapzilla_1::/mapzilla/nodes.script@river.applyFn` and tried to call it.
- **A `.script.lua` must publish through `function data() return {...} end`.**
  A `.script.tl` returns its table directly; doing that from Lua fails with
  `Lua error: function data() not defined`, logged with the resource name and
  followed by `Error while applying layer generator node: node='...'`. That
  failure does not crash the game - the map just generates without the node's
  output.
- **Never remove or rename a generator carelessly.** `settings.lua` remembers
  the last one used by resource name (`terrainGenerator = "mapzilla_1::/..."`).
  When the mesa generator was dropped from a build while it was the remembered
  choice, the new game dialog crashed on opening with the same assertion.
  Restoring it fixed the dialog.

- **The scripted river works.** One trunk with a three-way split appeared in
  the game exactly as `nodes.script.lua` lays it out.

Confirmed in the game with "Temperate + River to sea" - river, delta, sea and
mountains all came out oriented correctly:

- **A mod can ship a texture for `rasterizer_map`**, named with the mod prefix:
  `mapzilla_1::/mapzilla/tex/gradient.tga` (8-bit greyscale TGA, like the stock
  stamps). Note the contrast with scripted nodes, which take no prefix.
- **The layout trick.** The river node also returns a quad over the whole map;
  rasterised with that gradient it gives the graph a map of position along the
  river's axis. This is how a script's choices - here, which way it turned the
  river - reach the map-valued side of the graph.
- **The sea as a "lake".** Our sea mask is MAXed into `Sea Rasterization`, the
  stock lake map, and stock turns it into biome 0 with shore and textures.
- **Mountains by tilting the biome selector** (`New Normalize maps #13`, 0..1,
  split into biome 1..4 by interval) along the same axis.

## Files that make up a generator

Per climate, in `climates/<climate>/`:

| file | role |
|---|---|
| `<climate>.gen.lua` | the generator: name, `climate`, `nodeTree`, sliders |
| `<climate>_gen.tree.lua` | height, biome masks, assets (325-430 nodes) |
| `<climate>.clima.lua` + `<climate>_clima.tree.lua` | ground textures |
| `<climate>_import.gen.lua` + tree | used when importing a heightmap |

`nodeTree` and `climate` in the stock `.gen.lua` are bare names
(`"temperate_gen.tree"`, `"temperate.clima"`), resolved relative to the file's
own folder. A generator that lives elsewhere must name the climate in full:
`"::/climates/temperate/temperate.clima"`. That full form is also what the new
game dialog compares against when it lists generators for the chosen climate
(`gui/menu/new_game_react_util.tl`, `gatherMapConfig`), along with
`not editorOnly`, `not isImportGenerator` and `visible`.

## The texture tree depends on the generator

The climate's texture tree reads named maps that the generator tree writes with
`output_map_data`. A generator must write every key its climate reads:

| climate | keys the texture tree reads |
|---|---|
| temperate | `biome0`-`biome4`, `biome4_mountains`, `biome4_no_mountains`, `forest_mask` |
| dry | `biome0`-`biome4`, `coast_hills`, `lakes`, `mesas`, `monument_valley`, `mountains` |
| subarctic | `biome1`-`biome4`, `forest_mask`, `mountain_mask` |
| tropical | `biome1`-`biome4`, `forest_mask`, `highway`, `mountains`, `volcano` |

So a feature transplanted into another climate is textured by that climate's
rules. Splicing into a stock tree keeps all of its `output_map_data` nodes, so
this takes care of itself.

## How a stock tree builds height

All four end the same way: `add_map(land, river) -> height_map_output`, where
the river term is negative. Anything added to the *land* side is still cut by
rivers; anything added after would fill them in.

Land is five elevation zones (`biome0` water through `biome4` highland) picked
by low-frequency noise and merged by `maskcomb_map5`, plus stamped features.
Temperate zone heights: biome 0 at -100m, biome 1 0..4m, biome 2 5..120m,
biome 3 80..140m, biome 4 100..160m, alpine stamps up to 380m on top.

### Stamps

Mountains, mesas, cliffs, lakes, swamps, volcanoes and islands are all the same
three nodes:

```
random_quads.node -> rasterizer_map (an atlas from climates/gen/tex) -> map_clamp_map to metres
```

`random_quads` takes a `mask` map and keeps a quad where the mask is **0** at
its centre (`centerCheck`) - stock always feeds it an inverted mask, and the
lake stamp, which may go anywhere, gets a constant 0. `numQuads` is the number
of *attempts*; stock scales it by map area in km2 (`Calc map size`).

The feature in an atlas tile is much smaller than its quad. In
`dry_mesa_plateau_01.png` (2x2) each mesa is a blob about a third of the tile
wide, so a 1200-1500m quad gives a mesa roughly 450m across. Stamps blend with
`Max`, so once quads are dense enough to overlap they merge into one ragged
plateau. The desert does this on purpose: at ~4 attempts per km2 its mesa stamp
is really the "high plateau" of its biome 3, not a field of separate mesas.

### Node semantics worth knowing

- `map_clamp_map`: `from_x..from_y` is the **input interval** and `to_x..to_y`
  the output interval. Inverting a mask is `from = (0, 1)`, `to = (1, 0)`.
  With `clamp = false` it is a plain linear map, so `to = (0, -1)` negates.
- `compare_map` with `op = "MAX"` / `"MIN"` is a per-pixel max / min.
- `mix_map(in1, in2, mask)` blends two maps; only subarctic uses it.
- `fractal_noise_map` frequency is per metre and cannot be wired, so anything
  built on it does not scale with map size. `ridged_noise_map.baseFreq` can be
  wired, but its value distribution is different.
- `river_points.node` takes a `riverWeight` map: river density can vary by
  region inside one connected network.
- There is no subtract node. `a - b` is `add_map(a, negate(b))`.

## Open questions

1. How long does a 346-node tree take in the new game dialog's preview?
2. Will the dialog show a fourth slider? Every stock generator declares exactly
   three, though the trees also read a `forest` key no slider declares.
3. Can two `river_map` nodes coexist in one tree?
