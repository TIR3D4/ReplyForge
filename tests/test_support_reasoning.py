from types import SimpleNamespace
import pytest
from replyforge.support_reasoning import understand


@pytest.mark.parametrize('raw,accepted', [
    ('{"action":"flow:connection","device":"ios","application":"V2Box","confidence":0.9}', True),
    ('{"action":"confirm_payment","confidence":1}', False),
    ('{"action":"human","confidence":0.2}', False),
    ('{"action":"human","confidence":1,"command":"delete"}', False),
    ('{"action":"human","device":"secret","confidence":1}', False),
    ('not json', False),
])
def test_only_typed_allowed_confident_decisions(raw, accepted):
    ai = SimpleNamespace(_complete=lambda *_: raw)
    result = understand(ai, 'با گوشی اپل وصل نمیشه', [], [{'label':'Connection', 'action':'flow:connection'}])
    assert bool(result) is accepted
