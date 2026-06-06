$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $repo "scripts\run_local_filter.ps1"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At "04:10"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName "TVBox Mainland Source Filter" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Validate TVBox streams without a proxy and publish the mainland-reachable list." `
    -Force
