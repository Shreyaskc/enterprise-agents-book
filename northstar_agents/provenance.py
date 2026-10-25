# SPDX-License-Identifier: MIT
"""Optional exact-root Git metadata; archive hashes remain the source identity."""
from pathlib import Path
import shutil
from .execution import run_bounded

def git_metadata(root: Path) -> dict:
    absent = {'git_revision': None, 'worktree_clean': None}
    git = shutil.which('git')
    if git is None:
        return {**absent, 'git_metadata_reason': 'git_unavailable'}
    if not (root / '.git').exists():
        return {**absent, 'git_metadata_reason': 'source_archive_no_local_git'}

    def run(*args):
        return run_bounded([git, *args], cwd=root, timeout=2)
    top = run('rev-parse', '--show-toplevel')
    if top['error'] or top['exit_code'] != 0:
        return {**absent, 'git_metadata_reason': top['error'] or 'git_root_unavailable'}
    if Path(top['stdout'].strip()).resolve() != root.resolve():
        return {**absent, 'git_metadata_reason': 'git_root_mismatch'}
    revision, status = (run('rev-parse', 'HEAD'), run('status', '--porcelain'))
    if any((r['error'] or r['exit_code'] != 0 for r in [revision, status])):
        return {**absent, 'git_metadata_reason': 'git_metadata_unavailable'}
    return {'git_revision': revision['stdout'].strip(), 'worktree_clean': not status['stdout'].strip(), 'git_metadata_reason': 'local_checkout_metadata_not_upstream_attestation'}
