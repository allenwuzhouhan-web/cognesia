"""Area-00 contracts. Version changes require coordinator review.

JSON artifacts use these explicit identities; fixtures are never native evidence.
Times are milliseconds, membrane drive is normalized mV, observations retain units.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from typing import Any, Mapping

INTERFACE_VERSION = "1.0.0"
SCHEMA_VERSION = 1
EVIDENCE_CLASSES = frozenset({"measured", "independently_supported", "transferred", "development_estimated", "assumed", "unsupported", "synthetic"})
PREDICTION_STATUSES = frozenset({"predicted", "unsupported", "failed", "numerically_unqualified"})


def canonical_json(value: Any) -> str:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(value: Any) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty")


def _finite(value: float, name: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")


class Contract:
    def to_dict(self) -> dict[str, Any]:
        return {"interface_version": INTERFACE_VERSION, **asdict(self)}

    @property
    def digest(self) -> str:
        return identity(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]):
        data = dict(payload)
        if data.pop("interface_version", None) != INTERFACE_VERSION:
            raise ValueError("incompatible interface_version")
        return cls(**data)


@dataclass(frozen=True)
class Registration(Contract):
    registration_id: str
    model_id: str
    model_sha256: str
    source_id: str
    source_sha256: str
    root_ids: tuple[str, ...]
    evidence_class: str
    spatial_correspondence: Mapping[str, Any] = field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    scope: str = "fixture"  # fixture, restricted_hypothesis, supported_native
    uncertainty: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("registration_id", "model_id", "model_sha256", "source_id", "source_sha256"):
            _nonempty(getattr(self, name), name)
        object.__setattr__(self, "root_ids", tuple(str(x) for x in self.root_ids))
        if not isinstance(self.assumptions, (tuple, list)) or any(
            not isinstance(item, str) or not item.strip() for item in self.assumptions
        ):
            raise ValueError("assumptions must be a sequence of nonblank strings")
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        if not self.root_ids or len(set(self.root_ids)) != len(self.root_ids):
            raise ValueError("root_ids must be nonempty and unique")
        if self.evidence_class not in EVIDENCE_CLASSES:
            raise ValueError("unknown evidence_class")
        if self.scope not in {"fixture", "restricted_hypothesis", "supported_native"}:
            raise ValueError("unknown scope")
        if self.scope == "supported_native" and self.evidence_class not in {"measured", "independently_supported"}:
            raise ValueError("supported_native requires supported evidence")
        if self.scope == "restricted_hypothesis" and not self.assumptions:
            raise ValueError("restricted_hypothesis requires explicit assumptions")


@dataclass(frozen=True)
class StimulusInput(Contract):
    stimulus_id: str
    source_sha256: str
    registration_id: str
    time_ms: tuple[float, ...]
    target_root_ids: tuple[str, ...]
    drive_mv: tuple[tuple[float, ...], ...]
    modality: str = "synthetic"
    cursor: int = 0
    input_provenance: Mapping[str, Any] = field(default_factory=dict)
    units: str = "normalized_mV"

    def __post_init__(self):
        for name in ("stimulus_id", "source_sha256", "registration_id"):
            _nonempty(getattr(self, name), name)
        object.__setattr__(self, "time_ms", tuple(float(x) for x in self.time_ms))
        object.__setattr__(self, "target_root_ids", tuple(str(x) for x in self.target_root_ids))
        object.__setattr__(self, "drive_mv", tuple(tuple(float(x) for x in row) for row in self.drive_mv))
        if self.units != "normalized_mV":
            raise ValueError("membrane drive must be normalized_mV; register physical conversion upstream")
        if not self.time_ms or any(not math.isfinite(t) or t < 0 for t in self.time_ms) or any(b <= a for a, b in zip(self.time_ms, self.time_ms[1:])):
            raise ValueError("time_ms must be finite, nonnegative and strictly increasing")
        if not self.target_root_ids or len(set(self.target_root_ids)) != len(self.target_root_ids):
            raise ValueError("targets must be unique and nonempty")
        if len(self.drive_mv) != len(self.time_ms) or any(len(row) != len(self.target_root_ids) for row in self.drive_mv):
            raise ValueError("drive shape must be time by target")
        if any(not math.isfinite(x) for row in self.drive_mv for x in row):
            raise ValueError("drive must be finite")
        if not isinstance(self.cursor, int) or not 0 <= self.cursor <= len(self.time_ms):
            raise ValueError("cursor outside input grid")


@dataclass(frozen=True)
class DynamicsVariant(Contract):
    variant_id: str
    equation_id: str
    parameters: Mapping[str, float]
    parameter_bounds: Mapping[str, tuple[float, float]]
    active_mechanisms: tuple[str, ...] = ()
    ablation_of: str | None = None
    assumptions: tuple[str, ...] = ()

    def __post_init__(self):
        _nonempty(self.variant_id, "variant_id")
        _nonempty(self.equation_id, "equation_id")
        if set(self.parameters) != set(self.parameter_bounds):
            raise ValueError("every parameter requires declared bounds")
        for name, value in self.parameters.items():
            lo, hi = self.parameter_bounds[name]
            for x in (value, lo, hi):
                _finite(x, name)
            if not lo <= value <= hi:
                raise ValueError(f"parameter {name} outside bounds")
        if self.ablation_of == self.variant_id:
            raise ValueError("ablation must have separate identity")


@dataclass(frozen=True)
class ObservationSpec(Contract):
    observation_id: str
    units: str
    root_ids: tuple[str, ...]
    state_variable: str = "voltage_mv"
    filter_spec: Mapping[str, Any] = field(default_factory=lambda: {"kind": "none"})
    baseline_spec: Mapping[str, Any] = field(default_factory=lambda: {"kind": "none"})
    repeat_aggregation: str = "none"
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        _nonempty(self.observation_id, "observation_id")
        if self.units not in {"mV", "deltaF/F_percentage_points", "normalized_mV"}:
            raise ValueError("unsupported observation units")
        if not self.root_ids or len(set(self.root_ids)) != len(self.root_ids):
            raise ValueError("observation roots must be nonempty and unique")


@dataclass(frozen=True)
class PredictionRecord(Contract):
    case_id: str
    status: str
    model_id: str
    input_id: str
    runtime_id: str
    variant_id: str
    observation_id: str
    trace_path: str | None = None
    trace_sha256: str | None = None
    failure_reason: str | None = None
    numerical_qualification: Mapping[str, Any] = field(default_factory=dict)
    scope: str = "fixture"
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("case_id", "model_id", "input_id", "runtime_id", "variant_id", "observation_id"):
            _nonempty(getattr(self, name), name)
        if self.status not in PREDICTION_STATUSES:
            raise ValueError("unknown prediction status")
        if self.status == "predicted" and (not self.trace_path or not self.trace_sha256):
            raise ValueError("predicted record requires trace identity")
        if self.status != "predicted" and not self.failure_reason:
            raise ValueError("non-predicted record requires failure_reason")


@dataclass(frozen=True)
class EvaluationSpec(Contract):
    evaluation_id: str
    case_ids: tuple[str, ...]
    training_observation_ids: tuple[str, ...]
    evaluation_observation_ids: tuple[str, ...]
    metrics: Mapping[str, Any]
    margins: Mapping[str, float]
    units: str = "mV"
    retrospective: bool = True
    seal_before_scoring: bool = True
    max_free_parameters: int = 6
    max_proposals: int = 32
    failure_policy: str = "retain_all_declared_cases"
    assumptions: tuple[str, ...] = ()

    def __post_init__(self):
        _nonempty(self.evaluation_id, "evaluation_id")
        if not self.case_ids or len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("all declared case identities must be unique")
        if set(self.training_observation_ids) & set(self.evaluation_observation_ids):
            raise ValueError("training and evaluation observations overlap")
        if not self.seal_before_scoring:
            raise ValueError("prediction sealing is mandatory")
        if not 0 <= self.max_free_parameters <= 6 or not 1 <= self.max_proposals <= 32:
            raise ValueError("calibration exceeds inherited finite schedule")
        if self.failure_policy != "retain_all_declared_cases":
            raise ValueError("coverage cannot be reduced")
        for name, value in self.margins.items():
            _finite(value, name)
            if value < 0:
                raise ValueError("margins must be nonnegative")
