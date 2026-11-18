# ClearPageDigital Mission Control — Windows-first deployment

Nur's current choice is a **Windows PC**. The Linux systemd templates are
optional for a later server migration; do not install them on Windows.

## What is ready and what is not

- The Python worker code, local SQLite ledger, scoped Mission Control task
  workflow, bounded fixture tests, and recovery inspection are implemented.
- `clearpage/windows/Save-ScopedKey.ps1` stores each role's API key encrypted
  with Windows DPAPI for the currently signed-in Windows user.
- `clearpage/windows/Start-ScopedWorker.ps1` launches one Researcher, Validator,
  or read-only monitor process, using only that role's key and a persistent
  ledger under `%LOCALAPPDATA%\ClearPageDigital\State`.
- **No Scheduled Task is installed**, and no startup automation is enabled.
  That will require Nur at the computer to authorize it.

## When you are at your Windows PC

1. Install/update Python 3.12+, Node.js and pnpm using their official installers.
   Clone the reviewed GitHub branch to a directory you own. Do not delete the
   previous project or its data while testing.
2. Start the Mission Control board according to its README, initially bound
   to `127.0.0.1`, and confirm its health page. Do not expose the test board
   publicly.
3. With Mission Control running, register the native ClearPage Researcher and
   Validator agents. Provision **different, least-privilege scoped keys**. A
   separate coordinator credential will be required to schedule fixture tasks.
   Rotate any key previously pasted into chat before testing.
4. Open PowerShell **as your normal Windows user** and, from the repository:

   ```powershell
   .\clearpage\windows\Save-ScopedKey.ps1 -Role research
   .\clearpage\windows\Save-ScopedKey.ps1 -Role validation
   .\clearpage\windows\Save-ScopedKey.ps1 -Role monitor
   ```

   Enter each key in the secure prompt. Don't paste API keys into messages or
   commands. DPAPI files are tied to that Windows user and computer. Backups
   of encrypted files alone cannot necessarily be decrypted on another PC.
5. Schedule one unique **fixture** run with the coordinator. Create a reviewed
   fixture JSON file with exactly that `research_id`. Then launch Validator
   **first** and Researcher **second**, in separate PowerShell windows:

   ```powershell
   .\clearpage\windows\Start-ScopedWorker.ps1 -Role validation -RunId FIXTURE_RUN_ID -RepoRoot C:\path\to\Mission-board
   .\clearpage\windows\Start-ScopedWorker.ps1 -Role research -RunId FIXTURE_RUN_ID -RepoRoot C:\path\to\Mission-board -FixturePath C:\path\to\fixture.json
   ```

6. After handoff, inspect the run using the read-only monitor:

   ```powershell
   .\clearpage\windows\Start-ScopedWorker.ps1 -Role monitor -RunId FIXTURE_RUN_ID -RepoRoot C:\path\to\Mission-board
   ```

7. Verify two native tasks in review, `RESEARCH_MORE`, zero model calls,
   duplicate execution blocked, and no unexplained in-progress tasks.

## Startup and recovery policy

- Do **not** configure Windows Task Scheduler to automatically restart
  Researcher or Validator on failure. A server claim may already have been
  accepted before the worker crashed; automatic restart risks duplicate work.
- A read-only monitoring task may be scheduled after its Windows account,
  credentials, path permissions, and logs are checked. Run it under the **same
  Windows user** who encrypted its DPAPI key, not SYSTEM or another account.
- Back up the worker SQLite ledger with `clearpage/ledger_backup.py`, using
  a new snapshot path every time. The Mission Control database needs a
  separate verified backup and restore procedure.
- A crash, missing task ID, or stale `in_progress` state must go through
  `RECOVERY_PLAYBOOK.md`. Do not auto-reset, force-finish or replay it.

## Unverified Windows-specific items

The supplied PowerShell scripts have been reviewed statically in this Linux
workspace; **PowerShell execution and Windows Task Scheduler behavior have
not been tested on Nur's computer**. Before enabling startup automation, we
must verify script execution policy, DPAPI decryption, Windows filesystem
permissions, the user account, loopback networking, Python installation,
backup restoration and controlled process termination on Windows itself.

The goal is to make that a short, supervised setup session. Until then, the
GitHub PR remains a draft and real market/paid APIs stay disabled.
