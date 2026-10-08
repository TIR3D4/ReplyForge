# Architecture Decision Record — V1

## Execution topology

The core is a **modular monolith**, not a swarm of untrusted autonomous agents.

1. HTTPS reverse proxy receives Telegram updates.
2. FastAPI authenticates the Telegram secret and writes each update once to PostgreSQL.
3. The single default worker claims an update, locks its conversation row, applies a deterministic state transition, and stores an output intent.
4. Outbox transport dispatches an approved message through the Business Bot API.
5. An operator can take over and stop further AI proposals.

### Data flow

~~~text
Telegram Business -> FastAPI webhook -> incoming_events -> Worker
                                          |                 |
                                     PostgreSQL        State machine
                                          |          /   |    \   \
                                          |       FAQs  AI  providers human
                                          |                 |
                                    Outbox <--------------+
                                          |
                                    Telegram Bot API
~~~

## State and concurrency

Conversation identity: (business_connection_id, chat_id), with a database uniqueness constraint. Every transition increments revision. Inline menus store an unpredictable nonce, plus a server-side array of permitted actions. Callback actions are never trusted directly from user-supplied strings.

The event lease is a *recovery* mechanism, not a parallel per-chat work scheduler. **Run only one worker instance in V1**; scaling requires per-chat serial scheduling, lease renewal and fencing. PostgreSQL SKIP LOCKED avoids simultaneous row claims but does not by itself guarantee ordered execution of two queued updates for the same conversation with multiple workers.

A Telegram send outcome may be unknown after an HTTP timeout or process crash. A prior in-flight send becomes **uncertain**; it must be inspected and resolved manually. This chooses at-most-one automatic attempt over blind retries, not mathematically guaranteed exactly-once delivery. Confirmed edits can be retried safely only when semantics are proven idempotent.

## Ownership and human handoff

Modes: ai, human_pending, human. Customer messages are always recorded; only ai mode can invoke the AI workflow. Human pending is created by explicit request, failed authorized lookup, or unresolved knowledge, with an open ticket. Owner-origin Business messages set human immediately. Admin resume clears the previous workflow and increments the revision.

Active business playbooks are stored as versioned, validated YAML. Superseded conversation workflows reset safely instead of continuing under an incompatible schema. A pre-send revision check cancels stale outbox work. A race still exists if a human types *after* the check and *while* a network send is in-flight. Full distributed atomic send coordination is impossible across Telegram and PostgreSQL. Production governance should monitor this and maintain an operator emergency pause.

## Security boundaries

Untrusted: inbound Telegram text, URLs, callback payloads, images, file names, model output. Trusted only after validation: Webhook secret, admin authentication, local config, business rights, authenticated internal provisioning API and panel data with a known shape.

The model selects only predefined menu actions or options. It cannot execute SQL, call arbitrary HTTP URLs, access panel tokens or declare a receipt paid. Links are fingerprinted with an environment-bound HMAC pepper. Unknown links lead to human support.

## Explicit V1 limitations

- No automatic payment confirmation, renewals, provisioning or subscription mutation.
- No retroactive customer history before bot connection.
- No multi-worker horizontal processing guarantee.
- No per-account business settings within one deployment.
- No semantic vector embeddings or image OCR in V1; approved FAQ lookup uses lexical search plus optional model selection from a bounded list. Images are collected for manual review.
- Database schema is initialized by Alembic migration 0001 on first boot. All future schema changes require reviewed forward migrations, backups and a staging rehearsal.


## V1.1 support-hardening additions

- Monitor-only startup and audited admin automation switch.
- Real human reply outbox, operator message capture, follow-up evidence alerts, safe menu handoff edits.
- Optional bounded screenshot and voice analysis; financial documents excluded from model vision.
- Subscription catalog backfill and URL-token fingerprints for trusted relay-domain links.
- Durable worker heartbeat and readiness endpoint; explicit human-feedback outcome metrics.
- Rule-based slot extraction prevents redundant device/application questions.

The LLM remains a bounded classifier and approved-FAQ selector; it is **not** given arbitrary terminal, database or network tools. A privacy-controlled learning pipeline and end-to-end production integrations need additional review before full autonomy.
