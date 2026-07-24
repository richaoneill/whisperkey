# Registers WhisperKey to launch hidden at login.
# Creates a shortcut in the user's Startup folder that runs the app via
# pythonw.exe (no console window). No admin required.
#
# NOTE: launched this way the app runs at normal privilege, which is fine for
# dictating into browsers, editors, Office, and non-elevated terminals. To also
# inject into ELEVATED windows, use Task Scheduler with "highest privileges"
# instead (ask and I'll set that up).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$mainpy = Join-Path $root "src\supervisor.py"   # supervisor keeps main.py alive

if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found at $pythonw" }
if (-not (Test-Path $mainpy))  { throw "supervisor.py not found at $mainpy" }

$startup = [Environment]::GetFolderPath("Startup")
$lnkPath = Join-Path $startup "WhisperKey.lnk"

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnkPath)
$sc.TargetPath = $pythonw
$sc.Arguments = "`"$mainpy`""
$sc.WorkingDirectory = $root
$sc.WindowStyle = 7   # minimized / hidden
$sc.Description = "WhisperKey - local dictation"
$sc.IconLocation = "$pythonw,0"
$sc.Save()

Write-Output "Installed startup shortcut:"
Write-Output "  $lnkPath"
Write-Output ""
Write-Output "It will start automatically at your next login."
