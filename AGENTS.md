# Instructions for AI coding agents contributing to ReplyForge

- The safety of a customer's financial and subscription data takes priority over automation rate.
- No production secrets, customer links, user identifiers or server IPs in code, tests, issues or logs.
- V1 has a single default Worker. Any multi-worker change requires tests for per-chat ordering, leases and fencing.
- New workflow inputs must validate shape and must not permit arbitrary tool or shell calls.
- A new provider adapter must provide read-only status through a typed result and NEVER fetch arbitrary customer-supplied URLs.
- Always include business_connection_id for Telegram Business sends and edits.
- Never retry unknown-result sendMessage automatically. An idempotent edit or a confirmed rate-limit rejection may be retried under bounded policy.
- Inbound payload changes, admin routes and ownership changes need tests.
- Model output is untrusted. Business actions require a deterministic policy layer.
- Keep business-specific branding in YAML presets. Do not hardcode AzadBird text into core logic.
- Make docs and tests accurate; don't claim capabilities the current implementation doesn't offer.
- Do not modify production customer data in tests.
- Python >= 3.11. Prefer explicit return types, short functions, narrow exception handling and PostgreSQL transactions.
- CI: python -m compileall -q replyforge; pytest -q.

- Human replies must preserve FIFO order. A prior uncertain send must block later replies until explicit operator reconciliation.
- First-response SLA can be satisfied only by confirmed Telegram delivery or a verifiably owner-authored reply; enqueue alone does not count.
- AI-generated operator reply drafts must require an explicit human submit action. No autonomous financial confirmation.
- FAQ suggestions extracted from resolved tickets must be approved by a human before publishing to active knowledge.
- Add privacy regression tests for every change in data-retention or local-erasure logic.
- Keep a tested migration chain. Use staged deployment and a verified backup/restore before changes to production databases.
