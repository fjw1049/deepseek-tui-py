# Compression recovery follow-up — 2026-11-12

Baseline: `0cb31607` compression implementation, reviewed on top of `4e445c4b`.

## Changes

- Remove working-set filename pins from automatic summary execution. Keep recent-history retention, complete tool-call/result pairs, user request ledger, and the working-path summary. Planning and execution both exclude an earlier compaction bridge when counting summarizable messages.
- Restore L0 aging by real user turns. Emergency cleanup remains independent of age and preserves recent complete exchanges.
- Copy the task request for summaries and cycle handoffs, retaining reasoning, sampling, extra body, tools and tool choice. Overflow callbacks receive the effective request, including the active tool catalog and output reserve.
- On failed overflow summarization, clear old tool bodies deterministically on a copy. Preserve user messages, tool pairing and the recent window; TurnLoop stops if this makes no progress.
- Persist `failure_reason` and `model_calls` in `harness.intervention`. Budget rejection before a provider request records zero calls; fallback cleanup reports `pruned` rather than a successful summary.
- Start summaries at 4K tokens for smaller windows and 8K for large windows. A 4K truncation may retry at 8K; an 8K truncation stops and preserves history. Input plus output must fit the configured window before any request.
- Expose positive absolute input caps in configuration:

```toml
[context]
max_input_tokens = 150000
cycle_max_input_tokens = 250000
```

Cycle remains enabled by the existing default configuration. This change does not establish that either cap is optimal.

## Live smoke evidence

Exactly two DeepSeek Flash requests, reasoning off, automatic tool choice. The fixture contained 1500 repeated records, three preservation constraints and a prior thinking block. This is a cache/serialization smoke test, not a real coding-task evaluation.

| Request | Input | Cache-read input | Output | Tool calls |
| --- | ---: | ---: | ---: | ---: |
| Warm prefix | 21,798 | 0 | 1 | 0 |
| Append summary | 23,636 | 21,760 | 432 | 0 |

Summary cache hit ratio: **92.06%**. Prefix probe reported no divergence. The summary passed structural validation and explicitly preserved offline support, Chinese exports and `config.toml`. Native payload regression tests separately verify that reasoning off removes prior reasoning from both requests, and that sampling settings are preserved.

Raw evidence: `evals/artifacts/compression-optimized-thinking-off-probe.json` (local artifact). The fixture/settings differ from the earlier 94% probe, so these percentages are not an A/B comparison.

The reusable two-request probe now accepts an output path and reasoning override:

```sh
PYTHONPATH=src .venv/bin/python -m evals.compression_probe \
  --reasoning-effort off \
  --output evals/artifacts/compression-followup-probe.json
```

Running that command spends model-account credit; it was not run again after the two-request smoke above.

## Validation and limits

The focused regression group passes 71 tests, including actual Engine request flow, working-file retention failure, old bridge counting, user constraints, native wire serialization, summary truncation bounds, overflow cleanup, configured caps, and persisted intervention diagnostics.

Reproduce the focused offline checks:

```sh
.venv/bin/pytest -q \
  tests/engine/test_compression_recovery.py \
  tests/engine/test_context_audit_fixes.py \
  tests/engine/test_append_summary.py \
  tests/engine/test_browser_cua_mechanisms.py \
  tests/engine/test_context_followup.py \
  tests/contract/test_transcript.py
```

For subsequent company-environment task evaluations, explicitly configure the company provider/model and set `[context].max_input_tokens = 30000` in the evaluation configuration to force compression. Keep concurrency, input cases, retention settings and provider settings identical between arms. Check persisted `failure_reason`, `model_calls`, task scores, total usage/cost and user-constraint survival. The raw smoke artifact above is local and is not included in this Git commit; its usage figures are recorded in the table.

The full non-live suite initially recorded 4,353 passes, 180 skips and 36 deselections. Its 13 failures and 46 setup errors were localhost/nested-sandbox permission failures; all 59 passed when rerun with the required local execution permissions. One additional Engine-flow regression was then included in the 71-test focused group, which also passed. `git diff --check` is clean; lint review found no new diagnostics relative to the baseline.

No paid three-case or ten-case A/B batch was run. The repository's evaluation-budget rule limits the personal account to bounded smoke tests. This work demonstrates fixes to reproducible failure paths and cache compatibility; it does **not** establish a production compression failure rate, total task cost improvement, or task-quality advantage. Those still require matched company-environment runs with equal concurrency and settings.
