$action = New-ScheduledTaskAction `
    -Execute "C:\Program Files\Git\bin\bash.exe" `
    -Argument "-c 'cd /m/bridgecrew && ./startup.sh >> /m/bridgecrew/startup-boot.log 2>&1'" `
    -WorkingDirectory "M:\bridgecrew"

$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "Bridgecrew Bot Startup" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force
