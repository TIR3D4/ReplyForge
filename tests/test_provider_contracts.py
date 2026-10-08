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
