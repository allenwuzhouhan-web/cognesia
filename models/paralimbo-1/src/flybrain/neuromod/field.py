"""Dimensionless compartment fields, independent of fast synaptic currents.

Clearance is integrated exactly with exponential Euler; symmetric adjacency
provides an explicit, frozen-state diffusion term. A step can reach adjacent
volumes only. Repeated nonzero spillover reaches multiple hops (especially NO);
strict nonadjacent zero is guaranteed for the default zero-spillover DA field.
All concentrations are normalized a.u., never molar concentrations.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import numba as nb
import numpy as np
import pandas as pd
from scipy import sparse
import yaml

from ..fetch import checksum
from ..inspect_data import atomic_write_json
from .compartments import CompartmentMap, load_compartments
from .sources import parse_positive_nt, positive_nt_masks, source_masks, require_source_gate

FIELD_SPECIES = ("DA", "OA", "5HT", "NO", "sNPF", "peptide_pool", "TA", "ACh")
PEPTIDE_TOKENS = frozenset({"dilp2", "dilp3", "dilp5", "darc1", "dh44", "myosuppressin",
                          "myosupressin", "itp", "tachykinin", "snpf", "leucokinin",
                          "corazonin", "dh31", "capability", "hugin"})


@dataclass(frozen=True)
class FieldParameters:
    species: tuple[str, ...]
    dt_base_ms: float
    dt_mod_ms: float
    concentration_max_au: float
    tau_clear_ms: np.ndarray
    spillover_per_ms: np.ndarray
    max_source_rate_hz: np.ndarray
    source_gain: np.ndarray

    def __post_init__(self):
        if not self.species or len(set(self.species)) != len(self.species):
            raise ValueError("Field species must be nonempty and unique")
        for name in ("dt_base_ms", "dt_mod_ms", "concentration_max_au"):
            value = getattr(self, name)
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        ratio = self.dt_mod_ms / self.dt_base_ms
        if not np.isclose(ratio, round(ratio), rtol=0, atol=1e-9) or ratio < 1:
            raise ValueError("dt_mod_ms must be an integer multiple of dt_base_ms")
        for name in ("tau_clear_ms", "spillover_per_ms", "max_source_rate_hz", "source_gain"):
            values = np.asarray(getattr(self, name), dtype=np.float64)
            if values.shape != (len(self.species),) or not np.isfinite(values).all():
                raise ValueError(f"{name} needs one finite value per species")
            if (values < 0).any() or (name in {"tau_clear_ms", "max_source_rate_hz"} and (values == 0).any()):
                raise ValueError(f"Invalid negative or zero {name}")
            values = values.copy()
            values.flags.writeable = False
            object.__setattr__(self, name, values)
        if np.any(self.tau_clear_ms < 10 * self.dt_mod_ms):
            raise ValueError("Every tau_clear_ms must be >= 10 * dt_mod_ms")

    @classmethod
    def from_root(cls, root: Path) -> "FieldParameters":
        document = yaml.safe_load((Path(root) / "config/neuromod.yaml").read_text())
        entries = document.get("parameters", {})

        def value(name):
            row = entries[name]
            if not {"value", "unit", "source"}.issubset(row) or not row["source"] or not row["unit"]:
                raise ValueError(f"Field parameter lacks provenance: {name}")
            if row["source"] == "ASSUMPTION" and not row.get("sweep"):
                raise ValueError(f"Field assumption lacks sensitivity sweep: {name}")
            return float(row["value"])

        return cls(FIELD_SPECIES, *(value(name) for name in
                   ("dt_base_ms", "dt_mod_ms", "concentration_max_au")),
                   *(np.array([value(f"{name}_{species}") for species in FIELD_SPECIES]) for name in
                     ("tau_clear_ms", "spillover_per_ms", "max_source_rate_hz", "source_gain")))

    def for_species(self, name: str, **changes) -> "FieldParameters":
        i = self.species.index(name)
        subset = replace(self, species=(name,), tau_clear_ms=self.tau_clear_ms[[i]],
                         spillover_per_ms=self.spillover_per_ms[[i]],
                         max_source_rate_hz=self.max_source_rate_hz[[i]], source_gain=self.source_gain[[i]])
        return replace(subset, **changes)


@dataclass(frozen=True)
class SourceProjection:
    """CSR rows species×compartment; columns retain the base neuron row order."""
    species: tuple[str, ...]
    compartment_names: tuple[str, ...]
    mean_rate_matrix: sparse.csr_matrix
    source_counts: np.ndarray
    metadata: dict

    def mean_rates_hz(self, rates_hz: np.ndarray) -> np.ndarray:
        # Accumulate thousands of sources in float64 so normalization error is
        # not amplified by a large population; concentration state stays float32.
        rates = np.asarray(rates_hz, dtype=np.float64)
        if rates.shape != (self.mean_rate_matrix.shape[1],) or not np.isfinite(rates).all() or (rates < 0).any():
            raise ValueError("Source firing/release rates must be finite nonnegative Hz in model row order")
        return (self.mean_rate_matrix @ rates).reshape(self.source_counts.shape)


def build_source_projection(neurons: pd.DataFrame, compartments: CompartmentMap,
                            species: tuple[str, ...] = FIELD_SPECIES) -> SourceProjection:
    """Project per-neuron ground truth onto coarse compartment memberships.

    Source locations inherit the compartment map's explicit volume assumptions.
    Endocrine peptide_pool has positive peptide-annotated sources only and is
    restricted to hemolymph. Unidentified endocrine cells remain unassigned to
    this generic pool; they are never assigned an invented peptide identity.
    """
    if not np.array_equal(neurons.root_id.to_numpy(dtype=np.int64), compartments.model_root_ids):
        raise ValueError("Source table and compartments use different root-ID order")
    masks = source_masks(neurons)
    masks.update(positive_nt_masks(neurons, {"ACh": "acetylcholine"}))
    masks["peptide_pool"] = (neurons.super_class.eq("endocrine").to_numpy(dtype=bool)
                             & neurons.known_nt.map(parse_positive_nt).map(lambda x: bool(x & PEPTIDE_TOKENS)).to_numpy(dtype=bool))
    n, k = len(neurons), len(compartments.names)
    if compartments.membership.shape != (k, n):
        raise ValueError("Compartment membership shape mismatch")
    counts = np.zeros((len(species), k), np.int32)
    rows, columns, values = [], [], []
    unassigned = {}
    for si, name in enumerate(species):
        if name not in masks:
            raise ValueError(f"Unknown ground-truth field species: {name}")
        eligible = masks[name]
        covered = np.zeros(n, bool)
        for ci, compartment in enumerate(compartments.names):
            if name == "peptide_pool" and compartment != "hemolymph":
                continue
            indices = np.flatnonzero(eligible & compartments.membership[ci]).astype(np.int32)
            counts[si, ci] = len(indices)
            if len(indices):
                rows.extend([si * k + ci] * len(indices))
                columns.extend(indices.tolist())
                values.extend([1 / len(indices)] * len(indices))
                covered[indices] = True
        unassigned[name] = int((eligible & ~covered).sum())
    matrix = sparse.csr_matrix((np.asarray(values, np.float64), (rows, columns)),
                               shape=(len(species) * k, n), dtype=np.float64)
    matrix.sort_indices()
    return SourceProjection(species, compartments.names, matrix, counts,
                            {"units": "Hz mean over positive ground-truth sources", "identity": "per-neuron positive known_nt; KC excluded from aminergic masks",
                             "unassigned_sources": unassigned, "source_counts_model": {name: int(masks[name].sum()) for name in species},
                             "release_location": "ASSUMPTION: source membership in coarse volume; not measured release sites",
                             "peptide_pool": "ASSUMPTION: equal normalized contributions from positive peptide endocrine cells in hemolymph only"})


@nb.njit(cache=True, fastmath=False)
def _advance_field(C, adjacency_indptr, adjacency_indices, adjacency_weights,
                   decay, diffusion_scale, drive_scale, drive, Cmax, steps, clearance_disabled):
    """Frozen-state exponential Euler, serial ordered reductions and float32 C."""
    next_C = np.empty_like(C)
    clamps = 0
    for _ in range(steps):
        for species in range(C.shape[0]):
            for compartment in range(C.shape[1]):
                laplacian = 0.0
                for edge in range(adjacency_indptr[compartment], adjacency_indptr[compartment + 1]):
                    neighbor = adjacency_indices[edge]
                    laplacian += adjacency_weights[edge] * (C[species, neighbor] - C[species, compartment])
                effective_decay = 1.0 if clearance_disabled[species, compartment] else decay[species]
                updated = (effective_decay * C[species, compartment]
                           + drive_scale[species] * drive[species, compartment]
                           + diffusion_scale[species] * laplacian)
                if updated < 0:
                    updated = 0.0
                    clamps += 1
                elif updated > Cmax:
                    updated = Cmax
                    clamps += 1
                next_C[species, compartment] = updated
        C[:, :] = next_C
    return clamps


class FieldEngine:
    """No synaptic current output: only normalized concentration C in a.u.

    `advance(rates_hz)` projects source rates before stepping. `advance_drive`
    accepts a dimensionless mean-source drive for deterministic reference tests
    and source-drive protocols (1 = own population at maximal reference rate).
    Both use the same kernel, source gain, clearance and adjacency.
    """
    units = "a.u."

    def __init__(self, parameters: FieldParameters, compartment_names: tuple[str, ...],
                 adjacency: np.ndarray, projection: SourceProjection | None = None):
        self.parameters = parameters
        self.species = parameters.species
        self.compartment_names = tuple(compartment_names)
        self.projection = projection
        k = len(compartment_names)
        adjacency = np.asarray(adjacency, dtype=np.float64)
        if not k or len(set(compartment_names)) != k or adjacency.shape != (k, k):
            raise ValueError("Field requires unique compartments and square adjacency")
        if not np.isfinite(adjacency).all() or (adjacency < 0).any() or np.any(np.diag(adjacency) != 0):
            raise ValueError("Adjacency must be finite, nonnegative and have zero diagonal")
        if not np.array_equal(adjacency, adjacency.T):
            raise ValueError("Diffusive adjacency must be symmetric to conserve mass")
        if "hemolymph" in compartment_names:
            i = compartment_names.index("hemolymph")
            if np.any(adjacency[i]):
                raise ValueError("Hemolymph must be an isolated global pool")
        if projection is not None and (projection.species != self.species or projection.compartment_names != self.compartment_names):
            raise ValueError("Projection species/compartment ordering mismatch")
        self.adjacency = sparse.csr_matrix(adjacency)
        dt, tau = parameters.dt_mod_ms, parameters.tau_clear_ms
        self.decay = np.exp(-dt / tau)
        self.drive_scale = -np.expm1(-dt / tau)
        self.diffusion_scale = tau * self.drive_scale * parameters.spillover_per_ms
        degrees = adjacency.sum(axis=1)
        if np.any(self.decay[:, None] < self.diffusion_scale[:, None] * degrees[None, :]):
            raise ValueError("Exponential-Euler diffusion positivity bound fails: decay < tau*(1-decay)*sigma*degree")
        self.reset()
        self.clearance_disabled = np.zeros(self.C.shape, dtype=np.bool_)

    def reset(self):
        self.C = np.zeros((len(self.species), len(self.compartment_names)), np.float32)
        self.clamp_count = 0
        self.steps = 0

    @property
    def t_sim_ms(self):
        return self.steps * self.parameters.dt_mod_ms

    def advance(self, rates_hz: np.ndarray, steps: int = 1) -> np.ndarray:
        if self.projection is None:
            raise ValueError("Neuron rates require an explicit ground-truth source projection")
        drive = self.projection.mean_rates_hz(rates_hz) / self.parameters.max_source_rate_hz[:, None]
        return self.advance_drive(drive, steps)

    def step(self, rates_hz: np.ndarray) -> np.ndarray:
        return self.advance(rates_hz, 1)

    def advance_drive(self, normalized_source_drive: np.ndarray, steps: int = 1) -> np.ndarray:
        if not isinstance(steps, (int, np.integer)) or isinstance(steps, (bool, np.bool_)) or steps < 1:
            raise ValueError("Field steps must be a positive integer")
        drive = np.asarray(normalized_source_drive, np.float64)
        if drive.shape != self.C.shape or not np.isfinite(drive).all() or (drive < 0).any():
            raise ValueError("Normalized source drive must be finite, nonnegative and match C")
        if not np.isfinite(self.C).all() or (self.C < 0).any() or (self.C > self.parameters.concentration_max_au).any():
            raise ValueError("Existing field state is nonfinite or outside concentration bounds")
        if "peptide_pool" in self.species:
            si = self.species.index("peptide_pool")
            allowed = np.array([name == "hemolymph" for name in self.compartment_names])
            if np.any(drive[si, ~allowed] != 0):
                raise ValueError("Endocrine peptide_pool drive belongs only in hemolymph")
        scaled_drive = drive * self.parameters.source_gain[:, None]
        if not np.isfinite(scaled_drive).all():
            raise ValueError("Scaled source drive is nonfinite")
        self.clamp_count += int(_advance_field(self.C, self.adjacency.indptr, self.adjacency.indices,
                                               self.adjacency.data, self.decay, self.diffusion_scale,
                                               self.drive_scale, scaled_drive,
                                               self.parameters.concentration_max_au, steps, self.clearance_disabled))
        self.steps += steps
        return self.C


def _scalar_reference(params: FieldParameters, species: str, pulse_ms=500., end_ms=1000.) -> dict:
    chosen = params.for_species(species, spillover_per_ms=np.array([0.]))
    name = "hemolymph" if species == "peptide_pool" else "reference"
    engine = FieldEngine(chosen, (name,), np.zeros((1, 1)))
    pulse_steps = round(pulse_ms / chosen.dt_mod_ms)
    engine.advance_drive(np.ones((1, 1)), pulse_steps)
    peak = float(engine.C[0, 0])
    engine.advance_drive(np.zeros((1, 1)), round((end_ms - pulse_ms) / chosen.dt_mod_ms))
    return {"species": species, "peak_au": peak, "final_au": float(engine.C[0, 0]),
            "clamp_count": engine.clamp_count, "dt_mod_ms": chosen.dt_mod_ms,
            "pulse_ms": pulse_ms, "end_ms": end_ms}


def validate_field(root: Path) -> dict[str, Any]:
    """Persist V-NM-D using the same engine and actual compartment adjacency.

    Reference pulses are explicitly numerical fixtures, not simulated neural
    experiments. Sensitivity sweeps vary only predeclared assumptions and never
    replace defaults to make a biology or stability gate pass.
    """
    root = Path(root).resolve()
    output = root / "build"
    output.mkdir(parents=True, exist_ok=True)
    result = {"gate": "V-NM-D", "status": "FAIL", "created_at": datetime.now(timezone.utc).isoformat(),
              "checks": [], "units": "a.u.", "scope": "Headless field integrator only; not a modulated network, receptor or behaviour validation",
              "notes": ["DA zero spillover makes nonadjacent concentrations exactly zero by assumption.",
                        "One explicit frozen-neighbor step reaches adjacent volumes only; repeated nonzero NO spillover reaches multiple hops.",
                        "Every clearance, source gain, maximal source rate and adjacency spillover coefficient is ASSUMPTION."]}
    destination = output / "validation_neuromod_field.json"
    atomic_write_json(destination, result | {"failed_checks": ["validation_in_progress"]})

    def check(name, observed, expected, passed=None):
        okay = observed == expected if passed is None else bool(passed)
        result["checks"].append({"name": name, "observed": observed, "expected": expected, "status": "PASS" if okay else "FAIL"})

    try:
        # Bind inputs before reading/using them, then compare at completion.
        result["config_hashes"] = {"neuromod.yaml": checksum(root / "config/neuromod.yaml")}
        result["implementation_hashes"] = {"src/flybrain/neuromod/field.py": checksum(Path(__file__))}
        result["dependency_hashes"] = {name: checksum(root / name) for name in (
            "build/validation_neuromod_sources.json", "build/validation_neuromod_compartments.json", "build/compartments.npz")}
        source = require_source_gate(root)
        for key in ("source_hashes", "source_stats", "base_artifact_hashes", "base_config_hashes"):
            result[key] = source[key]
        params = FieldParameters.from_root(root)
        mapping = load_compartments(root)
        neurons = pd.read_parquet(output / "neurons.parquet")
        projection = build_source_projection(neurons, mapping, params.species)
        engine = FieldEngine(params, mapping.names, mapping.adjacency, projection)
        result["source_projection"] = projection.metadata
        result["source_counts_by_compartment"] = projection.source_counts.tolist()
        result["species"] = list(params.species)
        result["compartments"] = list(mapping.names)
        check("tau_at_least_10_dt", float(np.min(params.tau_clear_ms / params.dt_mod_ms)), ">= 10", passed=bool(np.all(params.tau_clear_ms >= 10 * params.dt_mod_ms)))
        check("integer_timestep_ratio", params.dt_mod_ms / params.dt_base_ms, "positive integer", passed=True)
        engine.advance(np.full(len(neurons), 50., np.float32), round(1000 / params.dt_mod_ms))
        check("default_concentration_clamps", engine.clamp_count, 0)
        check("field_float32", str(engine.C.dtype), "float32")
        result["default_full_source_drive_1000ms_peak_au"] = float(engine.C.max())
        references, sweeps = [], []
        document = yaml.safe_load((root / "config/neuromod.yaml").read_text())["parameters"]
        for si, species in enumerate(params.species):
            reference = _scalar_reference(params, species)
            references.append(reference)
            expected_peak = params.source_gain[si] * (1 - np.exp(-500 / params.tau_clear_ms[si]))
            expected_final = expected_peak * np.exp(-500 / params.tau_clear_ms[si])
            check(f"analytic_pulse_decay_{species}", max(abs(reference['peak_au']-expected_peak), abs(reference['final_au']-expected_final)), "< 1e-5 a.u.", passed=max(abs(reference['peak_au']-expected_peak), abs(reference['final_au']-expected_final)) < 1e-5)
            half = _scalar_reference(replace(params, dt_mod_ms=params.dt_mod_ms / 2), species)
            relative = abs(reference["peak_au"] - half["peak_au"]) / max(reference["peak_au"], 1e-30)
            check(f"half_dt_peak_{species}", relative, "< 0.01", passed=relative < .01)
            isolated = params.for_species(species, spillover_per_ms=np.array([0.]))
            name = "hemolymph" if species == "peptide_pool" else "reference"
            steady = FieldEngine(isolated, (name,), np.zeros((1, 1)))
            steady.advance_drive(np.ones((1, 1)), int(np.ceil(12 * isolated.tau_clear_ms[0] / isolated.dt_mod_ms)))
            error = abs(float(steady.C[0, 0]) - float(isolated.source_gain[0]))
            check(f"full_drive_normalization_{species}", float(steady.C[0, 0]), "source_gain (1 a.u. by default), error < 0.003", passed=error < .003)
            for parameter in ("tau_clear_ms", "source_gain", "spillover_per_ms", "max_source_rate_hz"):
                for value in document[f"{parameter}_{species}"]["sweep"]:
                    changed = np.array([float(value)])
                    chosen = params.for_species(species, **{parameter: changed})
                    # Two connected volumes expose spillover; an isolated global pool is used for endocrine peptides.
                    names = ("hemolymph",) if species == "peptide_pool" else ("source", "neighbor")
                    adjacent = np.zeros((len(names), len(names))) if len(names) == 1 else np.array([[0, 1], [1, 0]])
                    experiment = FieldEngine(chosen, names, adjacent)
                    drive = np.zeros_like(experiment.C)
                    drive[0, 0] = 50. / chosen.max_source_rate_hz[0]
                    experiment.advance_drive(drive, round(500 / chosen.dt_mod_ms))
                    sweeps.append({"species": species, "parameter": parameter, "value": float(value),
                                   "source_peak_au": float(experiment.C[0, 0]),
                                   "neighbor_peak_au": float(experiment.C[0, 1]) if len(names) > 1 else None,
                                   "clamp_count": experiment.clamp_count, "source": "ASSUMPTION"})
        for parameter in ("dt_base_ms", "dt_mod_ms", "concentration_max_au"):
            for value in document[parameter]["sweep"]:
                varied = replace(params, **{parameter: float(value)})
                for species in params.species:
                    chosen = varied.for_species(species, spillover_per_ms=np.array([0.]))
                    name = "hemolymph" if species == "peptide_pool" else "reference"
                    experiment = FieldEngine(chosen, (name,), np.zeros((1, 1)))
                    # The numerical guard sweep uses explicit excessive drive
                    # to expose guard effects; it is not a default experiment.
                    amplitude = 10. if parameter == "concentration_max_au" else 1.
                    experiment.advance_drive(np.full((1, 1), amplitude), round(500 / chosen.dt_mod_ms))
                    sweeps.append({"species": species, "parameter": parameter, "value": float(value),
                                   "source_peak_au": float(experiment.C[0, 0]), "neighbor_peak_au": None,
                                   "clamp_count": experiment.clamp_count, "source": "ASSUMPTION",
                                   "normalized_source_drive": amplitude,
                                   "fixture": "excess-drive numerical guard test" if amplitude > 1 else "unit-drive reference"})
        # DA test on the actual 96-volume map: source pulse cannot spread when sigma=0.
        da = params.for_species("DA")
        da_engine = FieldEngine(da, mapping.names, mapping.adjacency)
        drive = np.zeros_like(da_engine.C); drive[0, mapping.names.index("g1")] = 1
        da_engine.advance_drive(drive, round(500 / da.dt_mod_ms))
        other = np.ones(len(mapping.names), bool); other[mapping.names.index("g1")] = False
        check("default_DA_other_compartments_exact_zero", int(np.count_nonzero(da_engine.C[0, other])), 0)
        # A three-volume fixture shows one-step locality and subsequent multi-hop spread honestly.
        no = params.for_species("NO")
        line = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
        no_engine = FieldEngine(no, ("a", "b", "c"), line)
        no_engine.C[0, 0] = 1
        no_engine.advance_drive(np.zeros((1, 3)))
        check("single_step_nonadjacent_exact_zero", float(no_engine.C[0, 2]), 0.)
        expected_mass = float(np.exp(-no.dt_mod_ms / no.tau_clear_ms[0]))
        check("symmetric_diffusion_mass_after_clearance", float(no_engine.C.sum()), expected_mass,
              passed=abs(float(no_engine.C.sum())-expected_mass) < 1e-6)
        no_engine.advance_drive(np.zeros((1, 3)))
        result["NO_two_step_two_hop_concentration_au"] = float(no_engine.C[0, 2])
        result["references"] = references
        result["sensitivity_runs"] = len(sweeps)
        result["sensitivity_clamp_events"] = sum(row["clamp_count"] for row in sweeps)
        result["sensitivity_runs_with_clamps"] = sum(row["clamp_count"] > 0 for row in sweeps)
        result["sensitivity_clamp_note"] = "Excess-drive concentration-guard fixtures intentionally expose clamping; default full-source-drive clamp count is reported separately."
        atomic_write_json(output / "neuromod_field_references.json", {"units": "a.u.", "fixtures": references, "provenance": "Numerical fixtures computed by the Python FieldEngine, not measured biology"})
        pd.DataFrame(sweeps).to_csv(output / "neuromod_field_sensitivity.csv", index=False)
        # Detect concurrent upstream changes before accepting dependent evidence.
        load_compartments(root)
        for field, base in (("config_hashes", root / "config"), ("implementation_hashes", root), ("dependency_hashes", root)):
            for name, digest in result[field].items():
                check(f"unchanged_{field}_{name}", checksum(base / name), digest)
        result["artifact_hashes"] = {name: checksum(output / name) for name in ("neuromod_field_references.json", "neuromod_field_sensitivity.csv")}
    except Exception as exc:
        check("field_validation_execution", {"type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["status"] = "PASS" if result["checks"] and all(row["status"] == "PASS" for row in result["checks"]) else "FAIL"
    result["failed_checks"] = [row["name"] for row in result["checks"] if row["status"] == "FAIL"]
    atomic_write_json(destination, result)
    return result
