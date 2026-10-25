# Tests for PostgreSQL bin detection in common.ps1. Plain PowerShell (no Pester needed):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\Find-PgBin.Tests.ps1
# Exits 1 if any case fails. Runs on Windows PowerShell 5.1 and PowerShell 7 (any OS):
# the probes are replaced by fakes, so no PostgreSQL install is needed.

. "$PSScriptRoot\..\common.ps1"
$ErrorActionPreference = 'Stop'
$script:failures = 0

function Assert-Equal($Expected, $Actual, [string]$Name) {
    if ($Expected -ne $Actual) {
        Write-Host "FAIL  $Name : expected '$Expected', got '$Actual'" -ForegroundColor Red
        $script:failures++
    } else {
        Write-Host "ok    $Name"
    }
}

# --- parsing helpers
$parseCases = @(
    @{ Name = 'service ImagePath (quoted)'; Expected = 'C:\Program Files\PostgreSQL\18\bin'
       Actual = { Get-ExeDirectory -CommandLine '"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" runservice -N "postgresql-x64-18" -D "C:\data"' } },
    @{ Name = 'service ImagePath (unquoted)'; Expected = 'D:\PG18\bin'
       Actual = { Get-ExeDirectory -CommandLine 'D:\PG18\bin\pg_ctl.exe runservice -N postgresql-x64-18' } },
    @{ Name = 'empty ImagePath'; Expected = $null; Actual = { Get-ExeDirectory -CommandLine '' } },
    @{ Name = 'version 18.1'; Expected = 18; Actual = { Get-PgMajorVersion -VersionText 'pg_dump (PostgreSQL) 18.1' } },
    @{ Name = 'version 16.4'; Expected = 16; Actual = { Get-PgMajorVersion -VersionText 'pg_dump (PostgreSQL) 16.4 (Ubuntu 16.4-1)' } },
    @{ Name = 'version garbage'; Expected = $null; Actual = { Get-PgMajorVersion -VersionText 'garbage' } }
)
foreach ($case in $parseCases) {
    Assert-Equal -Expected $case.Expected -Actual (& $case.Actual) -Name $case.Name
}

# --- order of probes, with fakes. A folder is "valid" if it is listed in $script:validDirs.
function Test-PgBinDir([string]$Dir) { return ($script:validDirs -contains $Dir.TrimEnd('\')) }
function Get-PgBinFromEnv { $script:probes.env }
function Get-PgBinFromService { $script:probes.svc }
function Get-PgBinFromRegistry { $script:probes.reg }
function Get-PgBinDefault { $script:probes.def }
function Get-PgBinFromPath { $script:probes.path }

$default = 'C:\Program Files\PostgreSQL\18\bin'
$script:validDirs = @('E:\env\bin', 'E:\svc\bin', 'E:\reg\bin', $default, 'E:\path\bin')
$orderCases = @(
    @{ Name = 'BOMS_PG_BIN wins (trailing slash trimmed)'; Expected = 'E:\env\bin'
       Probes = @{ env = 'E:\env\bin\'; svc = 'E:\svc\bin'; reg = 'E:\reg\bin'; def = $default; path = 'E:\path\bin' } },
    @{ Name = 'then the service ImagePath'; Expected = 'E:\svc\bin'
       Probes = @{ env = $null; svc = 'E:\svc\bin'; reg = 'E:\reg\bin'; def = $default; path = 'E:\path\bin' } },
    @{ Name = 'invalid env folder skipped, then the registry'; Expected = 'E:\reg\bin'
       Probes = @{ env = 'E:\not-valid'; svc = $null; reg = 'E:\reg\bin'; def = $default; path = 'E:\path\bin' } },
    @{ Name = 'then the default folder'; Expected = $default
       Probes = @{ env = $null; svc = $null; reg = $null; def = $default; path = 'E:\path\bin' } },
    @{ Name = 'then pg_dump.exe on PATH'; Expected = 'E:\path\bin'
       Probes = @{ env = $null; svc = $null; reg = $null; def = 'C:\nothing-here'; path = 'E:\path\bin' } },
    @{ Name = 'nothing found'; Expected = $null
       Probes = @{ env = $null; svc = $null; reg = $null; def = 'C:\nothing-here'; path = $null } }
)
foreach ($case in $orderCases) {
    $script:probes = $case.Probes
    Assert-Equal -Expected $case.Expected -Actual (Find-PgBin) -Name $case.Name
}

if ($script:failures -gt 0) { Write-Host "$($script:failures) failure(s)" -ForegroundColor Red; exit 1 }
Write-Host 'all Find-PgBin tests passed' -ForegroundColor Green
