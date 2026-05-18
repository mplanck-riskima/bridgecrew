# Drive Check Startup Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At every system boot, automatically detect if the M: drive registry mapping is missing and apply it (then restart), so the M: drive is always available before the user logs in.

**Architecture:** Three new files under `scripts/`: the `.reg` source file (moved from Desktop into source control), a `check-drive.ps1` check script installed to `C:\ProgramData\BridgecrewDriveCheck\`, and a `setup-drive-check.ps1` that copies both files to that stable C: location and registers an AtStartup Task Scheduler task running as SYSTEM. The installed C: copy is what the task references so it works even when M: is unmapped.

**Tech Stack:** PowerShell 5.1, Windows Task Scheduler (`Register-ScheduledTask`), Windows Registry (`reg import`, `Get-ItemProperty`)

---

### Task 1: Add drive-map.reg to source control

**Files:**
- Create: `scripts/drive-map.reg`

- [ ] **Step 1: Create `scripts/drive-map.reg`**

  Exact content (copy from Desktop original — do not modify):

  ```
  Windows Registry Editor Version 5.00

  [HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Session Manager\DOS Devices]

  "M:"="\\??\\C:\\projects"
  ```

- [ ] **Step 2: Verify the registry key path and value are correct**

  Run in PowerShell:
  ```powershell
  Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\DOS Devices" -Name "M:" -ErrorAction SilentlyContinue
  ```

  Expected: outputs a property named `M:` with value `\??\C:\projects`. If this machine already has the mapping, this confirms the reg file content is correct.

- [ ] **Step 3: Commit**

  ```powershell
  git add scripts/drive-map.reg
  git commit -m "feat: add drive-map.reg to source control"
  ```

---

### Task 2: Write check-drive.ps1

**Files:**
- Create: `scripts/check-drive.ps1`

- [ ] **Step 1: Create `scripts/check-drive.ps1`**

  ```powershell
  $ErrorActionPreference = "Stop"
  $InstallDir = "C:\ProgramData\BridgecrewDriveCheck"
  $LogFile    = "$InstallDir\drive-check.log"
  $RegFile    = "$InstallDir\drive-map.reg"

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
  $output = & reg import $RegFile 2>&1
  if ($LASTEXITCODE -ne 0) {
      Write-Log "ERROR: reg import failed (exit $LASTEXITCODE): $output"
      exit 1
  }

  Write-Log "Registry imported successfully — restarting."
  Restart-Computer -Force
  ```

- [ ] **Step 2: Manually verify the "already mapped" path**

  The task runs as SYSTEM at boot so you can't run it interactively with full fidelity, but you can smoke-test the registry check logic:

  ```powershell
  # Run from repo root (not installed location)
  $regPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\DOS Devices"
  $existing = Get-ItemProperty -Path $regPath -Name "M:" -ErrorAction SilentlyContinue
  if ($existing) { Write-Host "Key found: $($existing.'M:')" } else { Write-Host "Key missing" }
  ```

  Expected on this machine (mapping already exists): `Key found: \??\C:\projects`

- [ ] **Step 3: Commit**

  ```powershell
  git add scripts/check-drive.ps1
  git commit -m "feat: add check-drive.ps1 boot script"
  ```

---

### Task 3: Write setup-drive-check.ps1

**Files:**
- Create: `scripts/setup-drive-check.ps1`

- [ ] **Step 1: Create `scripts/setup-drive-check.ps1`**

  ```powershell
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
  ```

- [ ] **Step 2: Commit**

  ```powershell
  git add scripts/setup-drive-check.ps1
  git commit -m "feat: add setup-drive-check.ps1 installer"
  ```

---

### Task 4: Run setup and verify

**Files:** (none new — this is installation + verification)

- [ ] **Step 1: Run setup as admin**

  Open PowerShell as Administrator, then:

  ```powershell
  cd M:\bridgecrew
  .\scripts\setup-drive-check.ps1
  ```

  Expected output:
  ```
  Install dir: C:\ProgramData\BridgecrewDriveCheck
  Copied check-drive.ps1 and drive-map.reg
  Task 'Bridgecrew Drive Check' registered.
  Log file will appear at: C:\ProgramData\BridgecrewDriveCheck\drive-check.log

  You can now delete: C:\Users\mplanck\Desktop\drive-map.reg
  ```

- [ ] **Step 2: Verify installed files exist**

  ```powershell
  Get-ChildItem "C:\ProgramData\BridgecrewDriveCheck"
  ```

  Expected:
  ```
  check-drive.ps1
  drive-map.reg
  ```

- [ ] **Step 3: Verify the task is registered**

  ```powershell
  Get-ScheduledTask -TaskName "Bridgecrew Drive Check" | Select-Object TaskName, State
  ```

  Expected:
  ```
  TaskName                 State
  --------                 -----
  Bridgecrew Drive Check   Ready
  ```

- [ ] **Step 4: Verify task action and trigger**

  ```powershell
  $t = Get-ScheduledTask -TaskName "Bridgecrew Drive Check"
  $t.Actions | Select-Object Execute, Arguments
  $t.Triggers | Select-Object CimClass
  $t.Principal | Select-Object UserId, RunLevel
  ```

  Expected:
  ```
  Execute        Arguments
  -------        ---------
  powershell.exe -ExecutionPolicy Bypass -NonInteractive -File "C:\ProgramData\BridgecrewDriveCheck\check-drive.ps1"

  CimClass
  --------
  root/Microsoft/Windows/TaskScheduler:MSFT_TaskBootTrigger

  UserId  RunLevel
  ------  --------
  SYSTEM  Highest
  ```

- [ ] **Step 5: Delete the Desktop .reg file**

  ```powershell
  Remove-Item "C:\Users\mplanck\Desktop\drive-map.reg"
  ```

- [ ] **Step 6: Commit final state**

  ```powershell
  git add -A
  git commit -m "chore: remove Desktop drive-map.reg (now in scripts/)"
  ```

  > Note: `drive-map.reg` was not tracked in git before this feature, so this commit is a no-op for that file. The `-A` here just catches any incidental unstaged changes.

---

## Post-Setup Verification (Optional)

To confirm the check script runs correctly on next boot, check the log after restarting:

```powershell
Get-Content "C:\ProgramData\BridgecrewDriveCheck\drive-check.log"
```

Expected (mapping already present):
```
2026-05-18 XX:XX:XX  M: already mapped — no action.
```
