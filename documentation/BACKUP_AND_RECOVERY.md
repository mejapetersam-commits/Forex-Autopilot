# FOREX AUTOPILOT database backup and recovery

## Scope and safety

The telemetry database contains market candles, broker specifications, account
snapshots and demo execution telemetry. Treat backups as sensitive operational
data: restrict filesystem access, encrypt them at rest and keep off-device copies
in an access-controlled location. Never put backups or credentials in Git.

The maintenance utility uses SQLite's online backup API. It includes committed
WAL content and verifies the resulting database with `PRAGMA integrity_check`.
It emits a SHA-256 checksum and row counts by table. It does not include secrets
stored in environment variables and it never enables trading.

## Create and verify a backup

From the repository root:

```bash
cd backend
source .venv/bin/activate
python -m app.operations.backup backup \
  --source data/telemetry.sqlite3 \
  --destination ../backups/telemetry-$(date -u +%Y%m%dT%H%M%SZ).sqlite3
```

Verify any backup independently:

```bash
python -m app.operations.backup verify \
  --backup ../backups/telemetry-YYYYMMDDTHHMMSSZ.sqlite3
```

For the Docker deployment, the database is at
`/var/lib/forex-autopilot/telemetry.sqlite3` inside the API container. A backup
job must write to a separately mounted, access-restricted backup volume; do not
assume the container filesystem is persistent.

## Restore

**Stop the API before restoring.** Replacing a database file while the API is
writing to it is not supported. Confirm the selected backup and preserve a copy
of the current database first.

```bash
docker compose stop api telemetry-backup
```

Then run the restore utility in an environment that can access both the backup
and the persistent database volume. The destination must not already exist unless
the explicit `--replace` flag is supplied. With `--replace`, the utility first
creates and verifies a timestamped pre-restore backup, then atomically replaces
the destination with the verified source.

```bash
python -m app.operations.backup restore \
  --backup /secure/backups/telemetry.sqlite3 \
  --destination /secure/data/telemetry.sqlite3 \
  --replace
```

After restore, start the API and verify health, MT5 telemetry freshness, candle
counts, symbol specifications and execution reconciliation. A restore is not
permission to resume any execution path; keep demo execution disabled and the
kill switch active until the normal release checks are complete.

## Retention and off-device copies

Schedule backups outside active database maintenance windows and retain multiple
recovery points (for example daily plus weekly). Copy verified backups to a
separate encrypted device or storage account. Periodically perform a restore
drill to a disposable path. Retention deletion and cloud replication are
intentionally left to the deployment operator until storage policy and target
provider are selected.


## Automated local backup service

Compose includes a dedicated `telemetry-backup` process. It creates and verifies
a SQLite online backup at startup, then repeats every 24 hours by default. If a backup attempt fails, it retries within five minutes rather than waiting for the next daily interval. The
default retention window is 30 days. Only expired snapshots with the managed
filename pattern and a passing SQLite integrity check are pruned; corrupt
snapshots and unrelated files are retained for manual review.

Snapshots use a separate Docker named volume, `telemetry_backups`. This is a
local recovery layer, **not an encrypted or off-device disaster-recovery copy**.
Use encrypted host storage and independent off-device replication before
relying on it for disaster recovery. The backup process opens the SQLite source database in read-only mode. Its volume mount permits SQLite to coordinate WAL shared-memory sidecars safely while the API is running. It has no broker credentials, no network ports and no execution permissions.

Optional settings:
- `FOREX_AUTOPILOT_BACKUP_INTERVAL_SECONDS` (default 86400; allowed 3600-604800)
- `FOREX_AUTOPILOT_BACKUP_RETENTION_DAYS` (default 30; allowed 1-3650)

Inspect logs with `docker compose logs --tail=100 telemetry-backup`.
