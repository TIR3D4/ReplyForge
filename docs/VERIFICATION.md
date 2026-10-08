# Verification record — 2026-10-08

No real customer data or live Telegram/panel/provider credentials were used.

## Reproducible green Actions run

Commit: [`9cd99d8805a11dcb199315c182c3ae018307e680`](https://github.com/TIR3D4/ReplyForge/commit/9cd99d8805a11dcb199315c182c3ae018307e680).
[Complete successful run 37848284654](https://github.com/TIR3D4/ReplyForge/actions/runs/37848284654).

| Check | Observed result | Boundary |
|---|---|---|
| Python suite | 129 passed, 6 skipped | Skips are 4 PostgreSQL tests and 2 browser tests, executed separately below |
| PostgreSQL 16 | 4 passed | Migration chain, queue claim, takeover/send row-lock race, worker exclusivity, JSON-state retention |
| Chromium UI | 2 parametrized tests passed | English/Persian, 1440px/360px, 8 routes, themes, actual policy submit and playground submit |
| Docker build/config/migration | Passed | Production image and non-root migration command |
| Disposable Compose deployment | Passed | API/worker readiness, restart, pg_dump, pg_restore into a separate database, restored schema head |
| Python runtime dependency audit | Passed | No known vulnerabilities reported for `requirements.lock`; JSON report in run artifacts |
| Compile and static checks | Passed | `compileall`, Ruff E4/E7/E9/F |

The latest local run after adding readable HTML errors and seeded browser coverage was **130 passed, 6 skipped**. See subsequent PR checks for the enriched browser scenario before deploying that newer commit. One Starlette TestClient deprecation warning remains; it is not a test failure.

## Screenshots and visual review

The `interface-screenshots` artifact on the Actions run contains full-page PNGs generated from the actual running application, not design mockups. The earlier [verified responsive artifact](https://github.com/TIR3D4/ReplyForge/actions/runs/37847413600/artifacts/11579898933) contains 36 images (two locales, two widths, eight routes plus theme captures). Persian mobile dashboard and desktop Insight and English desktop dashboard were visually inspected. CI found a real 360px horizontal overflow; CSS grid/heading sizing was corrected and the subsequent browser checks passed. Later tests add a populated conversation/ticket to cover non-empty states.

Artifacts have finite retention (currently 90 days). Download them from Actions for longer-term release evidence. Screenshots use synthetic content and no production credentials.

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
