import pytest
from sqlalchemy import select

from replyforge.config import ConfigError, load_playbook, parse_playbook_yaml
from replyforge.database import session_scope
from replyforge.models import PlaybookVersion
from replyforge.playbooks import activate_version, effective_playbook, save_playbook


def test_versioned_playbook_save_edit_and_rollback(database):
    fallback = load_playbook("config/business.yaml")
    base = """brand: New Shop
locale: en
welcome: Hi
handoff_text: A human is coming
menu:
  - {label: Support, action: human}
workflows: {}
"""
    second = base.replace("New Shop", "Second Shop")
    with session_scope(database) as db:
        assert effective_playbook(db, fallback)[1] == 0
        one = save_playbook(db, base)
        first_id = one.id
        save_playbook(db, second)
        cfg, ver = effective_playbook(db, fallback)
        assert cfg["brand"] == "Second Shop"
        assert ver != first_id
        assert activate_version(db, first_id)
        assert effective_playbook(db, fallback)[0]["brand"] == "New Shop"
    with session_scope(database) as db:
        assert db.scalar(select(PlaybookVersion).where(PlaybookVersion.active.is_(True))).id == first_id


def test_playbook_rejects_insecure_or_invalid_transitions(database):
    with session_scope(database) as db:
        with pytest.raises(ConfigError):
            save_playbook(db, "brand: Shop\nmenu: [{label: bad, action: 'flow:fake'}]\nworkflows: {}")
        with pytest.raises(ValueError):
            save_playbook(db, "x" * 50001)
