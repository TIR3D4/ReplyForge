# Upgrade guide: ReplyForge 1.0.0rc1 → 1.1.0rc1

This release improves customer support operations while retaining the same official Telegram Business Bot API connection and self-hosted topology.

## Checklist before updating

1. Temporarily pause AI replies in the admin interface. Assign human staff to handle incoming chats during the maintenance period.
2. Verify that exactly ONE worker is deployed. The current scheduler does not support multiple concurrent workers.
3. Back up PostgreSQL and separately restore into a temporary staging environment to verify that backup recovery actually works.
4. Securely retain the existing .env and deployment configuration. Never commit BotFather tokens, panel API keys or subscription links.
5. Check that GitHub Actions CI is green for the commit you are deploying.

## Update commands

From the deployment directory on your own host (not this chat):

    git fetch --all
    git checkout main
    git pull --ff-only
    docker compose build
    docker compose up -d
    docker compose ps
    docker compose logs --tail=100 init
    docker compose exec api replyforge check-config
    curl --fail http://127.0.0.1:8080/healthz

The init container applies Alembic migrations before starting the API and worker. The target schema head is 0007_knowledge_review.

Never manually stamp the Alembic head just to bypass a migration error. Review the failure and restore in staging if needed. Migration and deployment behavior should be tested on a copy of real schema, not on production first.

## Optional new configuration

- MESSAGE_DEBOUNCE_MS=1200: bundle safe consecutive text messages before one AI interaction. Set 0 to disable. Maximum 5000.
- DATA_RETENTION_DAYS=180: scrub expired content and media references. Set 0 to disable; retention policy is the deployer's responsibility.
- MAX_LLM_CALLS_PER_CHAT_PER_DAY=40: daily limit on model invocations per conversation.
- AUTO_REPLY_ENABLED=false: leave new deployments in monitor-only mode. Existing deployments may have an admin override in the controls table.
- SUPPORT_ALERT_CHAT_ID: optional Telegram destination for staff alerts; grant the connected bot permission first.

## New operator workflows

- Open /admin/tickets and verify filtering, assignment, priority and first-response SLA status.
- Open any conversation to create human replies and optionally request a human-reviewed AI draft. The draft DOES NOT automatically send.
- Use private notes and close the ticket with a resolution summary. Review pending candidate articles at /admin/knowledge/review. Nothing is published without deliberate approval.
- Test quick repeated human messages, and uncertainty reconciliation, using test customers before public release.
- Check /admin to inspect pending and overdue issues. Separate readiness endpoint: /readyz.

## Privacy

- A background scrub runs periodically; an operator can manually invoke: docker compose exec api replyforge prune.
- To delete a test customer's local data, use the conversation erasure form and type the exact displayed confirmation. This does not erase Telegram history, upstream account information or encrypted backups.
- If any outbound send is uncertain or being sent, erasure is blocked until it is reconciled to avoid a stray send.
- Publish a real data retention and access policy before collecting private customer messages.

## Rollback strategy

Rolling back the application image is not identical to rolling back the database schema. Prefer rehearsing a recovery from the verified backup into a clean recovery environment and performing an authorized cutover. Avoid downgrading the production database in place without a migration plan.

## Release restrictions

- Real Telegram Business permissions and message edit behavior MUST be verified against an actual staging Business account.
- Read-only Marzban and Pasarguard APIs must be validated against the installed panel versions.
- Inbound media and user privacy must be tested with dummy data and consent.
- No automated bank receipt confirmation; all financial disputes remain human reviewed.
- No multi-role SSO/RBAC, multi-worker distributed execution, or pre-connection Telegram chat history import in this release.
