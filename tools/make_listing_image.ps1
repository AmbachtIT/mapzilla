<#
.SYNOPSIS
Renders the mod.io listing image (1920x1080) for Mapzilla.

.DESCRIPTION
This is a stylised illustration of the map view, not a capture of the game.
Nothing here is a screenshot: it is drawn with GDI+ so it can be regenerated
and tweaked. Same palette and type as the Town Clustering listing image.

The map is one island whose coastline happens to be a certain large lizard:
dorsal plates as a jagged north-west coast, a town for an eye, and a chain of
islets off the mouth.

.PARAMETER OutFile
Where to write the PNG.
#>
[CmdletBinding()]
param(
	[string]$OutFile
)

$ErrorActionPreference = "Stop"

# Resolved here rather than as the parameter default: under Windows PowerShell
# -File, $PSScriptRoot is still empty while defaults are bound, and the image
# lands in C:\mod instead.
if (-not $OutFile) { $OutFile = Join-Path $PSScriptRoot "..\mod\mapzilla_1\_metadata\0.png" }
Add-Type -AssemblyName System.Drawing

$W = 1920
$H = 1080

function New-Colour([string]$Hex, [int]$Alpha = 255) {
	$r = [Convert]::ToInt32($Hex.Substring(0, 2), 16)
	$g = [Convert]::ToInt32($Hex.Substring(2, 2), 16)
	$b = [Convert]::ToInt32($Hex.Substring(4, 2), 16)
	return [System.Drawing.Color]::FromArgb($Alpha, $r, $g, $b)
}

function New-Point([double]$X, [double]$Y) {
	return New-Object System.Drawing.PointF ([float]$X), ([float]$Y)
}

# Map-view palette: muted terrain greens, water teal, warm amber for towns.
$SeaTop    = New-Colour "2B5A73"
$SeaBot    = New-Colour "1A3848"
$WaterEdge = New-Colour "3C7795"
$Coast     = New-Colour "26382C"
$Lowland   = New-Colour "36503D"
$Midland   = New-Colour "4A6B52"
$Upland    = New-Colour "5F8265"
$Peak      = New-Colour "7A9A7C"
$Shore     = New-Colour "E4D8BE" 150
$Town      = New-Colour "F5B95C"
$TownCore  = New-Colour "FFF0D2"
$Road      = New-Colour "E4D8BE" 190
$Accent    = New-Colour "E8734A"
$Ink       = New-Colour "F6F3EC"

$bmp = New-Object System.Drawing.Bitmap $W, $H
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$gfx.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$gfx.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic

# ---------------------------------------------------------------- sea
$rect = New-Object System.Drawing.Rectangle 0, 0, $W, $H
$seaBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush $rect, $SeaTop, $SeaBot, 70.0
$gfx.FillRectangle($seaBrush, $rect)

# Deterministic jitter so the image is reproducible.
$script:seed = 20261002
function Next-Rand {
	$script:seed = ($script:seed * 1103515245 + 12345) % 2147483648
	return $script:seed / 2147483648.0
}

# Soft blotches, to stop a gradient reading as flat paper. Used for the sea
# here and again, clipped to the coastline, for the land.
function Draw-Blotches([int]$Count, [string]$Light, [string]$Dark) {
	for ($i = 0; $i -lt $Count; $i++) {
		$cx = (Next-Rand) * $W
		$cy = 180 + (Next-Rand) * ($H - 180)
		$rr = 70 + (Next-Rand) * 230
		$aa = 8 + [int]((Next-Rand) * 12)
		if ((Next-Rand) -gt 0.45) {
			$col = New-Colour $Light $aa
		} else {
			$col = New-Colour $Dark $aa
		}
		$br = New-Object System.Drawing.SolidBrush $col
		$gfx.FillEllipse($br, [float]($cx - $rr), [float]($cy - $rr / 1.7), [float]($rr * 2), [float]($rr * 1.18))
		$br.Dispose()
	}
}
Draw-Blotches 70 "3C7795" "10222C"

# ---------------------------------------------------------------- coastline
# The whole island is nudged up a little so the feet clear the bottom edge.
$OffY = -18.0

