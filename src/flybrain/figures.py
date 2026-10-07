"""Plots made only from saved experimental results."""
from pathlib import Path
import json
import numpy as np


def reference_figure(root):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    root = Path(root)
    evidence = json.loads((root / "build/validation_engine.json").read_text())
    if evidence["status"] != "PASS":
        return None
    path = root / "build/engine_crosscheck/exponential_euler/firing_counts.npz"
    if not path.exists():
        return None
    with np.load(path) as arrays:
        factor = 1000 / evidence["protocol"]["duration_ms"]
        model = arrays["custom"].mean(axis=0) * factor
        reference = arrays["reference"].mean(axis=0) * factor
        driven = arrays["driven_neuron_indices"]
    active = (model > 0) | (reference > 0)
    followers = active.copy()
    followers[driven] = False
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.6), constrained_layout=True)
    for ax, mask, title, key in zip(axes, [active, followers], ["All firing neurons", "Excluding the 20 driven neurons"], ["mean_rate_correlation", "follower_mean_rate_correlation"]):
        ax.scatter(reference[mask], model[mask], s=22, alpha=.65, c="#167b8a", edgecolors="none")
        bound = float(max(reference[mask].max(initial=0), model[mask].max(initial=0))) * 1.06
        ax.plot([0, bound], [0, bound], color="#9ca3af", linewidth=1, linestyle="--")
        ax.set(xlabel="Brian2 reference mean rate (Hz)", ylabel="Flybrain mean rate (Hz)", title=title, xlim=(-bound*.02, bound), ylim=(-bound*.02, bound))
        r = evidence["metrics"][key]
        ax.text(.04, .96, f"r = {r:.6f}\nn = {int(mask.sum()):,}", transform=ax.transAxes, va="top")
    fig.suptitle("Whole-brain engine cross-check · 10 one-second trials", fontsize=15)
    output = root / "build/figures"
    output.mkdir(exist_ok=True)
    fig.savefig(output / "reference_comparison.png", dpi=180)
    fig.savefig(output / "reference_comparison.svg")
    plt.close(fig)
    return output / "reference_comparison.png"


def hybrid_failure_figure(root):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    from matplotlib.ticker import MaxNLocator, FuncFormatter
    root = Path(root)
    path = root / "build/validation_hybrid.json"
    if not path.exists():
        return None
    evidence = json.loads(path.read_text())
    if not evidence.get("runs") or evidence.get("stage4_status") != "FAIL":
        return None
    directory = root / evidence["runs"][0]
    if not (directory / "endpoint_state.npz").exists():
        return None
    gate = next(g for g in evidence["gates"] if g["gate"] == "V-C")
    neurons = pd.read_parquet(root / "build/neurons.parquet")
    with np.load(directory / "activity.npz") as activity:
        spike_times = activity["spike_times"]
        spike_indices = activity["spike_indices"]
    central = (neurons.super_class == "central").fillna(False).to_numpy(dtype=bool)
    with np.load(directory / "endpoint_state.npz") as state:
        derivatives = np.abs(state["final_dvdt"])
    counts = sorted([r for r in gate["equilibration"]["affected_cell_types"] if r["clamp_events"]], key=lambda r: r["clamp_events"], reverse=True)[:6]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.1), constrained_layout=True)
    bins = np.arange(0, 1020, 20)
    all_hist = np.histogram(spike_times, bins)[0]
    central_hist = np.histogram(spike_times[central[spike_indices]], bins)[0]
    axes[0].plot(bins[:-1] + 10, all_hist, color="#167b8a", label="All spiking cells")
    axes[0].plot(bins[:-1] + 10, central_hist, color="#d56c42", label="Central brain")
    axes[0].set(title="Spikes during equilibration", xlabel="Time (ms)", ylabel="Spikes per 20 ms", xlim=(0, 1000))
    axes[0].legend(frameon=False)
    positive = derivatives[np.isfinite(derivatives) & (derivatives > 0)]
    if len(positive):
        lower = max(min(float(positive.min()), float(positive.max()) / 10), 1e-300)
        hist_bins = np.geomspace(lower, float(positive.max()) * 1.01, 65)
        axes[1].hist(positive, bins=hist_bins, color="#167b8a", alpha=.8)
    else:
        axes[1].text(.05, .9, "No finite positive derivatives", transform=axes[1].transAxes)
    axes[1].axvline(.001, color="#d56c42", linestyle="--", label="Stationarity limit")
    axes[1].set(xscale="log", title="Endpoint voltage change", xlabel="|dV/dt| (mV/ms)", ylabel="Neurons")
    axes[1].legend(frameon=False)
    labels = [row["cell_type"] for row in counts][::-1]
    values = [row["clamp_events"] for row in counts][::-1]
    axes[2].barh(labels, values, color="#d56c42")
    axes[2].set(title="Largest clamp counts by cell type", xlabel="Clamp events")
    axes[2].xaxis.set_major_locator(MaxNLocator(4))
    axes[2].xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:g}k" if value else "0"))
    fig.suptitle("Hybrid equilibration failed · 1,000 ms · zero external input", fontsize=14)
    output = root / "build/figures"
    output.mkdir(exist_ok=True)
    fig.savefig(output / "hybrid_equilibration.png", dpi=180)
    fig.savefig(output / "hybrid_equilibration.svg")
    plt.close(fig)
    return output / "hybrid_equilibration.png"
