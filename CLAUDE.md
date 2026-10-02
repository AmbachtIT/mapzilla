# Mapzilla

Mapzilla is a mod for Transport Fever 3. The aim is to expose more options in the map generator to create more varied and realistic maps.

## How it works

TODO

## Mod parameters

TODO
## Layout

```
mod/mapzilla_1/      the publishable mod (deploy.ps1 installs this)
```

## Conventions

- All files are LF (`.gitattributes` pins this); `core.autocrlf` must not win.
- `mod.json` param indices are 1-based - confirmed against the stock climate
  generators in `base/content/climates.zip`, which default to index 3 of
  `[Sparse, Scattered, Medium, Dense, Packed]`.
- `.gs.lua` game scripts run in the game state; never `require` anything under
  `::/gui/...` from them.
