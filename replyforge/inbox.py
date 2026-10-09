"""Unified operator inbox using the same ownership, CSRF and outbox controls."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, desc, or_, func
from .database import session_scope
from .models import Conversation, Message, Ticket, Outbox
from .playbooks import effective_playbook


def register_inbox(app, authenticate, csrf_value, templates):
    @app.get('/admin/inbox')
    def inbox(request: Request, conversation_id: int | None = None, owner: str = 'all',
              search: str = '', page: int = 1, _=Depends(authenticate)):
        if owner not in ('all','ai','human','human_pending') or len(search) > 100 or not 1 <= page <= 10000:
            raise HTTPException(422, detail='Invalid inbox filters')
        with session_scope(request.app.state.factory) as db:
            conditions = []
            if owner != 'all':
                conditions.append(Conversation.owner == owner)
            if search:
                matches = Message.content.ilike('%' + search.replace('%','').replace('_','') + '%')
                conditions.append(or_(Conversation.id.in_(select(Message.conversation_id).where(matches)),
                                      Conversation.chat_id == int(search) if search.isdecimal() else False))
            count = db.scalar(select(func.count(Conversation.id)).where(*conditions)) or 0
            conversations = db.scalars(select(Conversation).where(*conditions).order_by(
                Conversation.last_inbound_at.desc().nullslast(), Conversation.id.desc()).offset((page-1)*30).limit(30)).all()
            selected = db.get(Conversation, conversation_id) if conversation_id else (conversations[0] if conversations else None)
            if conversation_id and not selected:
                raise HTTPException(404)
            history, ticket, pending = [], None, []
            if selected:
                history = list(reversed(db.scalars(select(Message).where(Message.conversation_id == selected.id)
                                       .order_by(desc(Message.id)).limit(100)).all()))
                ticket = db.scalar(select(Ticket).where(Ticket.conversation_id == selected.id).order_by(desc(Ticket.id)).limit(1))
                pending = db.scalars(select(Outbox).where(Outbox.conversation_id == selected.id,
                    Outbox.status.in_(('pending','sending','uncertain'))).order_by(Outbox.id).limit(20)).all()
            playbook, _ = effective_playbook(db, request.app.state.playbook)
            return templates.TemplateResponse(request, 'inbox.html', {
                'locale': playbook.get('locale','en'), 'brand': playbook['brand'], 'csrf': csrf_value(request),
                'conversations': conversations, 'selected': selected, 'history': history, 'ticket': ticket,
                'pending': pending, 'owner': owner, 'search': search, 'page': page, 'pages': max(1,(count+29)//30)})
