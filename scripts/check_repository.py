# SPDX-License-Identifier: MIT
"""Bounded source-only check; .git is neither required nor treated as provenance."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib
ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {'.git', '.venv', '__pycache__', '.cache', '.uv-cache', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.state', 'raw', 'derived', 'local', 'reports', 'build', 'dist', 'htmlcov'}
REQUIRED = ['pyproject.toml', 'northstar_agents/__main__.py', 'data/fixtures/northstar_synthetic.json', 'data/manifests/synthetic.json', 'evals/cases/regression.json', 'docs/lab-index.json', 'README.md', 'LICENSE']

def main():
    try:
        if not all(((ROOT / p).is_file() and (not (ROOT / p).is_symlink()) for p in REQUIRED)):
            raise ValueError('invalid_lab_root')
        if tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['name'] != 'northstar-enterprise-agents':
            raise ValueError('invalid_lab_root')
        files = []
        total = 0
        for absolute in sorted(ROOT.rglob('*')):
            path = absolute.relative_to(ROOT)
            if any((part in EXCLUDED or part.endswith('.egg-info') for part in path.parts)):
                continue
            if absolute.is_symlink():
                raise ValueError('symlink_denied')
            if not absolute.is_file() or path.name == '.DS_Store' or absolute.suffix in {'.pyc', '.pyo'}:
                continue
            if absolute.stat().st_size > 1000000:
                raise ValueError('source_file_too_large')
            total += absolute.stat().st_size
            files.append(path)
            if len(files) > 300 or total > 5000000:
                raise ValueError('source_set_too_large')
        if not files:
            raise ValueError('empty_source_set')
        counts = {'python': 0, 'json': 0, 'markdown': 0, 'fixture_hash': 0}
        for path in files:
            absolute = ROOT / path
            if path.suffix == '.py':
                ast.parse(absolute.read_text(), filename=str(path))
                counts['python'] += 1
            if path.suffix == '.json':
                json.loads(absolute.read_text())
                counts['json'] += 1
            if path.name.startswith('.env') or path.suffix in {'.xlsx', '.zip', '.sqlite', '.sqlite3', '.pem', '.key'}:
                raise ValueError('disallowed_source_file')
            if path.suffix in {'.md', '.py', '.json', '.yml', '.toml'}:
                value = absolute.read_text()
                patterns = ['ghp_[A-Za-z0-9]{20,}', 'github_pat_[A-Za-z0-9_]{20,}', 'sk-[A-Za-z0-9_-]{24,}', '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
                if any((re.search(pattern, value) for pattern in patterns)):
                    raise ValueError('potential_credential')
                if path.suffix == '.md':
                    counts['markdown'] += 1
                    for target in re.findall('\\]\\(([^)#]+)(?:#[^)]*)?\\)', value):
                        if '://' in target or target.startswith('mailto:'):
                            continue
                        resolved = (absolute.parent / target).resolve()
                        if not resolved.is_relative_to(ROOT) or not resolved.exists():
                            raise ValueError('broken_relative_link')
        fixture = ROOT / 'data/fixtures/northstar_synthetic.json'
        if hashlib.sha256(fixture.read_bytes()).hexdigest() != json.loads((ROOT / 'data/manifests/synthetic.json').read_text())['sha256']:
            raise ValueError('fixture_checksum_mismatch')
        counts['fixture_hash'] = 1
        sys.path.insert(0, str(ROOT))
        from northstar_agents.coverage import load_contract
        load_contract(ROOT / 'docs/lab-index.json', 'labs')
        load_contract(ROOT / 'evals/cases/regression.json', 'regression')
        identity = hashlib.sha256()
        for path in files:
            identity.update(path.as_posix().encode() + b'\x00' + (ROOT / path).read_bytes())
        print(json.dumps({'status': 'pass', 'check_type': 'bounded_source_only_no_git_provenance', 'files_checked': len(files), 'source_files': [p.as_posix() for p in files], 'source_set_sha256': identity.hexdigest(), 'total_bytes': total, 'checks_executed': counts, 'labs': 12}, indent=2))
        return 0
    except (ValueError, OSError, KeyError, SyntaxError) as exc:
        print(json.dumps({'status': 'fail', 'check_type': 'bounded_source_only_no_git_provenance', 'error_type': type(exc).__name__}))
        return 1
if __name__ == '__main__':
    raise SystemExit(main())
