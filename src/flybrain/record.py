"""Sparse run output and reproducibility manifests."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import uuid

import numpy as np

from .fetch import checksum
from .inspect_data import atomic_write_json


def run_directory(root, name):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(root) / "runs" / f"{stamp}_{name}_{uuid.uuid4().hex[:6]}"
    path.mkdir(parents=True)
    return path


def save_run(root, directory, result, *, config, seed, experiment, peak_rss=None, complete=True):
    root, directory = Path(root), Path(directory)
    arrays = {}
    for key in ("spike_indices", "spike_times", "voltages", "voltage_times", "record_indices"):
        if key in result:
            arrays[key] = np.asarray(result[key])
    np.savez_compressed(directory / "activity.npz", **arrays)
    checkpoint = {key: np.asarray(value) for key, value in result.items() if key.startswith("checkpoint_")}
    if checkpoint:
        np.savez_compressed(directory / "checkpoint.npz", **checkpoint)
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"))
    try:
        git_hash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        git_hash, dirty = None, None
    versions = {name: importlib.metadata.version(name) for name in ("flybrain", "numpy", "scipy", "numba", "pyarrow", "brian2")}
    manifest = {"experiment": experiment, "complete": complete, "seed": int(seed),
                "config": config, "config_hash": hashlib.sha256(config_json.encode()).hexdigest(),
                "git_hash": git_hash, "git_dirty": dirty, "versions": versions,
                "platform": platform.platform(), "wall_seconds": result.get("wall_seconds"),
                "peak_rss_bytes": peak_rss, "clamp_count": int(result.get("clamp_count", 0)),
                "spike_count": len(arrays.get("spike_indices", [])),
                "output_sha256": checksum(directory / "activity.npz"),
                "source_manifest": json.loads((root / "build/downloads.json").read_text()) if (root / "build/downloads.json").exists() else None}
    atomic_write_json(directory / "run_manifest.json", manifest)
    return manifest
