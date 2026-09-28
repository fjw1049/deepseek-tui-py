"""Compare pre-fix ledger against the working tree; no user data or timing assertions."""

import json
import subprocess
import sys
import time
import types
from unittest.mock import patch

from deepseek_tui.workspace import mutation_ledger as current

BASELINE = "0eeaeb8c"
source = subprocess.check_output(
    ["git", "show", f"{BASELINE}:src/deepseek_tui/workspace/mutation_ledger.py"], text=True
)
old = types.ModuleType("audit_old_ledger")
sys.modules[old.__name__] = old
exec(compile(source, "<baseline ledger>", "exec"), old.__dict__)
results = []
for count in (1, 100, 1000):
    row = {"commits": count}
    snapshots = []
    for label, module in [("before", old), ("after", current)]:
        ledger = module.TurnMutationLedger("turn")
        with patch.object(
            module, "synthesize_unified_diff", wraps=module.synthesize_unified_diff
        ) as spy:
            start = time.perf_counter()
            for i in range(count):
                change = module.FileMutation(
                    str(i), "turn", f"{i}.py", "update", "", 0, 0, "write_file"
                )
                ledger.commit(change, emit=False, before_content="old\n", after_content="new\n")
            elapsed = time.perf_counter() - start
            row[label] = {"seconds": round(elapsed, 6), "diff_calls": spy.call_count}
        snapshots.append(ledger.snapshot().to_dict())
    row["same_snapshot"] = snapshots[0] == snapshots[1]
    results.append(row)
print(json.dumps({"baseline": BASELINE, "runs_per_case": 1, "results": results}, indent=2))
