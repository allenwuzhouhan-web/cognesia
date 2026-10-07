"""Explicit endocrine boundary model: source release and parameter gains, no currents.

All state equations and quantitative couplings are assumptions. The endocrine
inventory is measured; it does not identify receptor expression or driver lines.
AKH is an external nutritional-axis proxy, since corpora cardiaca are absent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..fetch import checksum
from ..inspect_data import atomic_write_json
from .sources import parse_positive_nt, source_masks, require_source_gate

STATE_NAMES = ("energy", "hydration", "arousal", "circadian_phase", "stress")
HORMONES = ("insulin", "corazonin", "dh44", "itp", "dh31", "myosuppressin", "capa", "hugin")
INITIAL_STATE = dict(energy=1., hydration=1., arousal=0., circadian_phase=0., stress=0.)


@dataclass(frozen=True)
class StateParameters:
    dt_ms: float = 1000.
    energy_depletion_tau_ms: float = 3_600_000.
    feeding_tau_ms: float = 300_000.
    hydration_loss_tau_ms: float = 1_800_000.
    drinking_tau_ms: float = 60_000.
    arousal_tau_ms: float = 5000.
    stress_tau_ms: float = 60_000.
    circadian_period_ms: float = 86_400_000.
    hormone_tau_ms: float = 10_000.
    source_max_rate_hz: float = 50.
    endocrine_tonic_drive: float = .25
    pam_hunger_gain: float = .35
    pam_insulin_suppression: float = .2
    oa_arousal_gain: float = .5
    circadian_tone_amplitude: float = .1
    gain_min: float = .25
    gain_max: float = 3.

    def validate(self):
        values = asdict(self)
        if not all(not isinstance(v, bool) and np.isfinite(v) for v in values.values()):
            raise ValueError("State parameters must be finite scalars")
        if self.dt_ms <= 0 or not np.isclose(self.dt_ms / .1, round(self.dt_ms / .1), atol=1e-8, rtol=0):
            raise ValueError("State timestep must be a positive multiple of base 0.1 ms")
        if any(v <= 0 for k, v in values.items() if k.endswith("tau_ms") or k.endswith("period_ms")):
            raise ValueError("State time constants and period must be positive")
        if self.source_max_rate_hz <= 0 or not 0 <= self.endocrine_tonic_drive <= 1:
            raise ValueError("Invalid normalized endocrine source parameters")
        if min(self.pam_hunger_gain, self.pam_insulin_suppression, self.oa_arousal_gain) < 0:
            raise ValueError("State gain magnitudes must be nonnegative")
        if not 0 <= self.circadian_tone_amplitude <= 1 or not 0 < self.gain_min <= 1 <= self.gain_max:
            raise ValueError("State gain bounds must contain identity")

    @classmethod
    def from_root(cls, root):
        entries = yaml.safe_load((Path(root) / "config/neuromod.yaml").read_text())["parameters"]
        values = {}
        for name in cls.__dataclass_fields__:
            key = "state_" + name
            entry = entries[key]
            if entry.get("source") != "ASSUMPTION" or not entry.get("unit") or not entry.get("sweep"):
                raise ValueError(f"State coefficient requires assumption provenance and sweep: {key}")
            values[name] = float(entry["value"])
        result = cls(**values)
        result.validate()
        return result


def read_endocrine_sources(path):
    table = pd.read_csv(path, keep_default_na=False)
    needed = {"cell_type", "expected_model_count", "hormone", "positive_nt", "state_driver", "source", "url", "coupling_provenance", "driver_line"}
    if not needed.issubset(table) or table.cell_type.duplicated().any() or len(table) != 10:
        raise ValueError("Endocrine table must identify the ten measured cell types")
    if table.expected_model_count.sum() != 76 or np.any(table.expected_model_count <= 0):
        raise ValueError("Endocrine inventory must retain all 76 cells")
    for row in table.to_dict("records"):
        if row["hormone"] not in (*HORMONES, "unknown"):
            raise ValueError("Unidentified endocrine hormone")
        if row["state_driver"] not in ("energy", "hunger_stress", "stress", "thirst", "arousal", "none"):
            raise ValueError("Unidentified endocrine state driver")
        if row["hormone"] == "unknown" and (row["positive_nt"] or row["state_driver"] != "none"):
            raise ValueError("Unknown endocrine cells cannot receive invented hormone identities")
    return table.to_dict("records")


class EndocrineState:
    """One-Hz slow state with exact frozen-input relaxation and replayable controls.

    Arrays use the supplied model neuron order. ``endocrine_drive`` is a
    dimensionless *release drive* at identified endocrine cells. It can replace
    their entries in the field's rate vector after multiplying by max source Hz;
    it is never a current or a synthetic spike. ``gain_factor`` multiplies the
    existing Layer-3 PAM gain. ``source_rate_scale`` scales measured aminergic
    source rates before field projection.
    """
    def __init__(self, neurons, parameters, endocrine_table, *, require_complete=True):
        parameters.validate()
        self.parameters = parameters
        self.root_ids = neurons.root_id.to_numpy(np.int64, copy=True)
        if len(np.unique(self.root_ids)) != len(self.root_ids):
            raise ValueError("State model requires unique neuron identities")
        self.root_ids.flags.writeable = False
        self.n = len(neurons)
        self.rows = copy.deepcopy(endocrine_table)
        cells = neurons.cell_type.fillna("")
        endocrine = neurons.super_class.fillna("").eq("endocrine").to_numpy()
        tokens = neurons.known_nt.map(parse_positive_nt)
        self.endocrine_mask = endocrine
        self.family_masks, self.driver_masks = {}, []
        covered = np.zeros(self.n, bool)
        for row in self.rows:
            selected = endocrine & cells.eq(row["cell_type"]).to_numpy()
            if require_complete and int(selected.sum()) != int(row["expected_model_count"]):
                raise ValueError(f"Endocrine population mismatch: {row['cell_type']}")
            covered |= selected
            if row["hormone"] == "unknown":
                continue
            positive = set(row["positive_nt"].split(";"))
            if np.any(selected & ~tokens.map(lambda nts: positive.issubset(nts)).to_numpy()):
                raise ValueError(f"Endocrine source lacks positive peptide annotation: {row['cell_type']}")
            self.family_masks[row["hormone"]] = selected
            self.driver_masks.append((row["state_driver"], selected))
        if np.any(endocrine & ~covered) or (require_complete and endocrine.sum() != 76):
            raise ValueError("Incomplete endocrine source inventory")
        self.identified_mask = np.logical_or.reduce(list(self.family_masks.values())) if self.family_masks else np.zeros(self.n, bool)
        self.pam_mask = cells.str.startswith("PAM").to_numpy()
        sources = source_masks(neurons)
        self.oa_mask, self.da_mask, self.ht_mask = sources["OA"], sources["DA"], sources["5HT"]
        self.identity_hash = hashlib.sha256(self.root_ids.tobytes()).hexdigest()
        self.parameter_hash = hashlib.sha256(json.dumps(asdict(parameters), sort_keys=True).encode()).hexdigest()
        self.source_table_hash = hashlib.sha256(json.dumps(self.rows, sort_keys=True).encode()).hexdigest()
        self.reset()

    @classmethod
    def from_root(cls, root, neurons=None):
        root = Path(root)
        if neurons is None:
            neurons = pd.read_parquet(root / "build/neurons.parquet")
        return cls(neurons, StateParameters.from_root(root), read_endocrine_sources(root / "config/endocrine_sources.csv"))

    def _source_drive(self, rates):
        drive = np.zeros(self.n, np.float64)
        s = self.state
        drivers = {"energy": s["energy"], "hunger_stress": min(1., 1-s["energy"]+s["stress"]),
                   "stress": s["stress"], "thirst": 1-s["hydration"], "arousal": s["arousal"]}
        for driver, selected in self.driver_masks:
            drive[selected] = rates[selected] / self.parameters.source_max_rate_hz + self.parameters.endocrine_tonic_drive * drivers[driver]
        return drive

    def reset(self, state=None):
        values = INITIAL_STATE | ({} if state is None else dict(state))
        self._validate_state(values)
        self.state = {name: float(values[name]) for name in STATE_NAMES}
        self.t_sim_ms = 0.
        self.events = []
        self.clamp_events = 0
        self.last_rates = np.zeros(self.n, np.float64)
        self.endocrine_drive = self._source_drive(self.last_rates)
        self.hormones = {name: float(self.endocrine_drive[mask].mean()) if mask.any() else 0.
                         for name, mask in self.family_masks.items()}

    @staticmethod
    def _validate_state(values):
        if set(values) != set(STATE_NAMES) or not all(np.isfinite(v) and 0 <= v <= 1 for v in values.values()):
            raise ValueError("State must contain five finite normalized values")
        if values["circadian_phase"] >= 1:
            raise ValueError("Circadian phase is measured in cycles on [0,1)")

    def apply_control(self, control_id, value):
        if control_id == "nutritional_state":
            if value not in ("fed", "starved"):
                raise ValueError("Nutritional preset is fed or starved")
            new = self.state | {"energy": 1. if value == "fed" else 0.}
        else:
            if control_id not in STATE_NAMES:
                raise ValueError("Unknown state control")
            new = self.state | {control_id: float(value)}
        self._validate_state(new)
        self.state = new
        event = {"t_sim_ms": self.t_sim_ms, "control_id": control_id, "value": value}
        self.events.append(event)
        return copy.deepcopy(event)

    def step(self, dt_ms, source_rates_hz=None, *, feeding=0., drinking=0., locomotion=0., aversive=0.):
        p = self.parameters
        if not np.isfinite(dt_ms) or dt_ms != p.dt_ms:
            raise ValueError("State step must equal the configured fixed timestep")
        controls = (feeding, drinking, locomotion, aversive)
        if not all(np.isfinite(v) and 0 <= v <= 1 for v in controls):
            raise ValueError("State driving controls must be finite on [0,1]")
        rates = np.zeros(self.n) if source_rates_hz is None else np.asarray(source_rates_hz, np.float64)
        if rates.shape != (self.n,) or not np.isfinite(rates).all() or np.any(rates < 0):
            raise ValueError("State rates must be finite nonnegative values in model order")
        s = self.state.copy()
        for name, input_value, fill_tau, drain_tau in (
            ("energy", feeding, p.feeding_tau_ms, p.energy_depletion_tau_ms),
            ("hydration", drinking, p.drinking_tau_ms, p.hydration_loss_tau_ms)):
            a, b = input_value/fill_tau, 1/drain_tau
            target = a/(a+b)
            s[name] = target + (s[name]-target)*np.exp(-(a+b)*dt_ms)
        for name, target, tau in (("arousal", locomotion, p.arousal_tau_ms), ("stress", aversive, p.stress_tau_ms)):
            s[name] += (target-s[name]) * -np.expm1(-dt_ms/tau)
        s["circadian_phase"] = (s["circadian_phase"] + dt_ms/p.circadian_period_ms) % 1.
        self._validate_state(s)
        old_state = self.state
        self.state = s
        try:
            proposal = self._source_drive(rates)
        finally:
            self.state = old_state
        if not np.isfinite(proposal).all():
            raise FloatingPointError("Nonfinite endocrine release proposal")
        clips = int(np.count_nonzero((proposal < 0) | (proposal > 1)))
        drive = np.clip(proposal, 0, 1)
        hormones = {}
        coefficient = -np.expm1(-dt_ms/p.hormone_tau_ms)
        for name, mask in self.family_masks.items():
            target = float(drive[mask].mean()) if mask.any() else 0.
            hormones[name] = self.hormones[name] + (target-self.hormones[name])*coefficient
        self.state, self.hormones = s, hormones
        self.endocrine_drive = drive
        self.last_rates = rates.copy()
        self.clamp_events += clips
        self.t_sim_ms += float(dt_ms)
        return self.outputs()

    def outputs(self):
        p, s = self.parameters, self.state
        gain = np.ones(self.n, np.float64)
        akh_proxy = 1-s["energy"]
        raw_gain = 1+p.pam_hunger_gain*akh_proxy-p.pam_insulin_suppression*self.hormones.get("insulin", 0)
        gain[self.pam_mask] = np.clip(raw_gain, p.gain_min, p.gain_max)
        scale = np.ones(self.n, np.float64)
        scale[self.oa_mask] *= 1+p.oa_arousal_gain*s["arousal"]
        tone = 1+p.circadian_tone_amplitude*np.sin(2*np.pi*s["circadian_phase"])
        scale[self.da_mask | self.ht_mask] *= tone
        return {"state": dict(s), "hormones_au": dict(self.hormones), "akh_axis_proxy_au": akh_proxy,
                "gain_factor": gain, "source_rate_scale": scale, "endocrine_drive": self.endocrine_drive.copy(),
                "endocrine_mask": self.identified_mask.copy(), "source_max_rate_hz": p.source_max_rate_hz,
                "clamp_events": self.clamp_events, "t_sim_ms": self.t_sim_ms,
                "gain_clamps_current": int(self.pam_mask.sum()) if raw_gain < p.gain_min or raw_gain > p.gain_max else 0,
                "provenance": "ASSUMPTION; identified hormone sources only; AKH is an external proxy; no membrane current"}

    def snapshot(self):
        return {"schema_version": 1, "parameter_hash": self.parameter_hash, "model_identity_hash": self.identity_hash,
                "source_table_hash": self.source_table_hash,
                "state": dict(self.state), "hormones_au": dict(self.hormones), "t_sim_ms": self.t_sim_ms,
                "endocrine_drive": self.endocrine_drive.tolist(), "last_rates_hz": self.last_rates.tolist(),
                "clamp_events": self.clamp_events, "events": copy.deepcopy(self.events)}

    def restore(self, snapshot):
        if (snapshot.get("schema_version") != 1 or snapshot.get("parameter_hash") != self.parameter_hash
                or snapshot.get("model_identity_hash") != self.identity_hash or snapshot.get("source_table_hash") != self.source_table_hash):
            raise ValueError("State snapshot differs in schema, parameter or model identity")
        self._validate_state(snapshot["state"])
        hormones = snapshot["hormones_au"]
        drive, rates = np.asarray(snapshot["endocrine_drive"], float), np.asarray(snapshot["last_rates_hz"], float)
        if (set(hormones) != set(self.hormones) or not all(np.isfinite(v) and 0<=v<=1 for v in hormones.values())
                or drive.shape != (self.n,) or rates.shape != (self.n,) or not np.isfinite(drive).all()
                or not np.isfinite(rates).all() or np.any((drive < 0)|(drive > 1)) or np.any(rates < 0)
                or np.any(drive[~self.identified_mask] != 0)):
            raise ValueError("Invalid endocrine snapshot arrays")
        t, clamps = snapshot["t_sim_ms"], snapshot["clamp_events"]
        if not np.isfinite(t) or t<0 or t/self.parameters.dt_ms != round(t/self.parameters.dt_ms) or not isinstance(clamps, int) or clamps<0:
            raise ValueError("Invalid endocrine snapshot time/counters")
        previous = -1.
        for event in snapshot["events"]:
            when, control, value = event["t_sim_ms"], event["control_id"], event["value"]
            if not np.isfinite(when) or not previous <= when <= t or when/self.parameters.dt_ms != round(when/self.parameters.dt_ms):
                raise ValueError("Invalid endocrine control event time")
            if control == "nutritional_state":
                valid = value in ("fed", "starved")
            else:
                valid = control in STATE_NAMES and np.isfinite(value) and 0 <= value <= 1 and (control != "circadian_phase" or value < 1)
            if not valid:
                raise ValueError("Invalid endocrine control event")
            previous = when
        self.state, self.hormones = dict(snapshot["state"]), dict(hormones)
        self.endocrine_drive, self.last_rates = drive.copy(), rates.copy()
        self.t_sim_ms, self.clamp_events = float(t), clamps
        self.events = copy.deepcopy(snapshot["events"])

    def clone(self):
        return copy.deepcopy(self)

    def save(self, path):
        atomic_write_json(Path(path), self.snapshot())


class MBONValence:
    """Inferred signed MBON rate, not a motor decoder or measured decision."""
    def __init__(self, neurons, table):
        self.n = len(neurons)
        self.weights = np.zeros(self.n, float)
        self.rows = pd.read_csv(table, keep_default_na=False) if isinstance(table, (str, Path)) else table.copy()
        if self.rows.cell_type.duplicated().any() or not set(self.rows.valence_sign).issubset({-1,0,1}):
            raise ValueError("Invalid MBON valence table")
        cells = neurons.cell_type.fillna("")
        present = cells.str.startswith("MBON")
        if not set(cells[present]).issubset(set(self.rows.cell_type)):
            raise ValueError("MBON valence table must explicitly retain unassigned types")
        known_types = 0
        for row in self.rows.to_dict("records"):
            selected = cells.eq(row["cell_type"]).to_numpy()
            if selected.any() and row["valence_sign"]:
                if row["evidence"] != "INFERRED_SIGN" or not row["url"]:
                    raise ValueError("Every nonzero valence needs explicit sign provenance")
                self.weights[selected] = row["valence_sign"] / selected.sum()
                known_types += 1
        if known_types:
            self.weights /= known_types
        self.coverage = {"mbon_neurons": int(present.sum()), "signed_neurons": int(np.count_nonzero(self.weights)),
                         "signed_types": known_types, "unknown_is_zero_not_neutral": True, "body_readout": "NOT-RUN"}

    def evaluate(self, rates_hz):
        rates = np.asarray(rates_hz, float)
        if rates.shape != (self.n,) or not np.isfinite(rates).all() or np.any(rates < 0):
            raise ValueError("Valence requires finite nonnegative model rates")
        return float(self.weights @ rates)


def valence_from_rates(neurons, rates, root):
    """Compatibility adapter for the shared runtime's inferred MBON readout."""
    return MBONValence(neurons, Path(root) / "config/mbon_valence.csv").evaluate(rates)


