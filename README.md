![Mapzilla](mod/mapzilla_1/_metadata/0.png)

A mod for **Transport Fever 3**. The stock map generator only exposes a few parameters per 
biome. The underlying map generation system is much more powerful, as described in 
[Dev Blog 1](https://www.transportfever3.com/news/dev-blog-episode-1-environment/).

The aim of this mod is to add map generation presets that use the power of this system
to generate more interesting maps. Currently the mod has one preset,
*Mapzilla - Mountains to delta*.

### Presets
## Mapzilla - Mountains to delta
A generator for the **Temperate** climate - set Climate to Temperate in the new game dialog and
it appears in the Generator list below it. It connects mountains to the ocean with a meandering
river ending in a delta system.
It can lay the map out in seven ways, chosen with the **Layout** dropdown in the new game
dialog, or left to the map seed:
- Single shore - mountains along one side, sea along the other
- Island - mountains in the middle, sea all round
- Inland sea - sea in the middle, mountains all round
- Isthmus - a mountain range down the middle, sea along both sides
- Strait - a sea channel down the middle, mountains along both sides
- Peninsula - mountains across one end, sea on the other three sides
- Bay - a bay in one end, mountains on the other three sides

The relief, the coastline, the lakes and the islands all follow the layout; the rivers run
from the highest ground to the water wherever that happens to be. Where a layout is the same
on both sides of the map - an isthmus, a strait, an island - they drain it both ways.

Two more settings sit with it in the new game dialog:
- **Coastline**, from Straight to Wild: how far the coast wanders in and out of the line the
  layout would otherwise draw.
- **Islands**, from Few to Packed: how many islands lie off the coast. A rough coastline
  strands a few of its own whatever this says, so an empty sea wants Coastline on Straight too.
- **Orientation**: Default, or Alternate for a quarter turn - which way round the layout sits
  on the map. A square map looks the same either way.
- **Rivers**, the stock slider, now sets how many separate river systems the map gets - one to
  five on a 16km map - as well as how densely their tributaries join.

## How this was built

Written with [Claude Code](https://claude.com/claude-code), in a back-and-forth with the author: 
the author played the game, decided what the mod should do and judged every result; Claude Code 
was used for reverse engineering, wrote the Teal and the tooling, and read the crash dumps.

Everything in NOTES.md was derived from the game's shipped `tealdef` definitions, its own Lua 
and Teal under `base/` and `mods/release/`,and the logs and minidumps in `crash_dump/` - 
including the two access violations that the connection-index bug turned out to be.

The listing image is drawn by a script in `tools/` rather than painted, for the
same reason: so it can be regenerated and reviewed rather than fiddled with.

### About AI

Some people dislike using AI in principle. I ask you not to judge this mod based on the fact 
that I used AI during its development. Without AI, writing the mod would have been much harder
if not impossible (for me, at least). I take full responsibility for the quality of this mod. 
If you believe something is not working as intended, let me know and I will try to fix it.

### The listing image

`tools/make_listing_image.ps1` draws it with GDI+, so it can be regenerated
rather than re-edited by hand. It is a stylised map, not a capture of the game -
there is no real screenshot in this repository yet. Two variants:

```powershell
.\tools\make_listing_image.ps1
```
## Development

No Lua or Teal toolchain is installed; the game compiles `.tl` at load time and
reports failures to `crash_dump/stdout.txt`. `tlconfig.lua` is there for editor
type-checking against the game's shipped `tealdef` definitions.

The mod logs with the prefix `[mapzilla]`. If that prefix never appears in
the log, the game script never ran.

## My mods
* [Mapzilla](https://mod.io/g/transportfever3/m/mapzilla) - A more varied map generator (this mod)
* [Town Clustering](https://mod.io/g/transportfever3/m/town-clustering) - Cluster towns to create agglomerations

## Licence

MIT - see [LICENSE](LICENSE).
