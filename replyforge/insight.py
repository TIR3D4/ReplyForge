"""Offline-first historical support analysis. No Telegram account login or URL fetches."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
import zipfile

from .agent import local_intent
from .security import redact

MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_MESSAGES = 100000


@dataclass(frozen=True)
class Analysis:
    conversations: list[dict]
    statistics: dict


def text_content(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(part if isinstance(part, str) else str(part.get('text', ''))
                       for part in value if isinstance(part, (str, dict)))
    return ''


def read_export(content: bytes) -> tuple[dict, set[str]]:
    """Inspect ZIP in memory; never extract paths or send archived media externally."""
    media = set()
    if content.startswith(b'PK'):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(e.file_size for e in entries) > MAX_ARCHIVE_BYTES:
                    raise ValueError('Archive exceeds the 32 MiB expanded limit')
                for entry in entries:
                    path = PurePosixPath(entry.filename)
                    if path.is_absolute() or '..' in path.parts or '\\' in entry.filename:
                        raise ValueError('Unsafe archive path')
                    if entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('Encrypted entries and symlinks are unsupported')
                candidates = [e for e in entries if e.filename.endswith('result.json')]
                if len(candidates) != 1:
                    raise ValueError('ZIP must contain exactly one result.json')
                prefix = str(PurePosixPath(candidates[0].filename).parent)
                prefix = '' if prefix == '.' else prefix + '/'
                media = {e.filename[len(prefix):] for e in entries if e.filename.startswith(prefix)}
                content = archive.read(candidates[0])
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError('Invalid or unsupported ZIP archive') from exc
    if len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError('Export is too large')
    try:
        result = json.loads(content)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid Telegram Desktop JSON export') from exc
    if not isinstance(result, dict):
        raise ValueError('Export must be an object')
    return result, media


def analyze_export(content: bytes, *, limit: int, operator_ids: set[str]) -> Analysis:
    if not 1 <= limit <= 5000:
        raise ValueError('Select 1–5000 conversations')
    if not operator_ids or any(not re.fullmatch(r'user\d+', key) for key in operator_ids):
        raise ValueError('Provide operator sender IDs in Telegram export format: user123')
    document, media = read_export(content)
    chats = document.get('chats', {}).get('list', []) if isinstance(document.get('chats'), dict) else []
    if 'messages' in document:
        chats = [document]
    if not isinstance(chats, list) or not chats:
        raise ValueError('No conversations found in export')
    results, seen = [], set()
    counts = Counter()
    topics = Counter()
    for chat in chats:
        if len(results) >= limit:
            break
        if not isinstance(chat, dict) or chat.get('type') not in ('personal_chat', 'private_group', None):
            counts['excluded_chats'] += 1
            continue
        # Group conversations cannot be safely attributed to one customer.
        if chat.get('type') == 'private_group':
            counts['excluded_chats'] += 1
            continue
        messages = chat.get('messages', [])
        if not isinstance(messages, list):
            continue
        counts['messages_scanned'] += len(messages)
        if counts['messages_scanned'] > MAX_MESSAGES:
            raise ValueError('Export exceeds 100000 messages; use a smaller export')
        names = {str(m.get('from', '')).strip() for m in messages if isinstance(m, dict)} - {''}
        turns = []
        last_text = None
        attachments = 0
        available = 0
        for message in messages:
            if not isinstance(message, dict) or message.get('type') != 'message':
                continue
            raw = text_content(message.get('text'))
            for name in sorted(names, key=len, reverse=True):
                raw = re.sub(r'(?<!\w)' + re.escape(name) + r'(?!\w)', '[person]', raw, flags=re.I)
            cleaned = redact(raw).strip()
            role = 'operator' if str(message.get('from_id')) in operator_ids else 'customer'
            attachment = message.get('photo') or message.get('file')
            if isinstance(attachment, str):
                attachments += 1
                available += int(attachment in media)
            if cleaned and (role, cleaned) != last_text:
                turns.append({'role': role, 'text': cleaned[:1200]})
                last_text = role, cleaned
            elif cleaned:
                counts['duplicate_messages'] += 1
        if not turns:
            continue
        turns = turns[-40:]
        digest = hashlib.sha256(json.dumps(turns, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if digest in seen:
            counts['duplicate_conversations'] += 1
            continue
        seen.add(digest)
        question = next((m['text'] for m in turns if m['role'] == 'customer'), '')
        answers = [m['text'] for m in turns if m['role'] == 'operator']
        topic = (local_intent(question, {'connection', 'subscription', 'payment', 'delivery', 'question'}) or 'flow:general')[5:]
        topics[topic] += 1
        # Historical statements are evidence for REVIEW, never proof of an outcome.
        results.append({'digest': digest, 'turns': turns, 'category': topic,
                        'question': question[:500], 'answer': '\n'.join(answers[-3:])[:3500],
                        'media_count': attachments, 'media_available': available,
                        'outcome': 'unverified', 'status': 'pending' if question and answers else 'insufficient'})
        counts['media_referenced'] += attachments
        counts['media_available'] += available
    counts['conversations_selected'] = len(results)
    counts['external_ai_calls'] = 0
    counts['topics'] = dict(topics)
    counts['privacy'] = 'Pattern redaction and sender-name removal; review free-text PII before publishing.'
    return Analysis(results, dict(counts))
