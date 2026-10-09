# ReplyForge 1.2.0rc1 — release checklist

A checked item means an implementation exists with the stated automated evidence. It does **not** mean live customer acceptance has passed. This candidate is intended for supervised installation, with automation off initially. No production server has been changed.

## Delivered engineering

- [x] Version 1.2.0rc1, source installation archive, SHA-256 checksum and per-file manifest verification.
- [x] Audit of the baseline; source/test/license research for all twelve requested repositories plus Taskiq (`SOURCE_RESEARCH.md`).
- [x] Telegram Business inbox/outbox, duplicate/stale callback handling, permission changes, bounded retries and unknown-send reconciliation.
- [x] Human ownership, operator inbox/reply composer, summaries, ticket SLA/notes and takeover locking.
- [x] Bounded contextual Persian/English intent and device/app extraction, approved FAQ selection and deterministic troubleshooting paths.
- [x] Runtime model/fallback policy, persisted independent cost reservations and daily configured-price budget, tested with concurrent PostgreSQL requests.
- [x] No automatic payment confirmation from receipts, no invented panel facts, read-only authorized adapters.
- [x] Responsive RTL/LTR administration, themes, actual browser form tests and screenshots at 360px/1440px.
- [x] Guided creation/editing of workflow steps, versioned playbooks and explicit knowledge publication.
- [x] Staff roles/password rotation, persisted login throttling, CSRF, request bounds, privacy erasure and retention.
- [x] Independent Marzban/PasarGuard contracts and optional version fences; generic and AzadBird presets.
- [x] Insight local JSON/ZIP preprocessing, 100/200/500/custom selection, deduplication and review queues.
- [x] Durable optional Insight model jobs, reviewed FAQ/guide/workflow proposals, crash uncertainty handling.
- [x] Selective image submission with local manual redaction, explicit consent, temporary pixels erased after processing, failure or retention.
- [x] Compose with migrations, isolated Insight service, CLI installer/doctor and protected backup helper.
- [x] Automated unit/security/workflow evaluations, PostgreSQL locking, browser interactions, Docker restart/restore and pinned Python dependency audit.

Verification is recorded per exact commit and run in [VERIFICATION.md](VERIFICATION.md). Installation instructions: [فارسی](INSTALL_1_2_FA.md).

## Gates still open before public activation

- [ ] Live Telegram Business send/edit/permissions/media/handoff acceptance on the owner's account.
- [ ] Actual Marzban/PasarGuard version and read-only credential compatibility tests.
- [ ] Live Persian/English model evaluation, measured resolution quality and billing reconciliation with an explicitly authorized budget.
- [ ] VPS HTTPS/firewall/access restrictions and customer-data backup/restore rehearsal.
- [ ] Multi-day load/soak, network partition tests, independent security and accessibility review.
- [ ] Staff training, privacy notice, retention/offsite backup policy and incident coverage.

## Scope remaining for the full original M0–M6 vision

- [ ] General multi-tool reasoning agent with semantic retrieval and a measured support-resolution benchmark. Current reasoning selects bounded approved actions.
- [ ] Native session login/MFA, finer-grained per-ticket ACLs and full accessibility verification.
- [ ] All integration secrets/settings managed safely through UI; currently endpoints and credentials remain environment configuration.
- [ ] Automatic image PII detection, large asynchronous import pipelines and broad semantic/vision caching. Current imports are bounded/local; masking is manual.
- [ ] High-volume parallel workers with per-conversation fencing and fairness. Current deployment intentionally permits one Telegram worker.

No exactly-once Telegram delivery, automatic financial proof, unrestricted provider compatibility or full M0–M6 completion is claimed. These unchecked items cannot be truthfully marked complete by a version bump.
