"""Read-only public-package inventory, syntax, link and boundary checks."""
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IGNORED_ROOTS = {'.git', '.venv', '.local', '.state', 'generated', 'artifacts'}
BANNED_SUFFIXES = {'.docx', '.pdf', '.png', '.jpg', '.jpeg', '.svg', '.xlsx', '.xls', '.csv', '.sqlite', '.sqlite3', '.pem', '.key', '.safetensors', '.whl', '.bundle'}
PRIVATE_PATHS = ['/' + name + '/' for name in ['Users', 'workspace', 'mnt/data']]
SECRETS = [r'ghp_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{40,}', r'sk-[A-Za-z0-9_-]{30,}', r'libfile_[a-f0-9]{32}', r'Sentinel_[a-f0-9]{32}']


def inspect_text(name, raw):
    text = raw.decode('utf-8')
    if any(path in text for path in PRIVATE_PATHS):
        raise ValueError('private host path: ' + name)
    if any(re.search(pattern, text) for pattern in SECRETS):
        raise ValueError('credential or internal identifier: ' + name)
    if name.endswith('.py'):
        ast.parse(text, filename=name)
    if name.endswith('.json'):
        json.loads(text)
    if name.endswith('.jsonl'):
        for line in text.splitlines():
            if line.strip(): json.loads(line)


def main():
    records = json.loads((ROOT / 'PUBLIC_SOURCE.json').read_text())['files']
    actual = {}
    nested = 0
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in IGNORED_ROOTS or '__pycache__' in rel.parts:
            continue
        if path.is_symlink(): raise ValueError('symlink: ' + rel.as_posix())
        if not path.is_file() or path.suffix in {'.pyc', '.pyo'}: continue
        name = rel.as_posix()
        if path.suffix.lower() in BANNED_SUFFIXES or rel.parts[0] in {'evidence', 'reviews', 'private'} or path.name.startswith('.env'):
            raise ValueError('private/non-source payload: ' + name)
        raw = path.read_bytes()
        if path.suffix == '.zip':
            if name != 'provenance/companion-code-baseline.zip': raise ValueError('unapproved archive')
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if len(archive.namelist()) != len(set(archive.namelist())): raise ValueError('duplicate member')
                for member in archive.namelist():
                    p = Path(member)
                    if p.is_absolute() or '..' in p.parts or p.suffix not in {'.py', '.sql', '.json', '.jsonl'}: raise ValueError('unsafe nested member')
                    inspect_text(name + ':' + member, archive.read(member)); nested += 1
        else:
            inspect_text(name, raw)
        if name != 'PUBLIC_SOURCE.json': actual[name] = hashlib.sha256(raw).hexdigest()
    if actual != records: raise ValueError('public source inventory/hash mismatch')
    print(json.dumps({'status':'pass', 'source_files':len(actual), 'nested_code_members':nested, 'executed_labs':False, 'executed_models':False}))


if __name__ == '__main__': main()
