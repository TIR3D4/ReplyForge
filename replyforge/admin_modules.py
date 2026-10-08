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
from .models import Audit, BusinessConnection, InsightImport, InsightCandidate, Knowledge, utcnow
from .playbooks import effective_playbook
from .security import redact, fingerprint


def register_admin_modules(app, authenticate, csrf, csrf_value, templates):
    def context(request, session):
        playbook, _ = effective_playbook(session, request.app.state.playbook)
        return {'locale': playbook.get('locale', 'en'), 'brand': playbook['brand'],
                'csrf': csrf_value(request)}

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
                     vision_enabled: bool = Form(False), voice_enabled: bool = Form(False),
                     _=Depends(authenticate)):
        csrf(request, csrf_token)
        try:
            policy = AIPolicy(model=model, fallback_model=fallback_model,
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
            ai = AIEngine(settings, allow_call=permit)
            action = ai.select_intent(text, playbook['menu'])
            result = action or 'NONE — choose a menu or request human assistance'
            return templates.TemplateResponse(request, 'agent.html', {
                **context(request, session), 'policy': policy_for(session, settings),
                'provider_configured': bool(settings.ai_api_key), 'result': result})

    @app.get('/admin/connections')
    def connections(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            return templates.TemplateResponse(request, 'connections.html', {
                **context(request, session), 'connections': session.scalars(select(BusinessConnection)).all(),
                'settings': request.app.state.settings})

    @app.get('/admin/system')
    def system(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            return templates.TemplateResponse(request, 'system.html', {
                **context(request, session), 'events': session.scalars(select(Audit).order_by(Audit.id.desc()).limit(100)).all()})

    @app.get('/admin/insight')
    def insight_dashboard(request: Request, import_id: int | None = None, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            imports = session.scalars(select(InsightImport).order_by(InsightImport.id.desc()).limit(20)).all()
            current = session.get(InsightImport, import_id) if import_id else (imports[0] if imports else None)
            candidates = session.scalars(select(InsightCandidate).where(
                InsightCandidate.import_id == current.id, InsightCandidate.status == 'pending'
            ).order_by(InsightCandidate.id).limit(50)).all() if current else []
            return templates.TemplateResponse(request, 'insight.html', {
                **context(request, session), 'imports': imports, 'current': current, 'candidates': candidates})

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
            session.execute(delete(InsightCandidate).where(InsightCandidate.import_id == import_id))
            session.delete(job)
            session.add(Audit(actor='admin', action='insight_erased'))
        return RedirectResponse('/admin/insight', 303)
