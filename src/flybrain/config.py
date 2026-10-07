"""Read parameter values without losing their provenance."""
from pathlib import Path
import yaml


def parameters(root: Path) -> dict:
    document = yaml.safe_load((Path(root) / "config/parameters.yaml").read_text())
    for name, entry in document["parameters"].items():
        if not {"value", "unit", "source"} <= entry.keys():
            raise ValueError(f"Missing provenance for {name}")
        if entry["source"] == "ASSUMPTION" and not entry.get("sweep"):
            raise ValueError(f"Missing sensitivity values for assumption {name}")
    return {name: entry["value"] for name, entry in document["parameters"].items()}
