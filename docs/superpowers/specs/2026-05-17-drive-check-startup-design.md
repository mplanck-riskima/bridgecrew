# Drive Check Startup Task — Design Spec

**Date:** 2026-05-17

## Problem

The `M:` drive (mapped to `C:\projects` via an HKLM registry symbolic link) may not be configured on a fresh boot. The existing bot logon task (`cd /m/bridgecrew`) fails silently if M: is missing. We need an automated boot-time check that detects the missing mapping and corrects it before the user logs in.

## Solution Overview

A Windows Task Scheduler task runs at system startup (as SYSTEM, elevated) and checks for the M: drive registry entry. If missing, it imports the registry fix and restarts the machine. Everything lives in a stable C: location so it works even when M: is unmapped.

## Files

### `scripts/drive-map.reg`
The registry file moved from the Desktop into source control. Maps `M:` → `C:\projects` via:
```
[HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Session Manager\DOS Devices]
"M:"="\\??\\C:\\projects"
```

### `scripts/check-drive.ps1`
The check script, installed to `C:\ProgramData\BridgecrewDriveCheck\` by the setup script. Logic:
1. Check if value `M:` exists under `HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\DOS Devices`
2. If present: log "M: already mapped, no action." and exit
3. If missing: log "M: not found, importing registry fix...", run `reg import` on the installed `.reg` file, log "Restarting...", then `Restart-Computer -Force`
4. All log entries timestamped and appended to `C:\ProgramData\BridgecrewDriveCheck\drive-check.log`

### `scripts/setup-drive-check.ps1`
Run once as admin to install and register everything:
1. Create `C:\ProgramData\BridgecrewDriveCheck\` if it doesn't exist
2. Copy `check-drive.ps1` and `drive-map.reg` from the repo's `scripts/` dir to that location
3. Register a Task Scheduler task:
   - **Name:** `Bridgecrew Drive Check`
   - **Trigger:** `AtStartup`
   - **Action:** `powershell.exe -ExecutionPolicy Bypass -NonInteractive -File "C:\ProgramData\BridgecrewDriveCheck\check-drive.ps1"`
   - **Principal:** `SYSTEM`, RunLevel Highest
   - **Settings:** StartWhenAvailable, no execution time limit
4. Print confirmation and log file path

## Installed Layout

```
C:\ProgramData\BridgecrewDriveCheck\
  check-drive.ps1      ← installed copy (task points here)
  drive-map.reg        ← installed copy (check script imports this)
  drive-check.log      ← created at first run
```

## Boot Sequence (After Setup)

```
System boot
  └─ Task Scheduler fires "Bridgecrew Drive Check" (SYSTEM)
       ├─ M: registry key present → log, exit → user logs in normally
       └─ M: registry key missing → import reg → restart
            └─ Next boot: key present → log, exit → user logs in normally
```

## Error Handling

- `reg import` failure is caught; error message written to log; no restart attempted (avoids reboot loop on broken .reg)
- Task registered with `-Force` so re-running setup is idempotent

## Out of Scope

- Verifying that `C:\projects` actually exists (the reg entry points there regardless)
- Network drive mappings (this is a kernel symbolic link, not a UNC share)