# The back, from the nape down to where the plates run out on the tail. The
# plates are cut into this stretch of coast, so it is kept apart from the rest.
$backRaw = @(
	@(1370, 320), @(1310, 380), @(1250, 460), @(1190, 560), @(1130, 660), @(1060, 750),
	@(960, 820), @(820, 870), @(660, 900), @(500, 905), @(360, 880)
)

# Everything else, carrying on from the end of the back: tail tip, underside,
# both feet, belly, arm, jaws, and over the top of the head back to the nape.
$restRaw = @(
	@(360, 880), @(250, 830), @(180, 760), @(150, 690), @(175, 800), @(240, 890),
	@(350, 955), @(510, 988), @(700, 992), @(900, 978), @(1040, 968),
	@(1075, 1000), @(1085, 1040), @(1250, 1046), @(1262, 1018), @(1200, 992),
	@(1235, 935), @(1300, 905),
	@(1332, 960), @(1325, 1040), @(1475, 1046), @(1485, 1018), @(1412, 988),
	@(1432, 900), @(1478, 800), @(1486, 700), @(1452, 625),
	@(1475, 605), @(1560, 642), @(1625, 622), @(1632, 592), @(1570, 582), @(1502, 542),
	@(1472, 500), @(1452, 455), @(1468, 415),
	@(1540, 418), @(1582, 398), @(1512, 380), @(1592, 366), @(1562, 335),
	@(1500, 305), @(1430, 295), @(1370, 320)
)

function ConvertTo-Points($Raw) {
	$list = New-Object 'System.Collections.Generic.List[System.Drawing.PointF]'
	foreach ($p in $Raw) { $list.Add((New-Point $p[0] ($p[1] + $OffY))) }
	return , $list.ToArray()
}
$backPts = ConvertTo-Points $backRaw
$restPts = ConvertTo-Points $restRaw

# Smooth the back into a dense polyline that can be walked by arc length.
$tmp = New-Object System.Drawing.Drawing2D.GraphicsPath
$tmp.AddCurve($backPts, 0.5)
$tmp.Flatten()
$dense = $tmp.PathPoints
$tmp.Dispose()

$cum = New-Object 'double[]' $dense.Count
for ($i = 1; $i -lt $dense.Count; $i++) {
	$dx = $dense[$i].X - $dense[$i - 1].X
	$dy = $dense[$i].Y - $dense[$i - 1].Y
	$cum[$i] = $cum[$i - 1] + [Math]::Sqrt($dx * $dx + $dy * $dy)
}
$backLen = $cum[$dense.Count - 1]

function Get-BackPoint([double]$S) {
	for ($i = 1; $i -lt $dense.Count; $i++) {
		if ($cum[$i] -ge $S) {
			$f = ($S - $cum[$i - 1]) / [Math]::Max(0.001, $cum[$i] - $cum[$i - 1])
			return @(($dense[$i - 1].X + ($dense[$i].X - $dense[$i - 1].X) * $f),
				($dense[$i - 1].Y + ($dense[$i].Y - $dense[$i - 1].Y) * $f))
		}
	}
	return @($dense[$dense.Count - 1].X, $dense[$dense.Count - 1].Y)
}

# Dorsal plates: jagged, three-pointed, biggest over the shoulders and hips and
# tapering toward the head and down the tail. They are part of the one coastline
# figure rather than separate shapes laid on top - a stroked outline would
# otherwise draw every plate's base straight across the island.
$coastBack = New-Object 'System.Collections.Generic.List[System.Drawing.PointF]'
$coastBack.Add($dense[0])
$s = 14.0
while ($true) {
	$t = $s / $backLen
	$f = [Math]::Sin([Math]::PI * [Math]::Pow($t, 0.75))
	$pw = 38 + 78 * $f
	$ph = 24 + 86 * $f
	if ($s + $pw -gt $backLen - 8) { break }

	$a = Get-BackPoint $s
	$b = Get-BackPoint ($s + $pw)
	$dx = $b[0] - $a[0]
	$dy = $b[1] - $a[1]
	$len = [Math]::Sqrt($dx * $dx + $dy * $dy)
	$dx /= $len; $dy /= $len
	# outward normal: up and to the left of the direction of travel
	$nx = -$dy * -1
	$ny = $dx * -1
	if ($ny -gt 0 -or ($ny -eq 0 -and $nx -gt 0)) { $nx = -$nx; $ny = -$ny }
	$mx = ($a[0] + $b[0]) / 2
	$my = ($a[1] + $b[1]) / 2

	$coastBack.Add((New-Point $a[0] $a[1]))
	$coastBack.Add((New-Point ($a[0] + $dx * $len * 0.14 + $nx * $ph * 0.50) ($a[1] + $dy * $len * 0.14 + $ny * $ph * 0.50)))
	$coastBack.Add((New-Point ($a[0] + $dx * $len * 0.30 + $nx * $ph * 0.44) ($a[1] + $dy * $len * 0.30 + $ny * $ph * 0.44)))
	$coastBack.Add((New-Point ($mx + $nx * $ph) ($my + $ny * $ph)))
	$coastBack.Add((New-Point ($b[0] - $dx * $len * 0.30 + $nx * $ph * 0.44) ($b[1] - $dy * $len * 0.30 + $ny * $ph * 0.44)))
	$coastBack.Add((New-Point ($b[0] - $dx * $len * 0.14 + $nx * $ph * 0.50) ($b[1] - $dy * $len * 0.14 + $ny * $ph * 0.50)))
	$coastBack.Add((New-Point $b[0] $b[1]))

	$s += $pw + 5
}
$coastBack.Add($dense[$dense.Count - 1])

