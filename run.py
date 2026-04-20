#!/usr/bin/env python3
"""CLI entry point for the benchmark runner."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from config import (
    DEFAULT_BENCH_ITERS,
    DEFAULT_PROFILE_ITERS,
    DEFAULT_TRIALS,
    detect_java,
)
from graphs import generate_graphs
from runner import run_benchmarks
from suites import SUITES

# Benchmarks considered "important" across suites.
IMPORTANT_BENCHMARKS: dict[str, list[str]] = {
    "dacapo": ["h2", "kafka", "eclipse"],
    "renaissance": ["dotty"],
}


def _run_suite(suite_name, benchmarks, java_path, jar_path, args, run_dir=None):
    """Instantiate a suite, validate, and run the given benchmarks."""
    suite_cls = SUITES[suite_name]
    resolved_jar = jar_path or suite_cls.detect_jar()

    print(f"\nJava:  {java_path}")
    print(f"Jar:   {resolved_jar}")

    suite = suite_cls(java_path=java_path, jar_path=resolved_jar, size=args.size)
    suite.validate_setup()

    available = suite.available_benchmarks()
    for b in benchmarks:
        if b not in available:
            print(f"Error: unknown benchmark '{b}'. Available: {available}", file=sys.stderr)
            sys.exit(1)

    print(f"Suite: {suite.name()}")
    print(f"Benchmarks: {benchmarks}")
    print(f"Config: profile_iters={args.profile_iters}, bench_iters={args.bench_iters}, trials={args.trials}")

    return run_benchmarks(
        suite=suite,
        benchmarks=benchmarks,
        profile_iters=args.profile_iters,
        bench_iters=args.bench_iters,
        trials=args.trials,
        output_dir=args.output_dir,
        cold_only=args.cold_only,
        run_dir=run_dir,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark runner for JIT profile checkpoint evaluation"
    )
    parser.add_argument("suite", nargs="?", choices=list(SUITES.keys()), default=None,
                        help="Benchmark suite")
    parser.add_argument("benchmarks", nargs="*", help="Benchmarks to run (default: all)")
    parser.add_argument("--important", action="store_true",
                        help="Run important benchmarks across all suites "
                             "(dacapo: h2, kafka, eclipse; renaissance: dotty)")
    parser.add_argument("--profile-iters", type=int, default=DEFAULT_PROFILE_ITERS,
                        help=f"Iterations for profiling run (default: {DEFAULT_PROFILE_ITERS})")
    parser.add_argument("--bench-iters", type=int, default=DEFAULT_BENCH_ITERS,
                        help=f"Iterations for cold/warm runs (default: {DEFAULT_BENCH_ITERS})")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS,
                        help=f"Number of trials per config (default: {DEFAULT_TRIALS})")
    parser.add_argument("--java", type=str, default=None, help="Path to java binary")
    parser.add_argument("--jar", type=str, default=None, help="Path to suite jar (auto-detected if omitted)")
    parser.add_argument("--output-dir", type=str, default="results",
                        help="Output directory (default: results/)")
    parser.add_argument("--no-graphs", action="store_true", help="Skip graph generation")
    parser.add_argument("--cold-only", action="store_true", help="Run only the cold phase (skip profiling and warm runs)")
    parser.add_argument("--size", type=str, default="small",
                        help="DaCapo benchmark size: small | default | large (default: small). "
                             "Ignored by Renaissance.")

    args = parser.parse_args()

    if args.important:
        if args.suite or args.benchmarks:
            parser.error("--important cannot be combined with a suite or benchmark list")

        java_path = args.java or detect_java()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shared_run_dir = str(Path(args.output_dir) / ts)

        merged_metrics = {}
        for suite_name, bench_list in IMPORTANT_BENCHMARKS.items():
            result = _run_suite(suite_name, bench_list, java_path, args.jar, args,
                                run_dir=shared_run_dir)
            merged_metrics.update(result["metrics"])

        # Write combined metrics over the per-suite ones
        metrics_path = Path(shared_run_dir) / "metrics.json"
        with open(metrics_path, "w") as f:
            json.dump(merged_metrics, f, indent=2)
        print(f"\nMerged metrics saved to {metrics_path}")

        if not args.no_graphs:
            generate_graphs(merged_metrics, shared_run_dir)

        print(f"\nDone. Results in {shared_run_dir}")
        return

    # --- Normal single-suite mode ---
    if not args.suite:
        parser.error("a suite is required (or use --important)")

    java_path = args.java or detect_java()
    suite_cls = SUITES[args.suite]
    jar_path = args.jar or suite_cls.detect_jar()

    print(f"Java:  {java_path}")
    print(f"Jar:   {jar_path}")

    # Create suite
    suite = suite_cls(java_path=java_path, jar_path=jar_path, size=args.size)
    suite.validate_setup()

    # Resolve benchmarks
    benchmarks = args.benchmarks or suite.available_benchmarks()
    available = suite.available_benchmarks()
    for b in benchmarks:
        if b not in available:
            print(f"Error: unknown benchmark '{b}'. Available: {available}", file=sys.stderr)
            sys.exit(1)

    print(f"Suite: {suite.name()}")
    print(f"Benchmarks: {benchmarks}")
    print(f"Config: profile_iters={args.profile_iters}, bench_iters={args.bench_iters}, trials={args.trials}")

    # Run
    result = run_benchmarks(
        suite=suite,
        benchmarks=benchmarks,
        profile_iters=args.profile_iters,
        bench_iters=args.bench_iters,
        trials=args.trials,
        output_dir=args.output_dir,
        cold_only=args.cold_only,
    )

    # Graphs
    if not args.no_graphs:
        generate_graphs(result["metrics"], result["run_dir"])

    print(f"\nDone. Results in {result['run_dir']}")


if __name__ == "__main__":
    main()
