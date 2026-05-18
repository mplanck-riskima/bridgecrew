#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

$InstallDir = "C:\ProgramData\BridgecrewDriveCheck"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition

# 1. Create install directory
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
}
Write-Host "Install dir: $InstallDir"

# 2. Copy files
Copy-Item -Path "$ScriptDir\check-drive.ps1" -Destination "$InstallDir\check-drive.ps1" -Force
Copy-Item -Path "$ScriptDir\drive-map.reg"   -Destination "$InstallDir\drive-map.reg"   -Force
Write-Host "Copied check-drive.ps1 and drive-map.reg"

# 3. Register scheduled task
$action = New-ScheduledTaskAction `
    -Execute   "powershell.exe" `
    -Argument  "-ExecutionPolicy Bypass -NonInteractive -File `"$InstallDir\check-drive.ps1`""

$trigger = New-ScheduledTaskTrigger -AtStartup

$principal = New-ScheduledTaskPrincipal `
    -UserId   "SYSTEM" `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName "Bridgecrew Drive Check" `
    -Action    $action `
    -Trigger   $trigger `
    -Principal $principal `
    -Settings  $settings `
    -Force | Out-Null

Write-Host "Task 'Bridgecrew Drive Check' registered."
Write-Host "Log file will appear at: $InstallDir\drive-check.log"
Write-Host ""
Write-Host "You can now delete: C:\Users\mplanck\Desktop\drive-map.reg"
