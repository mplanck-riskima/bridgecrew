$ErrorActionPreference = "Stop"
$InstallDir = "C:\ProgramData\BridgecrewDriveCheck"
$LogFile    = "$InstallDir\drive-check.log"
$RegFile    = "$InstallDir\drive-map.reg"

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $Message" | Add-Content -Path $LogFile
}

$regPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\DOS Devices"
$existing = Get-ItemProperty -Path $regPath -Name "M:" -ErrorAction SilentlyContinue

if ($existing) {
    Write-Log "M: already mapped — no action."
    exit 0
}

Write-Log "M: not found — importing $RegFile ..."

if (-not (Test-Path $RegFile)) {
    Write-Log "ERROR: $RegFile not found — cannot import."
    exit 1
}

$output = (& reg import $RegFile 2>&1) -join " "
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: reg import failed (exit $LASTEXITCODE): $output"
    exit 1
}

Write-Log "Registry imported successfully — restarting."
Restart-Computer -Force
