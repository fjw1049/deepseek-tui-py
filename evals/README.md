# DeepSeek TUI Eval Platform

This directory is a behavioral evaluation system, not another unit-test folder.

- `src/` implements the product.
- `tests/` proves deterministic code contracts and tests this platform.
- `evals/` measures the combined behavior of prompts, context assembly, models,
  provider serialization, tools, approval policy, compaction, and completion claims.

## Commands

Validate the versioned YAML corpus:

```bash
python -m evals validate
```

Run all deterministic suites and write an append-only artifact bundle:

```bash
python -m evals run --mode offline
```

Run and compare against committed hard gates in one CI-friendly command:

```bash
python -m evals run \
  --mode offline \
  --baseline evals/baselines/offline.json
```

Or compare an existing artifact:

```bash
python -m evals compare \
  evals/baselines/offline.json \
  evals/artifacts/<run-id>/summary.json
```

Run opt-in real-provider cases with explicit request, output-token, timeout,
and known-cost budgets:

```bash
python -m evals run \
  --mode live \
  --provider anthropic \
  --model your-model-id \
  --trials 3 \
  --max-live-requests 20 \
  --max-output-tokens 1024 \
  --max-cost-usd 5
```

`--max-cost-usd` is enforced when the product has pricing for the selected
model: scheduling stops after recorded cost reaches the cap, so the final
in-flight request can overshoot it. The request and output-token limits remain
the hard provider-independent budgets. Live mode includes deterministic cases
and is never run implicitly.

## Artifact contract

Every run writes:

- `manifest.json`: commit, dirty-diff hash, dataset hash, prompt hash, tool
  catalog hash, runtime versions, model, and provider.
- `cases.jsonl`: one flushed, redacted record per case trial.
- `summary.json`: aggregate metrics used by baseline comparison.
- `failures/*.json`: isolated evidence for failures and runner errors.

Credentials and common bearer/API-key forms are redacted before persistence.
Raw system prompts are not stored; reports contain hashes and structural
evidence instead.

## Case contract

Cases are data, not executable code. YAML may select only registered harnesses
and graders. Arbitrary Python, shell assertions, dynamic imports, and embedded
judge prompts are intentionally unsupported.

Critical runtime invariants must still have ordinary tests. An eval can measure
how often a model attempts an unsafe action, but only product tests can prove
that the runtime always blocks it.
