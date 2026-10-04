<#
.SYNOPSIS
Rebuilds the generators and copies the mod into the Transport Fever 3 user mods
or staging area folder.

.DESCRIPTION
Run after every edit, then restart the game - mods are read at startup.

Two destinations, and the difference matters:

  mods\          what the game loads for normal play. The default.
  staging_area\  what the in-game mod manager can publish from. Publishing
                 only ever looks here, so a mod that lives in mods\ cannot be
                 uploaded.

A deploy to staging_area\ keeps that folder's _metadata\mod.io_fileid.txt,
which is the game's record of the mod.io entry this mod belongs to. Lose it and
the next publish creates a new entry rather than updating the published one.

.PARAMETER Staging
Deploy to staging_area\ instead of mods\, ready to publish.

.PARAMETER NoBuild
Skip tools\build.py and deploy the generators as they are on disk.

.EXAMPLE
.\deploy.ps1
.EXAMPLE
.\deploy.ps1 -Staging
#>
[CmdletBinding()]
param(
	[switch]$Staging,
	[switch]$NoBuild
)

$ErrorActionPreference = "Stop"

$ModId = "mapzilla_1"
$Source = Join-Path $PSScriptRoot "mod\$ModId"

if (-not (Test-Path $Source)) {
	throw "Mod source not found: $Source"
}

# The generators are derived from the installed game's own node trees, so
# rebuild them first: a deploy should never ship a tree built against an older
# patch. The build validates each tree and writes nothing if one fails.
if (-not $NoBuild) {
	python (Join-Path $PSScriptRoot "tools\build.py")
	if ($LASTEXITCODE -ne 0) { throw "Build failed; nothing deployed." }
}

$Folder = if ($Staging) { "staging_area" } else { "mods" }

# Transport Fever 3 is Steam appid 3493540. The per-account userdata folder
# holds both destinations side by side.
$Local = Get-ChildItem "C:\Program Files (x86)\Steam\userdata\*\3493540\local" -Directory -ErrorAction SilentlyContinue |
	Select-Object -First 1

if (-not $Local) {
	throw "Could not find the TF3 userdata folder. Launch the game once, then retry."
}

$TargetRoot = Join-Path $Local.FullName $Folder
if (-not (Test-Path $TargetRoot)) {
	New-Item -ItemType Directory -Force $TargetRoot | Out-Null
}

$Target = Join-Path $TargetRoot $ModId

# When the mod manager publishes, the game writes the mod.io entry's id into
# _metadata\mod.io_fileid.txt inside the staging folder. That file is the only
# record of which entry this mod is - it is not in the repo, and nothing else
# on disk holds it - and the next publish reads it to know what to update. A
# deploy that wipes the folder therefore costs the mod its identity: the game
# finds no id, and publishes a second, empty mod.io entry beside the live one
# instead of updating it. So it is carried across the wipe.
$IdFile = Join-Path $Target "_metadata\mod.io_fileid.txt"
$KeptId = if (Test-Path $IdFile) { Get-Content -Raw $IdFile } else { $null }

if (Test-Path $Target) { Remove-Item -Recurse -Force $Target -Confirm:$false }
Copy-Item -Recurse $Source $Target

if ($KeptId) {
	Set-Content -Path $IdFile -Value $KeptId -NoNewline -Encoding ascii
	Write-Host "Kept mod.io id $($KeptId.Trim())"
}

Write-Host "Deployed to $Target"
Write-Host "Log: $(Join-Path $Local.FullName 'crash_dump\stdout.txt')"
