# PostgreSQL recovery runbook

The daily logical dump is the authoritative database backup. EBS snapshots are
an additional crash-consistent recovery path, not a replacement for `pg_dump`.

1. Start an SSM Session Manager session. Do not open SSH.
2. Confirm the desired object URI under `s3://<pilot-bucket>/backups/database/`.
3. Confirm the host has enough free space for the dump.
4. Run `sudo /opt/fieldintel/current/scripts/restore-postgres.sh <s3-uri> --confirm-replace-market-intel`.
5. The script first creates and verifies a safety backup, stops application
   writers, validates the selected archive, replaces the database, and restarts
   the application services.
6. Verify `/ready`, administrator sign-in, employee-master browse, and a signed
   webhook fixture before resuming pilot traffic.

If restore fails after application writers stop, leave them stopped. Preserve
the downloaded dump and logs, diagnose through Session Manager, and do not retry
with a broader or more destructive command.
