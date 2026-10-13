"""Publication wrapper; the scientific flybrain modules retain their frozen bytes."""
from importlib.resources import files
import json
from pathlib import Path

PUBLIC_NAME = "ParaLimbo 1"
__version__ = "1.0.0"
MODEL_ID = "paralimbo-visual-graded-v1"
MODEL_HASH = "229f9970e0b67cfa14658142dbc3adae8614d49887cd131521bf02e4d86cd884"


def archived_manifest():
    return json.loads(files(__package__).joinpath("model-manifest.json").read_text())


def parameters():
    """Return frozen parameters with the candidate's explicit 0.8 input cap."""
    from flybrain.config import parameters as read_parameters
    return read_parameters(Path(str(files(__package__)))) | {"graded_input_cap": 0.8}


def check_graph_inputs(root):
    """Check metadata and every archived output before allocating the engine."""
    from flybrain.fetch import checksum
    from flybrain.model_registry import get_model_manifest
    root = Path(root)
    expected = archived_manifest()
    folder = root / "build/model-versions" / MODEL_HASH
    required = ["manifest.json", *expected["output_hashes"]]
    missing = [name for name in required if not (folder / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "The source release excludes compiled connectome and optical tables. "
            f"Supply separately authorized archived inputs under {folder}; "
            "missing: " + ", ".join(missing) + ". See README.md: Required graph inputs."
        )
    actual = get_model_manifest(root, MODEL_ID, MODEL_HASH)
    if actual != expected:
        raise ValueError("Provided graph manifest differs from the archived ParaLimbo 1 binding")
    for name, digest in expected["output_hashes"].items():
        if checksum(folder / name) != digest:
            raise ValueError("Archived graph input checksum mismatch: " + name)
    return {"status": "PASS", "model_id": MODEL_ID, "model_hash": MODEL_HASH,
            "checked_outputs": len(expected["output_hashes"])}


def make_engine(root, *, threads=1):
    """Load a separately supplied, pin-verified archived graph and its dynamics."""
    from flybrain.hybrid_engine import HybridEngine
    from flybrain.model_registry import load_model_network
    check_graph_inputs(root)
    network = load_model_network(root, MODEL_ID, MODEL_HASH)
    engine = HybridEngine(network["graded"], network["spiking"],
                          network["neurons"].is_graded.to_numpy(bool),
                          parameters(), threads=threads)
    return engine, network


def check_rebuild_inputs(root):
    """Require original base and reference map, without downloading substitutes."""
    from flybrain.fetch import checksum
    from flybrain.model_registry import get_model_manifest
    from flybrain.neural_baseline import BASE_MODEL, BASE_HASH, HISTORICAL_RUN
    root = Path(root)
    base = get_model_manifest(root, BASE_MODEL, BASE_HASH)
    if base["model_hash"] != BASE_HASH:
        raise ValueError("Original base manifest identity differs from the required pinned hash")
    folder = root / "build/model-versions" / BASE_HASH
    for name, digest in base["output_hashes"].items():
        if not (folder / name).is_file() or checksum(folder / name) != digest:
            raise ValueError("Missing or changed original base artifact: " + name)
    # Avoid the compiler's alternate historical-run input path: its presence
    # must be resolved by a researcher before using this portable entry point.
    if (root / "runs" / HISTORICAL_RUN / "run_manifest.json").exists():
        raise ValueError("Use a clean data root containing the pinned base and config/reference-visual-map only")
    mapping = root / "config/reference-visual-map"
    if not (mapping / "manifest.json").is_file():
        raise FileNotFoundError("Exact rebuild needs separately authorized config/reference-visual-map/manifest.json, columns.parquet and assignments.parquet; these tables are not distributed")
    ref = json.loads((mapping / "manifest.json").read_text())
    saved = archived_manifest()["eye_snapshot"]
    expected = {"columns.parquet": saved["columns_sha256"],
                "assignments.parquet": saved["assignments_sha256"]}
    if (ref.get("historical_run") != HISTORICAL_RUN or ref.get("original_model_hash") != BASE_HASH
            or ref.get("sha256") != expected or ref.get("audit") != saved["audit"]):
        raise ValueError("Reference map metadata differs from the archived model")
    for name, digest in expected.items():
        if not (mapping / name).is_file() or checksum(mapping / name) != digest:
            raise ValueError("Missing or changed original optical table: " + name)
    return {"status": "PASS", "base_model_hash": BASE_HASH, "reference_map_verified": True}
