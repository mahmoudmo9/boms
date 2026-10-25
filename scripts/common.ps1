# Shared helpers for the BOMS Windows scripts. Dot-source it:  . "$PSScriptRoot\common.ps1"
# Compatible with Windows PowerShell 5.1.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# Plain strings (not Join-Path) so this file can also be loaded by the test script on non-Windows.
$script:BomsRoot = 'C:\BOMS'
$script:AppDir = "$($script:BomsRoot)\app"
$script:ConfigPath = "$($script:BomsRoot)\config.json"
$script:VenvPython = "$($script:AppDir)\venv\Scripts\python.exe"
$script:VenvPythonW = "$($script:AppDir)\venv\Scripts\pythonw.exe"
$script:BackendDir = "$($script:AppDir)\backend"
$script:PgServiceName = 'postgresql-x64-18'
$script:PgDefaultBin = 'C:\Program Files\PostgreSQL\18\bin'
$script:PgMinMajor = 18
$script:TaskNames = @('BOMS Backend', 'BOMS Worker')
$script:HttpPort = 8765

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Ok([string]$Text) { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow }

function Stop-WithError([string]$Text) {
    Write-Host ''
    Write-Host "ERROR: $Text" -ForegroundColor Red
    exit 1
}

function Get-SourceRoot {
    # Folder that contains backend\, scripts\, wheelhouse\ (the extracted release zip or C:\BOMS\app).
    return (Split-Path -Parent $PSScriptRoot)
}

function Assert-ReleaseFolder([string]$Root) {
    # install/update must run from a built release (scripts\build_release.py), not from a git checkout.
    $missing = @()
    if (-not (Test-Path (Join-Path $Root 'VERSION'))) { $missing += 'VERSION' }
    if (-not (Test-Path (Join-Path $Root 'backend\requirements.lock'))) { $missing += 'backend\requirements.lock' }
    if (-not (Test-Path (Join-Path $Root 'backend\app\static\index.html'))) { $missing += 'backend\app\static (built frontend)' }
    if (-not (Get-ChildItem -Path (Join-Path $Root 'wheelhouse') -Filter '*.whl' -ErrorAction SilentlyContinue)) {
        $missing += 'wheelhouse\*.whl (Python packages)'
    }
    if ($missing.Count -gt 0) {
        Write-Host ''
        Write-Host "ERROR: $Root is not a BOMS release folder. Missing: $($missing -join ', ')" -ForegroundColor Red
        Write-Host 'This looks like the source code (git checkout). Build the release first:' -ForegroundColor Yellow
        Write-Host '    python scripts\build_release.py      (needs Python 3.12, Node.js and internet)'
        Write-Host 'then extract dist\boms-<version>-win64.zip and run scripts\install.bat from the extracted folder.'
        exit 1
    }
}

function Get-AppVersion([string]$Root) {
    $file = Join-Path $Root 'VERSION'
    if (Test-Path $file) { return (Get-Content $file -Raw).Trim() }
    return 'unknown'
}

