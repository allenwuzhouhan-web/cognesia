"""Pinned DoOR consensus inputs on identified ORNs, with explicit missingness.

This prerequisite does not transform AL signals, measure KC sparseness, or supply
an animal behaviour decoder. Consensus response units are not measured Hz.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import numpy as np
import pandas as pd
import yaml

from ..fetch import checksum, stat_signature
from ..inspect_data import atomic_write_json
from .sources import block_masks, require_source_gate

DOOR_COMMIT = "db323a496577c4b4a72b5c2fcd1859e07521ffb5"
DOOR_BASE = f"https://raw.githubusercontent.com/ropensci/DoOR.data/{DOOR_COMMIT}/data/"
SOURCE_FILES = {
    "door_response_matrix.csv": ("bc2aa5414ff54d3a1399f5fe171e154bcadc754bcf323a3c27711a54f70848e2", (691, 78)),
    "door_mappings.csv": ("1197c492e769b1b587c907c5b750ffa2507d7e6c9fe9dfcb2ee8603871e00912", (96, 20)),
    "odor.csv": ("a31d1841cf90ce23ec149760a5efa38eae02de7820bb2300c3a7dba221745940", (691, 22)),
    "door_dataset_info.csv": ("6ab8bc1c843ffe4763e563eb763029c421898dce7889c31dc2c21b544c9be269", (42, 15)),
    "door_response_range.csv": ("5499f1d7bf3217f9af8bc45ee90c85ef09c9f2afd11ca833fae1ad055d97a7f4", (42, 4)),
}
ALIASES = {
    "OCT": "NMRPBPVERJPACX-UHFFFAOYSA-N",  # 3-octanol, CAS 589-98-0
    "MCH": "MQWCXKGKQLNYQG-UHFFFAOYSA-N",  # 4-methylcyclohexanol, CAS 589-91-3
}
BASELINE_NOTE = (
    "Missing measurements give zero evoked delta, not measured silence. An independently measured "
    "SFR may still drive tonic activity; unmapped, ambiguous and untyped neurons get zero input."
)
SYNTHETIC_LIMIT = (
    "SYNTHETIC ODOUR: reproducible timing-control input only; cannot support odour discrimination, "
    "generalisation or identity-coding claims."
)
PARAMETER_NAMES = ("odour_max_rate_hz", "odour_adaptation_tau_ms", "odour_transduction_tau_ms",
                   "odour_half_saturation", "odour_adaptation_strength", "odour_baseline_mode")


class SourceUnavailable(OSError):
    """Missing pinned source after an unavailable/failed network fetch."""


def fetch_door(root: Path, *, download: bool = True) -> tuple[dict, dict]:
    """Verify every cached byte before fetching; schema/corruption never falls back.

    R CSVs use ';' and implicit row names (not part of the header). The matrix's
    index is the InChIKey. Discovery is persisted before any mapping is built.
    """
    root = Path(root)
    folder = root / "data/raw/neuromod/door"
    folder.mkdir(parents=True, exist_ok=True)
    for name, (digest, _) in SOURCE_FILES.items():
        path = folder / name
        if path.exists() and checksum(path) != digest:
            raise ValueError(f"DoOR checksum mismatch: {name}; no synthetic fallback")
    for name, (digest, _) in SOURCE_FILES.items():
        path = folder / name
        if not path.exists():
            if not download:
                raise SourceUnavailable(f"Missing DoOR file with downloads disabled: {name}")
            try:
                with urlopen(DOOR_BASE + name, timeout=30) as response:
                    data = response.read()
            except (URLError, TimeoutError, OSError) as exc:
                raise SourceUnavailable(f"DoOR download failed for {name}: {exc}") from exc
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"Downloaded DoOR checksum mismatch: {name}; no synthetic fallback")
            partial = path.with_suffix(".partial")
            partial.write_bytes(data)
            partial.replace(path)
    tables, audit = {}, {}
    for name, (digest, shape) in SOURCE_FILES.items():
        before = stat_signature(folder / name)
        if checksum(folder / name) != digest:
            raise ValueError(f"DoOR changed before parsing: {name}")
        table = pd.read_csv(folder / name, sep=";", index_col=0)
        if stat_signature(folder / name) != before or checksum(folder / name) != digest:
            raise ValueError(f"DoOR changed during parsing: {name}")
        audit[name] = {"url": DOOR_BASE + name, "sha256": digest,
                       "source_stats": before,
                       "rows": len(table), "columns": len(table.columns),
                       "dtypes": {str(k): str(v) for k, v in table.dtypes.items()},
                       "index_dtype": str(table.index.dtype),
                       "first_three_rows": json.loads(table.head(3).reset_index().to_json(orient="records"))}
        tables[name] = table
    atomic_write_json(root / "build/schema_inspection_odour.json", audit)
    for name, (_, shape) in SOURCE_FILES.items():
        if tables[name].shape != shape:
            raise ValueError(f"Pinned DoOR schema changed: {name} {tables[name].shape} != {shape}")
    validate_tables(tables["door_response_matrix.csv"], tables["door_mappings.csv"], tables["odor.csv"])
    return tables, audit


def validate_tables(response: pd.DataFrame, mapping: pd.DataFrame, odors: pd.DataFrame) -> None:
    if not {"receptor", "code", "glomerulus", "comment"}.issubset(mapping.columns):
        raise ValueError("DoOR mapping lacks receptor/code/glomerulus/comment")
    if not {"Name", "InChIKey", "CAS"}.issubset(odors.columns):
        raise ValueError("DoOR odor metadata lacks chemical identity")
    if response.index.has_duplicates or response.columns.has_duplicates or "SFR" not in response.index:
        raise ValueError("DoOR matrix must have unique responding units/identities and SFR")
    if mapping.code.dropna().duplicated().any() or odors.InChIKey.duplicated().any():
        raise ValueError("DoOR chemical identifiers and glomerulus codes must be unique")
    values = response.to_numpy(dtype=float)
    if np.isinf(values).any() or np.any((values < 0) | (values > 1)):
        raise ValueError("DoOR consensus must contain [0,1] numeric values or explicit NaN")
    if not set(response.index).issubset(set(odors.InChIKey)):
        raise ValueError("DoOR response identifiers are absent from odor metadata")


@dataclass(frozen=True)
class OdourResponse:
    values: np.ndarray  # signed evoked delta in normalized a.u.; never Hz
    metadata: dict

    def __iter__(self):
        yield self.values
        yield self.metadata


class OdourLibrary:
    def __init__(self, neurons: pd.DataFrame, response: pd.DataFrame | None,
                 mapping: pd.DataFrame | None, odors: pd.DataFrame | None,
                 *, source_audit: dict | None = None, seed: int = 7, fallback_reason: str | None = None):
        required = {"root_id", "cell_type", "cell_class", "super_class"}
        if not required.issubset(neurons.columns) or neurons.root_id.duplicated().any():
            raise ValueError("Neuron table needs unique root IDs and normative ORN annotation fields")
        mask = block_masks(neurons)["ORN"]
        self.neuron_indices = np.flatnonzero(mask).astype(np.int32)
        self.root_ids = neurons.loc[mask, "root_id"].to_numpy(dtype=np.int64)
        self.neuron_types = neurons.loc[mask, "cell_type"].fillna("").to_numpy(dtype=str)
        self.types = tuple(sorted(set(self.neuron_types) - {""}))
        if any(not value.startswith("ORN_") for value in self.types):
            raise ValueError("Named normative ORNs must retain exact ORN_ anatomical identifiers")
        self.type_codes = np.array([self.types.index(v) if v else -1 for v in self.neuron_types], np.int32)
        self.type_counts = np.array([np.count_nonzero(self.neuron_types == v) for v in self.types], np.int32)
        self.mode = "synthetic" if response is None else "door"
        self.seed, self.fallback_reason = int(seed), fallback_reason
        self.source_audit = source_audit or {}
        self.response, self.mapping, self.odors = response, mapping, odors
        self.baseline = np.zeros(len(self.types), dtype=np.float64)
        self.raw_spontaneous = np.full(len(self.types), np.nan, dtype=np.float64)
        self.units, self.map_status = [], []
        if self.mode == "door":
            if mapping is None or odors is None:
                raise ValueError("Measured mode needs mapping and odor metadata")
            validate_tables(response, mapping, odors)
            codes = mapping.set_index("code")
            for i, ct in enumerate(self.types):
                glomerulus = ct[4:]
                if glomerulus not in codes.index:
                    unit, status = "", "unmapped_glomerulus"
                else:
                    row = codes.loc[glomerulus]
                    unit = str(row.receptor)
                    if glomerulus in {"DL2d", "DL2v"} and unit == "ac3A":
                        status = "ambiguous_ac3A_split"
                    elif unit == "?":
                        status = "unknown_receptor"
                    elif unit not in response.columns:
                        status = "unit_without_response_column"
                    else:
                        status = "mapped"
                        value = response.loc["SFR", unit]
                        if pd.notna(value):
                            self.baseline[i] = float(value)
                if unit in response.columns and pd.notna(response.loc["SFR", unit]):
                    self.raw_spontaneous[i] = float(response.loc["SFR", unit])
                self.units.append(unit)
                self.map_status.append(status)
        else:
            if not fallback_reason:
                raise ValueError("Synthetic fallback must record the actual source-unavailability reason")
            self.units = [""] * len(self.types)
            self.map_status = ["synthetic_not_measured"] * len(self.types)

    @classmethod
    def from_root(cls, root: Path, *, download: bool = True, allow_synthetic: bool = False,
                  seed: int = 7) -> "OdourLibrary":
        root = Path(root)
        require_source_gate(root)
        neurons = pd.read_parquet(root / "build/neurons.parquet")
        try:
            tables, audit = fetch_door(root, download=download)
        except SourceUnavailable as exc:
            if not allow_synthetic or not download:
                raise
            return cls(neurons, None, None, None, seed=seed, fallback_reason=str(exc))
        return cls(neurons, tables["door_response_matrix.csv"], tables["door_mappings.csv"],
                   tables["odor.csv"], source_audit=audit, seed=seed)

    def responses(self, name: str) -> OdourResponse:
        """Return ordered signed evoked responses, preserving inhibition and missingness."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("An explicit odour identity is required")
        values = np.zeros(len(self.types), np.float64)
        raw = np.full(len(self.types), np.nan)
        status = list(self.map_status)
        info = {"requested_name": name, "units": "a.u.", "value_meaning": "signed evoked consensus minus SFR",
                "mode": self.mode, "types": list(self.types), "baseline_note": BASELINE_NOTE,
                "source_commit": DOOR_COMMIT if self.mode == "door" else None}
        if self.mode == "synthetic":
            seed_bytes = hashlib.sha256(f"{self.seed}:{name}".encode()).digest()
            rng = np.random.default_rng(int.from_bytes(seed_bytes[:16], "little"))
            n_active = max(1, int(round(len(self.types) * 0.1))) if self.types else 0
            selected = rng.choice(len(self.types), n_active, replace=False)
            values[selected] = rng.uniform(0.25, 1.0, size=n_active)
            info.update(label="SYNTHETIC ODOUR", limitation=SYNTHETIC_LIMIT,
                        seed=self.seed, source_failure=self.fallback_reason,
                        synthetic_assumptions={"active_fraction": 0.1, "amplitude_uniform_au": [0.25, 1.0]})
        else:
            key = ALIASES.get(name.upper(), name)
            matches = self.odors[self.odors.InChIKey.eq(key) | self.odors.Name.str.casefold().eq(name.casefold())
                                 | self.odors.CAS.eq(name)]
            if len(matches) != 1:
                raise ValueError(f"Unknown or ambiguous DoOR odour: {name}")
            odor = matches.iloc[0]
            key = odor.InChIKey
            if key not in self.response.index:
                raise ValueError(f"No consensus row for DoOR odour: {name}")
            info.update(label="DoOR consensus", chemical_name=odor.Name, CAS=odor.CAS, InChIKey=key)
            for i, unit in enumerate(self.units):
                if unit in self.response.columns and pd.notna(self.response.loc[key, unit]):
                    raw[i] = float(self.response.loc[key, unit])
                if status[i] != "mapped":
                    continue
                value, sfr = self.response.loc[key, unit], self.response.loc["SFR", unit]
                if pd.isna(value):
                    status[i] = "missing_odor_measurement"
                elif pd.isna(sfr):
                    raw[i] = value
                    status[i] = "missing_spontaneous_baseline"
                else:
                    raw[i] = value
                    values[i] = value - sfr
                    status[i] = "measured_zero_evoked_response" if values[i] == 0 else "measured_consensus"
        measured = np.isin(status, ["measured_consensus", "measured_zero_evoked_response"])
        info.update(status=status, raw_consensus_au=[float(v) if np.isfinite(v) else None for v in raw],
                    spontaneous_au=[float(v) if np.isfinite(v) else None for v in self.raw_spontaneous],
                    baseline_input_au=self.baseline.tolist(),
                    measured_named_types=int(measured.sum()), named_types=len(self.types),
                    named_type_coverage=float(measured.mean()) if len(measured) else 0.0,
                    measured_neurons=int(self.type_counts[measured].sum()), total_orn_neurons=len(self.root_ids),
                    neuron_coverage=float(self.type_counts[measured].sum() / len(self.root_ids)) if len(self.root_ids) else 0.0,
                    untyped_neurons=int(np.count_nonzero(self.type_codes < 0)))
        return OdourResponse(values, info)

    def map_rows(self, names=("OCT", "MCH")) -> pd.DataFrame:
        rows = []
        for name in names:
            response = self.responses(name)
            for i, ct in enumerate(self.types):
                rows.append({"odor": name, "chemical_name": response.metadata.get("chemical_name"),
                             "InChIKey": response.metadata.get("InChIKey"), "CAS": response.metadata.get("CAS"),
                             "orn_type": ct, "neuron_count": int(self.type_counts[i]), "glomerulus": ct[4:],
                             "door_unit": self.units[i], "raw_consensus_au": response.metadata["raw_consensus_au"][i],
                             "spontaneous_au": response.metadata["spontaneous_au"][i],
                             "baseline_input_au": float(self.baseline[i]), "evoked_delta_au": float(response.values[i]),
                             "status": response.metadata["status"][i], "mode": self.mode,
                             "baseline_note": BASELINE_NOTE, "label": response.metadata["label"],
                             "mapping_source": DOOR_BASE + "door_mappings.csv" if self.mode == "door" else "ASSUMPTION",
                             "response_source": DOOR_BASE + "door_response_matrix.csv" if self.mode == "door" else "ASSUMPTION"})
        return pd.DataFrame(rows)

    def per_neuron(self, type_values: np.ndarray) -> np.ndarray:
        """Expand to all normative ORNs in full-model row order; untyped stays zero."""
        values = np.asarray(type_values, dtype=float)
        if values.shape != (len(self.types),) or not np.isfinite(values).all():
            raise ValueError("One finite value per ordered ORN type is required")
        output = np.zeros(len(self.root_ids), dtype=float)
        known = self.type_codes >= 0
        output[known] = values[self.type_codes[known]]
        return output


