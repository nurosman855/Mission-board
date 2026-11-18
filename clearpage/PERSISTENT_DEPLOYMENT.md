# ClearPage supervised worker service — deployment blueprint

**Not installed on Nur's computer.** These templates are for a Linux host
with systemd and are intentionally **not** an unattended agent fleet.
The board must already run under its own service with a durable database.

## Prerequisites

- Python 3.12+, a supported Linux systemd host, and a non-privileged `clearpage`
  service account. The checked-out repository resides at `/opt/mission-board`.
- `/var/lib/clearpage` is writable only by the ClearPage service account. All
  worker processes on this host reference the **same** `runs.sqlite` ledger.
- The Mission Control API uses a trusted HTTPS endpoint, or a local loopback
  address for supervised offline testing.
- Independent **scoped** Researcher and Validator keys, plus a read-only
  capable monitor key. Never share one API key between agent roles.
- The Researcher has an explicitly reviewed **fixture** packet. No live
  customer data, paid APIs, product creation or publication is enabled.

## Service units

Provided templates:

- `ops/templates/clearpage-worker@.service`
- `ops/templates/clearpage-recovery@.service`

Copy only the verified templates to `/etc/systemd/system/` with administrator
authorization. Keep the unit instances limited to `research` and `validation`;
the coordinator schedules runs separately. Create these root-readable-only
environment files:

| File | Required values |
| --- | --- |
| `/etc/clearpage/research.env` | `MC_API_KEY`, `MC_BASE_URL`, `CLEARPAGE_RUN_ID`, `MC_RESEARCH_PACKET_PATH` |
| `/etc/clearpage/validation.env` | `MC_API_KEY`, `MC_BASE_URL`, `CLEARPAGE_RUN_ID` |
| `/etc/clearpage/monitor.env` | `MC_API_KEY`, `MC_BASE_URL`, `CLEARPAGE_RUN_ID` |

The three API keys must be different. Use `chmod 0600` and root ownership for
the environment files. No keys should be embedded in unit files, GitHub,
terminal arguments, or diagnostic output.

For a **single reviewed fixture run**, after a separate coordinator has
scheduled the task, an administrator may start:

```bash
sudo systemctl daemon-reload
sudo systemctl start clearpage-worker@validation
sudo systemctl start clearpage-worker@research
sudo systemctl start clearpage-recovery@monitor
```

The worker units use **`Restart=no`** deliberately. If a worker dies after a
remote claim, it must not restart blindly. Inspect the case and reconcile
before manually restarting a safe unclaimed stage. The recovery unit performs
read-only monitoring and may restart after a transient read failure.

## Back up and verify the ledger

Use the SQLite online-backup helper rather than copying a live database file:

```bash
python clearpage/ledger_backup.py --source /var/lib/clearpage/runs.sqlite --destination /var/lib/clearpage/runs-YYYYMMDD-HHMM.sqlite
```

The helper refuses overwrite, verifies SQLite integrity, and produces a
transaction-consistent snapshot. Backups should be moved to independently
secured storage and restored/tested on a non-production host. The native
Mission Control database also needs its **own** backup process; this helper
backs up only the Python worker ledger.

## Acceptance gates before unattended deployment

1. Verify a supervised fixture handoff using distinct scoped keys and ensure
   the Validator produces `RESEARCH_MORE` with zero paid model calls.
2. Kill Researcher **after** claim in an isolated test. Verify no service
   restarts it, that the monitor flags reconciliation, and that replay fails.
3. Stop and start the monitoring service. Confirm read-only inspection and
   correct behavior across a server restart or temporary network failure.
4. Take a ledger snapshot during normal writes and restore it to a clean
   test directory; verify both task IDs and completion states.
5. Verify production TLS, process supervision, DB permissions, log redaction,
   least-privilege keys, alerts, and ability to revoke a compromised key.
6. Only after an operator signs off should the host run longer reliability
   exercises. Unverified stale tasks require manual administrator review.

## Evidence and limitations

The unit files passed `systemd-analyze verify` locally. The online SQLite
backup utility is covered by recovery and non-overwrite unit tests. The
standalone board has passed local HTTP startup, and a separate-process fixture
soak passed 40/40 consecutive tasks. **No systemd service was installed or
started on Nur's machine**, and no overnight or real network-partition test
has been performed. These are still deployment acceptance requirements.
