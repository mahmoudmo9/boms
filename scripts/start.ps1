# Start the BOMS backend and worker (normally they start by themselves at logon).
# Compatible with Windows PowerShell 5.1.
. "$PSScriptRoot\common.ps1"

if (Test-BackendUp) { Write-Ok "BOMS is already running at http://127.0.0.1:$($script:HttpPort)"; exit 0 }
Write-Step 'Starting BOMS'
if (Start-BomsProcesses) { Write-Ok "Running at http://127.0.0.1:$($script:HttpPort)" }
else { Stop-WithError 'BOMS did not start. Check the logs folder inside the data folder.' }
