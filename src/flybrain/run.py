"""Explicit reference experiments; biological eye experiments require their gates."""
from pathlib import Path
import time
import numpy as np

from .build import load_network
from .config import parameters
from .memguard import MemoryGuard
from .record import run_directory, save_run


def run_reference(root, *, duration_ms=1000.0, seed=None, threads=16, integrator="exponential_euler", mem_limit_gb=40):
    from .engine import LIFEngine
    root = Path(root)
    p = parameters(root)
    seed = p["seed"] if seed is None else seed
    if duration_ms <= 0:
        raise ValueError("Duration must be positive")
    network = load_network(root)
    rng = np.random.default_rng(seed)
    inputs = rng.choice(len(network["neurons"]), 20, replace=False).astype(np.int32)
    step_count = round(duration_ms / p["dt"])
    if abs(step_count * p["dt"] - duration_ms) > 1e-8:
        raise ValueError("Duration must be an integer multiple of dt; no silent rounding")
    events = np.argwhere(rng.random((step_count, len(inputs))) < p["poisson_rate"] * p["dt"] / 1000).astype(np.int32)
    directory = run_directory(root, "reference_poisson")
    np.savez_compressed(directory / "input.npz", neurons=inputs, events=events)
    with MemoryGuard(mem_limit_gb) as guard:
        engine = LIFEngine(network["reference"], p, integrator=integrator, threads=threads, clamp=True)
        try:
            result = engine.run(duration_ms, input_neurons=inputs, input_events=events, record_indices=inputs)
        except Exception:
            partial = getattr(engine, "partial_result", None)
            if partial:
                save_run(root, directory, partial, config={"parameters": p, "mode": "all_lif", "integrator": integrator, "duration_ms": duration_ms}, seed=seed, experiment="reference_poisson", peak_rss=guard.peak_rss, complete=False)
            raise
        result["record_indices"] = inputs
        guard.check()
        manifest = save_run(root, directory, result, config={"parameters": p, "mode": "all_lif", "integrator": integrator, "duration_ms": duration_ms, "signs": "unmodified release", "threads": threads}, seed=seed, experiment="reference_poisson", peak_rss=guard.peak_rss)
    return {"run_directory": str(directory), "spike_count": manifest["spike_count"], "clamp_count": manifest["clamp_count"], "wall_seconds": manifest["wall_seconds"], "peak_rss_bytes": manifest["peak_rss_bytes"], "note": "Explicit reference-comparison experiment; Poisson drive is not compound-eye input."}
