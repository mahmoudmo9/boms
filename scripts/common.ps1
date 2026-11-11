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

# ---- stopping BOMS (v0.10.0 section 0.1.1) -----------------------------------------------------------------------------
# Every process that belongs to the install is stopped, not only app.launch: the server, the worker, the Setad agent
# and its browser, the bundled Claude CLI - anything whose executable or command line is under C:\BOMS\app, and every
# descendant of such a process. The script that is running (and the console that started it) is never a target.

function Get-ProcessSnapshot {
    return @(Get-CimInstance Win32_Process | ForEach-Object {
        [pscustomobject]@{ ProcessId = [int]$_.ProcessId; ParentProcessId = [int]$_.ParentProcessId; Name = $_.Name
                           ExecutablePath = $_.ExecutablePath; CommandLine = $_.CommandLine }
    })
}

function Test-UnderRoot([string]$Text, [string[]]$Roots) {
    if (-not $Text) { return $false }
    foreach ($root in $Roots) {
        $r = $root.TrimEnd('\')
        $at = $Text.IndexOf($r, [System.StringComparison]::OrdinalIgnoreCase)
        while ($at -ge 0) {
            $end = $at + $r.Length
            # C:\BOMS\app must not match C:\BOMS\app-old: the root has to end at a separator, a quote or the end
            if ($end -ge $Text.Length -or '\/" '.IndexOf($Text[$end]) -ge 0) { return $true }
            $at = $Text.IndexOf($r, $end, [System.StringComparison]::OrdinalIgnoreCase)
        }
    }
    return $false
}

function Select-BomsProcesses {
    # Pure: from a process snapshot, the processes under $Roots and all their descendants, minus $SelfId and its
    # ancestors (the running script, the .bat console around it).
    param([object[]]$Processes, [string[]]$Roots, [int]$SelfId)
    $byId = @{}
    foreach ($p in $Processes) { $byId[$p.ProcessId] = $p }
    $protected = @{}
    $cursor = $SelfId
    while ($cursor -and $byId.ContainsKey($cursor) -and -not $protected.ContainsKey($cursor)) {
        $protected[$cursor] = $true
        $cursor = $byId[$cursor].ParentProcessId
    }
    $picked = @{}
    foreach ($p in $Processes) {
        if ($protected.ContainsKey($p.ProcessId)) { continue }
        if ((Test-UnderRoot $p.ExecutablePath $Roots) -or (Test-UnderRoot $p.CommandLine $Roots)) { $picked[$p.ProcessId] = $true }
    }
    do {
        $grew = $false
        foreach ($p in $Processes) {
            if ($picked.ContainsKey($p.ProcessId) -or $protected.ContainsKey($p.ProcessId)) { continue }
            if ($picked.ContainsKey($p.ParentProcessId)) { $picked[$p.ProcessId] = $true; $grew = $true }
        }
    } while ($grew)
    return @($Processes | Where-Object { $picked.ContainsKey($_.ProcessId) })
}

function Get-BomsProcesses {
    return @(Select-BomsProcesses -Processes (Get-ProcessSnapshot) -Roots @($script:AppDir) -SelfId $PID)
}

function Stop-OneProcess([int]$Id) { Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue }

function Format-ProcessList([object[]]$Processes) {
    return (@($Processes | ForEach-Object { "$($_.Name) (PID $($_.ProcessId))" }) -join ', ')
}

function Stop-BomsProcesses {
    # Stops the scheduled tasks, then every BOMS process, and waits until they have really exited.
    # Returns the processes still alive after $TimeoutSec (an empty list is success).
    param([int]$TimeoutSec = 30)
    foreach ($name in $script:TaskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        }
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ($true) {
        $alive = @(Get-BomsProcesses)
        if ($alive.Count -eq 0) { return @() }
        if ((Get-Date) -ge $deadline) { return $alive }
        foreach ($p in $alive) { Stop-OneProcess $p.ProcessId }
        Start-Sleep -Milliseconds 500
    }
}

# ---- replacing the program folders safely ------------------------------------------------------------------------------

$script:ProgramItems = @('backend', 'scripts', 'wheelhouse', 'docs')
$script:UpdateMarker = 'update-in-progress.json'

function Rename-Folder([string]$Path, [string]$NewPath) {
    # The one place a folder is renamed (the tests replace it to simulate a lock).
    [System.IO.Directory]::Move($Path, $NewPath)
}

function Test-FolderRenamable([string]$Path) {
    # Windows refuses to rename a folder while any file in it is open or a process has it as its working folder,
    # so renaming it away and back is the exact test of "can this folder be replaced now".
    if (-not (Test-Path -LiteralPath $Path)) { return $true }
    $probe = "$Path.renametest"
    try {
        if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction Stop }
        Rename-Folder $Path $probe
    } catch {
        return $false
    }
    for ($i = 0; $i -lt 20; $i++) {
        try { Rename-Folder $probe $Path; return $true } catch { Start-Sleep -Milliseconds 250 }
    }
    throw "Could not rename $probe back to $Path. Rename it by hand before doing anything else."
}

