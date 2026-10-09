"""Additional admin modules sharing the existing authentication and CSRF boundary."""
import hashlib
import json
from datetime import timedelta

from fastapi import Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError

from .ai_policy import AIPolicy, effective_settings, policy_for, save_policy
from .agent import AIEngine
from .database import session_scope
from .insight import analyze_export
from .models import AIBudgetDay, AIUsage, Control, InsightTask, Operator, Audit, BusinessConnection, InsightImport, InsightCandidate, Knowledge, utcnow
from .playbooks import effective_playbook
from .security import redact, fingerprint


def register_admin_modules(app, authenticate, csrf, csrf_value, templates):
    def context(request, session):
        playbook, _ = effective_playbook(session, request.app.state.playbook)
        return {'locale': playbook.get('locale', 'en'), 'brand': playbook['brand'],
                'csrf': csrf_value(request)}

    @app.post('/admin/playbook/step')
    def edit_workflow_step(request: Request, flow: str = Form(...), step: str = Form(...),
                           prompt: str = Form(''), next_step: str = Form(''),
                           csrf_token: str = Form(...), _=Depends(authenticate)):
        from copy import deepcopy
        import yaml
        from .config import ConfigError
        from .playbooks import save_playbook
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            current, _ = effective_playbook(session, request.app.state.playbook)
            changed = deepcopy(current)
            state = changed.get('workflows', {}).get(flow, {}).get('states', {}).get(step)
            if state is None or state.get('type') is not None:
                raise HTTPException(422, detail='Select an existing input state')
            if not prompt.strip() or len(prompt) > 4000:
                raise HTTPException(422, detail='Enter a prompt of 1–4000 characters')
            state['prompt'] = prompt.strip()
            if state.get('input') != 'choice':
                state['next'] = next_step
            try:
                version = save_playbook(session, yaml.safe_dump(changed, allow_unicode=True, sort_keys=False))
            except (ConfigError, ValueError) as exc:
                raise HTTPException(422, detail=str(exc)) from exc
            session.add(Audit(actor='admin', action='workflow_step_edited', detail=str(version.id)))
        return RedirectResponse('/admin/playbook', 303)

    @app.post('/admin/playbook/create-flow')
    def create_workflow(request: Request, name: str = Form(...), title: str = Form(...),
                        prompt: str = Form(...), csrf_token: str = Form(...), _=Depends(authenticate)):
        from .workflow_builder import create_flow
        return change_flow(request, csrf_token, lambda current: create_flow(current, name, title, prompt))

    @app.post('/admin/playbook/build-step')
    def build_step(request: Request, flow: str = Form(...), step: str = Form(...),
                   kind: str = Form(...), prompt: str = Form(''), field: str = Form(''),
                   target: str = Form(''), start: bool = Form(False),
                   option_value: list[str] = Form([]), option_label: list[str] = Form([]),
                   option_target: list[str] = Form([]), csrf_token: str = Form(...), _=Depends(authenticate)):
        from .workflow_builder import save_step
        return change_flow(request, csrf_token, lambda current: save_step(current, flow, step, kind,
                           prompt, field, target, option_value, option_label, option_target, start))

    def change_flow(request, token, mutate):
        import yaml
        from .playbooks import save_playbook
        csrf(request, token)
        try:
            with session_scope(request.app.state.factory) as db:
                current, _ = effective_playbook(db, request.app.state.playbook)
                updated = mutate(current)
                version = save_playbook(db, yaml.safe_dump(updated, allow_unicode=True, sort_keys=False))
                db.add(Audit(actor='admin', action='workflow_builder_saved', detail=str(version.id)))
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        return RedirectResponse('/admin/playbook', 303)

    @app.get('/admin/operators')
    def operators(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            return templates.TemplateResponse(request, 'operators.html', {
                **context(request, session), 'operators': session.scalars(select(Operator).order_by(Operator.id)).all()})

    @app.post('/admin/operators')
    def create_operator(request: Request, username: str = Form(...), password: str = Form(...),
                        role: str = Form('operator'), csrf_token: str = Form(...), _=Depends(authenticate)):
        import re
        from .operators import hash_password
        csrf(request, csrf_token)
        if (not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}', username)
                or username == request.app.state.settings.admin_username or role not in ('admin', 'operator')):
            raise HTTPException(422, detail='Invalid username or role')
        try:
            digest = hash_password(password)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        try:
            with session_scope(request.app.state.factory) as session:
                session.add(Operator(username=username, password_hash=digest, role=role))
                session.add(Audit(actor='admin', action='operator_created'))
        except IntegrityError as exc:
            raise HTTPException(409, detail='Username already exists') from exc
        return RedirectResponse('/admin/operators', 303)

    @app.post('/admin/operators/{operator_id}/disable')
    def disable_operator(request: Request, operator_id: int, csrf_token: str = Form(...),
                         username=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            staff = session.get(Operator, operator_id, with_for_update=True)
            if not staff:
                raise HTTPException(404)
            if staff.username == username:
                raise HTTPException(409, detail='Cannot disable your own account')
            staff.enabled = False
            session.add(Audit(actor='admin', action='operator_disabled', detail=str(staff.id)))
        return RedirectResponse('/admin/operators', 303)

    @app.post('/admin/operators/{operator_id}/password')
    def reset_operator_password(request: Request, operator_id: int, password: str = Form(...),
                                csrf_token: str = Form(...), _=Depends(authenticate)):
        from .operators import hash_password
        csrf(request, csrf_token)
        try:
            digest = hash_password(password)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        with session_scope(request.app.state.factory) as db:
            staff = db.get(Operator, operator_id, with_for_update=True)
            if not staff:
                raise HTTPException(404)
            staff.password_hash = digest
            db.add(Audit(actor='admin', action='operator_password_rotated', detail=str(staff.id)))
        return RedirectResponse('/admin/operators', 303)

    @app.get('/admin/agent')
    def agent_settings(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            return templates.TemplateResponse(request, 'agent.html', {
                **context(request, session), 'policy': policy_for(session, request.app.state.settings),
                'provider_configured': bool(request.app.state.settings.ai_api_key), 'result': None})

    @app.post('/admin/agent')
    def update_agent(request: Request, csrf_token: str = Form(...),
                     model: str = Form(...), fallback_model: str = Form(''),
                     max_output_tokens: int = Form(...), calls_per_chat_per_day: int = Form(...),
                     daily_budget_usd: str = Form('5'), input_price: str = Form('0'), output_price: str = Form('0'),
                     vision_enabled: bool = Form(False), voice_enabled: bool = Form(False),
                     _=Depends(authenticate)):
        csrf(request, csrf_token)
        try:
            policy = AIPolicy(model=model, fallback_model=fallback_model,
                              daily_budget_usd=daily_budget_usd, input_price=input_price, output_price=output_price,
                              max_output_tokens=max_output_tokens, calls_per_chat_per_day=calls_per_chat_per_day,
                              vision_enabled=vision_enabled, voice_enabled=voice_enabled)
        except ValidationError as exc:
            raise HTTPException(422, detail='Invalid model policy') from exc
        with session_scope(request.app.state.factory) as session:
            save_policy(session, policy)
            session.add(Audit(actor='admin', action='ai_policy_updated'))
        return RedirectResponse('/admin/agent', 303)

    @app.post('/admin/agent/test')
    def test_agent(request: Request, text: str = Form(...), csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        if not 1 <= len(text.strip()) <= 2000:
            raise HTTPException(422, detail='Enter 1–2000 characters')
        with session_scope(request.app.state.factory) as session:
            settings = effective_settings(session, request.app.state.settings)
            playbook, _ = effective_playbook(session, request.app.state.playbook)
            # Shared lock serializes playground budgets across concurrent admin requests.
            from .models import Control
            row = session.get(Control, 'ai.model', with_for_update=True)
            if row is None:
                save_policy(session, policy_for(session, settings))
                session.flush()
            def permit():
                used = session.scalar(select(func.count(Audit.id)).where(
                    Audit.action == 'playground_call', Audit.created_at >= utcnow() - timedelta(days=1))) or 0
                if used >= 20:
                    return False
                session.add(Audit(actor='admin', action='playground_call'))
                session.flush()
                return True
            from .budget import BudgetLedger
            ai = AIEngine(settings, allow_call=permit,
                          ledger=BudgetLedger(request.app.state.factory, settings, 'playground'))
            action = ai.select_intent(text, playbook['menu'])
            result = action or 'NONE — choose a menu or request human assistance'
            return templates.TemplateResponse(request, 'agent.html', {
                **context(request, session), 'policy': policy_for(session, settings),
                'provider_configured': bool(settings.ai_api_key), 'result': result})

    @app.post('/admin/service-notice')
    def set_service_notice(request: Request, message: str = Form(''), csrf_token: str = Form(...), _=Depends(authenticate)):
        from .models import Control
        csrf(request, csrf_token)
        if len(message) > 200:
            raise HTTPException(422, detail='Notice must be at most 200 characters')
        with session_scope(request.app.state.factory) as db:
            row = db.get(Control, 'service_notice')
            if row is None:
                db.add(Control(key='service_notice', value=message.strip()))
            else:
                row.value, row.updated_at = message.strip(), utcnow()
            db.add(Audit(actor='admin', action='service_notice_updated'))
        return RedirectResponse('/admin/connections', 303)

    @app.get('/admin/connections')
    def connections(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            return templates.TemplateResponse(request, 'connections.html', {
                **context(request, session), 'connections': session.scalars(select(BusinessConnection)).all(),
                'settings': request.app.state.settings, 'notice': session.get(Control, 'service_notice')})

    @app.get('/admin/system')
    def system(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            return templates.TemplateResponse(request, 'system.html', {
                **context(request, session), 'events': session.scalars(select(Audit).order_by(Audit.id.desc()).limit(100)).all(), 'budget_days': session.scalars(select(AIBudgetDay).order_by(AIBudgetDay.day.desc()).limit(7)).all(), 'usage': session.scalars(select(AIUsage).order_by(AIUsage.created_at.desc()).limit(30)).all()})

    @app.get('/admin/insight')
    def insight_dashboard(request: Request, import_id: int | None = None, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            imports = session.scalars(select(InsightImport).order_by(InsightImport.id.desc()).limit(20)).all()
            current = session.get(InsightImport, import_id) if import_id else (imports[0] if imports else None)
            candidates = session.scalars(select(InsightCandidate).where(
                InsightCandidate.import_id == current.id, InsightCandidate.status == 'pending'
            ).order_by(InsightCandidate.id).limit(50)).all() if current else []
            return templates.TemplateResponse(request, 'insight.html', {
                **context(request, session), 'imports': imports, 'current': current, 'candidates': candidates, 'tasks': {t.candidate_id: t for t in session.scalars(select(InsightTask).where(InsightTask.import_id == current.id)).all()} if current else {}})

    @app.post('/admin/insight/import')
    async def import_insight(request: Request, export: UploadFile = File(...),
                             limit: int = Form(100), operator_ids: str = Form(...),
                             csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        content = await export.read(16 * 1024 * 1024 + 1)
        await export.close()
        if len(content) > 16 * 1024 * 1024:
            raise HTTPException(413, detail='Upload limit is 16 MiB')
        if len(operator_ids) > 2000:
            raise HTTPException(422, detail='Too many operator IDs')
        identities = set(operator_ids.replace(',', ' ').split())
        key = fingerprint(hashlib.sha256(content).hexdigest() + json.dumps(sorted(identities)) + str(limit),
                          request.app.state.settings.binding_pepper)
        try:
            analysis = analyze_export(content, limit=limit, operator_ids=identities)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        try:
            with session_scope(request.app.state.factory) as session:
                previous = session.scalar(select(InsightImport).where(InsightImport.fingerprint == key))
                if previous:
                    return RedirectResponse('/admin/insight?import_id=' + str(previous.id), 303)
                job = InsightImport(fingerprint=key, statistics=analysis.statistics)
                session.add(job)
                session.flush()
                job_id = job.id
                for candidate in analysis.conversations:
                    session.add(InsightCandidate(import_id=job.id,
                        **{k: candidate[k] for k in ('digest', 'category', 'question', 'answer', 'status', 'media_count')}))
                session.add(Audit(actor='admin', action='insight_import', detail=str(job.id)))
        except IntegrityError as exc:
            raise HTTPException(409, detail='Export already imported; refresh Insight') from exc
        return RedirectResponse('/admin/insight?import_id=' + str(job_id), 303)

    @app.post('/admin/insight/{candidate_id}/image')
    def queue_reviewed_image(request: Request, candidate_id: int, image_base64: str = Form(...),
                             privacy_reviewed: bool = Form(False), csrf_token: str = Form(...), _=Depends(authenticate)):
        import base64
        import binascii
        import struct
        csrf(request, csrf_token)
        if not privacy_reviewed or not image_base64.startswith('data:image/png;base64,'):
            raise HTTPException(422, detail='Review and redact the image before authorizing analysis')
        try:
            content = base64.b64decode(image_base64.split(',', 1)[1], validate=True)
            if not 24 <= len(content) <= 2*1024*1024 or content[:8] != b'\x89PNG\r\n\x1a\n' or content[8:16] != b'\x00\x00\x00\x0dIHDR':
                raise ValueError()
            width, height = struct.unpack('>II', content[16:24])
            if not 1 <= width <= 1600 or not 1 <= height <= 1600:
                raise ValueError()
        except (ValueError, binascii.Error, struct.error) as exc:
            raise HTTPException(422, detail='Use the image editor to create a PNG up to 1600px / 2 MiB') from exc
        with session_scope(request.app.state.factory) as db:
            candidate = db.get(InsightCandidate, candidate_id, with_for_update=True)
            if not candidate or candidate.status != 'pending':
                raise HTTPException(409, detail='Candidate is not pending review')
            task = db.scalar(select(InsightTask).where(InsightTask.candidate_id == candidate_id).with_for_update())
            if task and task.status in ('pending','processing','published'):
                raise HTTPException(409, detail='Existing analysis must finish first')
            if not task:
                task = InsightTask(import_id=candidate.import_id, candidate_id=candidate_id)
                db.add(task)
            task.image_data, task.result, task.status = content, {}, 'pending'
            job_id = candidate.import_id
            db.add(Audit(actor='admin', action='insight_reviewed_image_queued', detail=str(candidate_id)))
        return RedirectResponse('/admin/insight?import_id=' + str(job_id), 303)

    @app.post('/admin/insight/{candidate_id}/refine')
    def refine_candidate(request: Request, candidate_id: int, csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as db:
            candidate = db.get(InsightCandidate, candidate_id, with_for_update=True)
            if not candidate or candidate.status != 'pending':
                raise HTTPException(409, detail='Only pending candidates can be analyzed')
            task = db.scalar(select(InsightTask).where(InsightTask.candidate_id == candidate_id))
            if task:
                if task.status not in ('failed','uncertain'):
                    raise HTTPException(409, detail='Task already queued or awaiting review')
                task.status, task.result = 'pending', {}
            else:
                db.add(InsightTask(import_id=candidate.import_id, candidate_id=candidate.id))
            job_id = candidate.import_id
            db.add(Audit(actor='admin', action='insight_refinement_requested', detail=str(candidate_id)))
        return RedirectResponse('/admin/insight?import_id=' + str(job_id), 303)

    @app.post('/admin/insight/tasks/{task_id}/publish-workflow')
    def publish_learned_workflow(request: Request, task_id: int, name: str = Form(...),
                                  title: str = Form(...), steps: str = Form(...),
                                  csrf_token: str = Form(...), _=Depends(authenticate)):
        import yaml
        from .workflow_builder import create_flow, save_step
        from .playbooks import save_playbook
        csrf(request, csrf_token)
        lines = [line.strip() for line in steps.splitlines() if line.strip()]
        if not 1 <= len(lines) <= 8 or any(len(line) > 500 for line in lines):
            raise HTTPException(422, detail='Provide 1–8 reviewed steps, up to 500 characters each')
        try:
            with session_scope(request.app.state.factory) as db:
                task = db.get(InsightTask, task_id, with_for_update=True)
                if not task or task.status != 'review':
                    raise HTTPException(409, detail='Task is not awaiting review')
                current, _ = effective_playbook(db, request.app.state.playbook)
                changed = create_flow(current, name, title, lines[0])
                # Build backwards so every transition is valid at each save.
                for index in reversed(range(len(lines))):
                    step = 'step_' + str(index)
                    destination = 'complete' if index == len(lines)-1 else 'step_' + str(index+1)
                    labels = ['انجام شد', 'کمک اپراتور'] if current.get('locale') == 'fa' else ['Done', 'Human help']
                    changed = save_step(changed, name, step, 'choice', lines[index], 'step_' + str(index), '',
                                        ['done','help'], labels, [destination,'handoff'], start=index == 0)
                save_playbook(db, yaml.safe_dump(changed, allow_unicode=True, sort_keys=False))
                task.status = 'published'
                db.add(Audit(actor='admin', action='insight_workflow_approved', detail=str(task.id)))
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        return RedirectResponse('/admin/playbook', 303)

    @app.post('/admin/insight/{candidate_id}/review')
    def review_insight(request: Request, candidate_id: int, decision: str = Form(...),
                       question: str = Form(''), answer: str = Form(''),
                       csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        if decision not in ('approve', 'reject'):
            raise HTTPException(422, detail='Invalid decision')
        if decision == 'approve' and (not question.strip() or not answer.strip() or len(question) > 500 or len(answer) > 4000):
            raise HTTPException(422, detail='Provide a question and an approved answer')
        with session_scope(request.app.state.factory) as session:
            candidate = session.get(InsightCandidate, candidate_id, with_for_update=True)
            if not candidate:
                raise HTTPException(404)
            if candidate.status != 'pending':
                raise HTTPException(409, detail='Candidate already reviewed')
            if decision == 'approve':
                session.add(Knowledge(question=redact(question.strip())[:500], answer=redact(answer.strip())))
            candidate.status = 'approved' if decision == 'approve' else 'rejected'
            candidate.reviewed_at = utcnow()
            session.add(Audit(actor='admin', action='insight_review', detail=f'{candidate.id}:{decision}'))
            job_id = candidate.import_id
        return RedirectResponse('/admin/insight?import_id=' + str(job_id), 303)

    @app.post('/admin/insight/imports/{import_id}/erase')
    def erase_import(request: Request, import_id: int, confirmation: str = Form(...),
                     csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        if confirmation != 'ERASE':
            raise HTTPException(422, detail='Type ERASE to remove this analysis')
        with session_scope(request.app.state.factory) as session:
            job = session.get(InsightImport, import_id, with_for_update=True)
            if not job:
                raise HTTPException(404)
            session.execute(delete(InsightTask).where(InsightTask.import_id == import_id))
            session.execute(delete(InsightCandidate).where(InsightCandidate.import_id == import_id))
            session.delete(job)
            session.add(Audit(actor='admin', action='insight_erased'))
        return RedirectResponse('/admin/insight', 303)