$island = New-Object System.Drawing.Drawing2D.GraphicsPath
$island.AddLines($coastBack.ToArray())
$island.AddCurve($restPts, 0.38)
$island.CloseFigure()

# Atomic breath, as a chain of islets trailing off from the mouth.
$islets = @(
	@(1668, 356, 27, 13), @(1742, 350, 21, 10), @(1803, 345, 15, 8),
	@(1851, 341, 10, 5.5), @(1888, 338, 6.5, 3.5)
)
$isletPath = New-Object System.Drawing.Drawing2D.GraphicsPath
foreach ($e in $islets) {
	$isletPath.StartFigure()
	$isletPath.AddEllipse([float]($e[0] - $e[2]), [float]($e[1] + $OffY - $e[3]), [float]($e[2] * 2), [float]($e[3] * 2))
}

# ---------------------------------------------------------------- land
# Shallows first: two soft halos in the water around every coast.
foreach ($halo in @(@(64, 26), @(30, 46))) {
	$pn = New-Object System.Drawing.Pen (New-Colour "3C7795" $halo[1]), $halo[0]
	$pn.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
	$gfx.DrawPath($pn, $island)
	$pn.Width = $halo[0] * 0.55
	$gfx.DrawPath($pn, $isletPath)
	$pn.Dispose()
}

# Elevation bands. Fill with the summit colour, then stroke the coast with ever
# narrower pens, clipped to the land: each stroke repaints everything within
# half its width of the sea, which leaves bands stepping up from the shore.
$peakBrush = New-Object System.Drawing.SolidBrush $Peak
$gfx.FillPath($peakBrush, $island)
$lowBrush = New-Object System.Drawing.SolidBrush $Lowland
$gfx.FillPath($lowBrush, $isletPath)

$gfx.SetClip($island)
foreach ($band in @(@(250, $Upland), @(150, $Midland), @(64, $Lowland))) {
	$pn = New-Object System.Drawing.Pen $band[1], $band[0]
	$pn.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
	$gfx.DrawPath($pn, $island)
	$pn.Dispose()
}
# Same shading the sea got, so the land is not flat either.
$shadeRect = New-Object System.Drawing.Rectangle 0, 0, $W, $H
$shade = New-Object System.Drawing.Drawing2D.LinearGradientBrush $shadeRect, (New-Colour "6E8F72" 30), (New-Colour "0E1712" 95), 70.0
$gfx.FillRectangle($shade, $shadeRect)
Draw-Blotches 90 "6E8F72" "1C2A20"
$gfx.ResetClip()

$shorePen = New-Object System.Drawing.Pen $Shore, 2.6
$shorePen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
$gfx.DrawPath($shorePen, $island)
$gfx.DrawPath($shorePen, $isletPath)

