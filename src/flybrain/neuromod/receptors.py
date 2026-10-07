"""Receptor table -> named parameter arrays, never additive membrane current.

Expression coverage and all numerical effect sizes are explicit assumptions.
Opposite dopamine branches are returned as separate history-dependent channels;
this layer never applies them as instantaneous release or weight changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.special import expit
import yaml

from ..fetch import checksum
from ..inspect_data import atomic_write_json
from .compartments import CompartmentMap, load_compartments
from .field import FIELD_SPECIES
from .sources import parse_positive_nt


EFFECTS = {"gain", "v_th", "tau_m", "release_prob", "plasticity_rate", "plasticity_sign"}
HISTORIES = {"instant", "kc_before_da", "da_before_kc"}
BOUND_DEFAULTS = {"gain_min": 0., "gain_max": 3., "threshold_factor_min": .25,
                  "threshold_factor_max": 3., "tau_factor_min": .1, "tau_factor_max": 5.,
                  "release_min": 0., "release_max": 2., "signal_abs_max": 5.}


def parse_kernel(value: str) -> tuple[str, tuple[float, ...]]:
    if value in {"linear", "biphasic"}:
        return value, ()
    match = re.fullmatch(r"hill\(\s*([0-9.eE+\-]+)\s*,\s*([0-9.eE+\-]+)\s*\)", value)
    if not match:
        raise ValueError(f"Unknown receptor kernel: {value}")
    n, k = map(float, match.groups())
    if not np.isfinite([n, k]).all() or n <= 0 or k <= 0 or n * np.log(k) > 700:
        raise ValueError("Hill n and K must be positive finite values with finite normalization")
    return "hill", (n, k)


def kernel_response(concentration, kernel: str) -> np.ndarray:
    """All shapes give 0 at C=0 and 1 at C=1; shape parameters are assumptions."""
    c = np.asarray(concentration, np.float64)
    if not np.isfinite(c).all() or np.any(c < 0):
        raise ValueError("Receptor concentration must be finite and nonnegative")
    name, parameters = parse_kernel(kernel)
    if name == "linear":
        return c.copy()
    if name == "biphasic":
        # Explicit assumed concentration response, not the temporal Dop1R rule.
        with np.errstate(over="ignore"):
            return c * (2. - c)
    n, k = parameters
    result = np.zeros_like(c)
    positive = c > 0
    result[positive] = (1 + np.exp(n * np.log(k))) * expit(n * (np.log(c[positive]) - np.log(k)))
    return result


def read_receptors(path: Path) -> list[dict]:
    table = pd.read_csv(path, keep_default_na=False, dtype=str)
    required = {"id", "modulator", "receptor", "target", "target_class", "target_nt", "effect",
                "edge_scope", "magnitude", "kernel", "history", "enabled", "provenance", "url",
                "sign_provenance", "expression_provenance", "magnitude_provenance", "magnitude_sweep", "notes"}
    if not required.issubset(table.columns) or table.id.duplicated().any() or not len(table):
        raise ValueError("Receptor table needs unique IDs and complete schema/provenance columns")
    rows = []
    for row in table.to_dict("records"):
        if not all(row[k] for k in ("id", "receptor", "target", "provenance", "url", "notes")):
            raise ValueError("Receptor rows require nonempty identity, target and evidence notes")
        try:
            re.compile(row["target"])
        except re.error as exc:
            raise ValueError(f"Invalid receptor target regex: {row['id']}") from exc
        if row["modulator"] not in FIELD_SPECIES or row["effect"] not in EFFECTS:
            raise ValueError("Unknown receptor modulator or effect")
        if row["enabled"] not in {"true", "false"} or row["history"] not in HISTORIES:
            raise ValueError("Invalid receptor enabled/history value")
        if row["edge_scope"] not in {"none", "all_out", "KC->MBON"}:
            raise ValueError("Unknown receptor edge scope")
        if row["effect"] in {"gain", "v_th", "tau_m"} and row["edge_scope"] != "none":
            raise ValueError("Neuron parameters must use edge_scope=none")
        if row["effect"] == "release_prob" and row["edge_scope"] == "none":
            raise ValueError("Release effects need an explicit edge scope")
        plastic = row["effect"].startswith("plasticity_")
        if plastic and (row["edge_scope"] != "KC->MBON" or row["history"] == "instant"):
            raise ValueError("Plasticity requires a KC->MBON scope and an explicit history branch")
        if not plastic and row["history"] != "instant":
            raise ValueError("History-dependent branches cannot become instantaneous membrane/release effects")
        if row["expression_provenance"] != "ASSUMPTION" or row["magnitude_provenance"] != "ASSUMPTION":
            raise ValueError("This seed table has no expression atlas or measured numerical strength; these must be ASSUMPTION")
        if row["sign_provenance"] not in {"PUBLISHED", "INFERRED_SIGN", "ASSUMPTION"}:
            raise ValueError("Unknown sign provenance")
        parse_kernel(row["kernel"])
        row["magnitude"] = float(row["magnitude"])
        row["magnitude_sweep"] = [float(x) for x in row["magnitude_sweep"].split(";")]
        if not np.isfinite([row["magnitude"], *row["magnitude_sweep"]]).all() or not row["magnitude_sweep"]:
            raise ValueError("Receptor magnitude and sweep must be finite")
        if row["magnitude"] not in row["magnitude_sweep"]:
            raise ValueError("Magnitude sweep must include the declared default")
        row["enabled"] = row["enabled"] == "true"
        rows.append(row)
    return rows


def receptor_bounds(root: Path | None = None) -> dict[str, float]:
    if root is None:
        return dict(BOUND_DEFAULTS)  # Explicit numerical-fixture defaults.
    parameters = yaml.safe_load((Path(root) / "config/neuromod.yaml").read_text())["parameters"]
    result = {}
    for name in BOUND_DEFAULTS:
        row = parameters["receptor_" + name]
        if row.get("source") != "ASSUMPTION" or not row.get("unit") or not row.get("sweep"):
            raise ValueError(f"Receptor guard must carry assumption and sweep: {name}")
        result[name] = float(row["value"])
    validate_bounds(result)
    return result


def validate_bounds(bounds):
    if set(bounds) != set(BOUND_DEFAULTS) or not np.isfinite(list(bounds.values())).all():
        raise ValueError("Receptor bounds need the complete finite parameter set")
    for name in ("gain", "threshold_factor", "tau_factor", "release"):
        if not 0 <= bounds[name + "_min"] < bounds[name + "_max"]:
            raise ValueError("Receptor bounds must be nonnegative and ordered")
    if min(bounds["threshold_factor_min"], bounds["tau_factor_min"], bounds["signal_abs_max"]) <= 0:
        raise ValueError("Threshold, tau and signal guard bounds must be positive")


@dataclass(frozen=True)
class PlasticityChannel:
    receptor: str
    history: str
    effect: str
    edge_indices: np.ndarray
    signal: np.ndarray
    provenance: str


@dataclass(frozen=True)
class ReceptorEffects:
    gain: np.ndarray
    threshold_factor: np.ndarray
    tau_factor: np.ndarray
    release_factor: np.ndarray
    edge_pre: np.ndarray
    edge_post: np.ndarray
    model_root_ids: np.ndarray
    plasticity_channels: dict[str, PlasticityChannel]
    guard_events: dict[str, int]
    coverage: list[dict]


class ReceptorModel:
    """Bind table targets and CSC edge identities to the verified neuron order.

    Neuron effects use the mean C over a neuron's assigned volumes (ASSUMPTION).
    KC->MBON effects instead read each target MBON's empirical compartment and
    require that the presynaptic KC matches the receptor row. No whole-row gain
    is used for an edge-scoped release effect.
    """
    def __init__(self, rows: list[dict], neurons: pd.DataFrame, mapping: CompartmentMap,
                 weights, *, model_indices=None, bounds=None, species=FIELD_SPECIES):
        self.rows, self.neurons, self.species = rows, neurons, tuple(species)
        self.bounds = receptor_bounds() if bounds is None else dict(bounds)
        validate_bounds(self.bounds)
        n = len(neurons)
        indices = np.arange(n) if model_indices is None else np.asarray(model_indices)
        if (indices.shape != (n,) or not np.issubdtype(indices.dtype, np.integer)
                or np.any(indices < 0) or np.any(indices >= len(mapping.model_root_ids))):
            raise ValueError("Invalid receptor model indices")
        self.root_ids = neurons.root_id.to_numpy(np.int64)
        if not np.array_equal(self.root_ids, mapping.model_root_ids[indices]):
            raise ValueError("Receptor neurons and compartments differ in row order")
        self.membership = sparse.csr_matrix(mapping.membership[:, indices].T, dtype=np.float64)
        size = np.asarray(self.membership.sum(axis=1)).ravel()
        self.membership = sparse.diags(1 / np.maximum(size, 1)) @ self.membership
        self.n_compartments = len(mapping.names)
        csc = sparse.csc_matrix(weights, dtype=np.float32, copy=True)
        if csc.shape != (n, n):
            raise ValueError("Receptor wiring must match neuron order")
        csc.sum_duplicates(); csc.eliminate_zeros(); csc.sort_indices()
        if not np.isfinite(csc.data).all():
            raise ValueError("Receptor wiring contains nonfinite counts")
        self.edge_pre = np.repeat(np.arange(n, dtype=np.int32), np.diff(csc.indptr))
        self.edge_post = csc.indices.astype(np.int32)
        self.edge_compartment = mapping.mb_assignment[indices][self.edge_post]
        cells = neurons.cell_type.fillna("")
        kc = cells.str.startswith("KC").to_numpy()
        mbon = cells.str.startswith("MBON").to_numpy()
        self.plastic_edges = kc[self.edge_pre] & mbon[self.edge_post]
        self.targets, self.coverage = [], []
        nt = neurons.get("known_nt", pd.Series([""] * n)).map(parse_positive_nt)
        for row in rows:
            if row["modulator"] not in self.species:
                raise ValueError(f"Receptor species absent from field: {row['modulator']}")
            target = cells.map(lambda value: re.search(row["target"], value) is not None).to_numpy(copy=True)
            if row["target_class"]:
                target &= neurons.cell_class.fillna("").eq(row["target_class"]).to_numpy()
            if row["target_nt"]:
                target &= nt.map(lambda values: row["target_nt"] in values).to_numpy()
            edges = target[self.edge_pre]
            if row["edge_scope"] == "KC->MBON":
                edges &= self.plastic_edges
            self.targets.append((target, edges))
            self.coverage.append({"id": row["id"], "enabled": row["enabled"],
                                  "target_neurons": int(target.sum()), "target_edges": int(edges.sum()) if row["edge_scope"] != "none" else 0,
                                  "target_neurons_without_volume": int((target & (size == 0)).sum()),
                                  "target_edges_without_empirical_compartment": int((edges & (self.edge_compartment < 0)).sum()) if row["edge_scope"] == "KC->MBON" else 0,
                                  "expression_provenance": row["expression_provenance"]})

    def evaluate(self, concentration: np.ndarray) -> ReceptorEffects:
        c = np.asarray(concentration, np.float64)
        if c.shape != (len(self.species), self.n_compartments) or not np.isfinite(c).all() or np.any(c < 0):
            raise ValueError("Receptor C must be finite nonnegative species-by-compartment state")
        n = len(self.neurons)
        arrays = {name: np.ones(n if name != "release" else len(self.edge_pre), np.float64)
                  for name in ("gain", "threshold_factor", "tau_factor", "release")}
        channels, guards = {}, {"signal": 0, "gain": 0, "threshold_factor": 0, "tau_factor": 0, "release": 0}
        neuron_c = {}
        for row, (target, edges) in zip(self.rows, self.targets, strict=True):
            if not row["enabled"]:
                continue
            ci = self.species.index(row["modulator"])
            if ci not in neuron_c:
                neuron_c[ci] = np.asarray(self.membership @ c[ci]).ravel()
            if row["edge_scope"] == "KC->MBON":
                selected = np.flatnonzero(edges & (self.edge_compartment >= 0))
                exposure = c[ci, self.edge_compartment[selected]]
            elif row["edge_scope"] == "all_out":
                selected = np.flatnonzero(edges)
                exposure = neuron_c[ci][self.edge_pre[selected]]
            else:
                selected = np.flatnonzero(target)
                exposure = neuron_c[ci][selected]
            with np.errstate(over="ignore"):
                signal = row["magnitude"] * kernel_response(exposure, row["kernel"])
            maximum = self.bounds["signal_abs_max"]
            guards["signal"] += int((~np.isfinite(signal) | (np.abs(signal) > maximum)).sum())
            signal = np.clip(signal, -maximum, maximum)
            if not np.isfinite(signal).all():
                raise FloatingPointError("Nonfinite receptor signal after explicit guard")
            if row["effect"].startswith("plasticity_"):
                selected.flags.writeable = signal.flags.writeable = False
                channels[row["id"]] = PlasticityChannel(row["receptor"], row["history"], row["effect"], selected, signal, row["provenance"])
            else:
                effect = {"v_th": "threshold_factor", "tau_m": "tau_factor", "release_prob": "release"}.get(row["effect"], row["effect"])
                arrays[effect][selected] += signal
        for key, values in arrays.items():
            lo, hi = self.bounds[key + "_min"], self.bounds[key + "_max"]
            guards[key] = int(((values < lo) | (values > hi)).sum())
            np.clip(values, lo, hi, out=values)
            values.flags.writeable = False
        for values in (self.edge_pre, self.edge_post, self.root_ids):
            values.flags.writeable = False
        return ReceptorEffects(arrays["gain"], arrays["threshold_factor"], arrays["tau_factor"], arrays["release"],
                               self.edge_pre, self.edge_post, self.root_ids, channels, guards, self.coverage)


def require_field_gate(root: Path) -> dict:
    load_compartments(root)
    result = json.loads((Path(root) / "build/validation_neuromod_field.json").read_text())
    if result.get("status") != "PASS" or not result.get("checks") or any(c.get("status") != "PASS" for c in result["checks"]):
        raise ValueError("Receptors require a passing field gate")
    for group, prefix in (("config_hashes", Path(root) / "config"), ("implementation_hashes", Path(root)),
                          ("dependency_hashes", Path(root)), ("artifact_hashes", Path(root) / "build")):
        if not result.get(group):
            raise ValueError(f"Field evidence lacks {group}")
        for name, digest in result[group].items():
            if checksum(prefix / name) != digest:
                raise ValueError(f"Field prerequisite is stale: {name}")
    return result


def _same_execution(left, right, left_engine, right_engine) -> bool:
    keys = ("spike_indices", "spike_times", "voltages", "voltage_times", "record_indices")
    states = ("v", "g", "last_spike", "refractory_steps", "ring_counts")
    return (all(np.array_equal(left[k], right[k]) for k in keys)
            and all(np.array_equal(getattr(left_engine, k), getattr(right_engine, k)) for k in states)
            and all(np.array_equal(left_engine.ring[i, :count], right_engine.ring[i, :count])
                    for i, count in enumerate(left_engine.ring_counts))
            and left["clamp_count"] == right["clamp_count"] and left_engine.step == right_engine.step)


def validate_receptors(root: Path) -> dict:
    """Persist V-NM-A for the released all-LIF core and explicit active fixtures.

    This is not certification of a whole-brain hybrid engine, a dynamic field
    feedback scheduler, or Layers 4/5. V-NM-I remains NOT-RUN on base V-G/V-H.
    """
    from ..config import parameters
    from ..engine import LIFEngine
    from .core import load_core
    from .field import build_source_projection
    from .receptor_engine import ReceptorLIFEngine
    from .sources import require_source_gate

    root = Path(root).resolve()
    output = root / "build"
    destination = output / "validation_neuromod_receptors.json"
    result = {"gate": "V-NM-A", "status": "FAIL", "created_at": datetime.now(timezone.utc).isoformat(),
              "checks": [], "scope": "Disable-equivalence on the released all-LIF core, recurrent numerical fixtures and frozen-effect active adapter; not whole-brain hybrid or Layers 4/5 certification",
              "visual_gate": {"gate": "V-NM-I", "status": "NOT-RUN", "reason": "depends on base V-G/V-H; no synthetic visual gain fixture substitutes for the required validated visual pathway"},
              "notes": ["Source-correct OAMB/PAM and mAChR-A/KC rows are active; requested Octbeta2R/PAM and mAChR-B/KC rows remain disabled assumptions because their cited receptor identities differ.",
                        "All expression coverage, numerical magnitudes, kernel shapes and bounds are ASSUMPTION. No single-cell RNA measurement was used.",
                        "Effects are frozen over each run; callers can update at field boundaries. No autonomous field-network feedback scheduler is certified here.",
                        "Separate Dop1R1/Dop1R2 history channels are emitted for Layer 4; this stage does not integrate eligibility traces or change weights."]}
    atomic_write_json(destination, result | {"failed_checks": ["validation_in_progress"]})

    def check(name, observed, expected):
        observed = observed.item() if isinstance(observed, np.generic) else observed
        expected = expected.item() if isinstance(expected, np.generic) else expected
        result["checks"].append({"name": name, "observed": observed, "expected": expected,
                                 "status": "PASS" if observed == expected else "FAIL"})

    try:
        require_field_gate(root)
        source = require_source_gate(root)
        for key in ("source_hashes", "source_stats", "base_artifact_hashes", "base_config_hashes"):
            result[key] = source[key]
        result["config_hashes"] = {name: checksum(root / "config" / name)
                                   for name in ("neuromod.yaml", "parameters.yaml", "receptors.csv")}
        result["implementation_hashes"] = {name: checksum(root / name) for name in (
            "src/flybrain/neuromod/receptors.py", "src/flybrain/neuromod/receptor_engine.py",
            "src/flybrain/engine.py", "src/flybrain/neuromod/core.py", "src/flybrain/neuromod/field.py")}
        result["dependency_hashes"] = {"build/" + name: checksum(output / name) for name in (
            "validation_neuromod_sources.json", "validation_neuromod_compartments.json",
            "validation_neuromod_field.json", "compartments.npz", "neurons.parquet")}
        rows, bounds = read_receptors(root / "config/receptors.csv"), receptor_bounds(root)
        mapping = load_compartments(root)
        core = load_core(root, kc_kc_mode="as_released")
        model = ReceptorModel(rows, core.neurons, mapping, core.counts,
                              model_indices=core.model_indices, bounds=bounds)
        zeros = model.evaluate(np.zeros((len(FIELD_SPECIES), len(mapping.names))))
        ones = model.evaluate(np.ones((len(FIELD_SPECIES), len(mapping.names))))
        check("zero_C_identity_parameters", all(np.all(a == 1) for a in
              (zeros.gain, zeros.threshold_factor, zeros.tau_factor, zeros.release_factor)), True)
        check("zero_C_history_channels", all(not c.signal.any() for c in zeros.plasticity_channels.values()), True)
        check("unit_C_default_guard_events", sum(ones.guard_events.values()), 0)
        check("two_separate_dopamine_history_channels", sorted(c.history for c in ones.plasticity_channels.values()), ["da_before_kc", "kc_before_da"])
        check("plastic_edge_identity_count", int(model.plastic_edges.sum()), 62261)
        check("Dop1R1_channel_negative", bool(np.all(ones.plasticity_channels["DA_Dop1R1_forward"].signal < 0)), True)
        check("Dop1R2_channel_positive", bool(np.all(ones.plasticity_channels["DA_Dop1R2_backward"].signal > 0)), True)
        check("numerical_magnitudes_assumption", all(r["magnitude_provenance"] == "ASSUMPTION" for r in rows), True)
        check("expression_is_not_scRNA_measurement", all(r["expression_provenance"] == "ASSUMPTION" for r in rows), True)
        result["core_target_coverage"] = model.coverage
        result["bounds"] = bounds

        # Reachability is anatomical/annotation overlap only, not an observed response.
        all_neurons = pd.read_parquet(output / "neurons.parquet")
        projection = build_source_projection(all_neurons, mapping)
        all_model = ReceptorModel(rows, all_neurons, mapping, sparse.csr_matrix((len(all_neurons), len(all_neurons))), bounds=bounds)
        reachability = []
        for row_index, (row, (target, _), coverage) in enumerate(zip(rows, all_model.targets, all_model.coverage, strict=True)):
            si = FIELD_SPECIES.index(row["modulator"])
            active_volumes = projection.source_counts[si] > 0
            reached = np.asarray(all_model.membership[:, active_volumes].sum(axis=1)).ravel() > 0
            shared = [name for i, name in enumerate(mapping.names)
                      if active_volumes[i] and np.any(mapping.membership[i] & target)]
            detail = {}
            if row["edge_scope"] == "KC->MBON":
                selected = model.targets[row_index][1]
                assigned = selected & (model.edge_compartment >= 0)
                with_source = np.zeros_like(selected)
                with_source[assigned] = active_volumes[model.edge_compartment[assigned]]
                detail = {"core_scoped_edges": int(selected.sum()),
                          "core_scoped_edges_with_source_in_target_compartment": int(with_source.sum()),
                          "core_scoped_edges_without_source_in_target_compartment": int((selected & ~with_source).sum()),
                          "target_compartments_without_source": sorted({mapping.names[int(i)] for i in model.edge_compartment[assigned] if not active_volumes[i]})}
            reachability.append(coverage | detail | {"target_neurons_sharing_source_volume": int((target & reached).sum()),
                                            "target_neurons_without_shared_source_volume": int((target & ~reached).sum()),
                                            "shared_volumes": shared,
                                            "interpretation": "Direct coarse-volume overlap, not measured release or observed physiology; adjacency spillover and dynamic firing are not assumed here"})
        result["source_target_reachability"] = reachability
        serotonin = next(r for r in reachability if r["id"] == "5HT_5HT7_GABA_ALLN")
        result["5HT_AL_scope"] = {"shared_target_neurons": serotonin["target_neurons_sharing_source_volume"],
                                   "mechanism": "CSD shares AL_unresolved with GABA-positive ALLNs; 5HT7 raises assumed LN gain, then existing signed LN->PN edges carry inhibition. No fabricated broadcast to named glomeruli and no DPM->MB claim."}

        p = parameters(root)
        classes = core.neurons.cell_class.fillna("")
        cells = core.neurons.cell_type.fillna("")
        sets = {"ORN": np.flatnonzero(classes.eq("olfactory"))[:4],
                "PN": np.flatnonzero(classes.eq("ALPN"))[:4],
                "KC": np.flatnonzero(cells.str.startswith("KC"))[:4],
                "DAN": np.flatnonzero(classes.eq("DAN"))[:4]}
        records = np.unique(np.concatenate(list(sets.values()))).astype(np.int32)
        saved, trials = {}, []
        for name, inputs in [("rest", np.empty(0, np.int32)), *sets.items(),
                             ("combined", np.unique(np.concatenate(list(sets.values()))))]:
            base = LIFEngine(core.counts, p, threads=1, clamp=False)
            adapter = ReceptorLIFEngine(core.counts, p, threads=1, clamp=False, enabled=False)
            for part, duration in enumerate((4.3, 5.7)):
                events = (np.array([[step, i] for step in (0, 10, 20) for i in range(len(inputs))], np.int64)
                          if len(inputs) else np.empty((0, 2), np.int64))
                a = base.run(duration, inputs, events, records, chunk_ms=1.)
                b = adapter.run(duration, inputs, events, records, chunk_ms=2.)
                check(f"disabled_exact_{name}_part{part}", _same_execution(a, b, base, adapter), True)
                for key in ("spike_indices", "spike_times", "voltages", "voltage_times"):
                    saved[f"{name}_{part}_{key}"] = a[key]
                trials.append({"stimulus": name, "part": part, "duration_ms": duration,
                               "input_neurons": inputs.tolist(), "spikes": len(a["spike_indices"]),
                               "exact_spikes_voltages_state_pending_delays": _same_execution(a, b, base, adapter)})
            saved[f"{name}_final_v"] = base.v
            saved[f"{name}_final_g"] = base.g
        check("disabled_battery_has_nonzero_spikes", any(t["spikes"] > 0 for t in trials), True)
        result["disabled_equivalence"] = {"core_neurons": len(core.neurons), "core_edges": int(core.counts.nnz),
                                           "clamping": False, "dt_ms": p["dt"], "trials": trials,
                                           "scope": "Six fixed core stimulus cases with two continuation calls each; no whole-brain or visual battery claim"}

        # Small diagnostic fixtures test active effects without pretending to be biology gates.
        neurons = pd.DataFrame({"root_id": np.arange(4, dtype=np.int64),
                                "cell_type": ["KCg", "MBON01", "MBON02", "PAM01"],
                                "cell_class": ["Kenyon_Cell", "MBON", "MBON", "DAN"]})
        mini_map = CompartmentMap(("g1", "g2"), np.array([[1, 1, 0, 1], [1, 0, 1, 0]], bool),
                                 np.zeros((2, 2), np.float32), np.array([-1, 0, 1, 0], np.int16), np.arange(4, dtype=np.int64), {})
        weights = sparse.csr_matrix(([1000., 1000., 1000.], ([1, 2, 3], [0, 0, 0])), shape=(4, 4))
        exposure = np.zeros((len(FIELD_SPECIES), 2)); exposure[FIELD_SPECIES.index("DA"), 0] = 1
        seed = rows[0] | {"id": "numerical_fixture", "target": "^KCg$", "effect": "gain",
                          "history": "instant", "edge_scope": "none", "magnitude": 2., "kernel": "linear"}
        fixture_model = ReceptorModel([seed], neurons, mini_map, weights, bounds=bounds)
        active = ReceptorLIFEngine(weights, p | {"poisson_factor": 20.}, enabled=True,
                                  model_root_ids=neurons.root_id.to_numpy(), threads=1, clamp=False)
        active.set_effects(fixture_model.evaluate(exposure))
        silence = active.run(.5, [], np.empty((0, 2), np.int64))
        check("active_no_current_at_rest", len(silence["spike_indices"]) == 0 and bool(np.all(active.v == p["v_rest"])), True)
        active.reset()
        gain_response = active.run(1., [0], [[0, 0]])
        baseline = LIFEngine(weights, p | {"poisson_factor": 20.}, threads=1, clamp=False).run(1., [0], [[0, 0]])
        check("active_gain_changes_evoked_response", len(gain_response["spike_indices"]) > len(baseline["spike_indices"]), True)
        release_row = seed | {"effect": "release_prob", "edge_scope": "KC->MBON", "magnitude": -1.}
        scoped = ReceptorModel([release_row], neurons, mini_map, weights, bounds=bounds).evaluate(exposure)
        active.reset(); active.set_effects(scoped); active.v[0] = p["v_threshold"] + 1
        active.run(p["synaptic_delay"] + p["dt"], [], np.empty((0, 2), np.int64))
        check("active_release_specific_postsynaptic_compartment", active.g[1] == 0 and active.g[2] == 1000 * p["spike_weight"], True)
        check("active_release_preserves_other_edge_scope", active.g[3] == 1000 * p["spike_weight"], True)
        changed_rows = [seed | {"effect": "tau_m", "magnitude": -.5}, seed | {"id": "threshold", "effect": "v_th", "magnitude": -.5}]
        transformed = ReceptorModel(changed_rows, neurons, mini_map, weights, bounds=bounds).evaluate(exposure)
        active.reset(); active.set_effects(transformed)
        check("active_tau_transform", float(active.receptor_decay_v[0]), float(np.exp(-p["dt"] / (p["tau_membrane"] * .75))))
        expected_threshold = p["v_rest"] + (p["v_threshold"] - p["v_rest"]) * .75
        check("active_threshold_transform", float(active.receptor_threshold[0]), float(expected_threshold))
        active.v[0] = (expected_threshold + p["v_threshold"]) / 2
        check("active_threshold_changes_firing", 0 in active.run(p["dt"], [], np.empty((0, 2), np.int64))["spike_indices"], True)
        guard_model = ReceptorModel([seed | {"magnitude": -100.}], neurons, mini_map, weights, bounds=bounds)
        guarded = guard_model.evaluate(exposure)
        check("guards_counted_and_outputs_bounded", guarded.guard_events["signal"] > 0 and guarded.guard_events["gain"] > 0 and guarded.gain[0] == bounds["gain_min"], True)
        for kernel in ("linear", "hill(1,1)", "hill(2,0.5)", "biphasic"):
            check("kernel_normalization_" + kernel, bool(np.allclose(kernel_response([0., 1.], kernel), [0, 1], atol=1e-15, rtol=0)), True)
        result["active_fixtures"] = {"gain_baseline_spikes": len(baseline["spike_indices"]),
                                     "gain_active_spikes": len(gain_response["spike_indices"]),
                                     "excess_signal_guard_events": guarded.guard_events,
                                     "interpretation": "Explicit diagnostic coefficients; not biology, sensitivity-sweep, visual or dynamic-feedback gate results"}
        pd.DataFrame(model.coverage).to_csv(output / "neuromod_receptor_coverage.csv", index=False)
        atomic_write_json(output / "neuromod_receptor_reachability.json", {"rows": reachability, "scope": "Annotation/coarse-volume overlap, not measured expression or activity"})
        np.savez_compressed(output / "neuromod_receptor_equivalence.npz", **saved)
        result["artifact_hashes"] = {name: checksum(output / name) for name in (
            "neuromod_receptor_coverage.csv", "neuromod_receptor_reachability.json", "neuromod_receptor_equivalence.npz")}
        require_field_gate(root)
        for group, base in (("config_hashes", root / "config"), ("implementation_hashes", root), ("dependency_hashes", root)):
            for name, digest in result[group].items():
                check(f"unchanged_{group}_{name}", checksum(base / name), digest)
    except Exception as exc:
        check("receptor_validation_execution", {"type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["status"] = "PASS" if result["checks"] and all(c["status"] == "PASS" for c in result["checks"]) else "FAIL"
    result["failed_checks"] = [c["name"] for c in result["checks"] if c["status"] == "FAIL"]
    atomic_write_json(destination, result)
    return result