def require_plasticity_gate(root):
    from .plasticity import require_receptor_gate
    root = Path(root)
    require_receptor_gate(root)
    record = json.loads((root / "build/validation_neuromod_plasticity.json").read_text())
    if record.get("gate") != "V-NM-E" or record.get("status") != "PASS" or not record.get("checks") or any(c["status"] != "PASS" for c in record["checks"]):
        raise ValueError("Endocrine stage requires the complete V-NM-E PASS")
    for group, prefix in (("implementation_hashes", root), ("dependency_hashes", root),
                          ("config_hashes", root / "config"), ("artifact_hashes", root / "build")):
        if not record.get(group):
            raise ValueError(f"Plasticity provenance is absent: {group}")
        for name, digest in record[group].items():
            if checksum(prefix / name) != digest:
                raise ValueError(f"Plasticity prerequisite is stale: {name}")
    return record


def _bind_trial_provenance(root, result, evidence):
    """A callback's network result must carry every actual runtime dependency."""
    from ..rt.engine_rt import runtime_fingerprint
    if not isinstance(evidence, dict):
        raise ValueError('Network state trials require explicit runtime provenance')
    _, expected = runtime_fingerprint(root)
    expected['src/flybrain/rt/validation.py'] = checksum(root/'src/flybrain/rt/validation.py')
    for path, digest in expected.items():
        group = 'config_hashes' if path.startswith('config/') else 'implementation_hashes' if path.startswith('src/') else 'dependency_hashes'
        name = path.removeprefix('config/') if group=='config_hashes' else path
        if evidence.get(group, {}).get(name) != digest:
            raise ValueError('Network state trial dependency missing or changed: '+path)
    for group, prefix in (('config_hashes',root/'config'),('implementation_hashes',root),('dependency_hashes',root)):
        for name,digest in evidence[group].items():
            if checksum(prefix/name) != digest or (name in result[group] and result[group][name] != digest):
                raise ValueError('Network state trial provenance changed: '+name)
        result[group].update(evidence[group])


