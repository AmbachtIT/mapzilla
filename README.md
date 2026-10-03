# Mapzilla

A mod for **Transport Fever 3**. The stock map generator only exposes a few parameters per biome. This mod exposes more so you can create more varied maps.

![Mapzilla](mod/mapzilla_1/_metadata/0.png)

### The listing image

`tools/make_listing_image.ps1` draws it with GDI+, so it can be regenerated
rather than re-edited by hand. It is a stylised map, not a capture of the game -
there is no real screenshot in this repository yet. Two variants:

```powershell
.\tools\make_listing_image.ps1
```

`arrows` is the accurate one, and is what `0.png` holds: the mod really does move
towns together, and keeps the count the same. `pruned` depicts the earlier
behaviour, when towns between the clusters were deleted outright; it is kept
because it shows more plainly where the empty countryside comes from.

Replace either with a real annotated in-game screenshot when there is one.

## Development

No Lua or Teal toolchain is installed; the game compiles `.tl` at load time and
reports failures to `crash_dump/stdout.txt`. `tlconfig.lua` is there for editor
type-checking against the game's shipped `tealdef` definitions.

The mod logs with the prefix `[mapzilla]`. If that prefix never appears in
the log, the game script never ran.

## How this was built

Written with [Claude Code](https://claude.com/claude-code), in a back-and-forth with the author: 
the author played the game, decided what the mod should do and judged every result; Claude Code 
was used for reverse engineering, wrote the Teal and the tooling, and read the crash dumps.

Everything in NOTES.md was derived from the game's shipped `tealdef` definitions, its own Lua 
and Teal under `base/` and `mods/release/`,and the logs and minidumps in `crash_dump/` - 
including the two access violations that the connection-index bug turned out to be.

The listing image is drawn by a script in `tools/` rather than painted, for the
same reason: so it can be regenerated and reviewed rather than fiddled with.

## Licence

MIT - see [LICENSE](LICENSE).
