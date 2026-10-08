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
