# Current candidate verification — 2026-10-09

The first 1.2.0rc1 batch at [`61e83d0`](https://github.com/TIR3D4/ReplyForge/commit/61e83d04385045a1a74d4ebc09143f96523a9093) passed all five jobs in [run 37918191146](https://github.com/TIR3D4/ReplyForge/actions/runs/37918191146): Python/PostgreSQL, real Chrome, Docker restart/restore including Insight, dependency audit and installation-package verification. Artifacts contain test XML, screenshots, audit JSON and source ZIP/checksum.

The subsequent selective-image/privacy changes passed **153 local tests, 7 skipped** (5 PostgreSQL, 2 browser executed separately in Actions), compileall and Ruff. They add explicit image-consent/queue tests, failure handling, pixel deletion, budget-customer unlinking and a browser canvas submission regression. The selective-image UI at [`6001bd7`](https://github.com/TIR3D4/ReplyForge/commit/6001bd773eb410eb0ae30b1cf7a3f7b42703da19) subsequently passed all five jobs in [run 37919288349](https://github.com/TIR3D4/ReplyForge/actions/runs/37919288349). Its [46 actual browser screenshots](https://github.com/TIR3D4/ReplyForge/actions/runs/37919288349/artifacts/11611163830) include both locales, 360px/1440px layouts and synthetic image masking/submission. Persian desktop/mobile inbox, the workflow editor and mobile image review were visually inspected. Final refinements add a forward migration from the first candidate and concise Persian inbox status/date labels. Consult the final commit's Actions before installation; an earlier green run does not validate a later commit. One TestClient deprecation warning remains.

Live Telegram, actual panel versions, provider billing/quality, long-running load and independent penetration tests remain unperformed. See [the current checklist](RELEASE_1_2_CHECKLIST.md).

---

# Verification record — 2026-10-08

No real customer data or live Telegram/panel/provider credentials were used.

## Reproducible green Actions run

Commit: [`c46764148e4dcaf56ae7142946ef895b6bab6747`](https://github.com/TIR3D4/ReplyForge/commit/c46764148e4dcaf56ae7142946ef895b6bab6747).
[Complete successful run 37848910918](https://github.com/TIR3D4/ReplyForge/actions/runs/37848910918).

| Check | Observed result | Boundary |
|---|---|---|
| Python suite | 130 passed, 6 skipped | Skips are 4 PostgreSQL tests and 2 browser tests, executed separately below |
| PostgreSQL 16 | 4 passed | Migration chain, queue claim, takeover/send row-lock race, worker exclusivity, JSON-state retention |
| Chromium UI | 2 parametrized tests passed | English/Persian, 1440px/360px, 9 routes including populated conversation/ticket, themes, actual policy submit and playground submit |
| Docker build/config/migration | Passed | Production image and non-root migration command |
| Disposable Compose deployment | Passed | API/worker readiness, restart, pg_dump, pg_restore into a separate database, restored schema head |
| Python runtime dependency audit | Passed | No known vulnerabilities reported for `requirements.lock`; JSON report in run artifacts |
| Compile and static checks | Passed | `compileall`, Ruff E4/E7/E9/F |

The subsequent local run including the late-batch follow-up regression is **131 passed, 6 skipped**. Check the current PR head's Actions before deploying that newer commit. One Starlette TestClient deprecation warning remains; it is not a test failure.

## Screenshots and visual review

The [populated-interface artifact](https://github.com/TIR3D4/ReplyForge/actions/runs/37848910918/artifacts/11580807158) contains 40 full-page PNGs from the actual running application: two locales, two widths, nine routes plus theme captures. Persian mobile conversation, desktop Insight and English desktop inbox were visually inspected. CI found a real 360px horizontal overflow in an earlier run; CSS grid/heading sizing was corrected and subsequent browser checks passed.

Selected original PNGs are preserved in the repository with provenance in [screenshots/README.md](screenshots/README.md). Full Actions artifacts have finite retention (currently 90 days). All screenshots use synthetic content.

![English desktop inbox](screenshots/inbox-en-desktop.png)

![Persian desktop Insight](screenshots/insight-fa-desktop.png)

[Persian mobile conversation screenshot](screenshots/conversation-fa-mobile.png)


## Meaningful regression coverage

- Official Business connection IDs, edits and explicit keyboard removal, echo avoidance, owner takeover, callback validation/expiry, duplicate inputs and reply window.
- HTTP 429 bounded delay/retry, 5xx/malformed/timeout uncertainty, stale outbox revisions and human FIFO blocking.
- Inbox backoff ordering, late customer input preservation without state advancement and stop-before-claim behavior.
- Persian/English intent/choice policy, invalid/unauthorized model action rejection, fallback selection and output limits. These are mocked/rule evaluations, **not a live model quality benchmark**.
- Panel response shape/type/status errors and optional version mismatch rejection before account lookup.
- CSRF, role restrictions, input bounds, PII pattern redaction, archive path/symlink/size handling, explicit approval and local erasure/retention.
- PostgreSQL locking and graceful worker restart; no assertion of exactly-once Telegram delivery.

## Not run / prerequisites

- Live Telegram Business send/edit/callback/media/rate-limit acceptance: needs an authorized bot, Business connection, HTTPS webhook and test customer.
- Real AI quality, token/cost and media evaluations: needs an approved provider endpoint/key, explicit test budget and redacted bilingual evaluation set.
- Actual Marzban/PasarGuard compatibility/scopes: needs staging panel versions and scoped credentials. Inspected source versions are not live deployment results.
- Multi-day soak, production-scale concurrency, infrastructure kill/partition chaos, base-image CVE scan, independent penetration test and screen-reader certification: not performed.
- Upstream reference test suites were inspected, not executed.

## Reproduce

```sh
python -m pip install -e '.[dev]'
python -m compileall -q replyforge
python -m ruff check --select E4,E7,E9,F replyforge
python -m pytest -q
# Use a disposable PostgreSQL database only:
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST/TEST_DB' python -m pytest -q tests/test_postgres.py
# Install an approved Chromium/Chrome build first:
RUN_BROWSER_TESTS=1 BROWSER_CHANNEL=chrome python -m pytest -q tests/test_browser.py
python scripts/deployment_smoke.py
python -m pip_audit -r requirements.lock --no-deps --disable-pip
```

PostgreSQL integration tests intentionally create schema and synthetic rows. Never point TEST_POSTGRES_URL at customer data. The Compose smoke uses its own uniquely named project, temporary environment and disposable volume.
