# BOMS installer. Run install.bat (as your normal Windows user) from the extracted release folder.
#   install.bat                       new install, or repair an existing one
#   restore.bat <backup folder>       clean PC: install and restore from a backup (calls this with -RestoreFrom)
# Compatible with Windows PowerShell 5.1.

param([string]$RestoreFrom = '')

. "$PSScriptRoot\common.ps1"

$source = Get-SourceRoot
$version = Get-AppVersion $source
Write-Host "BOMS installer - version $version" -ForegroundColor White

# ---- 1. system checks ------------------------------------------------------------
Write-Step 'Checking Windows'
$os = Get-CimInstance Win32_OperatingSystem
if (-not [Environment]::Is64BitOperatingSystem) { Stop-WithError 'BOMS needs 64-bit Windows 10 or 11.' }
if ([int]$os.BuildNumber -lt 10240) { Stop-WithError "BOMS needs Windows 10 or 11 (found: $($os.Caption))." }
Write-Ok "$($os.Caption) (build $($os.BuildNumber)), 64-bit"
$freeGb = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($freeGb -lt 3) { Stop-WithError "Drive C: has only $freeGb GB free; at least 3 GB is needed." }
Write-Ok "Drive C: $freeGb GB free"

$existing = Read-BomsConfig
$repair = $false
if ($existing) {
    if ($RestoreFrom) {
        Stop-WithError ("BOMS is already installed here (data folder $($existing.data_dir)). " +
            'Full restore is for a clean PC. See docs\OPERATIONS.md, section "Restore".')
    }
    Write-Warn "BOMS is already installed (data folder: $($existing.data_dir))."
    $answer = Read-Host 'Repair the installation? Your data is kept. [R]epair / [Q]uit'
    if ($answer -notmatch '^[Rr]') { Write-Host 'Nothing changed.'; exit 0 }
    $repair = $true
}

# ---- 2. prerequisites --------------------------------------------------------------
function Install-Prerequisite([string]$Name, [string]$WingetId, [string[]]$WingetArgs, [string]$ManualUrl,
                              [string]$ManualHint, [scriptblock]$Detect) {
    $found = & $Detect
    if ($found) { Write-Ok "$Name found: $found"; return $found }
    Write-Warn "$Name is not installed. Trying winget..."
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        & $winget.Source install -e --id $WingetId --accept-package-agreements --accept-source-agreements @WingetArgs
        $found = & $Detect
        if ($found) { Write-Ok "$Name installed: $found"; return $found }
        Write-Warn "winget could not install $Name (this is common without internet)."
    } else {
        Write-Warn 'winget is not available on this PC.'
    }
    while (-not $found) {
        Write-Host ''
        Write-Host "Please install $Name by hand:" -ForegroundColor Yellow
        Write-Host "  Download: $ManualUrl"
        Write-Host "  $ManualHint"
        Read-Host 'Press Enter when the installation has finished (Ctrl+C to cancel)' | Out-Null
        $found = & $Detect
        if (-not $found) { Write-Warn "$Name still not found." }
    }
    Write-Ok "$Name found: $found"
    return $found
}

Write-Step 'Checking prerequisites'
$python = Install-Prerequisite -Name 'Python 3.12' -WingetId 'Python.Python.3.12' -WingetArgs @('--scope', 'user') `
    -ManualUrl 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' `
    -ManualHint 'Run it, keep "Install for current user", and finish the setup.' -Detect { Find-Python312 }
$pgBin = Install-Prerequisite -Name 'PostgreSQL 18' -WingetId 'PostgreSQL.PostgreSQL.18' -WingetArgs @('--interactive') `
    -ManualUrl 'https://www.enterprisedb.com/downloads/postgres-postgresql-downloads  (Windows x86-64, version 18.x)' `
    -ManualHint 'Use port 5432 and write down the "postgres" superuser password you choose.' -Detect { Find-PgBin }
