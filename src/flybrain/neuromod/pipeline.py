"""Build source-bound headless artifacts in dependency order."""
from pathlib import Path

from .sources import build_sources
from .compartments import build_compartments
from .field import validate_field
from .odour import build_odours
from .core import validate_core_stationarity
from .receptors import validate_receptors
from .plasticity import validate_plasticity


def build_neuromod(root: Path) -> dict:
    """Stop on software/primary-data failures, never suppress a gate failure."""
    root = Path(root)
    gates = []
    for stage in (build_sources, build_compartments, validate_field, build_odours,
                  validate_core_stationarity, validate_receptors, validate_plasticity):
        gate = stage(root)
        gates.append(gate)
        if gate["status"] != "PASS":
            return {"status": "FAIL", "gates": gates,
                    "stop_reason": f"{gate['gate']} failed; dependent stages were not run."}
    return {"status": "PASS", "gates": gates,
            "scope": "Source, compartment, field, odour, core-rest, receptor and normalized-plasticity software gates. Biology, replay and speed are measured separately."}
