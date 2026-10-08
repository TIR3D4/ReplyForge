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

V1 schema is created with create_all for initial installation. Upgrade migrations are not yet automated. Avoid deploying schema-incompatible changes to an existing database without a reviewed migration and backup. In-flight Telegram send and human intervention can still race; the pre-send version check mitigates but cannot eliminate cross-service races.

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
