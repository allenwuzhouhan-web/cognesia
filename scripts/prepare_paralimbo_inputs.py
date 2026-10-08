#!/usr/bin/env python3
"""Prepare the exact public inputs required by ParaLimbo 0.1.

Run from a release checkout after installing Python 3.12 and
``python -m pip install -r requirements.lock``::

    python scripts/prepare_paralimbo_inputs.py --root .
    flybrain --root . models compile-paralimbo

The installed dependencies and neuron-mode configuration must match their
pins. Four source files are downloaded only when absent, verified before
publication, and never replaced on mismatch. No full FlyWire connectivity
file is needed. Existing BANC artifacts and source configuration are preserved.
The saved build/paralimbo-input-sources.json contains relative paths only.
"""
from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from flybrain.build import _prepare_modes
from flybrain.fetch import checksum
from flybrain.inspect_data import atomic_write_json
from flybrain.model_registry import (BANC_BUCKET, BANC_FILES, BANC_ID, _freeze_model,
                                     assemble_banc, get_model_manifest)
from flybrain.paralimbo import (BANC_BASELINE_HASH, FLYWIRE_MODE_CONFIG_SHA256,
                                FLYWIRE_NEURONS_SHA256, FLYWIRE_SOURCE_ARTIFACTS)

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
BANC_RAW_SHA256 = {
    "metadata.feather": "86ccf5df0c67419f8c5f43e93a7ed38d23a080e9f7fde26737290252f3780098",
    "edgelist.feather": "8c296e946f3c69a8c7222f30ad75fa8a98eeb189124fec6df829c9125f4be64b",
}


def _verify(path, expected_sha256, expected_bytes=None):
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        raise ValueError(f"Refusing mismatched byte count: {path.name}")
    if checksum(path) != expected_sha256:
        raise ValueError(f"Refusing mismatched SHA256: {path.name}")


def _publish_file(staged, target, expected_sha256, expected_bytes=None):
    """Atomically create a verified file; concurrent existing bytes never change."""
    _verify(staged, expected_sha256, expected_bytes)
    try:
        # The temporary and final names live on one filesystem. link() creates
        # the final name atomically and refuses to replace an existing name.
        os.link(staged, target)
    except FileExistsError:
        _verify(target, expected_sha256, expected_bytes)
        return False
    return True


