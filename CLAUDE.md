# Mapzilla

Mapzilla is a mod for Transport Fever 3. The aim is to expose more options in the map generator to create more varied and realistic maps.

## How it works

A terrain generator is a `.gen.lua` (name, climate, sliders) pointing at a
`.tree.lua` node graph. Mod-supplied generators show up in the new game
dialog's Generator list for the climate they name.

Mapzilla never writes a graph from scratch. `tools/build.py` reads a stock
graph out of the game's `base/content/climates.zip`, splices extra nodes into
its height chain, validates the result against the stock trees and writes it
under `mod/mapzilla_1/content/climates/mapzilla/`. Those files are generated -
change `build.py`, not them.

The goal is varied, realistic maps - for example a river that runs from the
mountains to the sea and ends in a delta. Three levers have been found:

- **Regional gates.** A feature stamped only where a low-frequency noise field
  allows it, so one side of the map differs from the other. Proven in the game
  with the desert's mesas on a temperate map (`splice_mesas`, no longer built).
- **A field the whole graph reads.** "Mountains to delta" puts everything -
  coastline, relief, lakes, islands - on one number: how far a place is from
  the mountains, towards the sea. The script paints that field by pointing a
  quad at one tile of `tex/layouts.tga`, so changing the shape of a map is
  changing one picture (`LAYOUTS` in `tools/build.py`).
- **Scripted nodes.** Some node types, the river layout among them, are Lua
  scripts rather than engine code. `content/mapzilla/` holds our own: a
  `.node.lua` definition plus `nodes.script.lua`. Proven in the game.

Ground textures and vegetation stay those of the generator's climate.

Generators currently built:

| generator | base | changes |
|---|---|---|
| Mapzilla - Mountains to delta | temperate | river systems laid out by our scripted node - trunk, tributaries and their tributaries, widening downstream with discharge - running from highland through rolling hills to flat plains, a delta and the sea, in one of seven layouts: single shore, island, inland sea, isthmus, strait, peninsula, bay |

Two probes are no longer built, because what a published mod ships it must go
on shipping - `settings.lua` remembers the last generator by resource name and
the new game dialog crashes if it has gone. Their splices stay in `build.py`
and putting either back in `GENERATORS` is one line: the river on otherwise
stock temperate terrain, and the desert's mesas inside noise-picked regions
(the worked example of a regional stamp).

See NOTES.md for what was learned about the node graph and scripted nodes.

## Mod parameters

None in `mod.json`. Each generator keeps the stock sliders of its base climate
(for temperate: Lakes, Rivers, Mountains). In "Mountains to delta" the Rivers slider
sets how densely tributaries join and the Lakes slider how many lakes lie along
the rivers.

That generator adds two params of its own, above the stock sliders. No stock
generator declares more than three, or anything but a slider, so both are
Mapzilla's own reading of the dialog's Teal:

- **Layout** (`mz_layout`), a dropdown: where the mountains and the sea are,
  with "Random" - the default - leaving it to the map seed. Confirmed working
  in the game.
- **Coastline** (`mz_coast`), a slider from Straight to Wild: how far the
  coastline wanders in and out of the line the layout would otherwise draw.
  The middle setting is what every map had before the param existed.
- **Islands** (`mz_islands`), a slider from Few to Packed: how many islands
  lie off the coast. The middle setting is again the old behaviour. The first
  takes the island noise out of the picture altogether, but a coastline rough
  enough to wander still strands the odd piece of shelf offshore, which is why
  it is not called None.
- **Orientation** (`mz_axis`), a dropdown: which side of the map the layout
  runs along, the long one (the default, and what every map did before) or the
  short one. Nothing to choose on a square map.

Either falls back to its middle on a dialog that will not show it. The Rivers
slider now also sets how many separate river systems a map gets, from one to
five on a 16km map, as well as how densely their tributaries join.

See Layouts in NOTES.md.

## Layout

```
mod/mapzilla_1/      the publishable mod (deploy.ps1 installs this)
  content/climates/mapzilla/   generated generators - do not edit by hand
  content/mapzilla/            our scripted nodes, written by hand
  content/mapzilla/tex/        generated: layouts.tga, one tile per layout
  _content.json                generated: lists everything under content/
tools/build.py       builds and validates the generators from the stock trees
tools/run_river.js   runs the river node's Lua outside the game (Node + fengari)
tools/preview_river.py   draws its river layout for a few seeds
tools/make_listing_image.ps1   redraws the listing image
deploy.ps1           rebuilds, then copies the mod into the game's mods folder
NOTES.md             reverse-engineered notes on the terrain node graph
```

## Checking a change

`python tools/build.py` validates every tree before writing it. The river
script has no such net in the game - a mistake only shows as a failed map - so
run it first:

```
npm install --no-save fengari
python tools/preview_river.py --out preview.png
```

That executes `content/mapzilla/nodes.script.lua` for six seeds and draws each
one: the layout shaded the way the node graph will read it, with the rivers on
top. `--layout island` (or any key from `LAYOUTS`) draws one layout instead of
leaving it to the seed. It catches Lua errors, a river laid out in a frame its
layout does not match - it checks that every mouth ends at sea and every source
in the highland - and bad layouts; it does not show terrain, which only the
game can. fengari is Lua 5.3 and the game's Lua is older, so keep the script to
plain 5.1.

## Conventions

- All files are LF (`.gitattributes` pins this); `core.autocrlf` must not win.
- `mod.json` param indices are 1-based - confirmed against the stock climate
  generators in `base/content/climates.zip`, which default to index 3 of
  `[Sparse, Scattered, Medium, Dense, Packed]`.
- `.gs.lua` game scripts run in the game state; never `require` anything under
  `::/gui/...` from them.
