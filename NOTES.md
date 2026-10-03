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

A mod can supply its own **scripted node** - see below. The river probe, no
longer built, replaced the temperate river layout with one from
`content/mapzilla/nodes.script.lua`.

Confirmed in the game: the **layouts** below and the **Layout dropdown** that
chooses between them. A fourth generator param does appear in the new game
dialog, a ComboBox renders, and the key reaches the tree - so a param's value
really is `(index - 1) / (count - 1)`.

Not yet seen in the game: **several river systems per map**, the **Coastline**,
**Islands** and **Orientation** params, and the constant-map trick two of them
rest on.

Seen in the game and worth recording: with the island noise taken out of the
picture entirely, a map still has a few islands. They are the coastline's
doing, not the island stamp's - a threshold on a noisy field stranded pieces of
the shelf offshore - so the setting that does it is called Few and not None.
Coastline at Straight is what makes a sea empty. Checked as far as they can be
without starting it - every layout, at both ends of both params, on three map
shapes, drawn by `tools/preview_river.py`.

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

Confirmed in the game with "Mountains to delta" (first named "Temperate +
River to sea"; its files are still `mapzilla_temperate_river_sea`) - river, delta, sea and
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

## The river tree and the relief along it

Built, checked offline, not yet seen in the game:

- **Tree.** Every river is listed mouth first, source last - stock's order,
  which puts the pointed tip on the source. Tributaries are marched upstream
  from a point on their parent, leaving at 35-50 degrees and bending further
  away, so they join pointing downstream. Rivers keep 1150m apart; a
  tributary's first four points are checked at 500m and not against its
  parent, or neighbours cross on the way out.
- **Width from discharge.** Discharge is kilometres of channel upstream,
  tributaries included; half-width is 15 * sqrt(discharge), between 9 and
  140m. Depth follows width.
- **No pond at the source.** Stock ends a river with width 0 and a width
  tangent of -1000. Widths are hermite-interpolated, so that overshoots by
  about 150m just before the tip - unnoticed on a 60m stock river, a round
  pond on a 9m stream. Ending with a flat width tangent avoids it.
- **Meanders.** The planned course (points 450m apart) is subdivided to 150m
  and each point pushed sideways by a sine of distance travelled. Wavelength
  is 13 river widths, between 1500 and 3200m; amplitude is a fraction of the
  wavelength that rises from 0.06 in the highland to 0.21 in the lowland.
  Every bend (half wave) draws its own length, 0.55 to 1.9 times that, and
  its own reach, changed where the sine crosses zero so nothing kinks - a
  single fixed wavelength made the bends come at an obviously even beat. The
  swing fades to nothing at every confluence and end, so rivers still meet
  where planned. Stock's method - swinging the hermite tangent to alternate
  sides at every point - was tried first and gives a 900m zigzag at any
  strength that shows. A finished 16km map carries about 1000 river points.
- **Long axis.** The river runs along the longer side of the map.
- **Rivers slider.** The stock slider's remapped value is wired into the node
  as `amount` and sets confluence spacing, 5400m down to 2200m.
- **Relief.** The biome selector becomes a profile along the river's axis
  (`pwlerp_map` over a `constant_pointcloud` of steps) plus or minus 0.08 of
  stock noise: 0.86 for the first quarter (highland), 0.66 through the middle
  (hills), 0.25 from two thirds on (plains). A plain ramp was tried first and
  crossed the 0.56-0.75 hills window so fast that the hills went unnoticed.
- **Valleys.** Stock multiplies each zone's height by a ramp of distance to
  the nearest river (`river_cut_02`: 0..500 for hills; `river_cut_03`,
  `river cut 04`, `river cut 04 #0`: 0..1500 for upland, highland and the
  alpine stamps), in the units of `New Add maps #329` - about 2.6 per metre if
  `distance_map` is in metres, which is not established. Ours start the
  highland ramp only beyond a valley floor, leaving flat ground along every
  river as buildable land in the mountains, and stretch the hills ramp to
  150..1850 so the hills roll down to the water instead of ending in a bluff.
  The highland ramp is also a curve rather than a straight line: a straight
  one between two clamps meets the floor at a corner and the ridge at another,
  and seen in the game a corner where a wide flat floor meets a mountainside
  reads as a wall - the wider the floor, the more it does. A smoothstep leaves
  the floor and arrives at full height tangentially, and because it is half
  again as steep in the middle, the climb is half again as long (1500 to 2250)
  to leave the steepest part exactly as steep as it was. Measured on a 300m
  mountain: steepest 27 degrees before and after, full height reached 1015m
  from the river before and 1302m after. The hills ramp is left straight -
  over 120m of hill it is a tenth of that gradient and the corner does not
  show.
- **The floodplain.** A floor pulled flat by those ramps is a slab: the land
  is multiplied to nothing, so only `ground_lift` holds it up and it is level
  to the millimetre for hundreds of metres. The lift is 8m rather than 4, and
  a slow noise - one swing per 1.2km, worth up to 7m, about a one per cent
  grade - is laid over the floor on top of it. It is faded out as the land
  starts to climb (by `valley`, so the hills and mountains keep the shape the
  ramps give them) and to nothing at the water's edge (by `bank`, so the
  channel keeps clean banks). The shore easing is stretched from 140m to 220m
  to match the taller lift, or a coastline comes out of the water as a bluff.
  That broad relief alone was not enough, for two reasons worth remembering:
  it is faded in over 23 to 162m from the river, which is exactly the band the
  gravel is laid on, so it left that band as flat as it found it; and a swing
  every 1.25km is a tilt and not a texture across a strip 150m wide. A second,
  finer ripple does the work there - a swing every 250m, 2.5m, held off the
  channel only far enough (8 to 46m) to leave its banks clean.
  Neither reaches the ground beside a lake or the sea while it rides on
  `bank`, whose shore term runs over 220m: 50m from a shore the relief was
  worth 2m, over land the shore ramps had already pulled flat. A lake on a
  river is up to 420m wide on its own, so that apron was large, smooth,
  featureless and gravelled throughout - which is what "flat at the same
  level" turned out to mean. The relief and the ripple now carry their own,
  much shorter fades (river 23..92m, shore 0..100m, and 8..46m / 0..60m for
  the ripple) while the lift keeps the long ones. Measured beside a lake: at
  50m out the ground now varies by about 7m where it varied by 2m, and the
  lift still eases to the water as gently as before.
