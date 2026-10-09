# Staging the production-readiness branch

This is a development branch, not a release tag. Read [READINESS.md](READINESS.md) before activation. Keep real customer traffic in monitor-only mode until live acceptance succeeds.

## Fresh VPS

Use Docker Engine with Compose v2 and a domain pointing to the VPS. Expose only HTTPS through the reverse proxy; the application binds localhost:8080. Follow the Caddy example in [DEPLOYMENT.md](DEPLOYMENT.md). Restrict `/admin` through a VPN, IP rules or identity proxy.

```sh
git clone https://github.com/TIR3D4/ReplyForge.git
cd ReplyForge
git checkout development/installable-v1.2
python3 scripts/setup.py --preset generic
# For AzadBird use --preset azadbird instead.
# Privately edit .env: BOT_TOKEN, WEBHOOK_PUBLIC_URL and desired optional settings.
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 init
docker compose exec api replyforge check-config
curl --fail http://127.0.0.1:8080/readyz
docker compose exec api replyforge set-webhook
```

The setup script creates `.env` with restrictive permissions and refuses to overwrite one. It is a command-line setup assistant; there is no web first-run wizard. Use generated hexadecimal database passwords to avoid URL-encoding issues. Do not paste credentials into issues, PRs or test logs.

Connect the bot through Telegram Business settings on the existing business account. Test receiving and human replies before enabling automation. Register webhook only after HTTPS works. Review [SMOKE_TEST.md](SMOKE_TEST.md) with an authorized test customer.

## Existing installation upgrade

1. Choose a reviewed commit with successful CI. Record `git rev-parse HEAD` and preserve the old image tag, `.env` and playbook privately.
2. Pause automated replies in the dashboard. Arrange human coverage. Stop the worker and API (and optional insight/catalog services) before migration so old code does not run against a changing schema.
3. Back up PostgreSQL and test restoring the dump to a separate database. The dump and environment secrets are sensitive. Never restore over production as a test.

```sh
umask 077
docker compose stop worker api
docker compose exec -T db pg_dump -U replyforge -d replyforge -Fc > replyforge-before-upgrade.dump
# Copy the dump to protected offsite storage and verify a separate staging restore.
git fetch origin development/installable-v1.2
# Replace REVIEWED_SHA with the reviewed, green commit; do not deploy a moving head blindly.
git checkout REVIEWED_SHA
docker compose build
docker compose run --rm init
docker compose up -d api worker
docker compose logs --tail=100 init api worker
curl --fail http://127.0.0.1:8080/readyz
```

Current migration head: `0011_release_runtime`. This branch adds `0008_delivery_attempts`, `0009_insight` , `0010_operators` and `0011_release_runtime` to the existing migration chain. Never use `alembic stamp` to hide a failed migration. All application containers drop capabilities and have read-only roots; writable temporary files belong in `/tmp`.

## Restore rehearsal and rollback

Create a separate PostgreSQL database or isolated Compose project, restore with `pg_restore`, and start the matching application version against that database. Validate schema head, row counts, operator access and configuration before any traffic switch. `scripts/deployment_smoke.py` automates a synthetic isolated deploy/restart/dump/restore test with a unique project name and disposes only its own volumes; it never uses the installation's `.env`.

If an upgrade fails, keep customer traffic paused. Preserve the failed database for diagnosis. Roll back application and database together to the recorded image/commit and a verified pre-upgrade snapshot in a **new** database, then repoint configuration during a planned maintenance window. Do not automatically downgrade migrations or delete production volumes. Restoring a backup can lose writes after the snapshot; identify and reconcile those writes before resuming. In-flight Telegram sends require manual uncertainty reconciliation regardless of database rollback.

## Troubleshooting

| Symptom | Check/action |
|---|---|
| `/healthz` green but `/readyz` degraded | Worker logs and heartbeat; only one worker is allowed. Second instance fails its advisory lock. |
| Startup migration failed | `docker compose logs init`; inspect error, privileges and database URL. Restore rehearsal before retry. |
| No Business updates | HTTPS webhook info, BotFather Business mode, connected account permissions and selected chats. |
| Cannot reply | Business rights and recent customer inbound window; old queued events do not renew that window. |
| Queue waits behind an earlier event | Retry backoff preserves FIFO; inspect dead-letter/worker errors. Do not start extra workers. |
| Reply uncertain | Inspect Telegram first; reconcile explicitly. No blind resend. |
| Panel lookup escalates | Credentials/scopes, exact-version gate and required response fields; never label an unavailable lookup as unlimited. |
| Import rejected | Export format, sender IDs, private chat eligibility and upload/expanded archive limits. |
| Admin form rejected | Check role, CSRF token and field limits; reload the form. Do not disable CSRF. |
