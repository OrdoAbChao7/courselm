from pathlib import Path
import shutil
import subprocess
import pytest


def test_frontend_async_regressions():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for frontend concurrency regression tests')
    root = Path(__file__).parents[2]
    result = subprocess.run([node, 'studio/tests/frontend_regressions.cjs'], cwd=root,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
