# Stop the BOMS backend and worker.
# Compatible with Windows PowerShell 5.1.
. "$PSScriptRoot\common.ps1"

Write-Step 'Stopping BOMS'
$alive = @(Stop-BomsProcesses)
if ($alive.Count -gt 0) { Stop-WithError "Still running: $(Format-ProcessList $alive)" }
Write-Ok 'Stopped'