def validate_state(root, trial_runner=None, *, runtime_provenance=None):
    """Validate state software, then measure V-NM-J only through real network trials.

    ``trial_runner(snapshot, seed)`` must provide valence, weight hashes before
    and after, stimulus_sha256 and parameter_sha256. Callback-backed trials also
    require complete ``runtime_provenance``, verified before and after use.
    No synthesized response is
    used when the network trial is unavailable. Biology may fail independently.
    """
    from .core import load_core
    root = Path(root).resolve()
    output = root / "build"
    output.mkdir(exist_ok=True)
    destination = output / "validation_neuromod_state.json"
    result = {"gate": "V-NM-J", "kind": "biology", "status": "FAIL", "software_status": "FAIL",
              "created_at": datetime.now(timezone.utc).isoformat(), "checks": [], "artifact_hashes": {},
              "biology_scope": "Same odor and seed, frozen weights; inferred MBON valence, no body decoder",
              "akh_scope": "External hunger-axis proxy; no AKH neuron or organ added to the connectome",
              "coupling_provenance": "ASSUMPTION", "body_readout": "NOT-RUN"}
    atomic_write_json(destination, result)
    def check(name, observed, expected):
        result["checks"].append({"name": name, "observed": observed, "expected": expected,
                                 "status": "PASS" if observed == expected else "FAIL"})
    biology = "NOT-RUN"
    try:
        require_plasticity_gate(root)
        source = require_source_gate(root)
        for key in ("source_hashes", "source_stats", "base_artifact_hashes", "base_config_hashes"):
            result[key] = source[key]
        result["config_hashes"] = {name: checksum(root / "config" / name) for name in
                                   ("neuromod.yaml", "endocrine_sources.csv", "mbon_valence.csv")}
        result["implementation_hashes"] = {"src/flybrain/neuromod/state.py": checksum(Path(__file__))}
        result["dependency_hashes"] = {"build/" + name: checksum(output / name) for name in
                                      ("validation_neuromod_sources.json", "validation_neuromod_plasticity.json", "mb_compartment_comparison.csv")}
        if trial_runner is not None:
            _bind_trial_provenance(root,result,runtime_provenance)
        neurons = load_core(root).neurons
        state = EndocrineState.from_root(root, neurons)
        check("endocrine_neurons", int(state.endocrine_mask.sum()), 76)
        check("identified_peptide_sources", int(state.identified_mask.sum()), 52)
        check("unknown_endocrine_retained_without_hormone", int((state.endocrine_mask & ~state.identified_mask).sum()), 24)
        check("no_akh_source_invented", "akh" in state.family_masks, False)
        reference = state.clone()
        state.apply_control("nutritional_state", "starved")
        reference.apply_control("nutritional_state", "starved")
        zero = np.zeros(len(neurons))
        for _ in range(10):
            state.step(state.parameters.dt_ms, zero)
            reference.step(reference.parameters.dt_ms, zero)
        check("control_replay_bit_exact", state.snapshot() == reference.snapshot(), True)
        restored = EndocrineState.from_root(root, neurons)
        restored.restore(state.snapshot())
        check("snapshot_restore_exact", restored.snapshot() == state.snapshot(), True)
        observed = state.outputs()
        check("parameter_gains_only_on_PAM", bool(np.all(observed["gain_factor"][~state.pam_mask] == 1)), True)
        check("no_release_in_unidentified_cells", bool(np.all(observed["endocrine_drive"][~state.identified_mask] == 0)), True)
        check("default_state_clamps", state.clamp_events, 0)
        readout = MBONValence(neurons, root / "config/mbon_valence.csv")
        result["readout_coverage"] = readout.coverage
        entries = yaml.safe_load((root / "config/neuromod.yaml").read_text())["parameters"]
        sweeps = []
        for name in StateParameters.__dataclass_fields__:
            for value in entries["state_" + name]["sweep"]:
                p = replace(state.parameters, **{name: float(value)})
                variant = EndocrineState(neurons, p, state.rows)
                for _ in range(max(1, round(60_000 / p.dt_ms))):
                    variant.step(p.dt_ms, zero, feeding=.2, drinking=.2, locomotion=.5, aversive=.25)
                out = variant.outputs()
                sweeps.append({"parameter": "state_" + name, "value": value, "t_sim_ms": variant.t_sim_ms,
                               **variant.state, "insulin_au": variant.hormones.get("insulin", 0),
                               "mean_PAM_gain": float(out["gain_factor"][variant.pam_mask].mean()),
                               "clamp_events": variant.clamp_events})
        pd.DataFrame(sweeps).to_csv(output / "neuromod_state_sensitivity.csv", index=False)
        check("sensitivity_all_finite", bool(np.isfinite(pd.DataFrame(sweeps).select_dtypes(include=np.number)).all().all()), True)
        result["sensitivity_runs"] = len(sweeps)
        if trial_runner is not None:
            trials = {}
            for label, energy in (("fed", 1.), ("starved", 0.)):
                trial_state = EndocrineState.from_root(root, neurons)
                trial_state.reset({"energy": energy})
                trials[label] = trial_runner(trial_state.snapshot(), 7)
            fed, starved = trials["fed"], trials["starved"]
            check("same_odor_stimulus", fed["stimulus_sha256"], starved["stimulus_sha256"])
            check("same_parameters", fed["parameter_sha256"], starved["parameter_sha256"])
            check("same_initial_weights", fed["weights_sha256_before"], starved["weights_sha256_before"])
            for label, trial in trials.items():
                check(label + "_weights_unchanged", trial["weights_sha256_after"], trial["weights_sha256_before"])
            difference = float(starved["valence"] - fed["valence"])
            check("finite_network_valence", bool(np.isfinite([fed["valence"], starved["valence"]]).all()), True)
            decisions = {label: int(np.sign(trial["valence"])) if np.isfinite(trial["valence"]) else None
                         for label, trial in trials.items()}
            biology = "PASS" if np.isfinite(difference) and decisions["fed"] != decisions["starved"] else "FAIL"
            result["trials"] = trials
            result["valence_difference_starved_minus_fed"] = difference
            result["decoded_decisions"] = decisions
            result["score_changed"] = bool(np.isfinite(difference) and difference != 0)
            result["decision_interpretation"] = "Sign of inferred MBON valence: -1 avoidance, 0 neutral, +1 approach; gate requires different categories"
        else:
            result["stop_reason"] = "State software checked; network fed/starved odor trials were not supplied"
        atomic_write_json(output / "neuromod_state_snapshot.json", state.snapshot())
        result["artifact_hashes"] = {name: checksum(output / name) for name in
                                     ("neuromod_state_sensitivity.csv", "neuromod_state_snapshot.json")}
        require_plasticity_gate(root)
        for group, prefix in (("config_hashes", root / "config"), ("implementation_hashes", root), ("dependency_hashes", root)):
            for name, digest in result[group].items():
                if checksum(prefix / name) != digest:
                    raise ValueError(f"State input changed during validation: {name}")
    except Exception as exc:
        check("state_validation_execution", {"type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["failed_checks"] = [item["name"] for item in result["checks"] if item["status"] != "PASS"]
    result["software_status"] = "PASS" if result["checks"] and not result["failed_checks"] else "FAIL"
    result["status"] = biology if result["software_status"] == "PASS" else "FAIL"
    atomic_write_json(destination, result)
    return result
