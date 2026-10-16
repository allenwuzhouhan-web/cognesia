"""Finite training-only calibration decisions for the transmission campaign.

These functions do not open observations or execute models. A controller must
freeze their returned identities before it grants development outcome access.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import scipy
from scipy.stats import qmc

from ..paralimbo_upgrade.interfaces import identity

DEFAULTS = {"spike_weight": .275, "tau_membrane": 20., "tau_synapse": 5.,
            "graded_gain": .0001, "graded_tau_membrane": 20., "graded_tau_synapse": 5.}
BOUNDS = {"spike_weight": (.1375, .55), "tau_membrane": (10., 40.), "tau_synapse": (2.5, 10.),
          "graded_gain": (.00003, .0003), "graded_tau_membrane": (10., 40.),
          "graded_tau_synapse": (2.5, 10.)}
FIXED = {"graded_cap": .8}
PROPOSAL_COUNTS = (32, 16, 8)
INPUT_MULTIPLIERS = (1., .5, 2.)


def candidate_schedule(arm, proposal_count=32, active_parameters=None):
    """Default first, then one fixed unscrambled Sobol block; never expand.

Inactive dimensions remain at their source defaults. Arms with the same active
dimensions receive identical numerical proposals and the same proposal count.
The arm label changes provenance, not the sampling sequence.
"""
    if not isinstance(arm, str) or not arm:
        raise ValueError("A named arm is required")
    if type(proposal_count) is not int or proposal_count not in PROPOSAL_COUNTS:
        raise ValueError("Choose 32, 16, or 8 before observation access")
    active = sorted(DEFAULTS if active_parameters is None else active_parameters)
    if len(set(active)) != len(active) or not set(active) <= set(DEFAULTS):
        raise ValueError("Unknown or duplicate active parameter")
    proposals = [dict(DEFAULTS)]
    exponent = int(math.ceil(math.log2(proposal_count)))
    if active:
        for point in qmc.Sobol(len(active), scramble=False, seed=0).random_base2(exponent):
            row = dict(DEFAULTS)
            for name, value in zip(active, point):
                low, high = BOUNDS[name]
                row[name] = float(low + (high - low) * value)
            if row not in proposals:
                proposals.append(row)
            if len(proposals) == proposal_count:
                break
        if len(proposals) != proposal_count:
            raise ValueError("Frozen Sobol block did not provide enough unique proposals")
    result = {"schema": "transmission-calibration-schedule-v1", "arm": arm,
              "algorithm": "default_then_scipy_sobol_v1", "scramble": False, "seed": 0,
              "scipy_version": scipy.__version__, "requested_proposal_count": proposal_count,
              "proposal_count": len(proposals), "active_parameters": active,
              "inactive_parameters": sorted(set(DEFAULTS) - set(active)),
              "bounds": {k: list(BOUNDS[k]) for k in sorted(BOUNDS)}, "fixed": dict(FIXED),
              "proposals": proposals, "additional_searches": 0,
              "selection": "minimum_balanced_training_mse_then_first_proposal_index"}
    return result | {"schedule_sha256": identity(result)}


def validate_schedule(schedule):
    expected = candidate_schedule(schedule["arm"], schedule["requested_proposal_count"],
                                  schedule["active_parameters"])
    if schedule != expected:
        raise ValueError("Calibration schedule changed after freeze")
    return expected


def sensitivity_pruning(deltas, refinement_error_mv=0.):
    """Keep a knob only if its maximum response change exceeds numerical error.

