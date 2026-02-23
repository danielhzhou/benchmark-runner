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
            # Optimal = mean of last 10 cold iterations (or all if fewer)
            tail = cold[-10:] if len(cold) >= 10 else cold
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

        # Our improvement: cold[0] / warm[2]
        warm_target = warm[2] if len(warm) > 2 else (warm[-1] if warm else 0)
        m["warm_target"] = warm_target
        m["our_improvement"] = cold[0] / warm_target if cold and warm_target > 0 else 0

        # Closeness to optimal curve: cold[N] / warm[2] for all N
        if warm_target > 0 and cold:
            m["closeness_ratio"] = [c / warm_target for c in cold]
        else:
            m["closeness_ratio"] = []

        # Compile time
        m["compile_time_median"] = statistics.median(compile_times) if compile_times else -1

        # Raw median curves for graphing
        m["cold_curve"] = cold
        m["warm_curve"] = warm

        metrics[bench] = m

    return metrics
