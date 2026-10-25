# BOMS updater. Extract the new release zip, then run its update.bat.
# Stops BOMS, takes a pre_update backup (aborts if it fails), replaces the program files,
# installs the new Python packages offline, runs migrations and starts BOMS again.
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

Write-Step 'Stopping BOMS'
Stop-BomsProcesses
Write-Ok 'Stopped'

Write-Step 'Pre-update backup'
if ((Invoke-BomsCli -Arguments @('backup', '--kind', 'pre_update') -AllowFailure) -ne 0) {
    Start-BomsProcesses | Out-Null
    Stop-WithError 'The pre-update backup failed. Nothing was changed; BOMS was started again.'
}
Write-Ok 'Backup done'

Write-Step 'Replacing program files'
$moved = @()
foreach ($item in @('backend', 'scripts', 'wheelhouse', 'docs')) {
    $target = Join-Path $script:AppDir $item
    $previous = "$target.previous"
    if (Test-Path $previous) { Remove-Item -Recurse -Force $previous }
    if (Test-Path $target) { Rename-Item $target $previous; $moved += $item }
    Copy-Item -Recurse -Path (Join-Path $source $item) -Destination $target
}
Copy-Item -Force (Join-Path $source 'VERSION') (Join-Path $script:AppDir 'VERSION')
Write-Ok 'Copied'

function Undo-Update([string]$Reason) {
    Write-Warn "$Reason - restoring the previous program files"
    foreach ($item in $moved) {
        $target = Join-Path $script:AppDir $item
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Rename-Item "$target.previous" $target
    }
    Set-Content -Path (Join-Path $script:AppDir 'VERSION') -Value $oldVersion
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
Write-Ok 'Database up to date'

Write-Step 'Starting BOMS'
if (Start-BomsProcesses) { Write-Ok 'Running' } else { Write-Warn "No answer yet; check $($config.data_dir)\logs\backend.log" }
Write-Host ''
Write-Host "Updated BOMS from $oldVersion to $newVersion." -ForegroundColor Green