def read_odour_parameters(root: Path) -> dict:
    config = yaml.safe_load((Path(root) / "config/neuromod.yaml").read_text())
    entries = config.get("parameters", {})
    values = {}
    for key in PARAMETER_NAMES:
        if key not in entries or not {"value", "unit", "source"}.issubset(entries[key]):
            raise ValueError(f"Missing odour parameter/provenance: {key}")
        values[key] = entries[key]["value"]
    return values


class OdourTransduction:
    """Eye-form adaptation/Naka–Rushton/passive filter; output is assumed ORN Hz.

    Algebra matches eye.Phototransduction with a different unit-bearing output
    scale. We do not pass Hz through its mV parameter or claim shared physiology.
    """
    def __init__(self, library: OdourLibrary, parameters: dict):
        self.library = library
        self.parameters = dict(parameters)
        self._deltas = {}
        for key in PARAMETER_NAMES[:-1]:
            if key not in parameters or not np.isfinite(parameters[key]):
                raise ValueError(f"Missing/nonfinite odour transduction parameter: {key}")
        for key in ("odour_max_rate_hz", "odour_adaptation_tau_ms", "odour_transduction_tau_ms", "odour_half_saturation"):
            if parameters[key] <= 0:
                raise ValueError(f"Odour parameter must be positive: {key}")
        if parameters["odour_adaptation_strength"] < 0:
            raise ValueError("Adaptation strength must be nonnegative")
        mode = parameters.get("odour_baseline_mode")
        if mode not in {"source_sfr", "zero"}:
            raise ValueError("odour_baseline_mode must be source_sfr or zero")
        self.baseline = library.baseline.copy() if mode == "source_sfr" else np.zeros(len(library.types))
        self.adaptation = self.baseline.copy()
        self.rates_hz = self._target(self.baseline, self.adaptation)
        self.metadata = {"units": "Hz", "source": "ASSUMPTION", "baseline_mode": mode,
                         "baseline_note": BASELINE_NOTE,
                         "zero_baseline_discards_inhibition": mode == "zero",
                         "initial_state": "equilibrium at selected baseline", "form_source": "flybrain.eye.Phototransduction"}

    def _target(self, activation, adaptation):
        p = self.parameters
        return p["odour_max_rate_hz"] * activation / (
            activation + p["odour_half_saturation"] + p["odour_adaptation_strength"] * adaptation)

    def step(self, name: str | None, intensity: float, dt_ms: float) -> np.ndarray:
        if not np.isfinite(dt_ms) or dt_ms <= 0 or not np.isfinite(intensity) or not 0 <= intensity <= 1:
            raise ValueError("Require positive finite dt and intensity in [0,1]")
        if name is not None and name not in self._deltas:
            self._deltas[name] = self.library.responses(name).values
        delta = np.zeros(len(self.library.types)) if name is None else self._deltas[name]
        activation = np.maximum(self.baseline + intensity * delta, 0)
        p = self.parameters
        self.adaptation += -np.expm1(-dt_ms / p["odour_adaptation_tau_ms"]) * (activation - self.adaptation)
        target = self._target(activation, self.adaptation)
        self.rates_hz += -np.expm1(-dt_ms / p["odour_transduction_tau_ms"]) * (target - self.rates_hz)
        return self.library.per_neuron(self.rates_hz)