function Read-BomsConfig {
    if (-not (Test-Path $script:ConfigPath)) { return $null }
    return (Get-Content $script:ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Save-BomsConfig($Config) {
    New-Item -ItemType Directory -Force -Path $script:BomsRoot | Out-Null
    $json = $Config | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($script:ConfigPath, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Set-BomsEnvironment($Config) {
    # Non-secret settings for child processes (python -m app.cli ...).
    $env:BOMS_DATA_DIR = $Config.data_dir
    $env:BOMS_DB_HOST = $Config.db_host
    $env:BOMS_DB_PORT = [string]$Config.db_port
    $env:BOMS_DB_NAME = $Config.db_name
    $env:BOMS_DB_USER = $Config.db_user
    $env:BOMS_HTTP_PORT = [string]$Config.http_port
    $env:BOMS_PG_BIN = $Config.pg_bin
}

function Invoke-BomsCli {
    # Runs "python -m app.cli <args>" from the installed venv. Returns the exit code.
    param([string[]]$Arguments, [switch]$AllowFailure)
    Push-Location $script:BackendDir
    try {
        & $script:VenvPython -m app.cli @Arguments | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($code -ne 0 -and -not $AllowFailure) {
        Stop-WithError "Command failed (exit $code): python -m app.cli $($Arguments -join ' ')"
    }
    return $code
}

function New-RandomSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return ([Convert]::ToBase64String($bytes)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function ConvertFrom-SecureToPlain([System.Security.SecureString]$Secure) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Read-PasswordTwice([string]$Prompt, [int]$MinLength) {
    while ($true) {
        $first = ConvertFrom-SecureToPlain (Read-Host -AsSecureString $Prompt)
        $second = ConvertFrom-SecureToPlain (Read-Host -AsSecureString 'Repeat')
        if ($first -ne $second) { Write-Warn 'The passwords do not match. Try again.'; continue }
        if ($first.Length -lt $MinLength) { Write-Warn "Use at least $MinLength characters."; continue }
        return $first
    }
}

function Find-Python312 {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        'C:\Program Files\Python312\python.exe',
        'C:\Python312\python.exe'
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $found = & $py.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { return $found.Trim() }
    }
    return $null
}

# ---- PostgreSQL bin folder detection ----------------------------------------------
# Each probe returns a candidate bin folder (or $null); Find-PgBin tries them in order and
# accepts the first folder whose pg_dump.exe reports major version 18 or newer.

function Get-ExeDirectory([string]$CommandLine) {
    # Service ImagePath, e.g.  "C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" runservice -N ...
    if (-not $CommandLine) { return $null }
    $line = $CommandLine.Trim()
    if ($line.StartsWith('"')) {
        $end = $line.IndexOf('"', 1)
        if ($end -lt 0) { return $null }
        $exe = $line.Substring(1, $end - 1)
    } else {
        $match = [regex]::Match($line, '^(.+?\.exe)(\s|$)', 'IgnoreCase')
        if (-not $match.Success) { return $null }
        $exe = $match.Groups[1].Value
    }
    $slash = $exe.LastIndexOf('\')
    if ($slash -lt 0) { return $null }
    return $exe.Substring(0, $slash)
}

function Get-PgMajorVersion([string]$VersionText) {
    # "pg_dump (PostgreSQL) 18.1" -> 18
    $match = [regex]::Match([string]$VersionText, '\)\s*(\d+)')
    if ($match.Success) { return [int]$match.Groups[1].Value }
    return $null
}

function Get-PgBinFromEnv {
    if ($env:BOMS_PG_BIN) { return $env:BOMS_PG_BIN }
    return $null
}

function Get-PgBinFromService {
    $svc = Get-CimInstance Win32_Service -Filter "Name = '$($script:PgServiceName)'" -ErrorAction SilentlyContinue
    if ($svc) { return (Get-ExeDirectory $svc.PathName) }
    return $null
}

function Get-PgBinFromRegistry {
    $key = "HKLM:\SOFTWARE\PostgreSQL\Installations\$($script:PgServiceName)"
    $item = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
    if ($item -and $item.PSObject.Properties['Base Directory']) {
        return ($item.'Base Directory'.TrimEnd('\') + '\bin')
    }
    return $null
}

function Get-PgBinDefault { return $script:PgDefaultBin }

function Get-PgBinFromPath {
    $cmd = Get-Command pg_dump.exe -ErrorAction SilentlyContinue
    if ($cmd) { return (Split-Path -Parent $cmd.Source) }
    return $null
}

function Test-PgBinDir([string]$Dir) {
    if (-not $Dir) { return $false }
    $exe = "$($Dir.TrimEnd('\'))\pg_dump.exe"
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    try { $text = & $exe --version 2>$null } catch { return $false }
    $major = Get-PgMajorVersion $text
    return ($null -ne $major -and $major -ge $script:PgMinMajor)
}

function Find-PgBin {
    # Order: BOMS_PG_BIN, the postgresql-x64-18 service, the registry, the default folder, PATH.
    $probes = @('Get-PgBinFromEnv', 'Get-PgBinFromService', 'Get-PgBinFromRegistry', 'Get-PgBinDefault',
                'Get-PgBinFromPath')
    foreach ($probe in $probes) {
        $dir = & $probe
        if ($dir -and (Test-PgBinDir $dir)) { return $dir.TrimEnd('\') }
    }
    return $null
}

function Test-BackendUp {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "http://127.0.0.1:$($script:HttpPort)/api/health"
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Stop-BomsProcesses {
    foreach ($name in $script:TaskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        }
    }
    # Any app.launch process still running (for example started by hand).
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'app\.launch' }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

function Start-BomsProcesses {
    foreach ($name in $script:TaskNames) {
        Start-ScheduledTask -TaskName $name
    }
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-BackendUp) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}
