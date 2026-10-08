from pathlib import Path
import subprocess
import sys


def test_setup_script_help():
    script = Path("scripts/setup.py")
    result = subprocess.run([sys.executable, str(script), "--help"],
                            check=False, text=True, capture_output=True)
    assert result.returncode == 0
    assert "--preset" in result.stdout


def test_setup_preserves_literal_dollar_and_refuses_overwrite(tmp_path, monkeypatch):
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location('setup_test', 'scripts/setup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / '.env.example').write_text('BOT_TOKEN=\nWEBHOOK_PUBLIC_URL=\nADMIN_USERNAME=\nADMIN_PASSWORD=\n')
    answers = iter(['https://support.example.com', 'admin'])
    passwords = iter(['123:synthetic-token', 'long-$literal-password'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(answers))
    monkeypatch.setattr(module.getpass, 'getpass', lambda prompt: next(passwords))
    monkeypatch.setattr(sys, 'argv', ['setup.py'])
    module.main()
    assert "ADMIN_PASSWORD='long-$literal-password'" in (tmp_path/'.env').read_text()
    assert os.stat(tmp_path/'.env').st_mode & 0o777 == 0o600
    import pytest
    with pytest.raises(SystemExit, match='already exists'):
        module.main()
