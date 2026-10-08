# Security policy

Report vulnerabilities privately to the repository owner through GitHub's private vulnerability reporting feature where supported. Do not create public issues containing credentials, customer data, subscription links or exploitation instructions.

## Threat model and intentional limits

- Webhook authenticity is checked against the Telegram-provided secret header with constant-time comparison.
- The admin web interface requires HTTPS HTTP Basic and per-form CSRF validation. Basic authentication by itself is unsuitable for an exposed public administrative endpoint without TLS and additional access restrictions.
- The internal subscription mapping API requires an independent API key.
- Customer-supplied URLs are never fetched. Only explicit, administrator-configured Marzban and Pasarguard API base URLs can be contacted.
- Subscription links are stored only as HMAC-SHA256 fingerprints. Change BINDING_PEPPER only when ready to re-associate all links.
- Incoming message text is redacted for links, obvious credentials and card-like numbers before durable history storage. Redaction cannot identify all forms of PII; establish retention/deletion policies for your jurisdiction.
- Telegram webhook updates temporarily contain raw data in the queue until processed, and photo file IDs are retained as ticket metadata. Treat PostgreSQL and backups as sensitive.
- The AI provider receives redacted text for bounded classification and FAQ selection. If the operator explicitly enables vision or voice processing, selected diagnostic media may also be sent to the configured model provider. Raw panel credentials and raw subscription links are never sent; financial receipt images are kept on the human review path.
- No model-generated string can become a SQL query, file command, arbitrary HTTP request, financial approval or configuration mutation.
- Conversation ownership is checked before any outgoing send; a delivery timeout is marked uncertain instead of auto-retried.
- Limit operator/admin and panel access to trusted personnel.

## Data retention

By default, the worker scrubs message contents and Telegram media file IDs older than DATA_RETENTION_DAYS (180 days), and old terminal outbound texts and internal suggestions/notes. Set DATA_RETENTION_DAYS=0 to disable automatic scrubbing. This does not remove conversation IDs, billing records, database backups or data stored by Telegram, model providers, or VPN panels; deployers still need a suitable privacy and backup-retention policy.

## Limitations

The system is not a payment processor, anti-fraud engine or secret vault. It has not undergone an independent security audit. Regular dependency updates, backup restoration drills and live integration tests remain required.


## Media processing changes

Media analysis is disabled by default. When a deployer opts into screenshot reading and/or voice transcription, selected media is fetched from Telegram's fixed file endpoint with a configured size bound and may be sent to the configured AI provider. The engine treats image text as untrusted and does not validate payment or financial claims from a screenshot. Operators must disclose this processing and protect logs and backups.

## Subscription catalog matching

Trusted Marzban/Pasarguard admin APIs may be used to list existing users. Only HMAC fingerprints of their long bearer tokens are stored; relay URL normalization does not make the bearer token public. An unknown, short or ambiguous token is not a verified subscription. The system never fetches a URL supplied by a customer.

## Staged activation and operator control

New installs default to monitor-only mode. The authenticated admin can pause automated customer replies immediately while leaving human replies available. Database worker heartbeats enable alerting when background processing fails. The Telegram Business reply time window is still enforced.
