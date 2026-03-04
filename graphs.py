"""Generate matplotlib plots from benchmark metrics."""

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
COLD_COLOR  = "#e05252"   # warm red  — cold / no-profile runs
WARM_COLOR  = "#4caf82"   # muted green — warm / profile-loaded runs
OPT_COLOR   = "#5b8dd9"   # blue — reference lines
GRID_COLOR  = "#e8e8e8"
BG_COLOR    = "#fafafa"

TITLE_FONT  = dict(fontsize=13, fontweight="bold", color="#1a1a2e")
LABEL_FONT  = dict(fontsize=9,  color="#444444")
TICK_FONT   = dict(labelsize=8, colors="#666666")
LEGEND_FONT = dict(fontsize=8)
SUPTITLE_FONT = dict(fontsize=15, fontweight="bold", color="#1a1a2e", y=1.01)

BADGE_STYLE = dict(
    boxstyle="round,pad=0.35", facecolor="#fff8e1",
    edgecolor="#e0c060", linewidth=0.8, alpha=0.92,
)

LINE_KW_COLD = dict(color=COLD_COLOR, linewidth=1.4, alpha=0.85, zorder=3)
LINE_KW_WARM = dict(color=WARM_COLOR, linewidth=1.4, alpha=0.85, zorder=3)


def _style_ax(ax: plt.Axes, title: str = "") -> None:
    """Apply consistent axis styling."""
    ax.set_facecolor(BG_COLOR)
    ax.grid(True, color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#cccccc")
    ax.tick_params(axis="both", **TICK_FONT)
    ax.set_xlabel("Iteration", **LABEL_FONT)
    ax.set_ylabel("Latency (ms)", **LABEL_FONT)
    if title:
        ax.set_title(title, **TITLE_FONT, pad=6)


def _add_speedup_badge(ax: plt.Axes, label: str) -> None:
    """Small annotation badge."""
    ax.text(
        0.03, 0.97, label,
        transform=ax.transAxes,
        verticalalignment="top", fontsize=8,
        color="#5a4000", bbox=BADGE_STYLE,
    )


def _make_figure(n: int, cols: int = 2, subplot_h: float = 3.8) -> tuple:
    rows = math.ceil(n / cols)
    fig_w = 6.5 * cols
    fig_h = subplot_h * rows
    fig, axes = plt.subplots(rows, cols, figsize=(fig_w, fig_h), squeeze=False)
    fig.patch.set_facecolor("white")
    return fig, axes, rows


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_graphs(metrics: dict, output_dir: str) -> None:
    graphs_dir = Path(output_dir) / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)

    benchmarks = [b for b in metrics if metrics[b].get("cold_curve")]

    if not benchmarks:
        print("No benchmark data to graph.")
        return

    _convergence_plot(metrics, benchmarks, graphs_dir)
    _per_iter_speedup_plot(metrics, benchmarks, graphs_dir)
    _summary_bar_chart(metrics, benchmarks, graphs_dir)
    _time_to_optimal_chart(metrics, benchmarks, graphs_dir)

    print(f"Graphs saved to {graphs_dir}")


# ---------------------------------------------------------------------------
# Individual plots
# ---------------------------------------------------------------------------