- **Floor width by zone.** The width above is scaled by a curve over u, so a
  valley is narrow where the land is high and keeps its full width on the
  plain: about 186m a side at the widest in the highland against 315m on the
  plain, averaging 93m against 157m. One width for the whole course was what
  read as wrong in the mountains - the gravel band is 150m wherever it falls,
  so a mountain floor of 300m is gravel from wall to wall, while the same band
  on the plain is a strip in a wide green field. Narrowing does not shrink the
  band; it shrinks the flat ground the band has to itself. Watch towns in the
  highland after changing this: buildable ground per side goes from 272m to
  208m there, and 248m was the figure that first got towns to appear at all.
  `floor_by_zone` is the dial.
- **Floor width.** 820 units, about 315m a side at the widest and nearer 160m
  on average; it was 1140 (440m). Narrowing it does not shrink the gravel
  band, which is measured from the water and belongs to the river rather than
  the floor - it replaces flat sandy ground with rising grassy ground. Towns
  did not lose by it: the eased ramp keeps the land under a tenth of full
  height for 162m past the floor edge and labelled plains for 115m of that, so
  buildable ground went from about 248m a side to about 272m even as the floor
  itself got narrower.
  The floor width is a map, not a number: a slow noise (0.00035, two octaves)
  read through a `pwlerp_map` curve and subtracted from the distance before
  the ramp. The curve is a straight line from 0 to 1140. One that kept most
  valleys shut and opened a few to 2600 was tried and looked worse in the
  game.

- **Shores.** How stock makes a lake: `Sea Rasterization` stamps lake
  outlines anywhere on the map (its quad mask is a constant 0);
  `Biome distance 0` is, inside an outline, the distance to its edge; and the
  biome 0 mask rises from 0 at the edge to 1 at 400 inside. `maskcomb_map5`
  blends by that mask between the land and the lake bed at -100m. So nothing
  outside the outline changes, and where the land is 150m high the whole
  drop to the water happens in the first 240 or so inside it - a hole with
  cliffs, cut through mountains and valleys alike. Ours adds a second
  `distance_map`, from the land side, and multiplies the hill and highland
  heights by a ramp of it (20..670 and 60..960), exactly as the river cuts
  do, so the land comes down to a lake before it gets there.
- **Lakes on the rivers.** The river node widens a stretch of river into a
  lake: 3 to 7 planned points long, up to 170-420m of extra half-width, each
  with its own fullness, skew and lean to one bank. Meanders are stilled
  inside it. Because a lake is part of `river_map`, the valley shaping gives
  it shores with no further work. The stock Lakes slider (`Ocean Amount`,
  key `oceans`) is wired in as `lakes` and sets the count, about 1 to 7 on a
  16km map.
