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
                for path in ['/admin', '/admin/tickets', '/admin/agent', '/admin/insight', '/admin/operators', '/admin/connections', '/admin/playbook', '/admin/system']:
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
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
