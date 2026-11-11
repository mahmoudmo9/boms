# Tests for the updater's stop / lock-check / repair / replace logic in common.ps1 (v0.10.0 section 0.1.1).
# Plain PowerShell (no Pester needed):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\Update.Tests.ps1
# Exits 1 if any case fails. Runs on Windows PowerShell 5.1 and PowerShell 7 (any OS): processes, scheduled tasks and
# folder locks are replaced by fakes; the folders are real ones in a temporary directory.

. "$PSScriptRoot\..\common.ps1"
$ErrorActionPreference = 'Stop'
$script:failures = 0

function Assert-Equal($Expected, $Actual, [string]$Name) {
    if ("$Expected" -ne "$Actual") {
        Write-Host "FAIL  $Name : expected '$Expected', got '$Actual'" -ForegroundColor Red
        $script:failures++
    } else {
        Write-Host "ok    $Name"
    }
}

function Assert-True($Condition, [string]$Name) { Assert-Equal $true ([bool]$Condition) $Name }

function New-Proc([int]$Id, [int]$Parent, [string]$Name, [string]$Exe, [string]$Cmd) {
    return [pscustomobject]@{ ProcessId = $Id; ParentProcessId = $Parent; Name = $Name; ExecutablePath = $Exe; CommandLine = $Cmd }
}

