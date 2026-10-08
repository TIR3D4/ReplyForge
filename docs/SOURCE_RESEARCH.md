# Source-code research — 2026-10-08

Scope: focused implementation and test inspection, not whole-project certification. No upstream source was copied into ReplyForge. SHAs below pin the actual inspected working trees. Reference suites were read, not executed. Licensing notes are engineering provenance, not legal advice.

## langchain-ai/langgraph
- Inspected commit: [`93f5eaff21bcc183044b0980a8844b9b7a1275a8`](https://github.com/langchain-ai/langgraph/commit/93f5eaff21bcc183044b0980a8844b9b7a1275a8); commit date 2026-10-08.
- Implementation: [libs/langgraph/langgraph/pregel/_retry.py](https://github.com/langchain-ai/langgraph/blob/93f5eaff21bcc183044b0980a8844b9b7a1275a8/libs/langgraph/langgraph/pregel/_retry.py)
- Tests inspected: [libs/langgraph/tests/test_retry.py](https://github.com/langchain-ai/langgraph/blob/93f5eaff21bcc183044b0980a8844b9b7a1275a8/libs/langgraph/tests/test_retry.py)
- License: MIT; [exact license](https://github.com/langchain-ai/langgraph/blob/93f5eaff21bcc183044b0980a8844b9b7a1275a8/LICENSE).
- Decision: Bound retry attempts, keep state writes behind cancellation fences; do not retry unknown external sends.

## pydantic/pydantic-ai
- Inspected commit: [`36529f3a8ebc5a5675129fe6262223b9da0815ec`](https://github.com/pydantic/pydantic-ai/commit/36529f3a8ebc5a5675129fe6262223b9da0815ec); commit date 2026-10-08.
- Implementation: [pydantic_ai_slim/pydantic_ai/usage.py](https://github.com/pydantic/pydantic-ai/blob/36529f3a8ebc5a5675129fe6262223b9da0815ec/pydantic_ai_slim/pydantic_ai/usage.py)
- Tests inspected: [tests/test_usage_limits.py](https://github.com/pydantic/pydantic-ai/blob/36529f3a8ebc5a5675129fe6262223b9da0815ec/tests/test_usage_limits.py)
- License: MIT; [exact license](https://github.com/pydantic/pydantic-ai/blob/36529f3a8ebc5a5675129fe6262223b9da0815ec/LICENSE).
- Decision: Check budgets before each request and tool call. Dollar budgets require reliable pricing and usage accounting; call limits are not a dollar guarantee.

## openai/openai-agents-python
- Inspected commit: [`125efa029b4bfd84238bd2c4fd69c3406f802663`](https://github.com/openai/openai-agents-python/commit/125efa029b4bfd84238bd2c4fd69c3406f802663); commit date 2026-10-08.
- Implementation: [src/agents/memory/session.py](https://github.com/openai/openai-agents-python/blob/125efa029b4bfd84238bd2c4fd69c3406f802663/src/agents/memory/session.py)
- Tests inspected: [tests/extensions/memory/test_sqlalchemy_session.py](https://github.com/openai/openai-agents-python/blob/125efa029b4bfd84238bd2c4fd69c3406f802663/tests/extensions/memory/test_sqlalchemy_session.py)
- License: MIT; [exact license](https://github.com/openai/openai-agents-python/blob/125efa029b4bfd84238bd2c4fd69c3406f802663/LICENSE).
- Decision: Bound history, retain chronological order, provide explicit session erasure. Do not introduce a second conflicting conversation store.

## temporalio/sdk-python
- Inspected commit: [`d42e654d2b892b404fb0832fa4cf32e56f8a4f7a`](https://github.com/temporalio/sdk-python/commit/d42e654d2b892b404fb0832fa4cf32e56f8a4f7a); commit date 2026-10-08.
- Implementation: [temporalio/worker/_workflow_instance.py](https://github.com/temporalio/sdk-python/blob/d42e654d2b892b404fb0832fa4cf32e56f8a4f7a/temporalio/worker/_workflow_instance.py)
- Tests inspected: [tests/worker/test_workflow.py](https://github.com/temporalio/sdk-python/blob/d42e654d2b892b404fb0832fa4cf32e56f8a4f7a/tests/worker/test_workflow.py)
- License: MIT; [exact license](https://github.com/temporalio/sdk-python/blob/d42e654d2b892b404fb0832fa4cf32e56f8a4f7a/LICENSE).
- Decision: Separate durable decision history from external activities and test replay. Reject adding a Temporal cluster before measured operational need; PostgreSQL remains the existing state store.

## aiogram/aiogram
- Inspected commit: [`b17c710ca9a05559e2141e1d16338b83dd50a445`](https://github.com/aiogram/aiogram/commit/b17c710ca9a05559e2141e1d16338b83dd50a445); commit date 2026-09-27.
- Implementation: [aiogram/types/business_connection.py](https://github.com/aiogram/aiogram/blob/b17c710ca9a05559e2141e1d16338b83dd50a445/aiogram/types/business_connection.py)
- Tests inspected: [tests/test_api/test_methods/test_send_message.py](https://github.com/aiogram/aiogram/blob/b17c710ca9a05559e2141e1d16338b83dd50a445/tests/test_api/test_methods/test_send_message.py)
- License: MIT; [exact license](https://github.com/aiogram/aiogram/blob/b17c710ca9a05559e2141e1d16338b83dd50a445/LICENSE).
- Decision: Business rights are optional and legacy can_reply is deprecated. Preserve connection ID in send/edit requests; support rights revocation.

## AliZakaee/SmarTel
- Inspected commit: [`c24604b7132b74497047e950661a874bd3beeb59`](https://github.com/AliZakaee/SmarTel/commit/c24604b7132b74497047e950661a874bd3beeb59); commit date 2026-08-15.
- Implementation: [handlers/business_updates.py](https://github.com/AliZakaee/SmarTel/blob/c24604b7132b74497047e950661a874bd3beeb59/handlers/business_updates.py)
- Tests inspected: [tests/unit/handlers/test_business_updates.py](https://github.com/AliZakaee/SmarTel/blob/c24604b7132b74497047e950661a874bd3beeb59/tests/unit/handlers/test_business_updates.py)
- License: MIT; [exact license](https://github.com/AliZakaee/SmarTel/blob/c24604b7132b74497047e950661a874bd3beeb59/LICENSE).
- Decision: Early echo guards, owner takeover, monitor-only start. Reject copying time-based automatic takeover expiry: ownership should remain explicit.

## bostrot/telegram-support-bot
- Inspected commit: [`5c4bb7386da42647bc4e55e3660238a1ab037b19`](https://github.com/bostrot/telegram-support-bot/commit/5c4bb7386da42647bc4e55e3660238a1ab037b19); commit date 2026-09-12.
- Implementation: [src/workflows.ts](https://github.com/bostrot/telegram-support-bot/blob/5c4bb7386da42647bc4e55e3660238a1ab037b19/src/workflows.ts)
- Tests inspected: [test/permissions.test.ts](https://github.com/bostrot/telegram-support-bot/blob/5c4bb7386da42647bc4e55e3660238a1ab037b19/test/permissions.test.ts)
- License: GPL-3.0 (see repository LICENSE); [exact license](https://github.com/bostrot/telegram-support-bot/blob/5c4bb7386da42647bc4e55e3660238a1ab037b19/LICENSE).
- Decision: Canned responses, escalation and staff permission checks. Ordinary bot/group forwarding is not a replacement for Telegram Business.

## chatwoot/chatwoot
- Inspected commit: [`807e9ed67ad00048d47c878c1945349391172b6b`](https://github.com/chatwoot/chatwoot/commit/807e9ed67ad00048d47c878c1945349391172b6b); commit date 2026-10-08.
- Implementation: [app/services/conversations/assignment_service.rb](https://github.com/chatwoot/chatwoot/blob/807e9ed67ad00048d47c878c1945349391172b6b/app/services/conversations/assignment_service.rb)
- Tests inspected: [spec/services/conversations/assignment_service_spec.rb](https://github.com/chatwoot/chatwoot/blob/807e9ed67ad00048d47c878c1945349391172b6b/spec/services/conversations/assignment_service_spec.rb)
- License: MIT core; enterprise separate; [exact license](https://github.com/chatwoot/chatwoot/blob/807e9ed67ad00048d47c878c1945349391172b6b/LICENSE).
- Decision: Mutually exclusive AI/human assignment under row locks; preserve explicit takeover and start SLA appropriately. Do not import enterprise code.

## tgoai/tgo
- Inspected commit: [`995da4577f6f91edb87d0f56fc9ea4c129f1a4eb`](https://github.com/tgoai/tgo/commit/995da4577f6f91edb87d0f56fc9ea4c129f1a4eb); commit date 2026-04-28.
- Implementation: [repos/tgo-ai/app/runtime/tools/custom/handoff.py](https://github.com/tgoai/tgo/blob/995da4577f6f91edb87d0f56fc9ea4c129f1a4eb/repos/tgo-ai/app/runtime/tools/custom/handoff.py)
- License: Modified Apache-2.0 with additional restrictions; [exact license](https://github.com/tgoai/tgo/blob/995da4577f6f91edb87d0f56fc9ea4c129f1a4eb/LICENSE).
- Decision: Human handoff represented as a structured request with reason/urgency. Do not copy source: multi-tenant and branding restrictions conflict with generic permissive distribution. No matching handoff test located.

## langfuse/langfuse
- Inspected commit: [`c106bb3d945323688e6f6079f65fb0ab28203b53`](https://github.com/langfuse/langfuse/commit/c106bb3d945323688e6f6079f65fb0ab28203b53); commit date 2026-10-08.
- Implementation: [worker/src/queues/ingestionQueue.ts](https://github.com/langfuse/langfuse/blob/c106bb3d945323688e6f6079f65fb0ab28203b53/worker/src/queues/ingestionQueue.ts)
- Tests inspected: [worker/src/__tests__/ingestionMasking.test.ts](https://github.com/langfuse/langfuse/blob/c106bb3d945323688e6f6079f65fb0ab28203b53/worker/src/__tests__/ingestionMasking.test.ts)
- License: MIT core; enterprise separate; [exact license](https://github.com/langfuse/langfuse/blob/c106bb3d945323688e6f6079f65fb0ab28203b53/LICENSE).
- Decision: Separate ingestion from processing, bounded retry categories, mask before telemetry persistence. Do not send customer messages to tracing by default; inspected masking tests reference an enterprise-related module.

## Gozargah/Marzban
- Inspected commit: [`7f396db3e703d71a28060bc9ce4a532ec64cb1f4`](https://github.com/Gozargah/Marzban/commit/7f396db3e703d71a28060bc9ce4a532ec64cb1f4); commit date 2025-01-09.
- Implementation: [app/models/user.py](https://github.com/Gozargah/Marzban/blob/7f396db3e703d71a28060bc9ce4a532ec64cb1f4/app/models/user.py)
- Implementation: [app/routers/user.py](https://github.com/Gozargah/Marzban/blob/7f396db3e703d71a28060bc9ce4a532ec64cb1f4/app/routers/user.py)
- License: Repository AGPL-family text; review exact LICENSE; [exact license](https://github.com/Gozargah/Marzban/blob/7f396db3e703d71a28060bc9ce4a532ec64cb1f4/LICENSE).
- Decision: Username lookup with bearer auth, integer expiration and explicit quota fields. Interoperate over public API without copying source. No upstream test executed; our mock contract tests are required.

## PasarGuard/panel
- Inspected commit: [`b56ffe369f542152c52c69733205baeaf3f6e4cd`](https://github.com/PasarGuard/panel/commit/b56ffe369f542152c52c69733205baeaf3f6e4cd); commit date 2026-09-12.
- Implementation: [app/models/user.py](https://github.com/PasarGuard/panel/blob/b56ffe369f542152c52c69733205baeaf3f6e4cd/app/models/user.py)
- Implementation: [app/routers/user.py](https://github.com/PasarGuard/panel/blob/b56ffe369f542152c52c69733205baeaf3f6e4cd/app/routers/user.py)
- Implementation: [app/routers/authentication.py](https://github.com/PasarGuard/panel/blob/b56ffe369f542152c52c69733205baeaf3f6e4cd/app/routers/authentication.py)
- License: Repository AGPL-family text; review exact LICENSE; [exact license](https://github.com/PasarGuard/panel/blob/b56ffe369f542152c52c69733205baeaf3f6e4cd/LICENSE).
- Decision: Numeric by-id lookup, users.read permission, X-Api-Key authentication. Fail closed on schema changes; API compatibility is not inferred from product name.

## taskiq-python/taskiq
- Inspected commit: [`f08a54ab3a8e4e16045c84379cf26eb4fa83d4b2`](https://github.com/taskiq-python/taskiq/commit/f08a54ab3a8e4e16045c84379cf26eb4fa83d4b2); commit date 2026-10-08.
- Implementation: [taskiq/middlewares/simple_retry_middleware.py](https://github.com/taskiq-python/taskiq/blob/f08a54ab3a8e4e16045c84379cf26eb4fa83d4b2/taskiq/middlewares/simple_retry_middleware.py)
- Tests inspected: [tests/middlewares/test_simple_retry.py](https://github.com/taskiq-python/taskiq/blob/f08a54ab3a8e4e16045c84379cf26eb4fa83d4b2/tests/middlewares/test_simple_retry.py)
- License: MIT; [exact license](https://github.com/taskiq-python/taskiq/blob/f08a54ab3a8e4e16045c84379cf26eb4fa83d4b2/LICENSE).
- Decision: Additional queue implementation: opt-in retries and exception classes, maximum retry count. Reject generic retry middleware for sendMessage because outcome can be uncertain.
