# ReplyForge ⚡

**Your support. Your AI. Your rules.**

ReplyForge is a **self-hosted, open-source Telegram Business support system** that responds from your *existing* Telegram account through the official Business Bot API. It combines editable inline menus, a declarative support playbook, optional AI intent recognition, a human escalation inbox, an audit trail, and integration adapters. It is not a userbot and does not require sharing an MTProto login session.

[Setup](#quick-start) · [Architecture](docs/ARCHITECTURE.md) · [Security](SECURITY.md) · [Playbooks](docs/WORKFLOWS.md) · [API](docs/API.md) · [Persian guide](docs/README-fa.md) · [Live acceptance tests](docs/SMOKE_TEST.md)

## V1 support hardening — release candidate

- Official Telegram Business connection, including Business permission updates, callbacks, manual-owner takeover, edited/deleted message handling.
- Compact one/two-column inline menu with editing instead of spamming new messages. Stale callbacks are rejected, and handoff edits clear old buttons.
- Durable PostgreSQL inbox/outbox, idempotent incoming update IDs, safe unknown-delivery handling, and event retry limits.
- Configurable YAML menus and **multi-step workflows**: ask for a choice, reference, image, question, subscription link; close or hand off.
- Optional AI intent/choice recognition, semantic selection among approved FAQs, opt-in screenshot reading and opt-in voice transcription with strict file-size and daily model budgets. Rule-driven workflows continue when the model is unavailable.
- A conservative, approved-only FAQ knowledge base. The model never makes up payment status or account balances.
- Default **monitor-only** onboarding (AI replies disabled until an administrator opts in), emergency pause, human handoff, a real operator reply composer, inbound evidence notifications and customer-confirmed resolution tracking.
- Marzban and Pasarguard **read-only account status**, optional catalog sync and HMAC token matching across trusted panel/relay domain variants. The AzadBird preset handles Persian VPN and payment triage.
- Internal link-provisioning API for a store/billing integration. No arbitrary customer URL is fetched.
- English default preset, Persian VPN preset, responsive dashboard and tests.

### Explicit boundaries

V1 is **not** an autonomous payment verifier. A receipt image is collected as evidence for a human; it is not proof that money arrived. It does not automatically issue, renew, revoke or delete subscriptions. It does not read an existing customer's Telegram history from before Business Bot connection, and it does not guarantee network reachability just because an account is active. The base product is a single-deployment workspace; run isolated deployments for separate businesses. Real Telegram and provider credentials are required for production integration tests.

## Production activation criteria

**V1.0.0rc1 is a release candidate, not a claim of production certification.** New deployments default to monitor-only. Before enabling AI for real customers, complete the staged checklist in [docs/SMOKE_TEST.md](docs/SMOKE_TEST.md), using the *actual* Telegram Business connection and installed Marzban/Pasarguard versions. CI cannot replace this live acceptance test.

## Quick start

Requirements: Docker Compose v2, PostgreSQL persistent volume, a domain with HTTPS reverse proxy, a Telegram account with the Business/Secretary chatbot option, and a bot created in @BotFather.

1. Clone the repository and create secrets.
   - Copy .env.example to .env.
   - Generate distinct random secrets for POSTGRES_PASSWORD, WEBHOOK_SECRET, ADMIN_PASSWORD, BINDING_PEPPER and INTERNAL_API_KEY. Use a cryptographically secure generator (example: openssl rand -hex 32).
   - Add BOT_TOKEN from @BotFather.
   - Set WEBHOOK_PUBLIC_URL to your own public HTTPS domain (without the /telegram/webhook suffix).
2. Select the business playbook:
   - Generic: BUSINESS_CONFIG=config/business.yaml.
   - VPN / Persian: BUSINESS_CONFIG=examples/azadbird.yaml.
3. Build and start (the Compose init service applies Alembic migrations before the API and worker):
   - docker compose up -d --build
   - docker compose ps
   - curl http://127.0.0.1:8080/healthz
4. Configure a TLS reverse proxy to forward https://YOUR_DOMAIN/telegram/webhook and https://YOUR_DOMAIN/admin to 127.0.0.1:8080. **Keep the admin behind HTTPS and preferably IP/VPN restrictions.**
5. Register webhook:
   - docker compose exec api replyforge set-webhook
   - docker compose exec api replyforge webhook-info
6. In @BotFather enable Business/Secretary Mode; in Telegram Settings > Business > Chatbots, connect the bot to your support account, permit message reading and replying, and select the correct incoming chats.
7. Open https://YOUR_DOMAIN/admin and authenticate with ADMIN_USERNAME and ADMIN_PASSWORD. Add approved FAQs and, if using VPN support, subscription associations.
8. For human-ticket notifications, start the bot or invite it into a controlled operator group, then set SUPPORT_ALERT_CHAT_ID and restart.
9. **Start in monitor-only mode.** Check /readyz for worker health, inspect real incoming messages, and test operator replies first. Only then click **Enable AI replies** on /admin.

For guided secret generation, run python3 scripts/setup.py --preset generic or --preset azadbird before starting Compose. Existing .env files are never overwritten.

No credentials are stored in the repository. The Bot API only permits replies under the current Business connection rights and the applicable recent-inbound window.

## How customer menus work

The first incoming message is interpreted (if its intent is clear) or opens a generic menu. Menu callbacks reference a short-lived nonce and button index stored in the conversation. Next steps edit the *same* menu message wherever possible, reducing Telegram chat clutter. A free-text reply is accepted while a workflow is active; choices can be interpreted with an LLM if configured. Customers may request a human at any stage. Manual replies from the Business account are treated as a human takeover.

## Personalize without editing Python

Edit active menus, prompts and workflows directly in /admin/playbook with validation, version history and rollback (changes apply on subsequent events; stale in-progress flows reset safely). You can also edit config/business.yaml, the file-backed default, and restart the services. Change brand, language, welcome/handoff text, menu labels, workflows, prompts, options and transitions. Knowledge answers and HMAC subscription associations can be added from the admin UI. See docs/WORKFLOWS.md for the schema and safety rules.

## AI operation

With AI_API_KEY empty, the system still handles all button-driven workflows and a limited set of keyword intents. AI_VISION_ENABLED and AI_VOICE_ENABLED default to false; enabling them sends selected technical screenshots or voice messages to the configured AI provider. Payment evidence is explicitly excluded from model vision. If configured, an OpenAI-compatible chat completion endpoint is used to choose from **allowed** menu actions or workflow choices. It never invents new actions or calls external tools directly. The approved knowledge-answer path returns the stored answer, not model-generated account or financial claims.

## Provider adapters

For Marzban provide MARZBAN_BASE_URL, MARZBAN_USERNAME and MARZBAN_PASSWORD. For Pasarguard provide PASARGUARD_BASE_URL and PASARGUARD_API_KEY with users.read scope. Import panel-issued subscription links using `docker compose exec api replyforge sync-subscriptions --provider both --limit 2000` (or sync one provider), or provision from the admin UI/internal API. Only HMAC fingerprints are stored, never raw links.

The original subscription URL or a forwarded/relayed URL containing the same sufficiently long secret token can match an imported account. No customer URL is fetched. Ambiguous, missing or unauthorized matches open a human ticket. The customer must possess the subscription link; this should be treated as a bearer credential. Never paste panel admin credentials into chat.

## Operating principles

- **Safe on uncertainty**: unknown Telegram delivery remains pending for manual review, never blindly re-sent.
- **State, not just chat history**: workflow, step, answers, menu nonce, revision and human ownership are in PostgreSQL.
- **Least privilege**: model chooses approved actions only; integration adapters expose read-only lookups.
- **Auditable**: human takeovers and resumes are recorded.
- **Human-first**: manual ownership overrides AI, operator replies can be sent from the dashboard, and unresolved cases become tickets.
- **Staged operation**: new installs are monitor-only until explicitly activated; readiness and dead-letter counts are visible at /readyz.

See docs/DEPLOYMENT.md for backups, secret rotation, known tradeoffs, and a production go-live checklist.

## Developer setup

Python 3.11+:
1. python -m venv .venv
2. Activate the environment.
3. pip install -e ".[dev]"
4. replyforge check-config
5. pytest -q

The CI workflow checks compilation and unit/integration tests with mock Telegram and provider APIs. Keep new workflows and adapters covered by tests.

## License

Apache-2.0. Contributions are welcome. Read SECURITY.md before reporting vulnerabilities.