$pgService = Get-Service -Name 'postgresql-x64-18' -ErrorAction SilentlyContinue
if ($pgService -and $pgService.Status -ne 'Running') {
    Write-Warn 'The PostgreSQL service is not running. Start it in services.msc (postgresql-x64-18), then continue.'
    Read-Host 'Press Enter when it is running' | Out-Null
}

# ---- 3. data folder and passwords --------------------------------------------------
Write-Step 'Settings'
if ($repair) {
    $config = $existing
    Write-Ok "Data folder: $($config.data_dir)"
} else {
    $default = 'C:\BOMS-Data'
    $d = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID = 'D:' AND DriveType = 3" -ErrorAction SilentlyContinue
    if ($d) { $default = 'D:\BOMS-Data' }
    if ($RestoreFrom) { Write-Host 'Choose where the restored data will live.' }
    $dataDir = Read-Host "Data folder [$default]"
    if (-not $dataDir) { $dataDir = $default }
    $config = [pscustomobject]@{
        data_dir  = $dataDir
        db_host   = '127.0.0.1'
        db_port   = 5432
        db_name   = 'boms'
        db_user   = 'boms'
        http_port = $script:HttpPort
        pg_bin    = $pgBin
    }
}
$config.pg_bin = $pgBin
foreach ($sub in @('', 'files', 'backups', 'logs')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $config.data_dir $sub) | Out-Null
}
Write-Ok "Data folder ready: $($config.data_dir)"

Write-Host 'The PostgreSQL superuser password is used only now, to create the BOMS database role.'
$superPassword = ConvertFrom-SecureToPlain (Read-Host -AsSecureString 'PostgreSQL "postgres" password')

$appPassword = ''
if (-not $repair -and -not $RestoreFrom) {
    $appPassword = Read-PasswordTwice 'Choose the BOMS app password (min. 8 characters)' 8
} elseif ($repair) {
    if ((Read-Host 'Also reset the BOMS app password? [y/N]') -match '^[Yy]') {
        $appPassword = Read-PasswordTwice 'New BOMS app password (min. 8 characters)' 8
    }
}

# ---- 4. program files and Python environment ---------------------------------------
Write-Step "Installing program files to $($script:AppDir)"
New-Item -ItemType Directory -Force -Path $script:AppDir | Out-Null
if ((Resolve-Path $source).Path -ne (Resolve-Path $script:AppDir).Path) {
    Stop-BomsProcesses
    foreach ($item in @('backend', 'scripts', 'wheelhouse', 'docs')) {
        $target = Join-Path $script:AppDir $item
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Copy-Item -Recurse -Path (Join-Path $source $item) -Destination $target
    }
    Copy-Item -Force (Join-Path $source 'VERSION') (Join-Path $script:AppDir 'VERSION')
}
Write-Ok 'Program files copied'

