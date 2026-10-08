# Changelog

## 1.1.0rc1 — 2026-10-08

### Professional operator support
- Searchable ticket queue, with category, priority, assignee, first-response SLA, audit trail and escalation.
- Operator private notes; manual closing, resolution summary and reopening.
- Live dashboard overdue/urgent indicators.
- Consecutive manual Business replies retain FIFO order; uncertain deliveries block later human sends until staff resolves the ambiguity.
- Only confirmed Telegram delivery or an observed Business-owner reply satisfies the first-response SLA.

### AI assistance and controlled learning
- Optional operator-only AI draft suggestions. Human staff must review, edit and explicitly click Send.
- Conservative financial response templates, approved FAQ lookup and daily model-call budget.
- Completed tickets can generate *unpublished* FAQ candidates. Separate operator review and approval required.

### Message processing and privacy
- Configurable short-burst bundling to avoid multiple model calls for consecutive customer messages while retaining individual source messages.
- Configurable periodic and CLI-driven scrubbing of old text, media file references, draft replies, internal notes, unreviewed knowledge suggestions and completed ticket summaries.
- Explicitly confirmed local conversation deletion with dependency cleanup and blocking safeguards for uncertain deliveries.

### Data and rollout
- New reversible schema migration files 0005, 0006, 0007. Existing deployments MUST back up and test restores before applying migrations.
- Full Python/SQLite and PostgreSQL test coverage for these flows, and Docker build smoke tests.
- New installations remain monitor-only by default.
- This is a release candidate, NOT a production certification. Live Telegram Business integration and installed panel versions still require staging acceptance tests.

## 1.0.0rc1 — 2026-10-08

- Initial Business Bot API gateway, editable inline menu, structured workflows, human handoff, read-only Marzban/Pasarguard adapters, admin UI and self-hosted PostgreSQL/Docker setup.
