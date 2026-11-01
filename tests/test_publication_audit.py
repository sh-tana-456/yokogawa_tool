"""Publication checks must also work in source exports without Git."""
import json
from pathlib import Path
import shutil
import subprocess
import sys


def run_audit(tmp_path):
    scripts = tmp_path/'scripts'
    scripts.mkdir(exist_ok=True)
    source = Path(__file__).resolve().parents[1]/'scripts/audit-public.py'
    shutil.copyfile(source, scripts/source.name)
    result = subprocess.run([sys.executable, str(scripts/source.name)],
                            capture_output=True, text=True, check=False)
    return result, json.loads(result.stdout)


def test_source_export_detects_credential_filename_without_secret_pattern(tmp_path):
    (tmp_path/'connection.key').write_text('synthetic exclusion canary')
    result, report = run_audit(tmp_path)
    assert result.returncode == 1
    assert {'file': 'connection.key', 'kind': 'private-file-in-source', 'count': 1} in report['findings']


def test_audit_redacts_token_value(tmp_path):
    token = 'ghp_' + 'x'*30
    (tmp_path/'example.txt').write_text(token)
    result, report = run_audit(tmp_path)
    assert result.returncode == 1
    assert token not in result.stdout + result.stderr
    assert any(item['kind'] == 'github-token' for item in report['findings'])


def test_source_export_allows_documented_empty_env_example(tmp_path):
    (tmp_path/'.env.example').write_text('PASSWORD=\n')
    result, report = run_audit(tmp_path)
    assert result.returncode == 0
    assert report['git_commits'] == 0
    assert report['findings'] == []
