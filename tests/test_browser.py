"""Actual Chromium checks; explicitly opt in with RUN_BROWSER_TESTS=1."""
import os
import socket
import threading
from pathlib import Path
from dataclasses import replace

import pytest

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Chromium not requested')


@pytest.mark.parametrize('locale', ['en', 'fa'])
def test_responsive_admin_and_policy_submission(database, test_settings, fake_telegram, locale):
    from playwright.sync_api import sync_playwright
    import uvicorn
    from replyforge.app import build_app
    settings = replace(test_settings, business_config='examples/azadbird.yaml' if locale == 'fa' else 'config/business.yaml')
    from replyforge.database import session_scope
    from replyforge.models import BusinessConnection, Conversation, Message, Ticket, utcnow
    with session_scope(database) as db:
        db.add(BusinessConnection(id='browser-synthetic', enabled=True, can_reply=True))
        db.flush()
        conv = Conversation(business_connection_id='browser-synthetic', chat_id=12345,
                            owner='human', last_inbound_at=utcnow(), state={})
        db.add(conv)
        db.flush()
        cid = conv.id
        db.add(Ticket(conversation_id=cid, status='open', priority='high', category='connection'))
        db.add(Message(conversation_id=cid, direction='in', kind='text',
                       content='اتصال روی آیفون برقرار نمی‌شود. Please help me update my subscription.'))
    from test_insight_worker import seed
    from replyforge.models import InsightTask
    task_id = seed(database)
    with session_scope(database) as db:
        db.get(InsightTask, task_id).status = 'failed'
    app = build_app(settings, factory=database, telegram=fake_telegram)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    folder = Path('artifacts/ui')
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel=os.getenv("BROWSER_CHANNEL") or None)
            context = browser.new_context(http_credentials={'username': settings.admin_username, 'password': settings.admin_password})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            for width in [1440, 360]:
                page.set_viewport_size({'width': width, 'height': 1000})
                for path in ['/admin', '/admin/tickets', '/admin/inbox', '/admin/agent', '/admin/insight', '/admin/operators', '/admin/connections', '/admin/playbook', '/admin/system', f'/admin/conversations/{cid}']:
                    response = page.goto(f'http://127.0.0.1:{port}{path}')
                    assert response.status == 200
                    assert page.locator('html').get_attribute('dir') == ('rtl' if locale == 'fa' else 'ltr')
                    assert page.locator('h1').count() == 1
                    page.screenshot(path=str(folder/f'{locale}-{width}-{path.split("/")[-1]}.png'), full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), f'{path} overflows at {width}'
                page.goto(f'http://127.0.0.1:{port}/admin/agent')
                current = page.locator('html').get_attribute('data-theme')
                page.locator('#theme-toggle').click()
                assert page.locator('html').get_attribute('data-theme') != current
                page.screenshot(path=str(folder/f'{locale}-{width}-theme.png'), full_page=True)
            page.locator('[name=model]').fill('test-model')
            page.locator('form[action="/admin/agent"] button').click()
            page.wait_for_url(f'http://127.0.0.1:{port}/admin/agent')
            assert page.locator('[name=model]').input_value() == 'test-model'
            page.locator('form[action="/admin/agent/test"] textarea').fill('payment problem')
            page.locator('form[action="/admin/agent/test"] button').click()
            page.wait_for_url(f'http://127.0.0.1:{port}/admin/agent/test')
            assert 'flow:payment' in page.locator('main').inner_text()
            page.goto(f'http://127.0.0.1:{port}/admin/insight')
            editor = page.locator('.image-editor').first
            editor.locator('summary').click()
            # Build a synthetic local PNG; no external image or customer data.
            import base64
            encoded = page.evaluate("""() => { const c = document.createElement('canvas'); c.width=100; c.height=100; const x=c.getContext('2d'); x.fillStyle='#ff0000'; x.fillRect(0,0,100,100); return c.toDataURL('image/png').split(',')[1]; }""")
            upload = {'name':'synthetic.png','mimeType':'image/png','buffer':base64.b64decode(encoded)}
            editor.locator('.image-input').set_input_files(upload)
            canvas = editor.locator('canvas')
            from playwright.sync_api import expect
            expect(canvas).to_be_visible()
            consent = editor.locator('[name=privacy_reviewed]')
            consent.check()
            editor.locator('.image-reset').click()
            expect(consent).not_to_be_checked()
            canvas.scroll_into_view_if_needed()
            bounds = canvas.bounding_box()
            page.mouse.move(bounds['x']+10, bounds['y']+10)
            page.mouse.down()
            page.mouse.move(bounds['x']+70, bounds['y']+70)
            page.mouse.up()
            assert canvas.evaluate("c => Array.from(c.getContext('2d').getImageData(40,40,1,1).data)") == [0,0,0,255]
            # The original has no form name and cannot be submitted with the form.
            assert editor.locator('.image-input').get_attribute('name') is None
            reviewed = canvas.evaluate("c => c.toDataURL('image/png').split(',')[1]")
            consent.check()
            page.screenshot(path=str(folder/f'{locale}-360-image-review.png'), full_page=True)
            editor.locator('[type=submit]').click()
            page.wait_for_url(f'http://127.0.0.1:{port}/admin/insight?import_id=*')
            with session_scope(database) as db:
                assert db.get(InsightTask, task_id).image_data == base64.b64decode(reviewed)
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
