param(
    [Parameter(Mandatory=$true)][string]$InstallScript,
    [Parameter(Mandatory=$true)][string]$StageRoot,
    [Parameter(Mandatory=$true)][string]$ResultPath,
    [switch]$ExistingConfig,
    [switch]$ForceConfig,
    [switch]$InvalidExistingConfig
)
$ErrorActionPreference = 'Stop'
$script:Events = [System.Collections.Generic.List[string]]::new()
$script:Validated = $false
$script:OriginalWriteEnv = $null
$script:Notes = [System.Collections.Generic.List[string]]::new()
$stageFull = [System.IO.Path]::GetFullPath($StageRoot)
if (Test-Path -LiteralPath $stageFull) { throw 'Owned staging directory must be new' }
New-Item -ItemType Directory -Path $stageFull | Out-Null
$ScriptDir = $stageFull
$LogFile = Join-Path $ScriptDir 'install.log'
$GamesDir = Join-Path $ScriptDir 'synthetic-games'
New-Item -ItemType Directory -Path $GamesDir | Out-Null
$LibraryRoots = "Synthetic=$GamesDir"
$Port = '6120'
$DbName = 'oneirodex_installer_test'
$TestDbName = 'oneirodex_installer_tests'
$SkipDb = $true
$Dev = $false
$Force = [bool]$ForceConfig
$script:InstallStage = 0
$envPath = Join-Path $ScriptDir '.env'
$priorSecret = 'synthetic-r2053-retained-secret-not-production'
if ($ExistingConfig) {
    $storedSecret = if ($InvalidExistingConfig) { '' } else { $priorSecret }
    Set-Content -LiteralPath $envPath -Encoding utf8 -Value @(
        'DATABASE_URL=postgresql://review:synthetic@127.0.0.1:1/oneirodex_installer_test',
        "SECRET_KEY=$storedSecret",
        'PORT=5006',
        'ONEIRODEX_OPERATOR_TEST_FLAG=preserve-me'
    )
}
$priorHash = if ($ExistingConfig) { (Get-FileHash -LiteralPath $envPath -Algorithm SHA256).Hash } else { $null }
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $InstallScript).Path, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count) { throw 'Installer AST parse failed' }
foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -is [System.Management.Automation.Language.FunctionDefinitionAst]) {
        . ([scriptblock]::Create($statement.Extent.Text))
    }
}
$script:OriginalWriteEnv = ${function:Write-EnvFile}
$script:OriginalShowSummary = ${function:Show-Summary}
$script:OriginalWriteNote = ${function:Write-Note}
function Test-Prerequisites { $script:Events.Add('prerequisites-stub') }
function New-Databases {
    $script:Events.Add('database-stub')
    return 'postgresql://review:synthetic@127.0.0.1:1/oneirodex_installer_test'
}
function Install-PythonEnvironment { $script:Events.Add('python-dependencies-stub') }
function Install-NativeSpas { $script:Events.Add('spa-build-stub') }
function Write-EnvFile([string]$DatabaseUrl) {
    $script:Events.Add('configuration-real-writer')
    & $script:OriginalWriteEnv $DatabaseUrl
}
function Test-NativeRuntime {
    $script:Events.Add('runtime-validation-precondition')
    if (-not (Test-Path -LiteralPath $envPath)) {
        throw 'SYNTHETIC_CONFIG_MISSING_AT_VALIDATION'
    }
    $values = @{}
    foreach ($line in (Get-Content -LiteralPath $envPath -Encoding utf8)) {
        if ($line -match '^([A-Z_]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
    }
    if ([string]::IsNullOrWhiteSpace($values['SECRET_KEY'])) {
        throw 'SYNTHETIC_SECRET_MISSING_AT_VALIDATION'
    }
    $expectedPort = if ($ExistingConfig -and -not $Force) { '5006' } else { $Port }
    if ($values['PORT'] -ne $expectedPort) { throw 'SYNTHETIC_UPDATED_CONFIG_NOT_VALIDATED' }
    if ($ExistingConfig -and $values['SECRET_KEY'] -ne $priorSecret) {
        throw 'SYNTHETIC_EXISTING_SECRET_CHANGED'
    }
    $script:Validated = $true
}
function Write-Note([string]$Message) {
    $script:Notes.Add($Message)
    & $script:OriginalWriteNote $Message
}
function Read-Host([string]$Prompt) { return 'n' }
function Show-Summary {
    $script:Events.Add('summary-without-app-launch')
    & $script:OriginalShowSummary
}
$main = $ast.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.TryStatementAst]
} | Select-Object -Last 1
if ($null -eq $main) { throw 'Installer main try body not found' }
$mainBody = $main.Body.Extent.Text
$failure = $null
try {
    # Execute the installer's actual ordered body. Only expensive/system/launch
    # phases are stubbed; configuration uses the real writer above.
    . ([scriptblock]::Create($mainBody.Substring(1, $mainBody.Length - 2)))
}
catch {
    $failure = $_.Exception.Message
}
if (-not $failure -and $ExistingConfig -and -not $Force -and (Get-FileHash -LiteralPath $envPath -Algorithm SHA256).Hash -ne $priorHash) {
    $failure = 'SYNTHETIC_EXISTING_CONFIG_OVERWRITTEN'
}
$backups = @(Get-ChildItem -LiteralPath $ScriptDir -Filter '.env.backup.*' -File)
$result = @{
    existing_config = [bool]$ExistingConfig
    force_config = [bool]$ForceConfig
    existing_bytes_preserved = if ($ExistingConfig) { (Get-FileHash -LiteralPath $envPath -Algorithm SHA256).Hash -eq $priorHash } else { $null }
    events = @($script:Events)
    validated = $script:Validated
    failure = $failure
    generated_config_exists = Test-Path -LiteralPath $envPath
    backup_count = $backups.Count
    backup_matches_prior = if ($ExistingConfig -and $backups.Count -eq 1) { (Get-FileHash -LiteralPath $backups[0].FullName -Algorithm SHA256).Hash -eq $priorHash } else { $null }
    summary_mentions_requested_port = [bool](@($script:Notes | Where-Object { $_.Contains('http://localhost:6120') }).Count)
    summary_mentions_requested_games = [bool](@($script:Notes | Where-Object { $_.Contains($GamesDir) }).Count)
    summary_preserved_notice = [bool](@($script:Notes | Where-Object { $_ -match '(?i)preserv' }).Count)
    system_installation_performed = $false
    database_connection_attempted = $false
    app_launched = $false
    source_script_sha256 = (Get-FileHash -LiteralPath $InstallScript -Algorithm SHA256).Hash.ToLowerInvariant()
}
if (Test-Path -LiteralPath $envPath) {
    $result.config_sha256 = (Get-FileHash -LiteralPath $envPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ResultPath -Encoding utf8
if ($failure -or -not $script:Validated) { exit 1 }
exit 0
