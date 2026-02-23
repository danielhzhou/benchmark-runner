"""Generate matplotlib plots from benchmark metrics."""

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def generate_graphs(metrics: dict, output_dir: str) -> None:
    graphs_dir = Path(output_dir) / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)

    benchmarks = [b for b in metrics if metrics[b].get("cold_curve")]

    if not benchmarks:
        print("No benchmark data to graph.")
        return

    _convergence_plot(metrics, benchmarks, graphs_dir)
    _cold_vs_warm_plot(metrics, benchmarks, graphs_dir)
    _summary_bar_chart(metrics, benchmarks, graphs_dir)
    _closeness_ratio_plot(metrics, benchmarks, graphs_dir)

    print(f"Graphs saved to {graphs_dir}")


def _convergence_plot(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Per-benchmark convergence: cold curve + warm curve."""
    cols = min(3, len(benchmarks))
    rows = math.ceil(len(benchmarks) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 4 * rows), squeeze=False)

    for idx, bench in enumerate(benchmarks):
        ax = axes[idx // cols][idx % cols]
        m = metrics[bench]
        cold = m["cold_curve"]
        warm = m["warm_curve"]

        ax.plot(range(len(cold)), cold, "o-", label="Cold", color="tab:blue", markersize=3)
        if warm:
            ax.plot(range(len(warm)), warm, "s-", label="Warm", color="tab:orange", markersize=3)
        ax.set_title(bench)
        ax.set_xlabel("Iteration")
        ax.set_ylabel("Latency (ms)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    # Hide unused subplots
    for idx in range(len(benchmarks), rows * cols):
        axes[idx // cols][idx % cols].set_visible(False)

    fig.suptitle("Convergence: Cold vs Warm", fontsize=14)
    fig.tight_layout()
    fig.savefig(out / "convergence.png", dpi=150)
    plt.close(fig)


def _cold_vs_warm_plot(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Per-benchmark: cold curve + warm[2] horizontal line + cold_optimal line."""
    cols = min(3, len(benchmarks))
    rows = math.ceil(len(benchmarks) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 4 * rows), squeeze=False)

    for idx, bench in enumerate(benchmarks):
        ax = axes[idx // cols][idx % cols]
        m = metrics[bench]
        cold = m["cold_curve"]

        ax.plot(range(len(cold)), cold, "o-", label="Cold", color="tab:blue", markersize=3)

        if m["warm_target"] > 0:
            ax.axhline(y=m["warm_target"], color="tab:orange", linestyle="--", label=f"Warm[2] = {m['warm_target']:.0f}ms")

        if m["cold_optimal"] > 0:
            ax.axhline(y=m["cold_optimal"], color="tab:green", linestyle=":", label=f"Cold optimal = {m['cold_optimal']:.0f}ms")

        ax.set_title(bench)
        ax.set_xlabel("Iteration")
        ax.set_ylabel("Latency (ms)")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    for idx in range(len(benchmarks), rows * cols):
        axes[idx // cols][idx % cols].set_visible(False)

    fig.suptitle("Cold Curve vs Warm Target & Cold Optimal", fontsize=14)
    fig.tight_layout()
    fig.savefig(out / "cold_vs_warm.png", dpi=150)
    plt.close(fig)


def _summary_bar_chart(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Bar chart: cold[0]/warm[2] improvement ratio per benchmark."""
    ratios = []
    labels = []
    for bench in benchmarks:
        r = metrics[bench]["our_improvement"]
        if r > 0:
            ratios.append(r)
            labels.append(bench)

    if not ratios:
        return

    fig, ax = plt.subplots(figsize=(max(8, len(labels)), 5))
    bars = ax.bar(labels, ratios, color="tab:blue", alpha=0.8)
    ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
    ax.set_ylabel("Improvement Ratio (cold[0] / warm[2])")
    ax.set_title("First-Iteration Improvement: Cold vs Profile-Loaded")
    ax.grid(True, axis="y", alpha=0.3)

    for bar, ratio in zip(bars, ratios):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                f"{ratio:.2f}x", ha="center", va="bottom", fontsize=9)

    fig.tight_layout()
    fig.savefig(out / "summary_improvement.png", dpi=150)
    plt.close(fig)


def _closeness_ratio_plot(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """cold[N] / warm[2] per iteration N — how many cold iters to match warm[2]."""
    fig, ax = plt.subplots(figsize=(10, 6))

    for bench in benchmarks:
        cr = metrics[bench].get("closeness_ratio", [])
        if cr:
            ax.plot(range(len(cr)), cr, "o-", label=bench, markersize=3)

    ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.7, label="Parity (cold = warm[2])")
    ax.set_xlabel("Cold Iteration")
    ax.set_ylabel("Ratio (cold[N] / warm[2])")
    ax.set_title("Cold Convergence Toward Warm[2] Target")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out / "closeness_ratio.png", dpi=150)
    plt.close(fig)
