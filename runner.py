"""Core orchestration: cold/profile/warm loop across benchmarks and trials."""

import json
import os
from datetime import datetime
from pathlib import Path

from suites.base import BenchmarkSuite, RunResult
from metrics import compute_metrics


def run_benchmarks(
    suite: BenchmarkSuite,
    benchmarks: list[str],
    profile_iters: int,
    bench_iters: int,
    trials: int,
    output_dir: str,
) -> dict:
    """Run all benchmarks and return results dict."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(output_dir) / ts
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    all_results = {}

    for bench in benchmarks:
        print(f"\n{'='*60}")
        print(f"Benchmark: {bench}")
        print(f"{'='*60}")

        bench_data = {"cold": [], "warm": [], "compile_times": []}

        for trial in range(trials):
            print(f"\n--- Trial {trial + 1}/{trials} ---")

            profile_path = str(run_dir / "raw" / f"{bench}_trial{trial}.mdox")

            # Cold run
            print(f"[cold] {bench} ({bench_iters} iters)")
            cold = suite.run_cold(bench, bench_iters)
            _save_log(raw_dir / f"{bench}_trial{trial}_cold.log", cold)
            bench_data["cold"].append(cold.iteration_times)
            print(f"  -> {len(cold.iteration_times)} iterations parsed, exit={cold.exit_code}")

            # Profiling run
            print(f"[profile] {bench} ({profile_iters} iters)")
            prof = suite.run_profiling(bench, profile_iters, profile_path)
            _save_log(raw_dir / f"{bench}_trial{trial}_profile.log", prof)
            print(f"  -> exit={prof.exit_code}, profile at {profile_path}")

            if not Path(profile_path).exists():
                print(f"  WARNING: profile file not created at {profile_path}")
                bench_data["warm"].append([])
                bench_data["compile_times"].append(-1.0)
                continue

            # Warm run
            print(f"[warm] {bench} ({bench_iters} iters)")
            warm = suite.run_warm(bench, bench_iters, profile_path)
            _save_log(raw_dir / f"{bench}_trial{trial}_warm.log", warm)
            bench_data["warm"].append(warm.iteration_times)
            bench_data["compile_times"].append(warm.compile_time)
            print(f"  -> {len(warm.iteration_times)} iterations parsed, compile={warm.compile_time}ms, exit={warm.exit_code}")

        all_results[bench] = bench_data

    # Compute metrics
    metrics = compute_metrics(all_results)

    metrics_path = run_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nMetrics saved to {metrics_path}")

    return {"run_dir": str(run_dir), "results": all_results, "metrics": metrics}


def _save_log(path: Path, result: RunResult) -> None:
    with open(path, "w") as f:
        f.write(f"exit_code: {result.exit_code}\n")
        f.write(f"iteration_times: {result.iteration_times}\n")
        f.write(f"compile_time: {result.compile_time}\n")
        f.write(f"{'='*40}\n")
        f.write(result.raw_output)
