# Administration and Insight

## Access and roles

The bootstrap administrator comes from `ADMIN_USERNAME`/`ADMIN_PASSWORD`. `/admin/operators` creates separately hashed staff credentials. An operator can access the ticket inbox, conversation evidence, notes, drafts, replies, triage and takeover/resume. Only administrators configure the agent, publish knowledge, import/erase Insight data, manage users or change the business playbook. Disabling a staff account prevents subsequent authenticated requests. Staff passwords can be rotated in the same UI. Login attempts are throttled in the database by an HMAC of the source IP (30 per five-minute bucket); configure the trusted reverse-proxy boundary carefully. The current bootstrap secret is rotated through `.env` and a service restart; this is HTTP Basic authentication, not an MFA/session system.

## Agent settings and test playground

`/admin/agent` stores the active model, optional fallback, output-token bound, daily calls per chat and media opt-ins. The API endpoint and secret remain environment configuration. The fallback is attempted only after a definite 429/500/502/503/504 response, not a timeout with unknown provider cost. Each attempt consumes call permission. Daily configured-price cost reservations persist independently of support transactions, including timeouts. Enter positive input/output USD-per-million prices covering the most expensive configured model; unknown pricing blocks requests. `/admin/system` shows reservations, actual reported tokens and uncertainty. This is not a provider billing guarantee, particularly for media; apply provider-side spending limits. Production external AI during support processing requires PostgreSQL; SQLite may fail closed on independent write contention. Insight currently shares the daily per-scope call limit under one `insight` scope; it is a global analysis-call allowance, not a per-import allowance.

The playground classifies entered text into permitted menu routes. It does not send a Telegram message and is not a full simulation of every conversation/tool. Payment confirmation, subscription facts and server-health assertions are never inferred from arbitrary model output.

## Workflows, branding and knowledge

`/admin/playbook` supports validated versioning/rollback, creation of new flows and typed steps, choice options, branch targets and start selection without YAML. Advanced playbooks can still use the YAML editor. This is a guided form editor, not drag-and-drop. The UI supports up to six options per edited choice; more complex graphs require the advanced editor. Branding, locale, welcome, menu and handoff text belong in the business playbook. The core stays generic; choose `examples/azadbird.yaml` for the VPN preset.

Approved knowledge appears on the dashboard. Conversation-generated candidates and Insight candidates have separate review queues. Publishing requires explicit administrator submission. Treat a historical operator answer as untrusted until generalized and checked.

## ReplyForge Insight import

1. Export authorized support conversations from Telegram Desktop as machine-readable JSON. This is an offline export; ReplyForge never asks for a Telegram login session.
2. Upload the JSON, or a ZIP containing exactly one `result.json` and associated media. Limits: 16 MiB upload, 32 MiB expanded ZIP, 10,000 entries and 100,000 scanned messages. Split larger exports. Paths are inspected in memory, never extracted to disk.
3. Supply the operator sender identifiers as found in the export (`user123` format, space-separated). These distinguish operator replies from customer questions; do not infer them from display names.
4. Select 100, 200, 500 or a custom 1–5000 conversation limit. Private chats only; a candidate needs both customer and operator messages. The limit is a maximum, not a guarantee that enough eligible conversations exist.
5. The local parser drops sender names, redacts common sensitive patterns, bounds recent conversation text, removes duplicates and classifies common topics without external model calls. Exact repeated import parameters reuse the previous import.
6. Review each question/answer. Remove personal details, subscription identifiers, customer-specific balances/payment assertions and obsolete instructions. Approve to create active knowledge, or reject. No learned content is published automatically.
7. To erase an import, use its explicit ERASE form. Already published knowledge is independent and must be removed separately. Scheduled retention scrubs old candidate text.

Import processing remains bounded, synchronous and local. Associated media are inventoried, not automatically uploaded to a model. Start the isolated model worker with `docker compose --profile insight up -d --build insight`, then request refinement for selected candidates. The job commits its claim before external requests. A crash leaves an uncertain task for explicit retry, not repeated paid execution. Proposals include FAQs and troubleshooting steps; an administrator must review and explicitly publish each FAQ or generated workflow. Outcomes remain unverified.

For selective image analysis, choose a relevant local export image, manually cover identifiers on the browser canvas and consent to provider submission. Only the canvas PNG is submitted; selecting another image or resetting masks clears prior consent. This is manual redaction, not automatic PII detection. Limits: local file 10 MiB / 40 million pixels, reviewed canvas 1600px per side / 2 MiB. Reviewed pixels are held in PostgreSQL only until processing completes/fails, crash expiry, erasure or retention. A failed vision request is not reported as successful text-only analysis. Text pattern redaction is best effort; manually inspect sensitive source text before optional external refinement. Online customer vision is a separate opt-in path and does not use this manual image editor.

Successful candidate results are reused for review; duplicate import fingerprints are reused locally. There is no general semantic/vision cache or automatic bulk media pipeline. The first import stage has no asynchronous recovery; split large exports. All previously published knowledge/workflows remain independent of import deletion.

## Provider gates

Set `MARZBAN_EXPECTED_VERSION` or `PASARGUARD_EXPECTED_VERSION` to the exact staging-validated semantic version to require a matching `/api/system` response before account lookup. A mismatch blocks lookup and follows the existing human-escalation path. Leaving a value empty retains schema-validated lookup without version probing. PasarGuard requires `system.read` for the optional version check; do not broaden a key silently. Revalidate before changing the version pin.

## Unified inbox and notices

`/admin/inbox` combines a filtered/paginated conversation list with selected message history and a human reply composer. Detailed ticket assignment, notes and reconciliation remain on the linked conversation/ticket pages. `/admin/connections` includes an administrator-authored service notice shown with the welcome menu; it is not automatic server-health detection.

## Delivery reconciliation

An `uncertain` delivery is not a failed delivery. Inspect the real Telegram conversation, then explicitly confirm sent or cancel in the dashboard. Never blindly re-enqueue it. Human reply FIFO remains blocked behind uncertainty. Staff should understand that an already-running external send can finish before a takeover request is committed.
