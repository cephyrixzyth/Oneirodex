<#
.SYNOPSIS
    Oneirodex Windows Installer v1.0

.DESCRIPTION
    Sets up a native (non-Docker) Oneirodex install on Windows: virtual
    environment, Python dependencies, PostgreSQL databases, and a .env with a
    generated SECRET_KEY.

    Prerequisites are checked, not silently installed. Python and PostgreSQL
    are system-wide changes that ask for elevation, so the script prints the
    exact winget command and stops rather than deciding for you.

.PARAMETER GamesDir
    Folder holding your games. Prompted for when omitted.

.PARAMETER LibraryRoots
    Extra scan locations, pipe-separated, each optionally prefixed "Label=".
    A mapped drive letter is per-user and disappears under a service account —
    prefer the UNC path. See docs/runbooks/remote-scan-locations.md

.PARAMETER Port
    Port to serve on. Default 5006.

.PARAMETER SkipDb
    Do not create databases; use an existing one.

.PARAMETER Dev
    Also install requirements-dev.txt when present.

.PARAMETER Force
    Overwrite an existing .env / config.py instead of backing off.

.EXAMPLE
    .\install-windows.ps1

.EXAMPLE
    .\install-windows.ps1 -GamesDir 'D:\Games' -LibraryRoots 'NAS ROMs=\\nas\roms|Archive=E:\archive'
#>

