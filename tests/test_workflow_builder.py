import pytest
from replyforge.config import load_playbook, ConfigError
from replyforge.workflow_builder import create_flow, save_step


def test_create_branching_flow_without_yaml():
    original = load_playbook('config/business.yaml')
    updated = create_flow(original, 'returns', 'Returns', 'Which order?')
    assert 'returns' not in original['workflows']
    updated = save_step(updated, 'returns', 'confirm', 'choice', 'Resolved?', 'result', '',
                        ['yes','no'], ['Yes','No'], ['complete','handoff'])
    updated = save_step(updated, 'returns', 'start', 'text', 'Order reference?', 'reference', 'confirm', [], [], [])
    assert updated['workflows']['returns']['states']['start']['next'] == 'confirm'
    with pytest.raises(ConfigError):
        save_step(updated, 'returns', 'start', 'text', 'Question', '', 'missing', [], [], [])
    with pytest.raises(ConfigError):
        create_flow(updated, 'returns', 'duplicate', 'question')