function Wait-FoldersRenamable {
    # Retries for up to $TimeoutSec. Returns the folders that still cannot be renamed (empty = all free).
    param([string[]]$Paths, [int]$TimeoutSec = 30, [int]$DelayMs = 1000)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ($true) {
        $blocked = @($Paths | Where-Object { -not (Test-FolderRenamable $_) })
        if ($blocked.Count -eq 0 -or (Get-Date) -ge $deadline) { return $blocked }
        Start-Sleep -Milliseconds $DelayMs
    }
}

function Get-RestartManagerLockers([string[]]$Files) {
    # Windows Restart Manager: which processes hold these files open. Best effort - any failure gives an empty list.
    try {
        if (-not ('Boms.RestartManager' -as [type])) {
            Add-Type -Namespace Boms -Name RestartManager -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] public struct RM_UNIQUE_PROCESS { public int dwProcessId; public System.Runtime.InteropServices.ComTypes.FILETIME ProcessStartTime; }
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct RM_PROCESS_INFO {
    public RM_UNIQUE_PROCESS Process;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string strAppName;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string strServiceShortName;
    public int ApplicationType; public uint AppStatus; public uint TSSessionId;
    [MarshalAs(UnmanagedType.Bool)] public bool bRestartable; }
[DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)] public static extern int RmStartSession(out uint pSessionHandle, int dwSessionFlags, System.Text.StringBuilder strSessionKey);
[DllImport("rstrtmgr.dll")] public static extern int RmEndSession(uint pSessionHandle);
[DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)] public static extern int RmRegisterResources(uint pSessionHandle, uint nFiles, string[] rgsFilenames, uint nApplications, IntPtr rgApplications, uint nServices, string[] rgsServiceNames);
[DllImport("rstrtmgr.dll")] public static extern int RmGetList(uint dwSessionHandle, out uint pnProcInfoNeeded, ref uint pnProcInfo, [In, Out] RM_PROCESS_INFO[] rgAffectedApps, ref uint lpdwRebootReasons);
'@
        }
        $handle = [uint32]0
        $key = New-Object System.Text.StringBuilder 64
        if ([Boms.RestartManager]::RmStartSession([ref]$handle, 0, $key) -ne 0) { return @() }
        try {
            if ([Boms.RestartManager]::RmRegisterResources($handle, [uint32]$Files.Count, $Files, 0, [IntPtr]::Zero, 0, $null) -ne 0) { return @() }
            $needed = [uint32]0; $count = [uint32]0; $reasons = [uint32]0
            [void][Boms.RestartManager]::RmGetList($handle, [ref]$needed, [ref]$count, $null, [ref]$reasons)
            if ($needed -eq 0) { return @() }
            $infos = New-Object 'Boms.RestartManager+RM_PROCESS_INFO[]' $needed
            $count = $needed
            if ([Boms.RestartManager]::RmGetList($handle, [ref]$needed, [ref]$count, $infos, [ref]$reasons) -ne 0) { return @() }
            return @($infos | Select-Object -First $count | ForEach-Object {
                [pscustomobject]@{ ProcessId = $_.Process.dwProcessId; Name = $_.strAppName } })
        } finally {
            [void][Boms.RestartManager]::RmEndSession($handle)
        }
    } catch {
        return @()
    }
}

function Find-FolderLockers([string]$Path) {
    # Who keeps $Path busy, as far as Windows will tell: processes started from it or with it on their command line,
    # and processes holding one of its files open. A console or Explorer window that is merely "inside" the folder
    # cannot be listed by Windows; the message of the updater says so.
    $found = @{}
    try {
        foreach ($p in (Select-BomsProcesses -Processes (Get-ProcessSnapshot) -Roots @($Path) -SelfId $PID)) {
            $found[$p.ProcessId] = "$($p.Name) (PID $($p.ProcessId))"
        }
        $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
            Select-Object -First 2000 | ForEach-Object { $_.FullName })
        if ($files.Count -gt 0) {
            foreach ($p in (Get-RestartManagerLockers $files)) {
                if ($p.ProcessId -ne $PID) { $found[$p.ProcessId] = "$($p.Name) (PID $($p.ProcessId))" }
            }
        }
    } catch {
        Write-Verbose "Find-FolderLockers: $_"
    }
    return @($found.Values)
}

function Get-BackendVersion([string]$AppDir) {
    # The version of the code that is really in backend\ (VERSION can be wrong after a half-finished update).
    $file = Join-Path (Join-Path $AppDir 'backend') 'pyproject.toml'
    if (Test-Path -LiteralPath $file) {
        $match = [regex]::Match((Get-Content -LiteralPath $file -Raw), '(?m)^version\s*=\s*"([^"]+)"')
        if ($match.Success) { return $match.Groups[1].Value }
    }
    return $null
}

