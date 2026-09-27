"""Offline audit characterization; only temporary normal Git repositories are mutated."""
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from deepseek_tui.workspace import diff_synth as ds, mutation_ledger as ml
from deepseek_tui.workspace import git_reconcile as gr, managed_worktree as mw
from deepseek_tui.workspace.shell_write_guard import is_allowlisted_path
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpointStore


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True).stdout


def repo(root):
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'config', 'user.name', 'Fixture')
    for name in ['a.txt', 'b.txt', '中文.txt']:
        (root / name).write_text('base\n')
    (root / 'raw.bin').write_bytes(b'\x00base')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'base')
    return root


def mutation(path, status='applied'):
    return ml.FileMutation(path, 'turn', path, 'update', '', 0, 0, 'write_file', status)


async def main():
    results = {}
    diff, stats, _ = ds.synthesize_unified_diff('.env', 'old', 'new', op='update')
    results['diff'] = {'hidden_path_changed': 'a/env' in diff,
                       'no_newline_lines_joined': '-old+new' in diff,
                       'stats': vars_stats(stats)}
    results['hunk_prefix_stats'] = vars_stats(ds.count_diff_stats('@@ -1 +1 @@\n---old\n+++new\n'))
    ledger = ml.TurnMutationLedger('turn')
    ledger.commit(mutation('x'), before_content='a\n', after_content='b\n')
    ledger.commit(mutation('x', 'failed'), before_content='b\n', after_content='c\n')
    results['failed_mutation_in_net'] = '+c\n' in ledger.snapshot().merged_unified_diff
    results['fold_cost'] = {}
    for n in [10, 100]:
        ledger = ml.TurnMutationLedger('turn')
        with patch.object(ml, 'synthesize_unified_diff', wraps=ds.synthesize_unified_diff) as spy:
            for i in range(n):
                ledger.commit(mutation(str(i)), emit=False, before_content='a\n', after_content='b\n')
            results['fold_cost'][str(n)] = {'current_diff_calls': spy.call_count, 'incremental_target_calls': n}
    with tempfile.TemporaryDirectory(prefix='workspace-audit-') as temp:
        root = Path(temp)
        store = TurnCheckpointStore(root / 'checkpoints')
        store.begin_turn('../escaped', None, head=None, is_git=False)
        results['checkpoint_id_escape'] = (root / 'escaped.json').exists()
        results['guard_dotdot_allowed'] = is_allowlisted_path('build/../src/main.py', workspace=root)
        src, dst = repo(root / 'src'), repo(root / 'dst')
        (src / 'raw.bin').write_bytes(b'\x00source')
        (dst / 'raw.bin').write_bytes(b'\x00destination')
        report = await mw.handoff_changes(src, dst, move=False)
        results['binary_conflict'] = {'report': report.to_dict(), 'destination_overwritten': (dst / 'raw.bin').read_bytes() == b'\x00source'}
        git(src, 'checkout', 'HEAD', '--', '.')
        git(dst, 'checkout', 'HEAD', '--', '.')
        for name in ['a.txt', 'b.txt']:
            (src / name).write_text('new\n')
        original = mw._write_text
        def fail_one(target, rel, content):
            if rel == 'b.txt':
                raise OSError('fixture failure')
            return original(target, rel, content)
        with patch.object(mw, '_write_text', side_effect=fail_one):
            report = await mw.handoff_changes(src, dst, move=True)
        results['partial_move'] = {'report': report.to_dict(), 'failed_source_erased': (src / 'b.txt').read_text() == 'base\n', 'destination_missing_change': (dst / 'b.txt').read_text() == 'base\n'}
        git(src, 'checkout', 'HEAD', '--', '.')
        (src / '中文.txt').write_text('preexisting\n')
        baseline = await gr.capture_baseline(src)
        found = await gr.reconcile_to_ledger(ml.TurnMutationLedger('turn'), baseline)
        results['quoted_paths'] = {'baseline': sorted(baseline.dirty_at_start), 'incorrectly_attributed': [m.path for m in found]}
        git(src, 'checkout', 'HEAD', '--', '.')
        baseline = await gr.capture_baseline(src)
        (src / 'a.txt').write_text('committed during turn\n')
        git(src, 'add', '.')
        git(src, 'commit', '-qm', 'during turn')
        found = await gr.reconcile_to_ledger(ml.TurnMutationLedger('turn'), baseline)
        results['head_moved'] = {'recorded_paths': [m.path for m in found]}
        baseline = await gr.capture_baseline(src)
        outside = root / 'outside.txt'
        outside.write_text('fixture outside workspace\n')
        (src / 'link.txt').symlink_to(outside)
        found = await gr.reconcile_to_ledger(ml.TurnMutationLedger('turn'), baseline)
        results['symlink_read'] = any('fixture outside workspace' in m.unified_diff for m in found)
    print(json.dumps(results, ensure_ascii=False, indent=2))


def vars_stats(stats):
    return {'additions': stats.additions, 'deletions': stats.deletions}


if __name__ == '__main__':
    asyncio.run(main())
