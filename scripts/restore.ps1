# Disaster recovery onto a CLEAN PC: installs BOMS and restores database + files from a backup folder.
# The backup folder is the "backups" folder of the old data folder (or the secondary copy):
# it contains db\boms_*.dump (+ .manifest.json) and files\.
#   restore.bat E:\BOMS-Backup
# Compatible with Windows PowerShell 5.1.
param([Parameter(Mandatory = $true)][string]$BackupDir)

. "$PSScriptRoot\common.ps1"

if (-not (Test-Path (Join-Path $BackupDir 'db'))) {
    Stop-WithError "$BackupDir does not look like a BOMS backup folder (no db\ subfolder)."
}
& "$PSScriptRoot\install.ps1" -RestoreFrom (Resolve-Path $BackupDir).Path
