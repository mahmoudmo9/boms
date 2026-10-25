# Shared helpers for the BOMS Windows scripts. Dot-source it:  . "$PSScriptRoot\common.ps1"
# Compatible with Windows PowerShell 5.1.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:BomsRoot = 'C:\BOMS'
$script:AppDir = Join-Path $script:BomsRoot 'app'
$script:ConfigPath = Join-Path $script:BomsRoot 'config.json'
$script:VenvPython = Join-Path $script:AppDir 'venv\Scripts\python.exe'
$script:VenvPythonW = Join-Path $script:AppDir 'venv\Scripts\pythonw.exe'
$script:BackendDir = Join-Path $script:AppDir 'backend'
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

function Find-PgBin {
    $path = 'C:\Program Files\PostgreSQL\18\bin'
    if (Test-Path (Join-Path $path 'pg_dump.exe')) { return $path }
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