[CmdletBinding()]
param(
    [string]$GamesDir = '',
    [string]$LibraryRoots = '',
    [string]$Port = '5006',
    [switch]$SkipDb,
    [switch]$Dev,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile = Join-Path $ScriptDir 'install.log'
$DbName = 'oneirodex'
$TestDbName = 'oneirodextest'
$script:InstallStage = 0

function Write-Log([string]$Message) {
    "{0}: {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message | Add-Content -Path $LogFile -Encoding utf8
}

function Write-Step([string]$Message) {
    $script:InstallStage++
    Write-Host ("`n  QUEST {0:D2}  //  FIELD LOG" -f $script:InstallStage) -ForegroundColor DarkYellow
    Write-Host "  ONEI > $Message" -ForegroundColor Cyan
    Write-Log "STEP: $Message"
}
function Write-Ok([string]$Message)      { Write-Host "  [+] $Message" -ForegroundColor Green;  Write-Log "SUCCESS: $Message" }
function Write-Fail([string]$Message)    { Write-Host "  [!] $Message" -ForegroundColor Red;    Write-Log "ERROR: $Message" }
function Write-Warn([string]$Message)    { Write-Host "  [!] $Message" -ForegroundColor Yellow; Write-Log "WARNING: $Message" }
function Write-Note([string]$Message)    { Write-Host "  [.] $Message" -ForegroundColor Cyan;   Write-Log "INFO: $Message" }

function Write-Header {
    Clear-Host
    Write-Host '+--------------------------------------------------------------------+' -ForegroundColor DarkGreen
    Write-Host '|  Oneirodex  //  EXPEDITION DECK                         WINDOWS   |' -ForegroundColor Green
    Write-Host '|  QUEST LOG / INSTALLATION                                      [*] |' -ForegroundColor DarkYellow
    Write-Host '+--------------------------------------------------------------------+' -ForegroundColor DarkGreen
    $oneiArt = @'
                         .-""""-.
                        /  .--.  \
                       |  (o  o)  |
                       |    v     |     ONEI
                        \  ____  /      map scout - keeper of the lantern
                       .-|      |-.
                      /  |  []  |  \    field kit: d20 - radio - spare key
                     /___|______|___\
                          /    \
                         /______\
'@
    Write-Host $oneiArt -ForegroundColor Green
    Write-Host ''
    Write-Host '  A little old-world magic. A well-stocked field terminal.' -ForegroundColor Gray
    Write-Host ''
}

function Get-CommandPath([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Test-Prerequisites {
    Write-Step 'Checking prerequisites...'

    $python = Get-CommandPath 'python'
    if ($null -eq $python) {
        Write-Fail 'Python 3.11+ was not found on PATH.'
        Write-Note 'Install it, then re-run this script:'
        Write-Note '  winget install --id Python.Python.3.12 --source winget'
        Write-Note 'Tick "Add python.exe to PATH" if you use the python.org installer.'
        throw 'Python is required'
    }

    $version = (& python -c 'import sys; print("%d.%d" % sys.version_info[:2])').Trim()
    Write-Ok "Python $version at $python"

    if ($SkipDb) {
        Write-Note 'Skipping PostgreSQL check (-SkipDb)'
        return
    }

    $psql = Get-CommandPath 'psql'
    if ($null -eq $psql) {
        # The installer does not add psql to PATH; look where it actually lands
        # before telling the operator to go and install something they have.
        $candidate = Get-ChildItem 'C:\Program Files\PostgreSQL' -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName 'bin\psql.exe' } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1

        if ($candidate) {
            $env:PATH = "$(Split-Path -Parent $candidate);$env:PATH"
            $psql = $candidate
        }
    }

    if ($null -eq $psql) {
        Write-Fail 'PostgreSQL 17+ was not found.'
        Write-Note 'Install it, then re-run this script:'
        Write-Note '  winget install --id PostgreSQL.PostgreSQL.17 --source winget'
        Write-Note 'Or run with -SkipDb and point DATABASE_URL at an existing server.'
        throw 'PostgreSQL is required'
    }
    Write-Ok "PostgreSQL client at $psql"
}

function New-Databases {
    if ($SkipDb) {
        Write-Note 'Skipping database creation (-SkipDb)'
        return 'postgresql://postgres:postgres@localhost:5432/oneirodex'
    }

    Write-Step 'Creating databases...'
    Write-Note 'Enter the password for the PostgreSQL "postgres" superuser.'
    Write-Note 'It is used to create the databases and is written to .env only.'
    $secure = Read-Host -Prompt 'postgres password' -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

    $env:PGPASSWORD = $plain
    try {
        foreach ($database in @($DbName, $TestDbName)) {
            $exists = & psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='$database'"
            if ($exists -eq '1') {
                Write-Note "Database already exists: $database"
            }
            else {
                & createdb -U postgres -h localhost $database
                if ($LASTEXITCODE -ne 0) { throw "Could not create database $database" }
                Write-Ok "Database created: $database"
            }
        }
    }
    finally {
        # Do not leave the password in the environment of anything this shell
        # launches next.
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }

    $encoded = [uri]::EscapeDataString($plain)
    return "postgresql://postgres:$encoded@localhost:5432/$DbName"
}

function Install-PythonEnvironment {
    Write-Step 'Setting up Python virtual environment...'
    $venv = Join-Path $ScriptDir 'venv'

    if (-not (Test-Path $venv)) {
        & python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment' }
        Write-Ok 'Virtual environment created'
    }
    else {
        Write-Note 'Using existing virtual environment'
    }

    $venvPython = Join-Path $venv 'Scripts\python.exe'
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r (Join-Path $ScriptDir 'requirements.txt') --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install Python dependencies' }
    Write-Ok 'Python dependencies installed'

    $devRequirements = Join-Path $ScriptDir 'requirements-dev.txt'
    if ($Dev -and (Test-Path $devRequirements)) {
        & $venvPython -m pip install -r $devRequirements --quiet
        Write-Ok 'Development dependencies installed'
    }
}

function Test-ScanLocations([string]$Roots) {
    # Warn, never fail: a share can legitimately be offline at install time.
    if ([string]::IsNullOrWhiteSpace($Roots)) { return }
    foreach ($entry in $Roots.Split('|')) {
        $path = $entry
        $separator = $entry.IndexOf('=')
        if ($separator -ge 0 -and $entry.Substring(0, $separator) -notmatch '[\\/]') {
            $path = $entry.Substring($separator + 1)
        }
        $path = $path.Trim()
        if ([string]::IsNullOrWhiteSpace($path)) { continue }

        if (Test-Path $path) {
            Write-Ok "Scan location found: $path"
        }
        else {
            Write-Warn "Scan location not reachable yet: $path"
        }
        if ($path -match '^[A-Za-z]:\\' -and (Get-PSDrive -Name $path.Substring(0,1) -ErrorAction SilentlyContinue).DisplayRoot) {
            Write-Warn "  $path is a mapped drive. Mapped drives are per-user and vanish under a service account - use the UNC path instead."
        }
    }
}

function Write-EnvFile([string]$DatabaseUrl) {
    Write-Step 'Writing configuration...'

    $envPath = Join-Path $ScriptDir '.env'
    $existingSecretKey = $null
    if (Test-Path $envPath) {
        $backup = "$envPath.backup.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item $envPath $backup
        Write-Ok "Existing .env backed up to $(Split-Path -Leaf $backup)"
        $secretLine = Get-Content $envPath | Where-Object { $_ -match '^SECRET_KEY=' } | Select-Object -First 1
        if ($secretLine) { $existingSecretKey = $secretLine.Substring('SECRET_KEY='.Length) }
    }

    $secretKey = $existingSecretKey
    if ([string]::IsNullOrWhiteSpace($secretKey)) {
        $secretKey = (& python -c 'import secrets; print(secrets.token_urlsafe(64))').Trim()
    }
    $testUrl = $DatabaseUrl -replace "/$DbName`$", "/$TestDbName"
    $uploadFolder = (Join-Path $ScriptDir 'oneirodex\static\library')
    $devMode = if ($Dev) { 'true' } else { 'false' }

    $lines = @(
        "# Oneirodex Configuration - Generated by install-windows.ps1 $(Get-Date)",
        '',
        '# Database connection',
        "DATABASE_URL=$DatabaseUrl",
        "TEST_DATABASE_URL=$testUrl",
        '',
        '# Game files directory',
        "DATA_FOLDER_GAMES=$GamesDir",
        '',
        '# Extra scan locations: UNC shares, second disks, anything else this',
        '# machine can open. Pipe-separated, optional "Label=" prefix. Prefer UNC',
        '# paths over mapped drive letters - a mapped drive is per-user.',
        '# See docs/runbooks/remote-scan-locations.md',
        "ONEIRODEX_LIBRARY_ROOTS=$LibraryRoots",
        '',
        '# Base folders for path resolution',
        'BASE_FOLDER_WINDOWS=C:\',
        '',
        '# Flask secret key (keep this secure!)',
        "SECRET_KEY=$secretKey",
        '',
        '# Upload directory for cover images and zips',
        "UPLOAD_FOLDER=$uploadFolder",
        '',
        "PORT=$Port",
        "DEV_MODE=$devMode",
        '',
        '# Local HTTP - set both true once Oneirodex sits behind HTTPS',
        'SESSION_COOKIE_SECURE=false',
        'REMEMBER_COOKIE_SECURE=false'
    )

    Set-Content -Path $envPath -Value $lines -Encoding utf8
    Write-Ok 'Environment configuration created'
}

function Show-Summary {
    Write-Host ''
    Write-Host '+--------------------------------------------------------------------+' -ForegroundColor Green
    Write-Host '|  QUEST COMPLETE  //  THE DECK IS READY                            |' -ForegroundColor Green
    Write-Host '+--------------------------------------------------------------------+' -ForegroundColor Green
    Write-Host '  ONEI > Your worlds are waiting at the gate.' -ForegroundColor Cyan
    Write-Host ''
    Write-Note "Launch gate:     http://localhost:$Port"
    Write-Note "Game cache:      $GamesDir"
    if (-not [string]::IsNullOrWhiteSpace($LibraryRoots)) {
        Write-Note "Trail markers:   $LibraryRoots"
    }
    Write-Note 'Start command:   .\startweb_windows.cmd'
    Write-Note 'Reset database:  .\startweb_windows.cmd --force-setup'
    Write-Note 'Run as service:  docs/runbooks/install-native.md (Windows)'
    Write-Note "Log File:        $LogFile"
    Write-Host ''

    $answer = Read-Host 'Start Oneirodex now? [Y/n]'
    if ([string]::IsNullOrWhiteSpace($answer) -or $answer -match '^[Yy]') {
        Write-Note "Opening the launch gate - http://localhost:$Port"
        & (Join-Path $ScriptDir 'startweb_windows.cmd')
    }
    else {
        Write-Note 'To start Oneirodex later, run: .\startweb_windows.cmd'
    }
}

# ---------------------------------------------------------------- main

"Oneirodex Windows Installer - $(Get-Date)" | Set-Content -Path $LogFile -Encoding utf8
Write-Header

Write-Note 'This installer will:'
Write-Note '  - Check for Python and PostgreSQL 17'
Write-Note '  - Create the oneirodex databases'
Write-Note '  - Set up a Python virtual environment'
Write-Note '  - Write .env (games folder, scan locations, secret key)'
Write-Host ''

try {
    Test-Prerequisites

    if ([string]::IsNullOrWhiteSpace($GamesDir)) {
        $default = 'C:\Games'
        $answer = Read-Host "Games directory path [$default]"
        if ([string]::IsNullOrWhiteSpace($answer)) { $GamesDir = $default } else { $GamesDir = $answer }
    }

    if (-not (Test-Path $GamesDir)) {
        Write-Warn "Games directory does not exist: $GamesDir"
        $answer = Read-Host 'Create this directory? [Y/n]'
        if ([string]::IsNullOrWhiteSpace($answer) -or $answer -match '^[Yy]') {
            New-Item -ItemType Directory -Path $GamesDir -Force | Out-Null
            Write-Ok "Created $GamesDir"
        }
        else {
            Write-Warn 'Update DATA_FOLDER_GAMES in .env before your first scan'
        }
    }
    else {
        Write-Ok "Games directory exists: $GamesDir"
    }

    if ([string]::IsNullOrWhiteSpace($LibraryRoots)) {
        Write-Host ''
        Write-Note "Extra scan locations beyond $GamesDir (optional)."
        Write-Note 'UNC shares work directly - e.g. NAS ROMs=\\nas\roms'
        Write-Note 'Separate several with a pipe character. Leave blank for none.'
        $LibraryRoots = Read-Host 'Extra scan locations'
        if ($null -eq $LibraryRoots) { $LibraryRoots = '' }
    }
    Test-ScanLocations $LibraryRoots

    $databaseUrl = New-Databases
    Install-PythonEnvironment
    Write-EnvFile $databaseUrl
    Show-Summary
}
catch {
    Write-Fail $_.Exception.Message
    Write-Warn "Check the log file: $LogFile"
    exit 1
}