``deltas`` is parameter -> maximum absolute mV change, or arm -> that mapping.
Use development input-only perturbations; this function never accepts outcomes.
Failure/NaN sensitivities are refused, never interpreted as inactive knobs.
"""
    if not math.isfinite(refinement_error_mv) or refinement_error_mv < 0:
        raise ValueError("Finite nonnegative measured refinement error required")
    maps = list(deltas.values()) if deltas and all(isinstance(x, dict) for x in deltas.values()) else [deltas]
    if not maps or any(set(m) != set(DEFAULTS) for m in maps):
        raise ValueError("Sensitivity must account for every registered parameter")
    maximum = {}
    for name in DEFAULTS:
        values = [float(m[name]) for m in maps]
        if not np.isfinite(values).all() or min(values) < 0:
            raise ValueError("Failed sensitivities cannot be pruned as zero")
        maximum[name] = max(values)
    threshold = max(.001, float(refinement_error_mv))
    body = {"schema": "transmission-sensitivity-v1", "tolerance_mv": threshold,
            "parameter_max_change_mv": maximum,
            "active_parameters": sorted(k for k, v in maximum.items() if v > threshold),
            "inactive_parameters": sorted(k for k, v in maximum.items() if v <= threshold),
            "rule": "union across arms; strict change greater than max(refinement_error,0.001mV)"}
    return body | {"sensitivity_sha256": identity(body)}


def _training_row(row, expected_training_case_ids=None):
    if row.get("split", "development") != "development":
        raise ValueError("Candidate selection may use development outcomes only")
    if expected_training_case_ids is not None:
        actual = row.get("case_ids", [])
        if len(actual) != len(set(actual)) or not set(actual) <= set(expected_training_case_ids):
            raise ValueError("Training case inventory contaminated or duplicated")
        if set(actual) != set(expected_training_case_ids):
            return False
    value = row.get("balanced_training_mse")
    return (row.get("status") in {"PASS", "COMPLETE", "SCORED"}
            and isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def select_candidate(rows, expected_training_case_ids=None):
    """Select finite successful training scores; retain every failure in result."""
    rows = [dict(r) for r in rows]
    for row in rows:
        value = row.get("balanced_training_mse")
        if isinstance(value, (int, float)) and not math.isfinite(value):
            row.update(balanced_training_mse=None, status="FAILED",
                       failure_reason="nonfinite_training_score")
    indices = [r["proposal_index"] for r in rows]
    if not rows or len(indices) != len(set(indices)) or any(type(i) is not int or i < 0 for i in indices):
        raise ValueError("Unique nonnegative proposal indices required")
    usable = [r for r in rows if _training_row(r, expected_training_case_ids)]
    winner = min(usable, key=lambda r: (r["balanced_training_mse"], r["proposal_index"])) if usable else None
    body = {"status": "SELECTED" if winner else "NO_VALID_CANDIDATE", "selected": winner,
            "attempts": rows, "failed_proposal_indices": [r["proposal_index"] for r in rows if r not in usable],
            "selection_uses": "development_only", "tie_break": "first_proposal_index"}
    return body | {"selection_sha256": identity(body)}


def select_shared_input_multiplier(rows, arms=("banc", "paralimbo"), expected_training_case_ids=None):
    """Choose one input scale by equal-arm mean training MSE, never per arm.

Rows contain multiplier, arm, proposal_index, status and balanced_training_mse.
A missing/failed arm disqualifies the whole multiplier, and remains visible.
"""
    if len(arms) != 2 or len(set(arms)) != 2:
        raise ValueError("Exactly two distinct paired arms required")
    grouped = defaultdict(dict)
    all_rows = [dict(r) for r in rows]
    for row in all_rows:
        scale = float(row["multiplier"])
        if scale not in INPUT_MULTIPLIERS or row["arm"] not in arms:
            raise ValueError("Input multiplier must be one of frozen {1,0.5,2}")
        if row.get('proposal_index') != INPUT_MULTIPLIERS.index(scale):
            raise ValueError('Input multiplier index differs from frozen default-first order')
        value = row.get('balanced_training_mse')
        if isinstance(value, (int,float)) and not math.isfinite(value):
            row.update(balanced_training_mse=None,status='FAILED',failure_reason='nonfinite_training_score')
        if row["arm"] in grouped[scale]:
            raise ValueError("Duplicate scale/arm calibration result")
        _training_row(row, expected_training_case_ids)
        grouped[scale][row["arm"]] = row
    candidates = []
    for scale, paired in grouped.items():
        indices = {r["proposal_index"] for r in paired.values()}
        if len(indices) != 1:
            raise ValueError("Both arms must receive the same indexed input proposal")
        ok = set(paired) == set(arms) and all(_training_row(r, expected_training_case_ids) for r in paired.values())
        candidates.append({"proposal_index": next(iter(indices)), "multiplier": scale,
                           "balanced_training_mse": math.fsum(r["balanced_training_mse"] for r in paired.values()) / 2 if ok else None,
                           "status": "PASS" if ok else "FAILED", "split": "development",
                           "case_ids": list(expected_training_case_ids or [])})
    result = select_candidate(candidates, expected_training_case_ids)
    result["arm_results"] = all_rows
    result["shared_multiplier"] = result["selected"]["multiplier"] if result["selected"] else None
    result["selection_sha256"] = identity({k: v for k, v in result.items() if k != "selection_sha256"})
    return result
