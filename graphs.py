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
OPT_COLOR   = "#5b8dd9"   # blue — cold-optimal reference line
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


def _add_speedup_badge(ax: plt.Axes, speedup: float) -> None:
    """Small annotation showing mean speedup ratio."""
    sign = "+" if speedup >= 1 else ""
    label = f"Mean speedup: {speedup:.2f}×"
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
    _cold_vs_warm_plot(metrics, benchmarks, graphs_dir)
    _summary_bar_chart(metrics, benchmarks, graphs_dir)
    _closeness_ratio_plot(metrics, benchmarks, graphs_dir)

    print(f"Graphs saved to {graphs_dir}")


# ---------------------------------------------------------------------------
# Individual plots
# ---------------------------------------------------------------------------

def _convergence_plot(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Per-benchmark convergence: cold curve vs warm curve."""
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
            cold_mean = np.mean(cold)
            warm_mean = np.mean(warm)
            if warm_mean > 0:
                _add_speedup_badge(ax, cold_mean / warm_mean)

        _style_ax(ax, bench)
        ax.legend(**LEGEND_FONT, framealpha=0.9, edgecolor="#dddddd")

    _hide_empty(axes, len(benchmarks), rows, cols)
    fig.suptitle("Convergence: Cold vs Warm", **SUPTITLE_FONT)
    fig.tight_layout()
    fig.savefig(out / "convergence.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _cold_vs_warm_plot(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Cold curve + warm[2] target line + cold optimal line."""
    cols = 2
    fig, axes, rows = _make_figure(len(benchmarks), cols)

    for idx, bench in enumerate(benchmarks):
        ax = axes[idx // cols][idx % cols]
        m = metrics[bench]
        cold = m["cold_curve"]
        xs = range(1, len(cold) + 1)

        ax.plot(xs, cold, label="Cold", **LINE_KW_COLD)

        if m["warm_target"] > 0:
            ax.axhline(
                y=m["warm_target"], color=WARM_COLOR, linestyle="--",
                linewidth=1.5, alpha=0.9,
                label=f"Warm target = {m['warm_target']:.0f} ms",
            )
        if m["cold_optimal"] > 0:
            ax.axhline(
                y=m["cold_optimal"], color=OPT_COLOR, linestyle=":",
                linewidth=1.5, alpha=0.9,
                label=f"Cold optimal = {m['cold_optimal']:.0f} ms",
            )

        _style_ax(ax, bench)
        ax.legend(**LEGEND_FONT, framealpha=0.9, edgecolor="#dddddd")

    _hide_empty(axes, len(benchmarks), rows, cols)
    fig.suptitle("Cold Curve vs Warm Target & Cold Optimal", **SUPTITLE_FONT)
    fig.tight_layout()
    fig.savefig(out / "cold_vs_warm.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _summary_bar_chart(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """Horizontal bar chart: cold[0]/warm[2] improvement ratio per benchmark."""
    items = [
        (bench, metrics[bench]["our_improvement"])
        for bench in benchmarks
        if metrics[bench]["our_improvement"] > 0
    ]
    if not items:
        return

    items.sort(key=lambda x: x[1])
    labels, ratios = zip(*items)

    fig_h = max(4, 0.55 * len(labels) + 1.5)
    fig, ax = plt.subplots(figsize=(9, fig_h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor(BG_COLOR)

    colors = [WARM_COLOR if r >= 1.0 else COLD_COLOR for r in ratios]
    bars = ax.barh(labels, ratios, color=colors, alpha=0.85, height=0.6, zorder=3)

    ax.axvline(x=1.0, color="#888888", linestyle="--", linewidth=1.2,
               alpha=0.7, label="No improvement (1.0×)", zorder=2)
    ax.grid(True, axis="x", color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    ax.tick_params(axis="both", **TICK_FONT)
    ax.set_xlabel("Improvement Ratio  (cold[0] / warm[2])", **LABEL_FONT)
    ax.set_title("First-Iteration Improvement: Cold vs Profile-Loaded",
                 **TITLE_FONT, pad=10)

    for bar, ratio in zip(bars, ratios):
        x_pos = ratio + 0.03
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                f"{ratio:.2f}×", va="center", fontsize=8.5, color="#333333")

    ax.legend(**LEGEND_FONT, framealpha=0.9, edgecolor="#dddddd")
    fig.tight_layout()
    fig.savefig(out / "summary_improvement.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _closeness_ratio_plot(metrics: dict, benchmarks: list[str], out: Path) -> None:
    """cold[N] / warm[2] per iteration — convergence toward warm target."""
    # Pick a palette that's distinguishable for up to ~12 series
    palette = plt.cm.tab10.colors  # type: ignore[attr-defined]

    fig, ax = plt.subplots(figsize=(11, 6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor(BG_COLOR)

    for i, bench in enumerate(benchmarks):
        cr = metrics[bench].get("closeness_ratio", [])
        if cr:
            color = palette[i % len(palette)]
            ax.plot(range(1, len(cr) + 1), cr,
                    label=bench, color=color,
                    linewidth=1.5, alpha=0.85, zorder=3)

    ax.axhline(y=1.0, color="#555555", linestyle="--", linewidth=1.4,
               alpha=0.7, label="Parity (cold = warm target)", zorder=4)

    ax.grid(True, color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#cccccc")
    ax.tick_params(axis="both", **TICK_FONT)
    ax.set_xlabel("Cold Iteration", **LABEL_FONT)
    ax.set_ylabel("Ratio  (cold[N] / warm target)", **LABEL_FONT)
    ax.set_title("Cold Convergence Toward Warm Target", **TITLE_FONT, pad=8)
    ax.legend(**LEGEND_FONT, framealpha=0.9, edgecolor="#dddddd",
              loc="upper right", ncol=max(1, len(benchmarks) // 6))

    fig.tight_layout()
    fig.savefig(out / "closeness_ratio.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hide_empty(axes, n_used: int, rows: int, cols: int) -> None:
    for idx in range(n_used, rows * cols):
        axes[idx // cols][idx % cols].set_visible(False)
