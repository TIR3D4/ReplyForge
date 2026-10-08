import pytest
from replyforge.integrations import normalize, ProviderError

@pytest.mark.parametrize('data', [
    {}, {'status': 'active'}, [],
    {'status': 'active', 'used_traffic': -1, 'data_limit': 0, 'expire': None},
    {'status': 'active', 'used_traffic': 0, 'data_limit': '0', 'expire': None},
    {'status': 'active', 'used_traffic': 0, 'data_limit': 0, 'expire': 'invalid'},
    {'status': 'new-upstream-state', 'used_traffic': 0, 'data_limit': 0, 'expire': None},
])
def test_panel_schema_drift_cannot_fabricate_unlimited_active_account(data):
    with pytest.raises(ProviderError):
        normalize('pasarguard', data)


@pytest.mark.parametrize("provider,version", [("marzban", "0.8.4"), ("pasarguard", "5.4.1")])
def test_opt_in_version_gate_rejects_changed_panel_before_account_lookup(test_settings, provider, version):
    from dataclasses import replace
    import httpx
    from replyforge.integrations import MarzbanAdapter, PasarguardAdapter
    settings = replace(test_settings, marzban_base_url="https://panel.example",
        marzban_username="test", marzban_password="synthetic", marzban_expected_version=version,
        pasarguard_base_url="https://panel.example", pasarguard_api_key="synthetic",
        pasarguard_expected_version=version)
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == '/api/admin/token':
            return httpx.Response(200, json={"access_token": "synthetic"})
        assert request.url.path == '/api/system'
        return httpx.Response(200, json={"version": "999.0.0"})
    adapter = (MarzbanAdapter if provider == 'marzban' else PasarguardAdapter)(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match='version_mismatch'):
        adapter.lookup('123')
    assert not any('/api/user/' in path for path in seen)


def test_version_probe_accepts_exact_version_and_rejects_unknown():
    import httpx
    from replyforge.integrations import verify_version
    with httpx.Client(base_url='https://panel.example', transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={'version': 'v5.4.1'}))) as client:
        verify_version(client, {}, '5.4.1', 'pasarguard')
        with pytest.raises(ProviderError, match='version_mismatch'):
            verify_version(client, {}, '5.4.2', 'pasarguard')
