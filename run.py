#!/usr/bin/env python3
"""CLI entry point for the benchmark runner."""

import argparse
import sys

from config import (
    DEFAULT_BENCH_ITERS,
    DEFAULT_PROFILE_ITERS,
    DEFAULT_TRIALS,
    detect_java,
)
from graphs import generate_graphs
from runner import run_benchmarks
from suites import SUITES


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark runner for JIT profile checkpoint evaluation"
    )
    parser.add_argument("suite", choices=list(SUITES.keys()), help="Benchmark suite")
    parser.add_argument("benchmarks", nargs="*", help="Benchmarks to run (default: all)")
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

    args = parser.parse_args()

    # Resolve paths
    java_path = args.java or detect_java()
    suite_cls = SUITES[args.suite]
    jar_path = args.jar or suite_cls.detect_jar()

    print(f"Java:  {java_path}")
    print(f"Jar:   {jar_path}")

    # Create suite
    suite = suite_cls(java_path=java_path, jar_path=jar_path)
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
