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
mountains to the sea and ends in a delta. Two levers have been found:

- **Regional gates.** A feature stamped only where a low-frequency noise field
  allows it, so one side of the map differs from the other. Proven in the game
  with the desert's mesas on a temperate map (`splice_mesas`, no longer built).
- **Scripted nodes.** Some node types, the river layout among them, are Lua
  scripts rather than engine code. `content/mapzilla/` holds our own: a
  `.node.lua` definition plus `nodes.script.lua`. Proven in the game.

Ground textures and vegetation stay those of the generator's climate.

Generators currently built:

| generator | base | changes |
|---|---|---|
| Temperate + River to sea | temperate | one river laid out by our scripted node, running from mountains at one end of the map to a sea at the other, with a delta |
| Temperate + River probe | temperate | river layout from our scripted node: one river across the map that splits into a delta |
| Temperate + Mesas | temperate | the desert's mesas inside noise-picked regions. Kept as a worked example, not as a feature |

See NOTES.md for what was learned about the node graph and scripted nodes.

## Mod parameters

None in `mod.json`. Each generator keeps the stock sliders of its base climate
(for temperate: Lakes, Rivers, Mountains).

## Layout

```
mod/mapzilla_1/      the publishable mod (deploy.ps1 installs this)
  content/climates/mapzilla/   generated generators - do not edit by hand
  content/mapzilla/            our scripted nodes, written by hand
  _content.json                generated: lists everything under content/
tools/build.py       builds and validates the generators from the stock trees
tools/make_listing_image.ps1   redraws the listing image
deploy.ps1           rebuilds, then copies the mod into the game's mods folder
NOTES.md             reverse-engineered notes on the terrain node graph
```

## Conventions

- All files are LF (`.gitattributes` pins this); `core.autocrlf` must not win.
- `mod.json` param indices are 1-based - confirmed against the stock climate
  generators in `base/content/climates.zip`, which default to index 3 of
  `[Sparse, Scattered, Medium, Dense, Packed]`.
- `.gs.lua` game scripts run in the game state; never `require` anything under
  `::/gui/...` from them.
