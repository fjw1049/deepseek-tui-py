"""Command-line entry point: ``python -m evals``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from evals.compare import compare_files
from evals.runner import RunOptions, load_cases, run_evaluations, validate_cases


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals")
    commands = parser.add_subparsers(dest="command", required=True)

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

    compare = commands.add_parser("compare", help="compare summary against gates")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("summary", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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

    if args.command == "compare":
        failures = compare_files(args.baseline, args.summary)
        if failures:
            for failure in failures:
                print(f"REGRESSION {failure}")
            return 1
        print("baseline gates passed")
        return 0

    if (
        args.trials < 1
        or args.max_live_requests < 0
        or args.max_output_tokens < 1
        or args.timeout <= 0
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
        if summary.failed == 0
        and summary.errors == 0
        and summary.skipped == 0
        and not failures
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
