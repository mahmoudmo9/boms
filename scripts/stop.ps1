# Stop the BOMS backend and worker.
# Compatible with Windows PowerShell 5.1.
. "$PSScriptRoot\common.ps1"

Write-Step 'Stopping BOMS'
Stop-BomsProcesses
Write-Ok 'Stopped'