def _convergence_plot(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Per-benchmark convergence: cold curve vs warm curve overlaid."""
    cols = 2
    fig, axes, rows = _make_figure(len(benchmarks), cols)

    for idx, bench in enumerate(benchmarks):
        ax = axes[idx // cols][idx % cols]
        m = metrics[bench]
        cold = m["cold_curve"]
        warm = m["warm_curve"]
        xs = range(1, len(cold) + 1)

        ax.plot(xs, cold, label="Cold (no profile)", **LINE_KW_COLD)
        if warm:
            ax.plot(range(1, len(warm) + 1), warm,
                    label="Warm (with profile)", **LINE_KW_WARM)
            speedup = m.get("first_iter_speedup", 0)
            if speedup > 0:
                _add_speedup_badge(ax, f"1st iter: {speedup:.2f}×")

        _style_ax(ax, bench)
        ax.legend(**LEGEND_FONT, framealpha=0.9, edgecolor="#dddddd")

    _hide_empty(axes, len(benchmarks), rows, cols)
    fig.suptitle("Convergence: Cold vs Warm", **SUPTITLE_FONT)
    fig.tight_layout()
    fig.savefig(out / "convergence.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _per_iter_speedup_plot(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Per-iteration speedup ratio: cold[i] / warm[i] for each benchmark."""
    palette = plt.cm.tab10.colors

    fig, ax = plt.subplots(figsize=(11, 6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor(BG_COLOR)

    for i, bench in enumerate(benchmarks):
        ratios = metrics[bench].get("per_iter_speedup", [])
        if ratios:
            color = palette[i % len(palette)]
            ax.plot(range(1, len(ratios) + 1), ratios,
                    label=bench, color=color,
                    linewidth=1.5, alpha=0.85, zorder=3)

    ax.axhline(y=1.0, color="#555555", linestyle="--", linewidth=1.4,
               alpha=0.7, label="Parity (cold = warm)", zorder=4)

    ax.grid(True, color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#cccccc")
    ax.tick_params(axis="both", **TICK_FONT)
    ax.set_xlabel("Iteration", **LABEL_FONT)
    ax.set_ylabel("Speedup  (cold[i] / warm[i])", **LABEL_FONT)
    ax.set_title("Per-Iteration Speedup: Cold / Warm", **TITLE_FONT, pad=8)
    ax.legend(**LEGEND_FONT, framealpha=0.9, edgecolor="#dddddd",
              loc="upper right", ncol=max(1, len(benchmarks) // 6))

    fig.tight_layout()
    fig.savefig(out / "per_iter_speedup.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _summary_bar_chart(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Horizontal bar chart: first-iteration speedup and mean speedup per benchmark."""
    items = [
        (bench, metrics[bench].get("first_iter_speedup", 0),
         metrics[bench].get("mean_speedup", 0))
        for bench in benchmarks
    ]
    items = [(b, f, m) for b, f, m in items if f > 0]
    if not items:
        return

    items.sort(key=lambda x: x[1])
    labels = [x[0] for x in items]
    first_speedups = [x[1] for x in items]
    mean_speedups = [x[2] for x in items]

    fig_h = max(4, 0.7 * len(labels) + 1.5)
    fig, ax = plt.subplots(figsize=(9, fig_h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor(BG_COLOR)

    y_pos = np.arange(len(labels))
    bar_h = 0.35

    bars1 = ax.barh(y_pos + bar_h / 2, first_speedups,
                     height=bar_h, color=WARM_COLOR, alpha=0.85,
                     zorder=3, label="1st iteration speedup")
    bars2 = ax.barh(y_pos - bar_h / 2, mean_speedups,
                     height=bar_h, color=OPT_COLOR, alpha=0.75,
                     zorder=3, label="Mean per-iter speedup")

    ax.axvline(x=1.0, color="#888888", linestyle="--", linewidth=1.2,
               alpha=0.7, zorder=2)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.grid(True, axis="x", color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    ax.tick_params(axis="both", **TICK_FONT)
    ax.set_xlabel("Speedup  (cold / warm)", **LABEL_FONT)
    ax.set_title("Profile Checkpoint Speedup", **TITLE_FONT, pad=10)

    for bar, val in zip(bars1, first_speedups):
        x_pos = val + 0.02
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}×", va="center", fontsize=8, color="#333333")

    ax.legend(**LEGEND_FONT, framealpha=0.9, edgecolor="#dddddd", loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "summary_improvement.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _time_to_optimal_chart(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Bar chart comparing iterations to reach optimal for cold vs warm."""
    items = [
        (bench,
         metrics[bench].get("cold_time_to_optimal", -1),
         metrics[bench].get("warm_time_to_optimal", -1))
        for bench in benchmarks
    ]
    items = [(b, c, w) for b, c, w in items if c >= 0 and w >= 0]
    if not items:
        return

    labels = [x[0] for x in items]
    cold_tto = [x[1] for x in items]
    warm_tto = [x[2] for x in items]

    fig_h = max(4, 0.7 * len(labels) + 1.5)
    fig, ax = plt.subplots(figsize=(9, fig_h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor(BG_COLOR)

    y_pos = np.arange(len(labels))
    bar_h = 0.35

    ax.barh(y_pos + bar_h / 2, cold_tto, height=bar_h,
            color=COLD_COLOR, alpha=0.85, zorder=3, label="Cold")
    ax.barh(y_pos - bar_h / 2, warm_tto, height=bar_h,
            color=WARM_COLOR, alpha=0.85, zorder=3, label="Warm")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.grid(True, axis="x", color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    ax.tick_params(axis="both", **TICK_FONT)
    ax.set_xlabel("Iterations to Reach Optimal", **LABEL_FONT)
    ax.set_title("Time to Optimal: Cold vs Warm", **TITLE_FONT, pad=10)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.legend(**LEGEND_FONT, framealpha=0.9, edgecolor="#dddddd")

    fig.tight_layout()
    fig.savefig(out / "time_to_optimal.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hide_empty(axes, n_used: int, rows: int, cols: int) -> None:
    for idx in range(n_used, rows * cols):
        axes[idx // cols][idx % cols].set_visible(False)
