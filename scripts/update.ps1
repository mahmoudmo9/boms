# BOMS updater. Extract the new release zip, then run its update.bat.
# 1. stops every BOMS process and waits until they have exited;
# 2. repairs a half-finished earlier update, then checks that every program folder can be renamed
#    (if one is in use: names the program when Windows tells, changes nothing, starts BOMS again);
# 3. takes a pre_update backup (stops if it fails, nothing changed);
# 4. replaces the program folders as one step (any error puts every folder back);
# 5. installs the new Python packages offline, runs migrations and starts BOMS again.
# Compatible with Windows PowerShell 5.1.

. "$PSScriptRoot\common.ps1"

$config = Read-BomsConfig
if (-not $config) { Stop-WithError 'BOMS is not installed on this PC. Run install.bat instead.' }
$source = Get-SourceRoot
Assert-ReleaseFolder $source
if ((Resolve-Path $source).Path -eq (Resolve-Path $script:AppDir).Path) {
    Stop-WithError 'Run update.bat from the extracted NEW release folder, not from C:\BOMS\app.'
}
$oldVersion = Get-AppVersion $script:AppDir
$newVersion = Get-AppVersion $source
Write-Host "BOMS update: $oldVersion -> $newVersion" -ForegroundColor White
Set-BomsEnvironment $config

function Resume-AndStop([string]$Text) {
    # Nothing was changed: BOMS is started again and the update ends with the reason.
    Write-Step 'Starting BOMS again'
    if (Start-BomsProcesses) { Write-Ok 'Running' } else { Write-Warn 'BOMS did not answer yet; run start.bat' }
    Stop-WithError $Text
}

Write-Step 'Stopping BOMS'
$alive = @(Stop-BomsProcesses -TimeoutSec 30)
if ($alive.Count -gt 0) {
    Resume-AndStop ("These BOMS processes did not stop: $(Format-ProcessList $alive). Nothing was changed. " +
        'Restart Windows and run update.bat again.')
}
Write-Ok 'Stopped (server, worker, Setad agent and browser, Claude CLI)'

Write-Step 'Checking the install'
$repairs = @(Repair-HalfUpdate -AppDir $script:AppDir)
foreach ($line in $repairs) { Write-Warn "Repaired a half-finished earlier update: $line" }
$oldVersion = Get-AppVersion $script:AppDir
$folders = @($script:ProgramItems | ForEach-Object { Join-Path $script:AppDir $_ })
$blocked = @(Wait-FoldersRenamable -Paths $folders -TimeoutSec 30)
if ($blocked.Count -gt 0) {
    $lines = @()
    foreach ($folder in $blocked) {
        $who = @(Find-FolderLockers $folder)
        if ($who.Count -gt 0) { $lines += "  $folder  <- in use by: $($who -join ', ')" }
        else { $lines += "  $folder  <- in use (Windows does not say by what)" }
    }
    Write-Host ''
    Write-Host 'These folders are in use by another program and cannot be replaced:' -ForegroundColor Yellow
    $lines | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
    Write-Host 'Close every File Explorer window, console window, editor or antivirus scan that is inside C:\BOMS\app,' -ForegroundColor Yellow
    Write-Host 'then run update.bat again.' -ForegroundColor Yellow
    Resume-AndStop "The update did not start: $($blocked.Count) folder(s) in use. Nothing was changed."
}
Write-Ok 'Every program folder can be replaced'

Write-Step 'Pre-update backup'
if ((Invoke-BomsCli -Arguments @('backup', '--kind', 'pre_update') -AllowFailure) -ne 0) {
    Resume-AndStop 'The pre-update backup failed. Nothing was changed.'
}
Write-Ok 'Backup done'

Write-Step 'Replacing program files'
# The backup ran python from the install: make sure it has gone before the folders move.
$alive = @(Stop-BomsProcesses -TimeoutSec 15)
if ($alive.Count -gt 0) { Resume-AndStop "These processes did not stop: $(Format-ProcessList $alive). Nothing was changed." }
try {
    $moved = @(Update-ProgramFiles -AppDir $script:AppDir -Source $source -OldVersion $oldVersion -NewVersion $newVersion)
} catch {
    Write-Warn "Replacing the program files failed: $($_.Exception.Message)"
    Resume-AndStop ("The program files could not be replaced; every folder was put back and version $oldVersion " +
        'is unchanged. Close programs that use C:\BOMS\app and run update.bat again.')
}
Write-Ok 'Copied'

function Undo-Update([string]$Reason) {
    Write-Warn "$Reason - restoring the previous program files"
    Stop-BomsProcesses -TimeoutSec 15 | Out-Null
    Undo-ProgramFiles -AppDir $script:AppDir -Moved $moved -Created $script:ProgramItems -OldVersion $oldVersion
    & $script:VenvPython -m pip install --quiet --no-index --find-links (Join-Path $script:AppDir 'wheelhouse') `
        -r (Join-Path $script:BackendDir 'requirements.lock') | Out-Host
    Start-BomsProcesses | Out-Null
    Stop-WithError ("Update to $newVersion failed; version $oldVersion is running again. " +
        'If the database was already migrated, restore the pre_update backup (docs\OPERATIONS.md).')
}

Write-Step 'Installing Python packages (offline)'
& $script:VenvPython -m pip install --quiet --no-index --find-links (Join-Path $script:AppDir 'wheelhouse') `
    -r (Join-Path $script:BackendDir 'requirements.lock') | Out-Host
if ($LASTEXITCODE -ne 0) { Undo-Update 'Installing packages failed' }
Write-Ok 'Packages installed'

Write-Step 'Database migrations'
if ((Invoke-BomsCli -Arguments @('migrate') -AllowFailure) -ne 0) { Undo-Update 'Migration failed' }
Invoke-BomsCli -Arguments @('seed') | Out-Null
# v0.9.0: the readable case folders (derived from the store; a failure never blocks the update)
Invoke-BomsCli -Arguments @('folders-rebuild') -AllowFailure | Out-Null
Write-Ok 'Database up to date'

Write-Step 'Starting BOMS'
if (Start-BomsProcesses) { Write-Ok 'Running' } else { Write-Warn "No answer yet; check $($config.data_dir)\logs\backend.log" }
Write-Host ''
Write-Host "Updated BOMS from $oldVersion to $newVersion." -ForegroundColor Green
