# Manual backup (the worker also backs up nightly). Add -RestoreTest to verify the new backup.
# Compatible with Windows PowerShell 5.1.
param([switch]$RestoreTest)

. "$PSScriptRoot\common.ps1"

$config = Read-BomsConfig
if (-not $config) { Stop-WithError 'BOMS is not installed on this PC.' }
Set-BomsEnvironment $config
Write-Step 'Backing up'
Invoke-BomsCli -Arguments @('backup', '--kind', 'manual') | Out-Null
Write-Ok "Backup written to $($config.data_dir)\backups"
if ($RestoreTest) {
    Write-Step 'Restore test'
    if ((Invoke-BomsCli -Arguments @('restore-test') -AllowFailure) -ne 0) { Stop-WithError 'Restore test FAILED (details above).' }
    Write-Ok 'Restore test passed'
}