- **Stock lakes, demoted.** `Sea quad generator`'s mask was a constant 0 -
  anywhere. Ours allows a centre only in the lowland stretch of the river's
  axis and clear of rivers, and stamps the atlas at 3200m instead of 6000m,
  so what is left is the odd isolated lowland lake.
- **Islands.** Peaks of a noise (0.0006, three octaves) above 0.30, counted
  only from 0.035 of the map past the coastline, are multiplied out of the
  sea mask. Where a second, slower noise (0.0003) is positive the selector
  is raised by 0.40 inside them, so about half the islands are hills and the
  rest stay flat. The shore ramps shape their coasts like any other.
- **Flattened land sits at the water level.** `map.waterLevel` is 0.0
  (`gui/menu/new_game_or_map_settings_page.tl`), and land multiplied down by
  a river or shore ramp is at height 0 too - the final sum leaves it 0.01m
  up. It renders as land. Stock never has this over any area: its ramps
  start at the river, and its plains are 0-4m. Ours adds 4m to all land,
  eased to nothing at river banks and shores, on the land side of the final
  sum. Confirmed in the game: with the lift, towns appear on
  the highland valley floors.
- **Towns stayed out of the highland valleys** although the floors looked
  flat and wide enough. The placer is native and unreadable, so the cause is
  not established. Two candidates, both acted on: (1) the labels - stock's
  `Biomes Output` is built from the zone masks alone and its `mountains`
  layer is the raw alpine stamp, so a flattened valley floor is still
  reported as biome 3/4 and as mountains; ours caps the biome map at biome 1
  where the highland has been pulled fully down and exports the stamp as cut
  by the valleys. (2) room - a town needs a level footprint on one side of
  the river, and the old floors were at most about 440m a side; the new curve
  reaches about 1000m. `BaseConfig.Locations.TownParamList.allowInRoughTerrain`
  exists and would be a third lever, from a mod script rather than the tree.
- `distance_map` semantics, worked out from how stock uses it: for a pixel
  above the threshold it gives the distance to the nearest pixel at or below
  it; pixels at or below get 0. Stock feeds it inverted masks for that reason.

## Layouts

Where the mountains and the sea are. The river-to-sea splice hangs the
coastline, the relief, the lakes and the islands off one field u - 0 deep in
the mountains, 1 out at sea - so a different u is a different map, and nothing
downstream has to know. Seven of them, in `LAYOUTS` in `tools/build.py`:
single shore, island, inland sea, isthmus, strait, peninsula, bay.