# --- which processes belong to BOMS ------------------------------------------------------------------------------------
$app = 'C:\BOMS\app'
$snapshot = @(
    (New-Proc 4 0 'System' $null $null),
    (New-Proc 100 4 'explorer.exe' 'C:\Windows\explorer.exe' 'explorer.exe'),
    (New-Proc 200 100 'pythonw.exe' 'C:\BOMS\app\venv\Scripts\pythonw.exe' '"C:\BOMS\app\venv\Scripts\pythonw.exe" -m app.launch server'),
    (New-Proc 201 100 'pythonw.exe' 'C:\BOMS\app\venv\Scripts\pythonw.exe' '"C:\BOMS\app\venv\Scripts\pythonw.exe" -m app.launch worker'),
    (New-Proc 202 201 'python.exe' 'C:\Users\o\AppData\Local\Programs\Python\Python312\python.exe' 'python.exe -m app.connectors.setad.agent'),
    (New-Proc 203 202 'chrome.exe' 'C:\Users\o\AppData\Local\ms-playwright\chromium\chrome.exe' 'chrome.exe --user-data-dir=D:\BomsData\setad'),
    (New-Proc 204 203 'chrome.exe' 'C:\Users\o\AppData\Local\ms-playwright\chromium\chrome.exe' 'chrome.exe --type=renderer'),
    (New-Proc 205 100 'claude.exe' 'c:\boms\APP\venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe' 'claude.exe --print'),
    (New-Proc 206 100 'notepad.exe' 'C:\Windows\notepad.exe' 'notepad.exe "C:\BOMS\app\docs\OPERATIONS.md"'),
    (New-Proc 300 100 'python.exe' 'C:\Python312\python.exe' 'python.exe other_project.py'),
    (New-Proc 301 100 'pythonw.exe' 'C:\BOMS\app-old\venv\Scripts\pythonw.exe' '"C:\BOMS\app-old\venv\Scripts\pythonw.exe" -m app.launch server'),
    (New-Proc 400 100 'cmd.exe' 'C:\Windows\System32\cmd.exe' 'cmd.exe /c "C:\BOMS\app\scripts\stop.bat"'),
    (New-Proc 401 400 'powershell.exe' 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' 'powershell.exe -File "C:\BOMS\app\scripts\stop.ps1"'),
    (New-Proc 402 401 'conhost.exe' 'C:\Windows\System32\conhost.exe' 'conhost.exe')
)
$picked = @(Select-BomsProcesses -Processes $snapshot -Roots @($app) -SelfId 401 | ForEach-Object { $_.ProcessId } | Sort-Object)
Assert-Equal '200 201 202 203 204 205 206' ($picked -join ' ') 'server, worker, agent, browser tree, Claude CLI and a program opened on an install file are stopped'
Assert-True (-not ($picked -contains 401) -and -not ($picked -contains 400)) 'the running script and the console that started it are never stopped'
Assert-True (-not ($picked -contains 300) -and -not ($picked -contains 301)) 'other Python programs and C:\BOMS\app-old are left alone'
Assert-True (Test-UnderRoot 'C:\BOMS\app' @('C:\BOMS\app\')) 'a root with a trailing slash matches the folder itself'
Assert-True (-not (Test-UnderRoot 'D:\x\C:\BOMS\apple.exe' @($app))) 'a longer name is not a match'

# --- stopping waits until the processes have exited ---------------------------------------------------------------------
function Get-ScheduledTask { param($TaskName, $ErrorAction) return $null }
$script:fakeProcs = @(); $script:kills = @(); $script:survives = @{}
function Get-ProcessSnapshot { return @($script:fakeProcs) }
function Stop-OneProcess([int]$Id) {
    $script:kills += $Id
    if ($script:survives.ContainsKey($Id)) {
        $script:survives[$Id]--
        if ($script:survives[$Id] -ge 0) { return }
    }
    $script:fakeProcs = @($script:fakeProcs | Where-Object { $_.ProcessId -ne $Id })
}
$script:AppDir = $app
$script:fakeProcs = @($snapshot | Where-Object { $_.ProcessId -in 200, 201, 300 })
$script:survives = @{ 201 = 2 }                      # the worker needs three attempts (it is finishing a job)
$alive = @(Stop-BomsProcesses -TimeoutSec 20)
Assert-Equal 0 $alive.Count 'Stop-BomsProcesses returns nothing alive once every process has exited'
Assert-Equal 3 (@($script:kills | Where-Object { $_ -eq 201 }).Count) 'a slow process is retried until it is gone'
Assert-Equal '300' (($script:fakeProcs | ForEach-Object { $_.ProcessId }) -join ' ') 'unrelated processes survive'
$script:fakeProcs = @($snapshot | Where-Object { $_.ProcessId -in 200, 205 }); $script:survives = @{ 205 = 100000 }
$alive = @(Stop-BomsProcesses -TimeoutSec 1)
Assert-Equal 'claude.exe (PID 205)' (Format-ProcessList $alive) 'a process that never exits is reported by name after the timeout'

# --- folders -------------------------------------------------------------------------------------------------------------
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("boms-update-test-" + [guid]::NewGuid().ToString('N'))
$realRename = ${function:Rename-Folder}
$script:locked = @{}                                  # path -> remaining failures (a large number = locked for good)
function Rename-Folder([string]$Path, [string]$NewPath) {
    if ($script:locked.ContainsKey($Path) -and $script:locked[$Path] -gt 0) {
        $script:locked[$Path]--
        throw [System.IO.IOException]::new('The process cannot access the file because it is being used by another process.')
    }
    & $realRename $Path $NewPath
}

function New-Install([string]$Name, [string]$Version) {
    # An install (or a release folder) with one marker file per program folder.
    $root = Join-Path $tmp $Name
    foreach ($item in $script:ProgramItems) {
        New-Item -ItemType Directory -Force -Path (Join-Path $root $item) | Out-Null
        Set-Content -Path (Join-Path (Join-Path $root $item) 'which.txt') -Value "$item $Version"
    }
    New-Item -ItemType Directory -Force -Path (Join-Path (Join-Path $root 'backend') 'app') | Out-Null
    Set-Content -Path (Join-Path (Join-Path $root 'backend') 'pyproject.toml') -Value "[project]`nname = `"boms`"`nversion = `"$Version`"`n"
    Set-Content -Path (Join-Path $root 'VERSION') -Value $Version
    return $root
}

function Get-Which([string]$Root, [string]$Item) {
    $file = Join-Path (Join-Path $Root $Item) 'which.txt'
    if (Test-Path $file) { return (Get-Content $file -Raw).Trim() }
    return '(missing)'
}

function Get-State([string]$Root) {
    # Every folder and file name with the content of the marker files: equal states mean "nothing was changed".
    return (@(Get-ChildItem -Path $Root -Recurse | Sort-Object FullName | ForEach-Object {
        $rel = $_.FullName.Substring($Root.Length)
        if ($_.PSIsContainer) { $rel } else { "$rel=" + (Get-Content $_.FullName -Raw).Trim() }
    }) -join '|')
}

try {
    # lock check
    $inst = New-Install 'lock' '0.9.0'
    $backend = Join-Path $inst 'backend'
    Assert-True (Test-FolderRenamable $backend) 'a free folder can be renamed (and is back in place)'
    Assert-True (Test-Path (Join-Path $backend 'which.txt')) 'the folder is where it was after the test'
    Assert-True (Test-FolderRenamable (Join-Path $inst 'not-there')) 'a folder that does not exist does not block'
    $before = Get-State $inst
    $script:locked = @{ $backend = 2 }
    $blocked = @(Wait-FoldersRenamable -Paths @($backend, (Join-Path $inst 'scripts')) -TimeoutSec 20 -DelayMs 50)
    Assert-Equal 0 $blocked.Count 'a lock that is released within the wait is not a failure (retried)'
    $script:locked = @{ $backend = 100000 }
    $blocked = @(Wait-FoldersRenamable -Paths @($backend, (Join-Path $inst 'scripts')) -TimeoutSec 1 -DelayMs 50)
    Assert-Equal $backend ($blocked -join ' ') 'a folder that stays locked is named after the timeout'
    Assert-Equal $before (Get-State $inst) 'the lock check changes nothing'

    # replace: success
    $script:locked = @{}
    $inst = New-Install 'ok' '0.9.0'; $new = New-Install 'ok-new' '0.10.0'
    New-Item -ItemType Directory -Force -Path (Join-Path $inst 'docs.previous') | Out-Null       # from the update before
    $moved = @(Update-ProgramFiles -AppDir $inst -Source $new -OldVersion '0.9.0' -NewVersion '0.10.0')
    Assert-Equal 'backend scripts wheelhouse docs' ($moved -join ' ') 'every program folder is moved'
    Assert-Equal 'backend 0.10.0|scripts 0.10.0|docs 0.10.0' ((Get-Which $inst 'backend'), (Get-Which $inst 'scripts'), (Get-Which $inst 'docs') -join '|') 'the new folders are in place'
    Assert-Equal 'backend 0.9.0' (Get-Which $inst 'backend.previous') 'the old folders are kept as .previous'
    Assert-Equal '0.10.0' (Get-AppVersion $inst) 'VERSION is the new one'
    Assert-True (-not (Test-Path (Join-Path $inst $script:UpdateMarker))) 'no marker is left after success'
    Assert-True (-not (Test-Path (Join-Path (Join-Path $inst 'backend') 'backend'))) 'no backend\backend'

    # replace: the third folder is locked -> everything is put back, and the error is thrown
    $inst = New-Install 'fail' '0.9.0'
    $before = Get-State $inst
    $script:locked = @{ (Join-Path $inst 'wheelhouse') = 100000 }
    $threw = $false
    try { Update-ProgramFiles -AppDir $inst -Source $new -OldVersion '0.9.0' -NewVersion '0.10.0' | Out-Null } catch { $threw = $true }
    Assert-True $threw 'a failed rename stops the replace step with an error'
    Assert-Equal $before (Get-State $inst) 'after a failed rename every folder and VERSION are exactly as before (no copy followed)'

    # replace: the FIRST folder is locked (the owner's case) -> nothing at all happens
    $script:locked = @{ (Join-Path $inst 'backend') = 100000 }
    $threw = $false
    try { Update-ProgramFiles -AppDir $inst -Source $new -OldVersion '0.9.0' -NewVersion '0.10.0' | Out-Null } catch { $threw = $true }
    Assert-True ($threw -and ($before -eq (Get-State $inst))) 'backend locked: nothing changed, no backend\backend'

    # replace: a copy fails (the release folder is incomplete) -> rolled back
    $script:locked = @{}
    $broken = New-Install 'broken-new' '0.10.0'
    Remove-Item -Recurse -Force (Join-Path $broken 'wheelhouse')
    $threw = $false
    try { Update-ProgramFiles -AppDir $inst -Source $broken -OldVersion '0.9.0' -NewVersion '0.10.0' | Out-Null } catch { $threw = $true }
    Assert-True ($threw -and ($before -eq (Get-State $inst))) 'a failed copy is rolled back too'

    # repair: the state the v0.9.0 updater left on the owner's PC (rename of backend failed, the script went on)
    $inst = New-Install 'half' '0.8.0'; $new9 = New-Install 'half-new' '0.9.0'
    Copy-Item -Recurse -Path (Join-Path $new9 'backend') -Destination (Join-Path $inst 'backend')       # lands INSIDE: backend\backend
    foreach ($item in @('scripts', 'wheelhouse', 'docs')) {
        & $realRename (Join-Path $inst $item) ((Join-Path $inst $item) + '.previous')
        Copy-Item -Recurse -Path (Join-Path $new9 $item) -Destination (Join-Path $inst $item)
    }
    Set-Content -Path (Join-Path $inst 'VERSION') -Value '0.9.0'
    Assert-True (Test-Path (Join-Path (Join-Path $inst 'backend') 'backend')) 'the simulated half-update has backend\backend'
    $done = @(Repair-HalfUpdate -AppDir $inst)
    Assert-True (-not (Test-Path (Join-Path (Join-Path $inst 'backend') 'backend'))) 'repair removes backend\backend'
    Assert-Equal 'backend 0.8.0' (Get-Which $inst 'backend') 'the old backend itself is untouched'
    Assert-Equal '0.8.0' (Get-AppVersion $inst) 'VERSION is corrected to the code that is really installed'
    Assert-Equal 2 $done.Count 'the repair reports what it did'
    Assert-Equal 0 (@(Repair-HalfUpdate -AppDir $inst)).Count 'a second repair finds nothing'
    $moved = @(Update-ProgramFiles -AppDir $inst -Source $new -OldVersion '0.8.0' -NewVersion '0.10.0')
    Assert-Equal 'backend 0.10.0|0.10.0' ((Get-Which $inst 'backend'), (Get-AppVersion $inst) -join '|') 'the update then runs cleanly on the repaired install'

    # repair: stopped between rename and copy (folder missing, .previous there)
    $inst = New-Install 'gap' '0.9.0'
    & $realRename (Join-Path $inst 'scripts') ((Join-Path $inst 'scripts') + '.previous')
    $done = @(Repair-HalfUpdate -AppDir $inst)
    Assert-Equal 'scripts 0.9.0' (Get-Which $inst 'scripts') 'a missing folder is restored from .previous'

    # repair: this updater was killed in the middle (marker file)
    $inst = New-Install 'killed' '0.9.0'
    $clean = Get-State $inst
    foreach ($item in @('backend', 'scripts')) { & $realRename (Join-Path $inst $item) ((Join-Path $inst $item) + '.previous') }
    Copy-Item -Recurse -Path (Join-Path $new 'backend') -Destination (Join-Path $inst 'backend')
    Set-Content -Path (Join-Path $inst $script:UpdateMarker) -Value '{"from":"0.9.0","to":"0.10.0","moved":["backend","scripts"]}'
    $done = @(Repair-HalfUpdate -AppDir $inst)
    Assert-Equal $clean (Get-State $inst) 'an interrupted update is rolled back to the old version completely'

    # a normal install after a successful update (.previous beside every folder) needs no repair
    $inst = New-Install 'normal' '0.9.0'
    foreach ($item in $script:ProgramItems) { New-Item -ItemType Directory -Force -Path ((Join-Path $inst $item) + '.previous') | Out-Null }
    Assert-Equal 0 (@(Repair-HalfUpdate -AppDir $inst)).Count 'leftover .previous folders of a successful update are not a fault'
} finally {
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
}

if ($script:failures -gt 0) { Write-Host "$($script:failures) failure(s)" -ForegroundColor Red; exit 1 }
Write-Host 'All updater tests passed.' -ForegroundColor Green
