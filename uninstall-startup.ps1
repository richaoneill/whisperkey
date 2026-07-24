# Removes the WhisperKey startup shortcut (stops it launching at login).
# This does NOT stop a currently-running instance - use the tray icon's Quit
# for that, or end "pythonw.exe" in Task Manager.

$startup = [Environment]::GetFolderPath("Startup")
$lnkPath = Join-Path $startup "WhisperKey.lnk"

if (Test-Path $lnkPath) {
    Remove-Item $lnkPath -Force
    Write-Output "Removed startup shortcut: $lnkPath"
} else {
    Write-Output "No startup shortcut found (nothing to remove)."
}