def acquire_source(root, relative_path, specification):
    target = root/relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        _verify(target, specification["sha256"], specification["bytes"])
        downloaded = False
    else:
        with tempfile.NamedTemporaryFile(prefix=".paralimbo-download-", dir=target.parent) as temporary:
            request = Request(specification["url"], headers={"User-Agent": "Cognesia-ParaLimbo/0.1 reproducible-inputs"})
            received = 0
            with urlopen(request, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > specification["bytes"]:
                        raise ValueError(f"Source exceeded pinned byte count: {target.name}")
                    temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
            downloaded = _publish_file(Path(temporary.name), target, specification["sha256"], specification["bytes"])
    return {"path": Path(relative_path).as_posix(), **specification, "downloaded": downloaded}


def verify_dependencies(root):
    lock = root/"requirements.lock"
    if not lock.is_file():
        raise ValueError("requirements.lock is required; use a complete release checkout")
    dependencies = re.findall(r"^([A-Za-z0-9_.-]+)==([^\s]+)$", lock.read_text(), flags=re.M)
    if not dependencies:
        raise ValueError("requirements.lock has no exact dependency pins")
    mismatches = []
    for name, expected in dependencies:
        try:
            observed = version(name)
        except PackageNotFoundError:
            observed = "not installed"
        if observed != expected:
            mismatches.append(f"{name}: expected {expected}, observed {observed}")
    if mismatches:
        raise ValueError("Install requirements.lock before preparing inputs; " + "; ".join(mismatches))
    return {"path": "requirements.lock", "sha256": checksum(lock), "checked_packages": len(dependencies)}


def prepare_donor(root):
    """Reproduce the pinned table without downloading FlyWire's edge matrix."""
    target = root/"build/neurons.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        _verify(target, FLYWIRE_NEURONS_SHA256)
        return {"path": "build/neurons.parquet", "sha256": FLYWIRE_NEURONS_SHA256, "reused": True}
    config = root/"config/neuron_modes.csv"
    _verify(config, FLYWIRE_MODE_CONFIG_SHA256)
    with tempfile.TemporaryDirectory(prefix=".paralimbo-donor-", dir=target.parent) as temporary:
        temporary = Path(temporary)
        copied_config = temporary/"neuron_modes.csv"
        shutil.copyfile(config, copied_config)
        raw = root/"data/raw"
        completeness = pd.read_csv(raw/"Completeness_783.csv").rename(columns={"Unnamed: 0": "root_id"})
        annotations = pd.read_csv(raw/"Supplemental_file1_neuron_annotations.tsv", sep="\t", low_memory=False)
        neurons = completeness.merge(annotations, on="root_id", how="left", sort=False, validate="one_to_one")
        neurons.insert(0, "index", np.arange(len(neurons), dtype=np.int32))
        graded = _prepare_modes(neurons, copied_config, "hybrid")
        neurons["is_graded"] = graded
        neurons["mode"] = np.where(graded, "graded", "spiking")
        staged = temporary/"neurons.parquet"
        neurons.to_parquet(staged, index=False)
        _publish_file(staged, target, FLYWIRE_NEURONS_SHA256)
    _verify(config, FLYWIRE_MODE_CONFIG_SHA256)
    return {"path": "build/neurons.parquet", "sha256": FLYWIRE_NEURONS_SHA256, "reused": False}


def _verified_banc_version(root):
    manifest = get_model_manifest(root, BANC_ID, BANC_BASELINE_HASH)
    folder = root/"build/model-versions"/BANC_BASELINE_HASH
    for name, digest in manifest["output_hashes"].items():
        _verify(folder/name, digest)
    return manifest, folder


def prepare_banc(root):
    """Install a verified immutable version without overwriting any old model."""
    frozen = root/"build/model-versions"/BANC_BASELINE_HASH
    if frozen.exists():
        _verified_banc_version(root)
        return {"path": f"build/model-versions/{BANC_BASELINE_HASH}", "model_hash": BANC_BASELINE_HASH, "reused": True}
    build = root/"build"
    build.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".paralimbo-banc-", dir=build) as temporary:
        temporary = Path(temporary)
        raw = temporary/"data/raw/models"/BANC_ID
        raw.mkdir(parents=True)
        for name in BANC_FILES:
            # Acquisition/assembly reads source bytes and writes only its own
            # sources.json into this isolated directory.
            (raw/name).symlink_to((root/"data/raw/models"/BANC_ID/name).resolve())
        manifest = assemble_banc(temporary)
        if manifest["model_hash"] != BANC_BASELINE_HASH:
            raise ValueError("BANC rebuild did not reproduce the pinned baseline; existing models preserved")
        candidate = temporary/"build/model-versions"/BANC_BASELINE_HASH
        _freeze_model(root, candidate, manifest)
        # A convenience alias is useful to the catalogue, but never replace an
        # existing alias, even if it names another valid BANC build.
        alias = root/"build/models"/BANC_ID
        if not alias.exists():
            alias.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".paralimbo-alias-", dir=alias.parent) as alias_stage:
                staged = Path(alias_stage)/BANC_ID
                shutil.copytree(candidate, staged)
                try:
                    os.rename(staged, alias)
                except FileExistsError:
                    pass
    _verified_banc_version(root)
    return {"path": f"build/model-versions/{BANC_BASELINE_HASH}", "model_hash": BANC_BASELINE_HASH, "reused": False}


def prepare_inputs(root, progress=print):
    root = Path(root).resolve()
    dependencies = verify_dependencies(root)
    mode_config = root/"config/neuron_modes.csv"
    _verify(mode_config, FLYWIRE_MODE_CONFIG_SHA256)
    # Reject an incompatible pre-existing donor before any network work.
    if (root/"build/neurons.parquet").exists():
        _verify(root/"build/neurons.parquet", FLYWIRE_NEURONS_SHA256)
    sources = []
    for name, specification in FLYWIRE_SOURCE_ARTIFACTS.items():
        progress(f"Verify pinned FlyWire source: {name}")
        sources.append(acquire_source(root, Path("data/raw")/name, specification))
    for name, (remote, generation, size) in BANC_FILES.items():
        progress(f"Verify pinned BANC source: {name}")
        specification = {"url": BANC_BUCKET + remote + "?generation=" + generation,
                         "bytes": size, "sha256": BANC_RAW_SHA256[name], "generation": generation}
        sources.append(acquire_source(root, Path("data/raw/models")/BANC_ID/name, specification))
    progress("Reproduce exact FlyWire donor annotations")
    donor = prepare_donor(root)
    progress("Reproduce or verify exact BANC baseline")
    banc = prepare_banc(root)
    result = {"schema_version": 1, "status": "PASS", "model": "ParaLimbo 0.1",
              "sources": sources, "dependencies": dependencies,
              "mode_config": {"path": "config/neuron_modes.csv", "sha256": FLYWIRE_MODE_CONFIG_SHA256},
              "flywire_donor": donor, "banc_baseline": banc,
              "scope": "Pinned source acquisition and byte-identical input reconstruction; no biological validation"}
    atomic_write_json(root/"build/paralimbo-input-sources.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="release checkout directory (default: repository containing this script)")
    args = parser.parse_args(argv)
    try:
        result = prepare_inputs(args.root)
    except (ValueError, FileNotFoundError, OSError) as exc:
        parser.exit(1, f"Input preparation failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
