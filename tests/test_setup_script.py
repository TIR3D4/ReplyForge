from pathlib import Path
import subprocess
import sys


def test_setup_script_help():
    script = Path("scripts/setup.py")
    result = subprocess.run([sys.executable, str(script), "--help"],
                            check=False, text=True, capture_output=True)
    assert result.returncode == 0
    assert "--preset" in result.stdout