# ---------------------------------------------------------------- towns
function Draw-Town($cx, $cy, $size) {
	$glow = New-Object System.Drawing.SolidBrush (New-Colour "F5B95C" 48)
	$gfx.FillEllipse($glow, [float]($cx - $size * 2.1), [float]($cy - $size * 2.1), [float]($size * 4.2), [float]($size * 4.2))
	$glow.Dispose()
	$br = New-Object System.Drawing.SolidBrush $Town
	$gfx.FillEllipse($br, [float]($cx - $size), [float]($cy - $size), [float]($size * 2), [float]($size * 2))
	$br.Dispose()
	$core = New-Object System.Drawing.SolidBrush $TownCore
	$gfx.FillEllipse($core, [float]($cx - $size * 0.38), [float]($cy - $size * 0.38), [float]($size * 0.76), [float]($size * 0.76))
	$core.Dispose()
}

# One trunk road from the tail up to the neck, with a couple of branches. It
# follows the spine, which is the only route the island really offers.
$towns = @(
	@(430, 925), @(640, 945), @(850, 928), @(1040, 890), @(1190, 810),
	@(1290, 690), @(1350, 560), @(1400, 450),
	@(1380, 850), @(1150, 985), @(1395, 1000), @(1560, 608)
)
$roads = @(
	@(0, 1), @(1, 2), @(2, 3), @(3, 4), @(4, 5), @(5, 6), @(6, 7),
	@(4, 8), @(4, 9), @(8, 10), @(6, 11)
)
$roadPen = New-Object System.Drawing.Pen $Road, 2.4
foreach ($r in $roads) {
	$p = $towns[$r[0]]
	$q = $towns[$r[1]]
	$gfx.DrawLine($roadPen, [float]$p[0], [float]($p[1] + $OffY), [float]$q[0], [float]($q[1] + $OffY))
}
foreach ($t in $towns) { Draw-Town $t[0] ($t[1] + $OffY) 11.0 }

# The eye: a town like any other, it just happens to sit in the right place.
Draw-Town 1478 (338 + $OffY) 12.0

# ---------------------------------------------------------------- title
# Scrim first, so the type stays legible over whatever the map does.
# Drawn one pixel taller than it is filled, and tile-flipped: a plain gradient
# brush leaves a visible seam at its own edge.
$scrimRect = New-Object System.Drawing.Rectangle 0, -1, $W, 362
$scrim = New-Object System.Drawing.Drawing2D.LinearGradientBrush $scrimRect, (New-Colour "0A1218" 215), (New-Colour "0A1218" 0), 90.0
$scrim.WrapMode = [System.Drawing.Drawing2D.WrapMode]::TileFlipXY
$gfx.FillRectangle($scrim, 0, 0, $W, 360)

# The title, with "Map generator" under the rule to say what the mod is. Sized
# so the two of them together still sit inside the scrim.
$titleFont = New-Object System.Drawing.Font "Segoe UI", 132, ([System.Drawing.FontStyle]::Bold), ([System.Drawing.GraphicsUnit]::Pixel)
$inkBrush = New-Object System.Drawing.SolidBrush $Ink

$titleText = "MAPZILLA"
$titleX = 104.0
$titleY = 74.0
$gfx.DrawString($titleText, $titleFont, $inkBrush, $titleX, $titleY)

# Accent rule under the title. Measured rather than placed by hand, so it
# stays put if the title or its size changes.
$titleSize = $gfx.MeasureString($titleText, $titleFont)
$rulePen = New-Object System.Drawing.Pen $Accent, 8
$ruleY = $titleY + $titleSize.Height - 18
$gfx.DrawLine($rulePen, [float]($titleX + 8), [float]$ruleY, [float]($titleX + 8 + 260), [float]$ruleY)

# Subtitle, hung off the rule rather than placed by hand for the same reason.
$subFont = New-Object System.Drawing.Font "Segoe UI", 46, ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Pixel)
$subBrush = New-Object System.Drawing.SolidBrush (New-Colour "F6F3EC" 225)
$gfx.DrawString("Map generator", $subFont, $subBrush, [float]($titleX + 4), [float]($ruleY + 14))

Write-Host ("  title {0:N0} x {1:N0} px, ends at x={2:N0}" -f $titleSize.Width, $titleSize.Height, ($titleX + $titleSize.Width))

# ---------------------------------------------------------------- save
$dir = Split-Path -Parent $OutFile
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
$resolved = Join-Path (Resolve-Path $dir).Path (Split-Path -Leaf $OutFile)
$bmp.Save($resolved, [System.Drawing.Imaging.ImageFormat]::Png)

$gfx.Dispose()
$bmp.Dispose()
Write-Host "Wrote $resolved (${W}x${H})"
