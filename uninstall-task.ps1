# Remove the WhisperKey Scheduled Task (stops auto-start + keepalive).
# Does not stop a running instance - use the tray icon's Quit for that.

$taskName = "WhisperKey"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Removed Scheduled Task '$taskName'."
} else {
    Write-Output "No Scheduled Task named '$taskName' found."
}