class OdourEventSampler:
    """Seeded Poisson source-event counts per ORN per step, mean rate*dt/1000.

    Counts are afferent source events, not verified spike times from the LIF
    network. More than one event in a step is retained, not clipped to one.
    """
    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)

    def sample(self, rates_hz: np.ndarray, dt_ms: float) -> np.ndarray:
        values = np.asarray(rates_hz, dtype=float)
        if values.ndim != 1 or not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("Source rates must be a finite nonnegative vector")
        if not np.isfinite(dt_ms) or dt_ms <= 0:
            raise ValueError("Source-event dt must be positive and finite")
        return self.rng.poisson(values * dt_ms / 1000.0)


def build_odours(root: Path, *, download: bool = True, allow_synthetic: bool = False,
                 seed: int = 7, names=("OCT", "MCH")) -> dict:
    """Record source/mapping/transduction software evidence, never sparseness PASS."""
    root = Path(root).resolve()
    output = root / "build"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "validation_neuromod_odour.json"
    result = {"gate": "V-NM-ODOUR", "status": "FAIL", "checks": [], "baseline_note": BASELINE_NOTE,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "sparseness": {"status": "NOT-RUN", "reason": "Requires actual connectome network simulation"}}
    atomic_write_json(destination, result | {"failed_checks": ["validation_in_progress"]})
    def check(name, observed, expected):
        result["checks"].append({"name": name, "observed": observed, "expected": expected,
                                 "status": "PASS" if observed == expected else "FAIL"})
    try:
        result["config_hashes"] = {"neuromod.yaml": checksum(root / "config/neuromod.yaml")}
        result["implementation_hashes"] = {"src/flybrain/neuromod/odour.py": checksum(Path(__file__))}
        result["dependency_hashes"] = {"build/validation_neuromod_sources.json": checksum(output / "validation_neuromod_sources.json")}
        source = require_source_gate(root)
        for key in ("source_hashes", "source_stats", "base_artifact_hashes", "base_config_hashes"):
            result[key] = dict(source[key])
        library = OdourLibrary.from_root(root, download=download, allow_synthetic=allow_synthetic, seed=seed)
        for name, evidence in library.source_audit.items():
            relative = "neuromod/door/" + name
            result["source_hashes"][relative] = evidence["sha256"]
            result["source_stats"][relative] = evidence["source_stats"]
        p = read_odour_parameters(root)
        check("normative_named_orn_types", len(library.types), 53)
        check("normative_orn_neurons", len(library.root_ids), 2279)
        check("normative_untyped_orn_neurons", int(np.count_nonzero(library.type_codes < 0)), 4)
        rows = library.map_rows(names)
        check("finite_usable_evoked_deltas", bool(np.isfinite(rows.evoked_delta_au).all()), True)
        measured = rows.status.isin(["measured_consensus", "measured_zero_evoked_response"])
        if library.mode == "door":
            check("missing_responses_zero_evoked_delta", bool((rows.loc[~measured, "evoked_delta_au"] == 0).all()), True)
        check("unique_type_odor_pairs", bool(not rows.duplicated(["orn_type", "odor"]).any()), True)
        transduction = OdourTransduction(library, p)
        rates = transduction.step(names[0], 1.0, 1.0)
        check("finite_nonnegative_rates", bool(np.isfinite(rates).all() and (rates >= 0).all()), True)
        check("untyped_zero_rates", bool((rates[library.type_codes < 0] == 0).all()), True)
        one, two = OdourEventSampler(seed), OdourEventSampler(seed)
        check("source_event_seed_determinism", bool(np.array_equal(one.sample(rates, 1), two.sample(rates, 1))), True)
        rows.to_csv(output / "odour_orn_map.csv", index=False)
        coverage = {name: library.responses(name).metadata for name in names}
        atomic_write_json(output / "odour_coverage.json", {"baseline_note": BASELINE_NOTE, "odors": coverage})
        result.update(mode=library.mode, label="SYNTHETIC ODOUR" if library.mode == "synthetic" else "DoOR consensus",
                      coverage=coverage, source_files=library.source_audit, parameters=p,
                      limitations=[BASELINE_NOTE, "Consensus-to-Hz conversion and adaptation parameters are assumptions; no AL transform is added",
                                   SYNTHETIC_LIMIT if library.mode == "synthetic" else "Measured odour response coverage is partial"],
                      transduction=transduction.metadata,
                      artifact_hashes={name: checksum(output / name) for name in ("odour_orn_map.csv", "odour_coverage.json")})
        require_source_gate(root)
        for field, base in (("config_hashes", root / "config"), ("implementation_hashes", root),
                            ("dependency_hashes", root), ("source_hashes", root / "data/raw"),
                            ("base_artifact_hashes", output), ("base_config_hashes", root / "config")):
            for name, digest in result[field].items():
                check(f"unchanged_{field}_{name}", checksum(base / name), digest)
        for name, before in result["source_stats"].items():
            check(f"unchanged_source_signature_{name}", stat_signature(root / "data/raw" / name), before)
    except Exception as exc:
        check("odour_stage_execution", {"type": type(exc).__name__, "error": str(exc)}, "no errors")
    result["status"] = "PASS" if result["checks"] and all(c["status"] == "PASS" for c in result["checks"]) else "FAIL"
    result["failed_checks"] = [c["name"] for c in result["checks"] if c["status"] == "FAIL"]
    atomic_write_json(destination, result)
    return result
