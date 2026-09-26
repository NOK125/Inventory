# Registers the Central Store server as a Windows scheduled task that starts at boot,
# runs in the background as SYSTEM (no window, no login needed), and restarts if it stops.
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $dir 'server.py'
$task = 'CentralStore'

# Full path to python.exe (SYSTEM does not see the user's PATH). Skip the Microsoft Store alias.
$py = Get-Command python -All -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue | Select-Object -First 1 }
if (-not $py) { Write-Host 'ERROR: Python not found. Install Python from python.org first.' -ForegroundColor Red; exit 1 }
$pyPath = $py.Source
Write-Host "Python : $pyPath"
Write-Host "Server : $server"

if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    $running = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if (-not $running -or $running.State -ne 'Running') {
        Write-Host 'WARNING: port 8000 is in use. Close the run.bat window, then run this again.' -ForegroundColor Yellow
        exit 1
    }
}

$action = New-ScheduledTaskAction -Execute $pyPath -Argument ('"{0}" --lan --log' -f $server) -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Central Store web server (server.py). Starts at boot.' -Force | Out-Null

# Allow other computers on the hospital network (not needed for Cloudflare Tunnel).
if (-not (Get-NetFirewallRule -DisplayName 'Central Store 8000' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName 'Central Store 8000' -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private,Domain | Out-Null
}

Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $task
Start-Sleep -Seconds 4
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/setup' -UseBasicParsing -TimeoutSec 10
    Write-Host ''
    Write-Host 'OK: the server is running in the background and will start automatically at boot.' -ForegroundColor Green
    Write-Host 'You can close this window. Do NOT use run.bat any more.'
} catch {
    Write-Host ''
    Write-Host 'The task was installed but the server did not answer yet. Last lines of data\server.log:' -ForegroundColor Yellow
    $log = Join-Path $dir 'data\server.log'
    if (Test-Path $log) { Get-Content $log -Tail 15 } else { Write-Host '(no log file yet)' }
}