- **One field, two readers.** A layout is a distance measured in the map frame
  (`a` along the map's longer side, `b` across) and the two distances at which
  u is 0 and 1. `build.py` bakes the field from them; the script lays the
  river out in the frame they describe, from u 0.05 to 1.03 along the map's
  centre line, where the field is linear in u by construction. They are two
  tables in two languages, so `check_layouts` reads the script's back and
  refuses to build if they have drifted apart, and `preview_river.py` checks
  the result the other way round: it reads u off the field at the trunk's two
  ends and says so if the mouth is not at sea or the source not in the
  highland.
- **A distance may end off the map.** That is what gives a layout a broad band
  of mountains along an edge rather than a thin rim: the map edge then lies
  partway up the ramp instead of at its end. The river's upper reach goes off
  the map with it, which is no odder than the mouth, which has always run a
  little past the edge.
- **One texture, seven tiles.** The layout is picked per map, by the seed or
  by the dropdown, so it cannot be a texture named in the tree. It is an
  atlas instead - `tex/layouts.tga`, the tiles side by side - and the script
  points the layout quad's texture coordinates at the tile it chose. The quad
  already overhangs the map by `LAYOUT_MARGIN`, so each tile is baked with the
  overhang in it and the map lands in the middle of its tile, clear of the
  filtering at the edges. One row of tiles, not a grid: how `random_quads`
  turns an atlas index into a column offset is plain, but which way up the
  rows are read is not, and every field is symmetrical across the map's centre
  line anyway.
- **Radial layouts are a wedge, not a strip.** A step sideways near the centre
  of the map covers far less ground than the same step at the coast, so
  lateral offsets are scaled by the distance from the centre - but never below
  a third, or a stream near the centre comes out as a straight radial line
  with its meanders pressed flat. The river is still planned on a plain
  rectangle; only the last step onto the map knows.
- **Several river systems.** The Rivers slider sets how many, from one to
  five on a 16km map and more on a wider one, as well as how densely their
  tributaries join. Each gets a lane of its own across the map and keeps its
  trunk, its wander and its delta inside it, so they never braid. Two things
  follow from lanes: a narrow lane makes for shorter tributaries, so the
  minimum length comes down with it (`MIN_POINTS_NARROW`) or there would be
  none at all; and the lanes only span `band`, the share of the map across the
  rivers that the layout leaves them - on a peninsula the flanks are sea all
  the way down, and a river laid out there would start in the water.
- **Lanes on a radial layout are counted per side.** Two systems draining
  opposite sides of an island are already as far apart as the map can put
  them; lanes on top of that drag their sources off the summit and their
  mouths away from the middle, which on a radial layout are the one point the
  whole thing turns around. A fold's two sides lie along the length of the
  map, where there is room to spread, so those keep their lanes. Before this,
  a two-river island put both sources in the hills.
- **Orientation.** Which of the map's two sides the layout runs along - the
  one the land changes down. The long side is what every map did before the
  param; the short side turns the whole thing a quarter turn, which on an
  isthmus or a strait is the difference between a range down the length of the
  map and one across it. A square map looks the same either way.
- **A fold drains both ways.** Isthmus and strait put the same land on both
  sides of the map's centre line, and successive systems take the two sides in
  turn - so a strait is drained from both of its shores and an island on both
  of its flanks. This is why rivers are kept apart in map metres and not in the
  frame: two systems on opposite sides of a fold share a (U, V) and are half a
  map apart, and near the centre of a radial layout the frame is squeezed.
- **Corners.** Peninsula and bay need a second term for their flanks. Combined
  with a plain max or min it gives the map square corners; taken in quadrature
  it rounds them off, and still leaves the centre line exactly u, which is the
  only place the field and the river's frame have to agree.
- **Confluences.** A folded or radial layout gives the river under half the
  map to run down, and confluences counted in metres leave it nearly bare. The
  spacing is pulled in by the square root of what the river lost - the land it
  drains does not shrink with it. A layout running the length of the map
  scales by exactly 1, so the generator that existed before layouts is
  untouched.

### The Coastline param, and a number as a map

The coastline is a threshold on u plus a noise, so how far it wanders is the
amplitude of that noise. Nothing in the graph multiplies a map by a number
that a slider can reach: the scalar inputs stock wires are thresholds,
frequencies and kernel sizes (`distance_map.threshold`, `ridged_noise_map`'s
`baseFreq`, `blur_map.sigma`), and `constant_map` takes its value from a param.

So the number is carried across as a picture, the way the layout is:

- The script emits a second quad over the whole map, every corner of it
  pointing at **one single texel**, so rasterising it fills the map with that
  one value. `mul_map` then scales the coast noise by it.
- The texel is a point on the first tile of the atlas, which is the plain ramp
  of the "shore" layout - its value is the map coordinate it stands for. So
  asking it for a number is reading that ramp backwards, and `build.py` asserts
  the first tile stays plain. `preview_river.py` decodes the texture coordinate
  the script sent and prints the amplitude back, which is what checks the two
  ends of the trick against each other.
- Any number a script works out can reach the map side of the graph this way,
  and so can a param that only the script is handed. The Islands slider goes
  across untouched - the script is a pipe - and a `pwlerp_map` on the far side
  bends it into island sizes, which is how five slider steps get a curve rather
  than a straight line. Being a curve is what lets its first setting push the
  noise clean out of the threshold's reach, so "None" really is none, while its
  middle setting still leaves the islands the mod has always had.
- The alternative, for a threshold like the islands' one, is the stock pattern:
  `param_number -> remap_number -> split_interval.percentage -> mask_map`,
  which is how the Mountains slider moves the biome splits. It was not used
  here for two reasons: `mask_map` is a hard in-or-out test, which would cost
  the islands the soft edge the threshold ramp gives their outlines, and the
  chain is linear end to end, so it could not have both a true "None" and the
  old behaviour in the middle.

Two things bound the amplitude, both in `nodes.script.lua`:

- u stops at 1, so beyond the end of the frame - the corners of a radial
  layout, the last of the map on any other - the whole sea reads exactly 1. A
  wobble of `1 - COAST` or more would turn that outermost water back into land
  wherever the noise dipped, so `ROUGHNESS_MAX` stays well under it.
- The wobble is two octaves, and the second one takes a share of it rather
  than adding to it, so the pair never reach further than the ceiling and the
  guarantee above still holds. The share is read off how far the coast wanders
  at all - the one number in the graph that follows the Coastline setting -
  through a `pwlerp_map`: nothing at Straight, two fifths at Wild. What the
  setting changes is therefore the character of the coast as much as its
  reach, which is what "rugged" has to mean once the reach has a ceiling.
- A layout that folds the map puts the whole of u into half its width, so the
  same distance on the ground is a much larger slice of u. The amplitude is
  therefore scaled by how much of the map the frame covers, which is what makes
  one setting mean the same number of metres on every layout - the folded ones
  being exactly the ones whose coastlines looked ruled. On those the top two
  settings meet the ceiling together.

### The Layout dropdown

A fourth generator param, which no stock generator has. From the dialog's own
Teal, not from a running game:

- `new_game_react_util.tl`, `addTerrainParameterSettingsEntry` builds one UI
  element per entry of `generatorDesc.params`, with no limit on the number.
- `uiType` is one of five (`api.type.enum.ScriptParamType`): Button, Slider,
  ComboBox, IconButton, CheckBox. Stock generators only ever use Slider.
- `param_number` reads a param by key and gives a number in 0..1 - every stock
  tree reads one through a `remap_number` whose input range is 0..1. The value
  looks to be `(index - 1) / (count - 1)`: the dummy a node falls back on is
  0.5 wherever the slider's default is the middle of five values. **Inferred,
  not confirmed** - if it is wrong the dropdown will be off by one, and the
  log line names the layout the script actually chose.
- An unwired optional input takes its value from the node's param of the same
  name. Stock relies on this: no `random_quads` anywhere wires `atlasSize`,
  and `layer_nodes.script.tl` reads `inputs.atlasSize.point` regardless.
- Index 1 is "Random", and 0 is also what `param_number` falls back on where
  the key is not set. So a generator that never got the param, or a dialog
  that turns out not to show a fourth one, still gets a layout from the seed.

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

### The texture tree also reads the height map, and that is a beach rule

`temperate_clima.tree` has a `height_map_input`, so not every texture comes
from the masks we write. Two layers are driven by `distance_map(height,
threshold 0)` - the horizontal distance to the nearest ground at or below
height 0, which is to say to the nearest water, river or sea alike:

- `gravel_01` is laid on at strength 2.3 at the water's edge, falling to 0 at
  **80m**, minus up to 2.3 of a ridged noise that breaks it into patches. It
  is drawn at order 500, over the grass.
- `grass_green` is multiplied by a ramp that is **0 within 50m** of water and
  only full at **150m**.

Under both is the background material, `grass_light_green`. So every water's
edge gets a band of patchy gravel on pale grass: stock's beach, applied to
river banks too, because the rule cannot tell a coast from a channel and has
no idea how wide the river is - a brook and a 280m river get the same 80m.
The plains tree mask keeps its distance from water as well (a `distance_map`
over `Percolation`), so the same band is bare.

This showed up as sandy, treeless valley floors: ours are flat, wide and at
the water's edge by design, so the band covered them instead of sitting on a
bank. What fixed the look was raising and roughening the floor (see the
floodplain relief above), not fighting the rule.

**Do not fight the rule by shipping a climate of our own. That is ruled out,
and it is a decision rather than an open question - the mod works within the
stock biomes.** It was looked at once and the reasons it was dropped are here
so that it does not get looked at again:

- `new_game_page.tl` builds the climate selection page from
  `climateRep.getAll()`, one card per clima with `visible` set. So a mod that
  ships a clima adds a fifth card beside Temperate, Desert, Subarctic and
  Tropical - it does not add a texture variant under Temperate. Setting
  `visible = false` hides the card, but then the climate can never be chosen
  and its generators never list.
- Savegames record the climate by resource name
  (`savegame_react_util.tl` looks it up with `climateRep.find`), so every map
  made with our own climate would need the mod installed to load. Pointing at
  stock temperate keeps maps loadable without us.
- A copied clima is 306 lines; only `nodeTree`, the name, the icon and the
  relative `temperate.env` reference would have to change. The numbers to
  change are the two above: `map_clamp_map8_from` (0..80) for the gravel and
  `map_clamp_map0` (50..150) for the grass.
- Overriding stock's `temperate_clima.tree` by shipping a file at the same
  path would avoid the card, but it would change every temperate map in the
  game, stock generators included, and collide with any other mod that tried
  it. Ruled out for the same reason.

So the ground textures and the vegetation are the stock climate's, and a
feature that looks wrong under them is fixed by changing the terrain we hand
the texture tree, not by changing the rules it reads it with.

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
2. How many params will the dialog show? Four is confirmed; five is not.
3. How much does a map of five river systems cost to generate? Rivers are kept
   apart by a scan over every point claimed so far, which grows with the square
   of the number of them.
4. Can two `river_map` nodes coexist in one tree?
