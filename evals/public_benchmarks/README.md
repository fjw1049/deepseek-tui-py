# Public benchmark campaign

This adapter runs the existing `Engine.create` / `Engine.run` entry point inside
official Harbor task containers. Production code and the official verifier are
unchanged. The current campaign uses the configured `endpoint/glm-5-3` route.

The first campaign is Terminal-Bench 2.1 (89 tasks, one attempt each). This matches
the benchmark version named in the GLM-5.3 model card. The published 88.2% uses
Claude Code 2.1.207; it is a reference, not a matched control. Gateway identity,
hardware, agent implementation, reasoning defaults and repetitions can differ.
Do not interpret a score difference as a causal architecture penalty.

Run directory: `evals/artifacts/public-benchmarks-20261019/`.

The user subsequently requested parallel execution. The active supervisor is now
`parallel.py`: up to two tasks with a combined requested memory limit of 8192 MiB.
The existing trial was adopted without replay. `parallel-handoff-*.json` records
the change and preserves the prior supervisor state; the initial manifest and
evaluated source archive remain intact. `progress.json` now lists `active_tasks`,
and new supervisor output is in `campaign-parallel.log`. Create a `STOP` file in
the run directory to request a graceful stop. Do not start the old sequential
command while this supervisor is running.

- `source.tar.gz` freezes the evaluated source; `manifest.json` records its hash,
  dataset commit, task order, model and budgets.
- `progress.json` records the supervisor PID, active task and last heartbeat.
- `campaign.log` and `configs/*.console.log` preserve supervisor/Harbor output.
- `results.jsonl` is the append-only result ledger. Pilots are separate.
- `jobs/<attempt>/<trial>/agent/trace.jsonl` contains complete model requests,
  normalized provider events and Engine events, including tool arguments/results.
- The same `agent/` directory holds `final.json`, `status.json`, sanitized runtime
  configuration, package versions and installation/worker output.
- Each `verifier/` directory and trial `result.json` hold official test evidence.
- `analysis.json` and `analysis.md` summarize outcomes and review candidates.

Credentials travel through a private pipe and temporary container file, which the
worker removes before executing the task. Known credential values are redacted
from traces. No results are uploaded to a public leaderboard.

Original worker limits (the parallel supervisor allows up to two tasks): 600 model requests per task; 65,536 output tokens per
request; six hours per task; 15 minutes without progress; 120 seconds for Engine
startup; bounded setup/verifier phases and a seven-hour supervisor deadline.
Quota/authentication/persistent API errors stop scheduling. Three consecutive
environment/runtime/idle failures also stop the campaign. Valid wrong answers do
not stop it. Cost is unknown because this custom gateway has no verified price.

When `fast-policy.json` exists in the run directory, the parallel supervisor
limits subsequent attempts to 300 seconds for setup, 300 seconds without model
progress, and 1800 seconds total including verification. A timed-out trial receives
SIGINT, then forced termination after 30 seconds if needed; its failure is retained
and scheduling continues subject to the consecutive-failure guard. Earlier attempts
used the original budgets, so this is a mixed-budget campaign, not an official
same-budget comparison. Preserve the policy file when resuming.

The model sees task instructions and the task container, not host benchmark
solutions/tests. Harbor supplies the verifier after the agent finishes. Container
access is unrestricted within the isolated task. Personal plugins, MCP, web
search, child agents and background tasks are disabled for this first campaign;
GUI and multi-agent behavior therefore remain outside its measured scope.

Setup uses Harbor 0.24.0 in a separate virtual environment and Linux uv 0.9.5.
Resume this existing campaign from the repository root (requires Docker and endpoint connectivity):

```sh
.venv/bin/python -m evals.public_benchmarks.parallel \
  evals/artifacts/public-benchmarks-20261019 \
  evals/artifacts/public-benchmarks-20261019/parallel-handoff-1792395368936875000.json
```

Do not run duplicate supervisors. A file lock prevents this. Resume skips all
already recorded attempts, including failures; a repaired rerun must be a
separate campaign, not a silent replacement or best-of selection. Preserve the
source archive and adapter while a campaign is active. Raw artifacts are local
and git-ignored, so keep the directory when cleaning the checkout.

Refresh the analysis without making model calls:

```sh
.venv/bin/python -m evals.public_benchmarks.analyze \
  evals/artifacts/public-benchmarks-20261019
```

Task correctness comes from the official verifier. Tool errors are diagnostic:
an expected merge conflict followed by successful recovery is not automatically
an architecture defect. Repeated identical calls and a completed turn that fails
verification are review candidates, not automatic judgments of dishonest claims.
Broader scores require separate BFCL/SWE/interactive-task adapters and an explicit
matched baseline; this run does not claim those benchmarks or whole-product coverage.

Official references:

- https://github.com/harbor-framework/terminal-bench-2-1
- https://huggingface.co/zai-org/GLM-5.3/blob/main/README.md
- https://docs.harborframework.com/agents/custom-agents
