"""Real release downloads, atomic writes, checksums and schema inspection."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import urllib.request

from .inspect_data import inspect_table, atomic_write_json, stat_signature
from .memguard import check_memory

BASE = "https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/main/"
SOURCES = {
    "Completeness_783.csv": BASE + "Completeness_783.csv",
    "Connectivity_783.parquet": BASE + "Connectivity_783.parquet",
    "Supplemental_file1_neuron_annotations.tsv": "https://raw.githubusercontent.com/flyconnectome/flywire_annotations/main/supplemental_files/Supplemental_file1_neuron_annotations.tsv",
    "model.py": BASE + "model.py",
    "zenodo_record_10676866.json": "https://zenodo.org/api/records/10676866",
}
NEUROPIL_FILES = [f"per_neuron_neuropil_count_{part}_783.feather" for part in ("post", "pre")]


def checksum(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            check_memory()
            digest.update(chunk)
    return digest.hexdigest()


def download(url, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "flybrain/0.1 release-research"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response, partial.open("wb") as f:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                check_memory()
                f.write(chunk)
        os.replace(partial, target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def fetch(root: Path, *, neuropils=True, synapses=False):
    root = Path(root)
    raw, build = root / "data/raw", root / "build"
    raw.mkdir(parents=True, exist_ok=True)
    build.mkdir(parents=True, exist_ok=True)
    manifest_path = build / "downloads.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    records = dict(previous.get("files", {}))
    inspection_path = build / "schema_inspection.json"
    inspections = json.loads(inspection_path.read_text()) if inspection_path.exists() else {}
    if isinstance(inspections, list):
        inspections = {entry["file"]: entry for entry in inspections}
    failures_path = build / "integrity_failures.json"
    failures = json.loads(failures_path.read_text()) if failures_path.exists() else {}

    def process(name, url, entry=None):
        path = raw / name
        digest = None
        try:
            if not path.exists():
                print(f"Downloading {name}", flush=True)
                download(url, path)
            signature = stat_signature(path)
            digest = checksum(path)
            if name in records and records[name]["sha256"] != digest:
                raise ValueError(f"Cached release changed: {name}; preserving original manifest for investigation")
            if entry is not None:
                if signature["size"] != entry["size"]:
                    raise ValueError(f"Wrong byte count for {name}")
                algorithm, expected = entry["checksum"].split(":", 1)
                if checksum(path, algorithm) != expected:
                    raise ValueError(f"Publisher checksum failed for {name}")
            if path.suffix in (".csv", ".tsv", ".parquet", ".feather"):
                inspections[name] = inspect_table(path)
                atomic_write_json(inspection_path, inspections)
            if signature != stat_signature(path):
                raise ValueError(f"Release changed during verification: {name}")
            records[name] = {"url": url, "sha256": digest, "bytes": signature["size"],
                             "stat": signature,
                             "verified_at": datetime.now(timezone.utc).isoformat(),
                             "publisher_checksum": entry["checksum"] if entry is not None else None}
            atomic_write_json(manifest_path, {"files": records})
            if name in failures:
                del failures[name]
                atomic_write_json(failures_path, failures)
        except Exception as error:
            failures[name] = {"error": str(error), "observed_sha256": digest,
                              "expected_sha256": previous.get("files", {}).get(name, {}).get("sha256"),
                              "time": datetime.now(timezone.utc).isoformat()}
            atomic_write_json(failures_path, failures)
            raise

    # Save each completed file before requesting the next, so failures preserve
    # the schema and checksum evidence already collected in this attempt.
    for name, url in SOURCES.items():
        process(name, url)
    zenodo = json.loads((raw / "zenodo_record_10676866.json").read_text())
    entries = {f["key"]: f for f in zenodo["files"]}
    wanted = (NEUROPIL_FILES if neuropils else []) + (["flywire_synapses_783.feather"] if synapses else [])
    for name in wanted:
        entry = entries[name]
        process(name, entry["links"]["self"], entry)
    return records
