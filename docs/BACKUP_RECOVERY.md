# Encrypted backup and recovery

Only disposable local drills are authorized in Phase 7. Actual off-server copy,
remote recovery and VPS operations need separate approval and missing destination
details. A local encrypted restore cannot prove an off-server recovery gate.

## Backup contract

`deploy/backup.py` runs in the pinned PostgreSQL17/age tools image, UID10001,
read-only root filesystem. It requires stopped API, proxy, both workers and
maintenance (`BACKUP_QUIESCED=1`). PostgreSQL and media form one quiesced recovery
point; Redis is transport and is rebuilt from PostgreSQL outbox/checkpoints.
Stop all other writers, including staff CLI sessions. Confirm no live paid call
is in flight before an approved maintenance window. Retain uncertain exposure;
never mark an unknown call unpaid merely to complete backup.

The tool streams a custom-format pg_dump and media tar directly through age.
Only encrypted `.age` files reach backup disk; the JSON manifest contains hashes,
timestamp, format and quiescence assertion, no identity or customer paths. It
fsyncs ciphertext then atomically publishes the manifest last. At least20GiB plus
twice DB+media size must be free; refusal leaves writers stopped. Do not disable
that guard to fit a large working set on100GB. File encryption protects off-server
contents; host/root access and writable ciphertext remain separate trust risks.
SHA256 checks catch corruption; authenticated age decryption verifies the encrypted
streams. Protect manifests from unauthorized replacement along with ciphertext.

After explicit server authorization, with reviewed `/etc/zoclip/staging.env`:

```sh
cd /opt/zoclip
python3 deploy/manage.py backup --env-file /etc/zoclip/staging.env --project zoclip-private --execute-local
# Use the exact manifest basename returned by the command; never a guessed/latest wildcard.
docker compose -p zoclip-private --env-file /etc/zoclip/staging.env -f deploy/compose.yaml run --rm --no-deps backup verify --manifest MANIFEST.json
```

This command leaves writers stopped. Copy exactly the manifest and its two
referenced ciphertext files to an approved separate host/storage account using
an independently verified SSH host key, dedicated restricted backup key,
BatchMode=yes and StrictHostKeyChecking=yes. Upload ciphertext first and manifest
last; compare remote SHA256s. A prepared manual transfer pattern is:

```sh
sudo scp -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=APPROVED_BACKUP_KNOWN_HOSTS -i APPROVED_BACKUP_KEY /var/backups/zoclip/BACKUP.db.age /var/backups/zoclip/BACKUP.media.age APPROVED_BACKUP_USER@APPROVED_BACKUP_HOST:APPROVED_PRIVATE_DIRECTORY/
sudo scp -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=APPROVED_BACKUP_KNOWN_HOSTS -i APPROVED_BACKUP_KEY /var/backups/zoclip/BACKUP.json APPROVED_BACKUP_USER@APPROVED_BACKUP_HOST:APPROVED_PRIVATE_DIRECTORY/
sudo ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=APPROVED_BACKUP_KNOWN_HOSTS -i APPROVED_BACKUP_KEY APPROVED_BACKUP_USER@APPROVED_BACKUP_HOST sha256sum APPROVED_PRIVATE_DIRECTORY/BACKUP.db.age APPROVED_PRIVATE_DIRECTORY/BACKUP.media.age
```

No endpoint/user/key/path is supplied or contacted by this repository. Never use
StrictHostKeyChecking=no. Before restarting, checksum verify, record off-server
receipt and run the approved restore cadence. Restart existing workload without
migrating: `python3 deploy/manage.py resume --env-file /etc/zoclip/staging.env
--project zoclip-private --execute-local`. This starts existing containers without
recreating them or rerunning the migrator. Confirm health, outbox and balances.
On backup/copy failure keep staging
stopped and alert; the sample timer requires an operator maintenance procedure.

Proposed policy for approval: nightly encrypted backup, seven daily and four
weekly off-server recovery points, monthly restore drill, RPO<=24h, RTO target4h.
These are targets, **not achieved SLA or automatically enabled deletion**. Keep
prior verified backups until replacement restore passes; do not retain private
media indefinitely. An approved deletion/legal/financial policy must reconcile
backup retention with erasure. No automatic backup deletion is implemented.

## Separate-target restore drill

Keep the age private identity offline/off the application host. Mount it only
into a manually approved restore container using a private staging directory with
host permissions like the other single-file secrets. Never bake it into an image
or pass it in an environment variable. Restore on an isolated recovery host with
reviewed PostgreSQL17/tools images, no public ports and no provider egress.

Create a **new** database owned by the schema-owner role ending `_restore` or
`_restore_test`, with no application connections. Create a new empty media volume
owned by10001. Set PGHOST,PGUSER,PGDATABASE (nonsecret metadata), mount a pgpass
file at `/run/secrets/backup_pgpass`, identity at `/run/secrets/backup_identity`,
ciphertext directory read-only at `/backups`, empty volume at `/restore-media`.
The explicit command inside the tools container is:

```sh
python3 /opt/zoclip/backup.py restore --manifest MANIFEST.json
```

The image entrypoint already runs `python3 /opt/zoclip/backup.py`, so image arguments
are simply `restore --manifest MANIFEST.json`. Use the actual COPY destination in
deploy/Dockerfile.ops if building a changed image. The tool refuses a populated
database or nonempty media; it never drops/cleans an existing database. DB restore
is one transaction, archive extraction admits only safe regular files/directories,
rejects links/traversal/duplicate files, ignores archived owners/modes and retains
20 GiB disk headroom. It streams files into exclusive mode0600 targets and verifies
authenticated decryption through stream EOF.
If extraction/decryption fails, quarantine the separate target; do not promote or
reuse it as an empty target. Preserve diagnostic state for investigation.

Verification before promotion:

1. Decrypt/restore both files, compare the recorded media fixture hashes or complete
   inventory and private application reads. Confirm migration head/schema drift.
2. Reapply reviewed role/default privileges and `deploy/migrate.py` grant revocations
   using the schema owner: pg_dump intentionally excludes roles/ACL/ownership.
   On recovery host configure the runtime role first; never run app as superuser.
3. Reconcile every wallet against its append-only ledger, held reservations and
   provider exposure; inspect payment events/idempotency and immutable audit rows.
4. Reapply privacy erasure requests/tombstones committed after the backup **before**
   opening access. Restore can resurrect expired media/tokens; run bounded cleanup
   while isolated, revoke old sessions and review retention/legal holds.
5. Keep paid APIs/payments disabled. Compare post-backup provider/merchant evidence
   privately before reenqueuing outbox work; UNKNOWN attempts/refunds never blindly
   retry. Redis replay must respect PostgreSQL job fencing and exactly-once money.
6. Smoke authentication/IDOR/admin, files, queues, deletion and a safe fixture
   render, then obtain explicit promotion approval. Record restore duration,
   actual recovery point, operator and off-server retrieval evidence.

The local automated drill is `scripts/phase7_smoke.py`; it creates its own separate
restore DB/volume and compares seeded ledger deltas/private media hash, then checks
overwrite refusal. It is not a customer-data restore or a remote deployment.

References: [PostgreSQL17 pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html),
[default privileges](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html),
[age encryption](https://github.com/FiloSottile/age).
