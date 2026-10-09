# ReplyForge 1.2.0rc1 — Live acceptance test plan

This test plan is a **release gate**, not a claim of prior production validation. Automated tests use simulated Bot API and provider responses. Do the following on a staging Business account with explicit participant permission before enabling ReplyForge for public customers.

## Prerequisites

- The exact reviewed commit being installed has successful GitHub Actions CI (Python, Postgres, Docker).
- Dedicated HTTPS domain and TLS reverse proxy; admin interface restricted to operators.
- Telegram bot in Business/Secretary mode, with read and reply permissions for test chats.
- One worker process, database initialized via Alembic, offsite encrypted backups.
- `AUTO_REPLY_ENABLED=false` to start; configured operator `SUPPORT_ALERT_CHAT_ID`.
- API credentials scoped as read-only to your Marzban/Pasarguard instances.
- No production credentials, receipts or subscription tokens in GitHub issues or logs.

## Test cases and expected behavior

| ID | Scenario | Required observable outcome |
|---|---|---|
| TG-01 | New inbound message with AI disabled | Appears in admin inbox, **no automatic customer reply** |
| TG-02 | Human reply from dashboard | Message appears as current Business account; delivery status recorded |
| TG-03 | Wrong / expired Business rights | Response is prevented and operator can see failure |
| TG-04 | Toggle AI on, first contact | One menu message; the choices work |
| TG-05 | Tap choice, then back | Same message edited wherever Telegram permits |
| TG-06 | Tap a stale callback after newer menu | Stale action ignored; no duplicated workflow |
| TG-07 | Customer writes three short messages | Short text burst coalesces into one model request when safe while retaining each individual Telegram message |
| TG-08 | Customer writes device/app in first message | Device and app are not asked a second time |
| TG-09 | Customer shares an imported Marzban subscription | Current status returned without disclosing the link |
| TG-10 | Customer shares Pasarguard tunnel subscription | Current status returned using read-only panel API |
| TG-11 | Same token through a known relay domain | Same account resolved if token is unique |
| TG-12 | Unknown or ambiguous token | Human handoff; no account information disclosed |
| TG-13 | Subscription inactive/expired | Accurate state, no invented network diagnosis |
| TG-14 | Partial panel outage / timeout | Graceful human handoff |
| TG-15 | VPN app update does not work | Different-network diagnostic, then handoff |
| TG-16 | Client confirms issue fixed | Feedback-positive audit written |
| TG-17 | Client says issue unresolved | Feedback-negative audit and human handoff |
| PAY-01 | Customer says receipt not approved | Ask time, then receipt; never falsely mark payment verified |
| PAY-02 | Receipt over 15 min old | Optional SMS debit image (masked), then human review |
| PAY-03 | Customer sends image after human handoff | Image visible to operator; customer does not get unwanted AI reply |
| MEDIA-01 | Technical screenshot with vision off | No third-party image inference; usable manual path |
| MEDIA-02 | Vision on and a safe technical screenshot | Bounded image inference; no financial confirmation |
| MEDIA-03 | Voice processing off | Clear text fallback; no transcription API call |
| MEDIA-04 | Voice processing on, short voice | Transcription available for routing (bounded usage) |
| SAFETY-01 | Owner types to customer | AI yields ownership and cancels queued reply |
| SAFETY-02 | Emergency AI pause during queued reply | No new automated response; operator remains functional |
| SAFETY-03 | Telegram send response becomes ambiguous | Outbox marked uncertain; no blind duplicate sends |
| SAFETY-04 | Restart worker mid-queue | Queue recovers or marks ambiguous delivery for manual review |
| SAFETY-05 | Two rapid operator replies | Both messages eventually send in FIFO order, neither silently canceled |
| SAFETY-06 | Unknown outcome of earlier operator send | Later send stays blocked until manual reconciliation |
| SAFETY-07 | Close ticket after human takeover | AI remains paused and does not resume implicitly |
| OPS-04 | SLA expires during continuous queue activity | Worker alerts on schedule with one audit record |
| OPS-05 | Human reply enqueued, but Telegram delivery fails | Initial-response SLA stays open; later genuine delivery closes it |
| AI-01 | Click Suggest Reply | Draft only, visible to operators; nothing is sent to customer |
| AI-02 | Suggest for disputed payment | No unsupported paid/confirmed statement |
| KB-01 | Close ticket with verified resolution summary | Unpublished FAQ candidate appears for review |
| KB-02 | Reject FAQ candidate | Answer never becomes part of active knowledge |
| PRIV-01 | Retention sweep | Historical text, attachment references, notes and resolution summaries scrubbed |
| PRIV-02 | Explicit local erasure | Customer data and dependent records removed from ReplyForge, not from Telegram |
| PRIV-03 | Erasure requested with uncertain outbound send | Rejected pending manual reconciliation |
| OPS-01 | Stop worker process | `/healthz` may stay 200; `/readyz` becomes 503 |
| OPS-02 | Restore from encrypted backup to staging | Restored conversations and migrations validate |
| OPS-03 | 100+ controlled test conversations | No unwanted cross-chat data leakage; inspect latency and backlog |

## Deployment acceptance rules

- **Block public activation** if TG-01 through TG-07, SAFETY-01 through SAFETY-07, OPS-05, KB-01 or PAY-03 fail.
- **Block live subscription diagnostics** until TG-09 through TG-14 pass on the actual panel versions.
- **Keep media AI off** until appropriate customer disclosure and MEDIA-01 through MEDIA-04 are verified.
- Define acceptable response latency, backlog and operator staffing before broad activation. A model answer is not equivalent to successful issue resolution.

## What V1 still does not claim

- Import of pre-connection history from a Telegram account: Bot API cannot fetch arbitrary historical direct messages.
- Automatic verification of a bank transfer from a screenshot or SMS.
- Guaranteed end-to-end delivery or exactly-once Telegram sends.
- Multi-worker scheduling with per-chat fencing and parallel high-volume workloads.
- Full autonomous debugging of live network nodes, or automatic account mutations.

Promote by progressively enabling on test chats, then a limited real-customer cohort, while retaining an immediately accessible admin pause and human support.

## 1.2 additional live gates

- AI-03: Enter known model prices and a small approved budget; validate recorded usage against provider billing. Unknown prices must prevent calls.
- AI-04: Trigger a provider timeout; the reservation remains and no blind fallback is made.
- INS-01: Import only authorized/redacted history, refine one candidate with the isolated Insight worker and confirm no automatic knowledge publication.
- INS-02: Manually mask a synthetic screenshot, submit only after review, check proposed observations and temporary-pixel erasure. Do not use a real receipt for this test.
- OPS-06: Rehearse a backup from this installation in a separate database and verify both credentials and application data. Synthetic CI restore alone is insufficient.