if (-not (Test-Path $script:VenvPython)) {
    & $python -m venv (Join-Path $script:AppDir 'venv')
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'Could not create the Python virtual environment.' }
}
& $script:VenvPython -m pip install --quiet --no-index --find-links (Join-Path $script:AppDir 'wheelhouse') `
    -r (Join-Path $script:BackendDir 'requirements.lock')
if ($LASTEXITCODE -ne 0) { Stop-WithError 'Installing Python packages from the bundled wheelhouse failed.' }
Write-Ok 'Python packages installed (offline, from wheelhouse)'

Save-BomsConfig $config
Set-BomsEnvironment $config

Write-Step 'Storing secrets in Windows Credential Manager'
foreach ($secret in @('db_password', 'session_key')) {
    if ((Invoke-BomsCli -Arguments @('has-secret', $secret) -AllowFailure) -eq 0) {
        Write-Ok "$secret already stored"
        continue
    }
    $env:BOMS_SECRET_VALUE = New-RandomSecret
    try { Invoke-BomsCli -Arguments @('store-secret', $secret) | Out-Null }
    finally { Remove-Item Env:\BOMS_SECRET_VALUE -ErrorAction SilentlyContinue }
    Write-Ok "$secret generated and stored (Credential Manager: BOMS/$secret)"
}

# ---- 5. database -------------------------------------------------------------------
Write-Step 'Database'
$env:BOMS_PG_SUPERUSER_PASSWORD = $superPassword
try {
    if ($RestoreFrom) {
        Write-Host "Restoring from $RestoreFrom ..."
        Invoke-BomsCli -Arguments @('restore', '--backup-dir', $RestoreFrom) | Out-Null
        Invoke-BomsCli -Arguments @('migrate') | Out-Null
        Write-Ok 'Database and files restored, hashes verified, migrations applied'
    } else {
        Invoke-BomsCli -Arguments @('init-db') | Out-Null
        Invoke-BomsCli -Arguments @('migrate') | Out-Null
        Invoke-BomsCli -Arguments @('seed') | Out-Null
        Write-Ok 'Database ready (role, extensions, migrations, base data)'
    }
} finally {
    Remove-Item Env:\BOMS_PG_SUPERUSER_PASSWORD -ErrorAction SilentlyContinue
    $superPassword = $null
}
if ($appPassword) {
    $env:BOMS_INITIAL_PASSWORD = $appPassword
    try {
        if ($repair) { Invoke-BomsCli -Arguments @('set-password') | Out-Null }
        else { Invoke-BomsCli -Arguments @('create-user', '--username', 'admin', '--language', 'fa') | Out-Null }
    } finally {
        Remove-Item Env:\BOMS_INITIAL_PASSWORD -ErrorAction SilentlyContinue
        $appPassword = $null
    }
    Write-Ok 'App user ready (username: admin)'
}

# ---- 6. Task Scheduler -------------------------------------------------------------
Write-Step 'Registering background start at logon (Task Scheduler)'
$user = "$env:USERDOMAIN\$env:USERNAME"
foreach ($kind in @('backend', 'worker')) {
    $name = if ($kind -eq 'backend') { 'BOMS Backend' } else { 'BOMS Worker' }
    $action = New-ScheduledTaskAction -Execute $script:VenvPythonW `
        -Argument "-m app.launch $kind --config `"$($script:ConfigPath)`"" -WorkingDirectory $script:BackendDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    try {
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
            -Principal $principal -Description "BOMS $kind (starts hidden at logon)" -Force | Out-Null
    } catch {
        Stop-WithError ("Could not register the scheduled task '$name': $($_.Exception.Message). " +
            'Run install.bat again with "Run as administrator".')
    }
    Write-Ok "$name"
}

# ---- 7. shortcut and start ---------------------------------------------------------
Write-Step 'Desktop shortcut and start'
$browser = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$url = "http://127.0.0.1:$($script:HttpPort)"
if ($browser) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'BOMS.lnk'))
    $shortcut.TargetPath = $browser
    $shortcut.Arguments = "--app=$url"
    $shortcut.IconLocation = (Join-Path $script:BackendDir 'app\static\icons\boms.ico')
    $shortcut.Description = 'BOMS'
    $shortcut.Save()
    Write-Ok 'Desktop shortcut "BOMS" created (opens in app mode)'
} else {
    Write-Warn "Edge/Chrome not found. Open $url in your browser."
}
Stop-BomsProcesses
if (Start-BomsProcesses) { Write-Ok "BOMS is running at $url" }
else { Write-Warn "BOMS did not answer yet. Check $($config.data_dir)\logs\backend.log" }

# ---- 8. summary --------------------------------------------------------------------
Write-Step 'Done'
Write-Host "  Version:      $version"
Write-Host "  Program:      $($script:AppDir)"
Write-Host "  Data:         $($config.data_dir)"
Write-Host "  Address:      $url   (only reachable from this PC)"
Write-Host "  User name:    admin"
Write-Host "  Backups:      nightly at 02:00 into $($config.data_dir)\backups (change in Settings)"
Write-Host ''
Write-Host 'Security recommendation: turn on BitLocker drive encryption for the drives that hold' -ForegroundColor Yellow
Write-Host 'C:\BOMS and the data folder (Settings > Privacy & security > Device encryption / BitLocker).' -ForegroundColor Yellow
Write-Host 'BOMS does not require it, but it protects your data if the PC is lost or stolen.' -ForegroundColor Yellow
