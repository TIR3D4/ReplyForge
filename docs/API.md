# ReplyForge API reference (V1)

All endpoints require HTTPS at the deployment ingress.

### POST /telegram/webhook

Used by Telegram. Authenticate with X-Telegram-Bot-Api-Secret-Token. The request is durably queued by update_id. Duplicate updates are safe. Do not expose a predictable secret.

### POST /api/bindings

For a connected shop/billing system to register a subscription link with its provider's user ID. Authentication: X-Internal-Api-Key. JSON:

~~~json
{
  "link": "https://example.com/sub/SECRET",
  "provider": "marzban",
  "user_ref": "username",
  "label": "optional private label",
  "customer_chat_id": 123456789
}
~~~

For Pasarguard use provider=pasarguard and a **numeric** panel user ID. If customer_chat_id is supplied, that Telegram chat ID must match the requesting user. This returns an opaque association ID. The plaintext URL is never persisted in subscription_bindings; a peppered HMAC fingerprint is used.

**Never** paste a real token into a public GitHub issue, test fixture or shell history shared with others.

### GET /healthz

Returns service health after a database check.

### GET /admin

HTTP Basic authentication required, over HTTPS. Dashboard includes latest conversations, tickets, knowledge entries and uncertain delivery. Form mutations require a separate CSRF token.

### GET /admin/conversations/{id}

Review a conversation with redacted message history. Forms permit manual takeover/resume, which increment revision to cancel stale outgoing messages.

### Local CLI

- replyforge init — create the current schema for a new empty database.
- replyforge worker — process inbound events and outbound messages.
- replyforge check-config — validate YAML.
- replyforge set-webhook — register allowed Telegram Business update types.
- replyforge webhook-info — inspect Telegram registration.

Healthcheck alone does not demonstrate end-to-end Telegram delivery. Perform a live customer-to-Business-account smoke test.


### GET /readyz
Checks PostgreSQL plus the processing Worker heartbeat. Returns HTTP 503 if the Worker is stale or missing, with pending/dead update counts.

### POST /admin/automation
Authenticated and CSRF-protected operation. Accepts enabled=true/false. New deployments start in monitor-only mode; the administrator must explicitly enable AI replies.

### POST /admin/conversations/{id}/reply
Sends a real operator reply from the connected Telegram Business account. Requires valid Telegram reply permission and a recent inbound message. Sends use the durable outbox and show confirmed/uncertain status in the conversation view.

### Import existing subscriptions
Run `replyforge sync-subscriptions --provider both --limit 2000` after configuring read-only panel credentials. The import reads `/api/users` in pages and stores both full-link and relay-compatible token HMAC values. No raw token or arbitrary customer URL is fetched. Providers can also be imported separately.

### Media settings
`AI_VISION_ENABLED` and `AI_VOICE_ENABLED` are opt-in. Downloads are limited by `AI_MEDIA_MAX_BYTES`; only screenshot diagnostics or transcription are sent to the selected AI provider. Financial receipts bypass model vision.
