# Operations & production deployment

## Before first launch

- DNS A/AAAA for a host under your control.
- Docker Compose installed.
- TLS proxy (Caddy, Nginx, Traefik). Only port 443 public. Bind the app to 127.0.0.1:8080.
- Random unique secrets in .env, never in GitHub. Ensure .env is readable only by the deployment user.
- Restrict /admin using an IP allowlist or VPN where possible.
- Confirm Telegram's Business / Secretary bot permission to read and reply and understand the recent-inbound reply window.
- Configure offsite backups and test restoration before handling real customers.
- Only one worker process/container for V1.
- Optional SUPPORT_ALERT_CHAT_ID must point to a Telegram DM/group authorized to receive bot messages; the owner must first start the bot in private chat.

## Suggested reverse proxy (Caddy)

~~~text
support.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
}
~~~

This is a minimal example. Add IP or identity restrictions on /admin before public production use.

## Startup

1. Copy .env.example to .env.
2. Generate distinct tokens and configure WEBHOOK_PUBLIC_URL.
3. docker compose up -d --build
4. docker compose exec api replyforge check-config
5. docker compose exec api replyforge set-webhook
6. docker compose ps
7. Verify HTTPS /healthz (not just local).
8. Send a message to the Business account from another Telegram account and test inline menu, a custom question and human takeover.

## Provider integrations

Marzban: API login uses /api/admin/token and /api/user/{username}. The credentials should be as restricted as your installed Marzban version permits. Pasarguard: prefer a role-scoped API key with users.read, accessing /api/user/by-id/{id}. Access to panel APIs should be limited to the application server by network policies. Never point them at arbitrary URL parameters from messages.

## Backup & restore

Back up PostgreSQL with pg_dump and encrypt the backup. Store independent, expiring backups offsite, monitor outcomes, periodically restore into a **separate** staging database, and never restore over the live database without a confirmed maintenance window. Rotate admin and panel credentials after suspected compromise.

A basic manual dump example:
docker compose exec -T db pg_dump -U replyforge -d replyforge > replyforge-backup.sql

Store backup files securely; they contain redacted chat records and customer metadata.

## Monitoring

Watch: incoming_events in dead status, outbox in uncertain or failed status, length of pending queues, oldest outstanding ticket, worker uptime, service health, recent successful delivery, panel lookup failure rate. Alert on unexpected growth. A temporary AI outage should not impact deterministic buttons; a Telegram send ambiguity must never trigger automatic duplicate messages.

## Known constraints

V1 uses an Alembic initial migration. The Compose init service applies pending migrations before starting API/worker; back up the database and rehearse version upgrades in staging. Do not bypass or downgrade a migration in production. In-flight Telegram send and human intervention can still race; the pre-send version check mitigates but cannot eliminate cross-service races.

## Go-live checklist

- [ ] Secrets configured and non-default
- [ ] HTTPS proxy and admin access restrictions verified
- [ ] Telegram Business rights tested
- [ ] Provider API keys are scoped and tested against real panel versions
- [ ] No customer URL is externally fetched
- [ ] Human handoff and operator takeover tested
- [ ] Outbox uncertainty and worker restart tested
- [ ] Database backup and restore tested
- [ ] User-facing privacy/retention policy published
- [ ] Runbook for API outage and human takeover shared with operators


## Safe activation

ReplyForge starts in **monitor-only** mode (`AUTO_REPLY_ENABLED=false`). Connect Telegram Business, verify /readyz, send a test customer message and issue a human reply from /admin/conversations/ID. Add your approved knowledge base before switching AI on. Use the dashboard emergency pause button to turn off automatic responses without blocking human replies.

## Importing customer VPN accounts

Configure Marzban API credentials and a Pasarguard read-only API key. To index panel-issued subscription links without storing plaintext bearer URLs:

    docker compose exec api replyforge sync-subscriptions --provider both --limit 2000

This is a read-only catalog import; run after subscription creation/rotation or schedule it through your own maintenance tooling. Panel API versions and subscription URL shapes must be verified on the installed instances. Ambiguous mappings require manual intervention.

## Media and privacy

Image interpretation and voice transcription are disabled until AI_VISION_ENABLED or AI_VOICE_ENABLED are explicitly enabled. A subset of technical customer media is transferred to the configured AI provider when enabled. Receipt evidence stays on the operator path; it is not automatically treated as confirmed payment. Publish a privacy policy and a retention/deletion procedure.

## Worker readiness

Check /readyz in addition to /healthz. A green /healthz only proves the web API can query the database; /readyz additionally requires a recent worker heartbeat. Monitor dead inbox events and uncertain outbox messages, and do not blindly resend uncertain deliveries.

## Optional automatic VPN subscription catalog refresh

After verifying both panel APIs and rate limits, run `docker compose --profile vpn up -d catalog` to enable the isolated, read-only `sync-daemon` service (default interval: 60 minutes, max users/provider 2000). It never mutates subscriptions, and failure of one panel does not block the Telegram worker or the other panel. Periodic sync status is retained in `controls`. Deploy only one catalog instance.