function Repair-HalfUpdate {
    # Brings a half-updated install back to one consistent state before a new update starts. Returns what was done.
    #  - marker left by an interrupted run of this updater: every folder it had moved is put back;
    #  - <item>\<item> (v0.9.0's updater copied the new folder INTO the old one after a failed rename): removed;
    #  - <item>.previous without <item> (stopped between rename and copy): the previous folder is put back;
    #  - VERSION that disagrees with the code in backend\: corrected.
    param([string]$AppDir, [string[]]$Items = $script:ProgramItems)
    $done = @()
    $markerPath = Join-Path $AppDir $script:UpdateMarker
    if (Test-Path -LiteralPath $markerPath) {
        $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($item in @($marker.moved)) {
            $target = Join-Path $AppDir $item
            if (Test-Path -LiteralPath "$target.previous") {
                if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop }
                Rename-Folder "$target.previous" $target
                $done += "restored $item from the interrupted update"
            }
        }
        Remove-Item -LiteralPath $markerPath -Force -ErrorAction Stop
    }
    foreach ($item in $Items) {
        $target = Join-Path $AppDir $item
        $nested = Join-Path $target $item
        if (Test-Path -LiteralPath $nested -PathType Container) {
            Remove-Item -LiteralPath $nested -Recurse -Force -ErrorAction Stop
            $done += "removed the stray copy $item\$item"
        }
        if (-not (Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath "$target.previous")) {
            Rename-Folder "$target.previous" $target
            $done += "restored $item from $item.previous"
        }
    }
    $real = Get-BackendVersion $AppDir
    $versionFile = Join-Path $AppDir 'VERSION'
    if ($real -and (Test-Path -LiteralPath $versionFile) -and ((Get-Content -LiteralPath $versionFile -Raw).Trim() -ne $real)) {
        Set-Content -LiteralPath $versionFile -Value $real
        $done += "corrected VERSION to $real (the code in backend)"
    }
    return $done
}

function Update-ProgramFiles {
    # Replaces the program folders as one step: either every folder is the new one, or (on any error) every folder is
    # the old one again and the error is thrown. A failed rename is never followed by a copy.
    param([string]$AppDir, [string]$Source, [string]$OldVersion, [string]$NewVersion, [string[]]$Items = $script:ProgramItems)
    $ErrorActionPreference = 'Stop'
    $markerPath = Join-Path $AppDir $script:UpdateMarker
    $moved = @()
    $created = @()
    try {
        foreach ($item in $Items) {
            $previous = (Join-Path $AppDir $item) + '.previous'
            if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force -ErrorAction Stop }
        }
        foreach ($item in $Items) {
            $target = Join-Path $AppDir $item
            if (Test-Path -LiteralPath $target) {
                Rename-Folder $target "$target.previous"
                $moved += $item
                $state = @{ from = $OldVersion; to = $NewVersion; moved = $moved } | ConvertTo-Json -Compress
                [System.IO.File]::WriteAllText($markerPath, $state, (New-Object System.Text.UTF8Encoding($false)))
            }
            if (Test-Path -LiteralPath $target) { throw "$target still exists after it was renamed" }
            $created += $item
            Copy-Item -LiteralPath (Join-Path $Source $item) -Destination $target -Recurse -ErrorAction Stop
        }
        Copy-Item -LiteralPath (Join-Path $Source 'VERSION') -Destination (Join-Path $AppDir 'VERSION') -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $markerPath) { Remove-Item -LiteralPath $markerPath -Force -ErrorAction Stop }
    } catch {
        $cause = $_
        Undo-ProgramFiles -AppDir $AppDir -Moved $moved -Created $created -OldVersion $OldVersion
        throw $cause
    }
    return $moved
}

function Undo-ProgramFiles {
    param([string]$AppDir, [string[]]$Moved, [string[]]$Created, [string]$OldVersion)
    foreach ($item in $Created) {
        $target = Join-Path $AppDir $item
        if (($Moved -contains $item) -or -not (Test-Path -LiteralPath "$target.previous")) {
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue }
        }
    }
    foreach ($item in $Moved) {
        $target = Join-Path $AppDir $item
        if ((Test-Path -LiteralPath "$target.previous") -and -not (Test-Path -LiteralPath $target)) { Rename-Folder "$target.previous" $target }
    }
    if ($OldVersion -and $OldVersion -ne 'unknown') { Set-Content -LiteralPath (Join-Path $AppDir 'VERSION') -Value $OldVersion }
    $markerPath = Join-Path $AppDir $script:UpdateMarker
    if (Test-Path -LiteralPath $markerPath) { Remove-Item -LiteralPath $markerPath -Force -ErrorAction SilentlyContinue }
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
