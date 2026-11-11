"""Command-line entry point: ``python -m evals``."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import Any

from evals.compare import compare_files
from evals.runner import RunOptions, load_cases, run_evaluations, validate_cases


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="start the independent local Eval Lab")
    serve.add_argument("--port", type=int, default=7879)

    validate = commands.add_parser("validate", help="validate all case files")
    validate.add_argument("--suite", action="append", default=[])

    run = commands.add_parser("run", help="run evaluation suites")
    run.add_argument("--suite", action="append", default=[])
    run.add_argument("--mode", choices=("offline", "live"), default="offline")
    run.add_argument("--provider")
    run.add_argument("--model")
    run.add_argument("--trials", type=int, default=1)
    run.add_argument("--max-cases", type=int)
    run.add_argument("--max-live-requests", type=int, default=20)
    run.add_argument("--max-output-tokens", type=int, default=2048)
    run.add_argument("--max-cost-usd", type=float)
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--output", type=Path)
    run.add_argument("--baseline", type=Path)
    run.add_argument("--case", action="append", default=[])
    run.add_argument("--label", default="")
    run.add_argument("--prompt-suffix", default="")
    run.add_argument("--concurrency", type=int, default=1)
    run.add_argument("--judge-provider")
    run.add_argument("--judge-model")
    run.add_argument("--max-input-tokens", type=int)

    card = commands.add_parser("scorecard", help="summarize the evidence in a finished run")
    card.add_argument("run", type=Path)

    compare = commands.add_parser("compare", help="compare summary against gates")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("summary", type=Path)

    runs = commands.add_parser("compare-runs", help="compare two finished runs case by case")
    runs.add_argument("a", type=Path)
    runs.add_argument("b", type=Path)

    campaign = commands.add_parser("campaign", help="run a frozen-source A/A + A/B experiment")
    campaign.add_argument("spec", type=Path, help="JSON hypothesis, cases, budgets and policy")
    campaign.add_argument("--output", type=Path, required=True)

    decision = commands.add_parser("decide", help="apply a frozen policy to paired run artifacts")
    decision.add_argument("baseline", type=Path)
    decision.add_argument("candidate", type=Path)
    decision.add_argument("--repeat", type=Path)
    decision.add_argument("--policy", type=Path, required=True)
    decision.add_argument("--output", type=Path, required=True)

    soak = commands.add_parser("soak-baseline", help="metrics from an archived thread store")
    soak.add_argument("store", type=Path)
    soak.add_argument("--output", type=Path, required=True)
    soak.add_argument("--exclude", type=Path, help="JSON list of thread ids to leave out")

    regrade = commands.add_parser("regrade", help="grade a finished run's sessions again")
    regrade.add_argument("run", type=Path)
    regrade.add_argument("--judge-provider")
    regrade.add_argument("--judge-model")
    regrade.add_argument("--max-live-requests", type=int, default=500)
    regrade.add_argument("--reuse-judge", action="store_true",
                         help="keep saved reviews; only the deterministic checks run again")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        import uvicorn

        from evals.server import create_app

        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)
        return 0
    if args.command == "validate":
        cases = load_cases()
        if args.suite:
            cases = [case for case in cases if case.suite in args.suite]
        if not cases:
            print("ERROR no eval cases selected")
            return 1
        errors = validate_cases(cases)
        if errors:
            for error in errors:
                print(f"ERROR {error}")
            return 1
        print(f"validated {len(cases)} eval cases")
        return 0

    if args.command == "scorecard":
        from evals.scorecard import write_scorecard

        print(write_scorecard(args.run))
        return 0

    if args.command == "compare":
        failures = compare_files(args.baseline, args.summary)
        if failures:
            for failure in failures:
                print(f"REGRESSION {failure}")
            return 1
        print("baseline gates passed")
        return 0

    if args.command == "compare-runs":
        from evals.experiments import format_comparison, load_run

        print(format_comparison(load_run(args.a), load_run(args.b)))
        return 0

    if args.command in {"campaign", "decide"}:
        from evals.decision import DecisionPolicy, decide
        from evals.experiments import load_run
        from evals.report import write_json

        try:
            if args.command == "campaign":
                from evals.campaign import CampaignSpec, run_campaign

                spec = CampaignSpec.model_validate_json(args.spec.read_text())

                async def execute() -> dict[str, Any]:
                    task = asyncio.create_task(run_campaign(spec, args.output))
                    loop = asyncio.get_running_loop()
                    loop.add_signal_handler(signal.SIGTERM, task.cancel)
                    try:
                        return await task
                    finally:
                        loop.remove_signal_handler(signal.SIGTERM)

                result = asyncio.run(execute())
            else:
                policy = DecisionPolicy.model_validate_json(args.policy.read_text())
                result = decide(load_run(args.baseline), load_run(args.candidate), policy,
                                load_run(args.repeat) if args.repeat else None)
                if args.output.exists():
                    raise ValueError("decision output already exists; preserve the previous record")
                write_json(args.output, result)
        except (ValueError, OSError) as exc:
            print(f"ERROR {exc}")
            return 2
        print(json.dumps({"decision": result["decision"], "reasons": result["reasons"],
                          "output": str(args.output)}, ensure_ascii=False))
        return {"review_candidate": 0, "keep_baseline": 1, "insufficient_evidence": 2}[
            result["decision"]
        ]

    if args.command == "soak-baseline":
        from evals.regrade import soak_baseline

        report = soak_baseline(args.store, args.output, args.exclude)
        print(f"sessions={report['sessions']} report={args.output}")
        return 0

    if args.command == "regrade":
        from evals.regrade import regrade

        output, summary = asyncio.run(
            regrade(args.run, args.judge_provider, args.judge_model, args.max_live_requests,
                    reuse_judge=args.reuse_judge)
        )
        print(f"passed={summary.passed} failed={summary.failed} errors={summary.errors} "
              f"artifacts={output}")
        return 0

    if (
        args.trials < 1
        or args.max_live_requests < 0
        or args.max_output_tokens < 1
        or args.timeout <= 0
        or args.concurrency < 1
        or (args.max_cost_usd is not None and args.max_cost_usd <= 0)
    ):
        print("invalid eval count, token, timeout, or cost budget")
        return 2
    options = RunOptions(
        mode=args.mode,
        suites=tuple(args.suite),
        provider=args.provider,
        model=args.model,
        trials=args.trials,
        max_cases=args.max_cases,
        max_live_requests=args.max_live_requests,
        max_output_tokens=args.max_output_tokens,
        max_cost_usd=args.max_cost_usd,
        timeout_seconds=args.timeout,
        output_dir=args.output,
        case_ids=tuple(args.case),
        label=args.label,
        prompt_suffix=args.prompt_suffix,
        concurrency=args.concurrency,
        judge_provider=args.judge_provider,
        judge_model=args.judge_model,
        max_input_tokens=args.max_input_tokens,
    )
    output, summary = asyncio.run(run_evaluations(options))
    print(
        f"run={summary.run_id} passed={summary.passed} failed={summary.failed} "
        f"errors={summary.errors} skipped={summary.skipped} artifacts={output}"
    )
    failures = []
    if args.baseline is not None:
        failures = compare_files(args.baseline, output / "summary.json")
        for failure in failures:
            print(f"REGRESSION {failure}")
    return (
        0
        if summary.failed == 0 and summary.errors == 0 and summary.skipped == 0 and not failures
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
