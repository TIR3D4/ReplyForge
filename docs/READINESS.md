# Production-readiness audit and delivery record

Audit baseline: `e2243763462470cf3bcd2edd185a5dac70c5d696` (1.1.0rc1).
Development branch: `development/production-readiness`.
Review: [PR #4](https://github.com/TIR3D4/ReplyForge/pull/4).
Date: 2026-10-08. All test identities and screenshots use synthetic data.

**Assessment: suitable for supervised staging; not yet the complete M0–M6 product or an unconditional production release.** Passing tests establish the tested boundaries, not autonomous problem-solving quality, security certification or compatibility with an untested live panel.

## Audit findings and implemented changes

| Finding in baseline | Change | Verification |
|---|---|---|
| Retry delays capped below Telegram retry_after; no delivery attempt limit | Honor confirmed rejection delay, cap five attempts, preserve uncertain results | `test_delivery_hardening.py`, Telegram mock tests |
| Reply window advanced by processing time | Use inbound Telegram date, prevent clock rollback and clamp future dates | Delivery hardening regressions |
| Menu removal omitted explicit empty keyboard | Send an empty inline keyboard on edit; expire callback nonce after 30 minutes | Telegram and callback regressions |
| Human takeover could commit between delivery revision check and send | Hold conversation row lock through bounded send and finalization; use consistent conversation-before-ticket locks | PostgreSQL concurrent takeover test; ticket tests |
| A second worker could reorder state transitions | Session advisory lock enforces one PostgreSQL worker; fail on lock connection loss | PostgreSQL exclusivity test |
| Retrying an earlier event allowed newer input to advance a flow | Global inbox FIFO including backoff/active leases; archive late message IDs without advancing state | `test_queue_ordering.py` |
| Worker as PID 1 did not drain on SIGTERM | Stop claiming after signal, finish current work, release advisory lock | Shutdown unit test and Compose restart smoke |
| Provider schema omissions became unlimited/unknown status | Required typed fields, strict status/traffic checks, safe user references | `test_provider_contracts.py` |
| No version fence against unplanned panel upgrades | Optional exact-version `/api/system` gate per independent adapter | Mock changed/matching version tests; live versions untested |
| No separate staff identities or roles | Scrypt password hashes, admin/operator allowlist, disable control | `test_operator_roles.py` |
| Unbounded request parsing and incomplete redaction | Streaming body bound, security headers/CSP, more PII patterns, prompt redaction | Security/config/Insight tests |
| Sensitive workflow answers survived text retention | Scrub inactive old workflow state and invalidate menus; preserve unresolved delivery evidence | SQLite and PostgreSQL retention tests |
| No historical import/review subsystem | Separate Insight module, bounded JSON/ZIP import, local deduplication, review-only candidates, explicit publication/erasure | `test_insight.py` |
| No runtime model policy or sandboxed test form | Validated model/fallback/output/call/media policy and routing playground | Policy and bilingual evaluation tests |
| Fragmented legacy administration pages | Shared responsive shell, RTL/LTR, themes, staff/AI/Insight/connections/system pages, guided workflow prompt editor | Actual Chromium on 1440px/360px in both locales |
| Browser submission errors exposed raw JSON | HTML error pages for browser requests; preserve API JSON behavior | Operator control regression |
| Installation only exercised build/migration | Disposable Compose deploy, health, restart, dump and isolated restore; pinned runtime dependencies | Actions Docker smoke and dependency audit |

## Phase coverage against the requested program

| Phase | Delivered | Still needed for the full requested phase |
|---|---|---|
| M0 | Source/config/schema/UI/test audit; implementation/test/licensing research for all 12 named projects plus Taskiq with commit SHAs | Independent review of this large change set |
| M1 | Durable Business inbox/outbox, echo/deduplication, permission handling, expiring callbacks, bounded retry, ownership locking and worker recovery | Live Business acceptance, sustained load/soak and failure-network testing; multiworker scheduling remains unsupported |
| M2 | Deterministic workflows, bounded intent/choice and approved FAQ selection, recent context/slots, model fallback policy, operator drafts, bilingual mock/rule evaluations | General reasoning agent with audited tool registry, reliable token/dollar ledger, semantic retrieval, measured live Persian/English resolution benchmark |
| M3 | Real responsive admin pages and forms, RTL/LTR/themes, role-aware navigation, guided existing-step edits, browser screenshots | Rich unified inbox interactions, full no-YAML workflow authoring, comprehensive keyboard/screen-reader audit, session login/MFA and password lifecycle |
| M4 | Independent read-only adapters, schema/version gates, secure link matching, AzadBird troubleshooting/payment flows | Compatibility matrix validated against deployed panel versions; all integration controls in UI; live scope checks |
| M5 | Local text preprocessing/import/deduplication, media inventory, configurable selection, FAQ review/approval/erasure | Durable asynchronous analysis jobs, selective image/OCR/vision redaction, semantic guide/workflow extraction, measured token/cost budgeting |
| M6 | Regression/security/PG/browser/Docker tests, dependency audit, restart/backup restoration smoke, operator/deployment docs | Long-running soak/load, independent penetration review, real Telegram/provider acceptance, recovery from actual infrastructure failures |

## Residual risk register

1. **AI quality and cost:** offline evaluations do not measure a live model. Call counts are not dollar budgets. AI audit writes share the event transaction and can roll back after a failed transition; provider-side spending limits are needed. No claim of complete financial usage accounting.
2. **External effects:** a send already started cannot be revoked by an owner typing in Telegram. Database locks serialize admin takeover with sends but cannot make Telegram and PostgreSQL atomic. Timeout/crash uncertainty requires manual reconciliation; exactly-once external delivery is not promised.
3. **Throughput:** one worker deliberately blocks later inbox events behind an earlier retry, up to the bounded retry/dead-letter policy. Continuous inbox traffic can delay outbox delivery. Scaling requires per-conversation fencing and fair scheduling, not extra replicas.
4. **Authentication:** HTTP Basic needs TLS plus an identity proxy/VPN/IP allowlist. There is no native MFA, session revocation UI or distributed login rate limiter. Added roles are coarse admin/operator; assignment is not per-ticket ACL isolation.
5. **Privacy:** regex redaction is best effort; it cannot identify every name/address or hidden PII in images/audio. Insight never sends imports to an external model. Opt-in online media processing does send original selected media to the configured provider and is not a redacted-media pipeline. Keep it disabled when that is unacceptable. Backups and external services need their own retention policy.
6. **Insight semantics:** candidates are extracted operator text, not validated general truth or proven outcomes. Payment/account-specific statements must be removed during human review. Images are counted, not understood; no automatic guide/workflow publication exists.
7. **Panel compatibility:** exact version equality is an optional deployment fence, not a proof of compatibility. PasarGuard's version probe additionally needs `system.read`; basic account access only needs `users.read`. Catalog sync currently validates its own response contract but does not apply the account lookup version gate.
8. **Security scope:** dependency scanning covers the pinned Python runtime set; it does not certify the base image, browsers, OS, external services, or future vulnerabilities. Customer-scale penetration testing and disaster drills are outstanding.

Do not merge this as a completed production-readiness program. Review the PR, run the live checklist with authorized staging credentials and resolve the scope gaps above before making that claim.
