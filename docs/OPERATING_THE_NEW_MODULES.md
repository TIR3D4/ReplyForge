# Administration and Insight

## Access and roles

The bootstrap administrator comes from `ADMIN_USERNAME`/`ADMIN_PASSWORD`. `/admin/operators` creates separately hashed staff credentials. An operator can access the ticket inbox, conversation evidence, notes, drafts, replies, triage and takeover/resume. Only administrators configure the agent, publish knowledge, import/erase Insight data, manage users or change the business playbook. Disabling a staff account prevents subsequent authenticated requests. The current bootstrap secret is rotated through `.env` and a service restart; this is HTTP Basic authentication, not an MFA/session system.

## Agent settings and test playground

`/admin/agent` stores the active model, optional fallback, output-token bound, daily calls per chat and media opt-ins. The API endpoint and secret remain environment configuration. The fallback is attempted only after a definite 429/500/502/503/504 response, not a timeout with unknown provider cost. Each attempt consumes call permission. A maximum token value is an output bound, not exact financial accounting. Apply provider-side spending limits.

The playground classifies entered text into permitted menu routes. It does not send a Telegram message and is not a full simulation of every conversation/tool. Payment confirmation, subscription facts and server-health assertions are never inferred from arbitrary model output.

## Workflows, branding and knowledge

`/admin/playbook` supports validated YAML versioning/rollback plus a form to update an existing input step's prompt and next step. Choice options and new graph structure still require the YAML editor. This is a guided editor, not a complete drag-and-drop workflow designer. Branding, locale, welcome, menu and handoff text belong in the business playbook. The core stays generic; choose `examples/azadbird.yaml` for the VPN preset.

Approved knowledge appears on the dashboard. Conversation-generated candidates and Insight candidates have separate review queues. Publishing requires explicit administrator submission. Treat a historical operator answer as untrusted until generalized and checked.

## ReplyForge Insight import

1. Export authorized support conversations from Telegram Desktop as machine-readable JSON. This is an offline export; ReplyForge never asks for a Telegram login session.
2. Upload the JSON, or a ZIP containing exactly one `result.json` and associated media. Limits: 16 MiB upload, 32 MiB expanded ZIP, 10,000 entries and 100,000 scanned messages. Split larger exports. Paths are inspected in memory, never extracted to disk.
3. Supply the operator sender identifiers as found in the export (`user123` format, space-separated). These distinguish operator replies from customer questions; do not infer them from display names.
4. Select 100, 200, 500 or a custom 1–5000 conversation limit. Private chats only; a candidate needs both customer and operator messages. The limit is a maximum, not a guarantee that enough eligible conversations exist.
5. The local parser drops sender names, redacts common sensitive patterns, bounds recent conversation text, removes duplicates and classifies common topics without external model calls. Exact repeated import parameters reuse the previous import.
6. Review each question/answer. Remove personal details, subscription identifiers, customer-specific balances/payment assertions and obsolete instructions. Approve to create active knowledge, or reject. No learned content is published automatically.
7. To erase an import, use its explicit ERASE form. Already published knowledge is independent and must be removed separately. Scheduled retention scrubs old candidate text.

Current media support is an inventory of referenced/available files only. No image understanding, OCR, generated troubleshooting guide, outcome verification or learned workflow graph is claimed. Import processing is synchronous and local; durable long-running jobs are future work.

## Provider gates

Set `MARZBAN_EXPECTED_VERSION` or `PASARGUARD_EXPECTED_VERSION` to the exact staging-validated semantic version to require a matching `/api/system` response before account lookup. A mismatch blocks lookup and follows the existing human-escalation path. Leaving a value empty retains schema-validated lookup without version probing. PasarGuard requires `system.read` for the optional version check; do not broaden a key silently. Revalidate before changing the version pin.

## Delivery reconciliation

An `uncertain` delivery is not a failed delivery. Inspect the real Telegram conversation, then explicitly confirm sent or cancel in the dashboard. Never blindly re-enqueue it. Human reply FIFO remains blocked behind uncertainty. Staff should understand that an already-running external send can finish before a takeover request is committed.
