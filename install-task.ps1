# Register WhisperKey as a Scheduled Task - more robust than the Startup folder.
#
# Why: the Startup shortcut only fires at LOGIN. If the machine runs for weeks
# without a logout (common on a desktop/always-on laptop) and the app's whole
# process tree dies, nothing relaunches it until the next reboot. This task adds
# a repeating keepalive so the app recovers within ~10 minutes of any death,
# with no login required.
#
# How it stays single-instance: the task uses IgnoreNew (Task Scheduler won't
# start a second copy while one is running) AND the app itself holds a named
# mutex. So the keepalive is a no-op whenever the app is already alive.
#
# No admin required for the default (normal-privilege) install. To also inject
# into ELEVATED windows, re-run this in an *admin* PowerShell with -Elevated.

param([switch]$Elevated)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$supervisor = Join-Path $root "src\supervisor.py"
$taskName = "WhisperKey"

if (-not (Test-Path $pyw)) { throw "pythonw.exe not found at $pyw (run setup.ps1 first)" }
if (-not (Test-Path $supervisor)) { throw "supervisor.py not found at $supervisor" }

$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$supervisor`"" -WorkingDirectory $root

# Trigger 1: at logon (prompt start after a real reboot).
$tLogon = New-ScheduledTaskTrigger -AtLogOn

# Trigger 2: keepalive - fire every 10 min. IgnoreNew makes this a no-op while
# the app is up, and a relaunch within 10 min if it ever died. Duration is set
# to 10 years (Task Scheduler rejects TimeSpan.MaxValue as out of range); it
# re-arms at every logon anyway, so this is effectively indefinite.
$tKeepalive = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$runLevel = if ($Elevated) { "Highest" } else { "Limited" }
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel $runLevel

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($tLogon, $tKeepalive) `
    -Principal $principal -Settings $settings -Force | Out-Null

# Confirm it actually registered before touching the old startup mechanism.
if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    throw "Task registration did not take effect - leaving Startup shortcut in place."
}
Write-Output "Registered Scheduled Task '$taskName' (run level: $runLevel)."

# Only now remove the old Startup-folder shortcut, so we don't double-launch.
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "WhisperKey.lnk"
if (Test-Path $lnk) {
    Remove-Item $lnk -Force
    Write-Output "Removed old Startup-folder shortcut (task replaces it)."
}

Write-Output ""
Write-Output "The app now relaunches within ~10 min of any death, no login needed."
Write-Output "Remove with: uninstall-task.ps1"
