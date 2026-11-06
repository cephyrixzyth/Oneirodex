# Fetch / validate WebRetro libretro WASM cores (Windows).
# Prefers Git Bash / WSL for the shell script; falls back to native PowerShell download.
#
# Usage:
#   .\scripts\fetch-webretro-cores.ps1 -Defaults
#   .\scripts\fetch-webretro-cores.ps1 -FromDir C:\path\to\built\cores
#   .\scripts\fetch-webretro-cores.ps1 -Defaults -FromDir C:\path\to\built\cores

param(
    [switch]$Defaults,
    [string]$FromDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BashScript = Join-Path $Root "scripts\fetch-webretro-cores.sh"

$bash = Get-Command bash -ErrorAction SilentlyContinue
if ($bash) {
    $args = @()
    if ($Defaults) { $args += "--defaults" }
    if ($FromDir) { $args += @("--from-dir", $FromDir) }
    if (-not $Defaults -and -not $FromDir) {
        Write-Error "Specify -Defaults and/or -FromDir <path>"
    }
    & bash $BashScript @args
    exit $LASTEXITCODE
}

# Native PowerShell fallback
$CoresDir = if ($env:WEBRETR_CORES_DIR) { $env:WEBRETR_CORES_DIR } else {
    Join-Path $Root "oneirodex\static\vendor\webretro\cores"
}
$Cdn = "https://cdn.jsdelivr.net/gh/BinBashBanana/webretro@6.5/cores"
$HashesFile = Join-Path $Root "scripts\webretro-cores.sha256"
$DefaultCores = @(
    "a5200", "freechaf", "freeintv", "gearcoleco", "genesis_plus_gx", "handy",
    "mednafen_ngp", "mednafen_psx_hw", "mednafen_vb", "mednafen_wswan", "melonds",
    "mgba", "mupen64plus_next", "neocd", "nestopia", "o2em", "opera", "parallel_n64",
    "prosystem", "snes9x", "stella2014", "vecx", "virtualjaguar", "yabause"
)

function Get-ExpectedHash([string]$Name) {
    foreach ($line in Get-Content -LiteralPath $HashesFile) {
        if (
            $line -match '^([0-9a-f]{64})  ([a-z0-9_]+_libretro\.(?:js|wasm))$' -and
            $Matches[2] -ceq $Name
        ) {
            return $Matches[1]
        }
    }
    return ""
}

if (-not $Defaults -and -not $FromDir) {
    Write-Error "Specify -Defaults and/or -FromDir <path>"
}

New-Item -ItemType Directory -Force -Path $CoresDir | Out-Null

if ($Defaults) {
    foreach ($id in $DefaultCores) {
        Write-Host "Fetching $id ..."
        $jsName = "${id}_libretro.js"
        $wasmName = "${id}_libretro.wasm"
        $jsExpected = Get-ExpectedHash $jsName
        $wasmExpected = Get-ExpectedHash $wasmName
        if ($jsExpected -notmatch '^[0-9a-f]{64}$' -or $wasmExpected -notmatch '^[0-9a-f]{64}$') {
            throw "No valid SHA-256 lock found for $id"
        }

        $jsTemp = Join-Path $CoresDir ".${jsName}.$([guid]::NewGuid().ToString('N')).part"
        $wasmTemp = Join-Path $CoresDir ".${wasmName}.$([guid]::NewGuid().ToString('N')).part"
        try {
            Invoke-WebRequest -Uri "$Cdn/$jsName" -OutFile $jsTemp
            Invoke-WebRequest -Uri "$Cdn/$wasmName" -OutFile $wasmTemp
            $jsActual = (Get-FileHash -LiteralPath $jsTemp -Algorithm SHA256).Hash.ToLowerInvariant()
            $wasmActual = (Get-FileHash -LiteralPath $wasmTemp -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($jsActual -ne $jsExpected -or $wasmActual -ne $wasmExpected) {
                throw "SHA-256 integrity check failed for $id; existing files were preserved"
            }
            Move-Item -LiteralPath $jsTemp -Destination (Join-Path $CoresDir $jsName) -Force
            Move-Item -LiteralPath $wasmTemp -Destination (Join-Path $CoresDir $wasmName) -Force
        }
        finally {
            Remove-Item -LiteralPath $jsTemp,$wasmTemp -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($FromDir) {
    if (-not (Test-Path -LiteralPath $FromDir -PathType Container)) {
        Write-Error "--FromDir is not a directory: $FromDir"
    }
    $copied = 0
    Get-ChildItem -LiteralPath $FromDir -Filter "*_libretro.wasm" | ForEach-Object {
        $id = $_.BaseName -replace "_libretro$", ""
        $js = Join-Path $FromDir "${id}_libretro.js"
        if (-not (Test-Path -LiteralPath $js)) {
            Write-Warning "Skip $id — missing matching .js"
            return
        }
        Copy-Item -Force $js (Join-Path $CoresDir "${id}_libretro.js")
        Copy-Item -Force $_.FullName (Join-Path $CoresDir "${id}_libretro.wasm")
        Write-Host "Copied $id"
        $copied++
    }
    if ($copied -eq 0) {
        Write-Error "No *_libretro.{js,wasm} pairs found in $FromDir"
    }
}

Write-Host ""
Write-Host "Cores directory: $CoresDir"
Get-ChildItem -LiteralPath $CoresDir -Filter "*_libretro.wasm" | ForEach-Object {
    $id = $_.BaseName -replace "_libretro$", ""
    Write-Host "  - $id"
}
Write-Host ""
Write-Host "Verify: curl -sS `$BASE/api/emulator/health"
Write-Host "See docs/runbooks/webretro-cores.md"
