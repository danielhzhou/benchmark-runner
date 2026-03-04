"""Compute metrics from raw benchmark timings."""

import statistics


def _median_across_trials(trial_arrays: list[list[float]]) -> list[float]:
    """Given multiple trials of iteration arrays, return median at each index."""
    if not trial_arrays or not any(trial_arrays):
        return []
    max_len = max(len(t) for t in trial_arrays if t)
    result = []
    for i in range(max_len):
        vals = [t[i] for t in trial_arrays if len(t) > i]
        result.append(statistics.median(vals) if vals else 0.0)
    return result


def compute_metrics(all_results: dict) -> dict:
    """Compute metrics for all benchmarks.

    all_results: {benchmark: {"cold": [[t1,t2,...], ...], "warm": [...], "compile_times": [...]}}
    """
    metrics = {}

    for bench, data in all_results.items():
        cold = _median_across_trials(data["cold"])
        warm = _median_across_trials(data["warm"])
        compile_times = [t for t in data["compile_times"] if t >= 0]

        m = {}

        if cold:
            # Optimal = mean of last 5 cold iterations (steady state)
            tail = cold[-5:] if len(cold) >= 5 else cold
            cold_optimal = statistics.mean(tail)
            m["cold_optimal"] = cold_optimal
            m["optimal_speedup"] = cold[0] / cold_optimal if cold_optimal > 0 else 0

            # Time to optimal: first index within 10% of min(cold)
            cold_min = min(cold)
            threshold = cold_min * 1.1
            m["cold_time_to_optimal"] = next(
                (i for i, t in enumerate(cold) if t <= threshold), len(cold)
            )
        else:
            m["cold_optimal"] = 0
            m["optimal_speedup"] = 0
            m["cold_time_to_optimal"] = -1

        # Per-iteration speedup: cold[i] / warm[i] for each iteration
        n = min(len(cold), len(warm))
        if n > 0:
            per_iter_speedup = [cold[i] / warm[i] if warm[i] > 0 else 0 for i in range(n)]
            m["per_iter_speedup"] = per_iter_speedup
            m["first_iter_speedup"] = per_iter_speedup[0]
            m["mean_speedup"] = statistics.mean(per_iter_speedup)
        else:
            m["per_iter_speedup"] = []
            m["first_iter_speedup"] = 0
            m["mean_speedup"] = 0

        # Warm time to optimal: first warm index within 10% of min(warm)
        if warm:
            warm_min = min(warm)
            warm_threshold = warm_min * 1.1
            m["warm_time_to_optimal"] = next(
                (i for i, t in enumerate(warm) if t <= warm_threshold), len(warm)
            )
        else:
            m["warm_time_to_optimal"] = -1

        # Compile time
        m["compile_time_median"] = statistics.median(compile_times) if compile_times else -1

        # Raw median curves for graphing
        m["cold_curve"] = cold
        m["warm_curve"] = warm

        metrics[bench] = m

    return metrics
