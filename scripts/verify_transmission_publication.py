#!/usr/bin/env python3
"""Offline audit of the finite transmission campaign's public evidence.

Requires only Python and NumPy. Does not import the simulator, run a model,
select a new candidate, access the network, or modify evidence. Recomputes
scores, development decisions and refinement errors from retained traces.
Hashes establish consistency with the included inventory, not an external
signature. Exported traces cannot prove the hidden whole-brain state or replay
its checkpoints; source excerpts are not a complete reproducible environment.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ARMS = ("banc", "paralimbo")
SOURCE_ID = "d8e027ebb3b71bfb32fbaa43b958ae641a103010f06f90d8b7a37012274b0671"
PROTOCOL_ID = "3b14457a56e6aab653c4cf60cef122b971584d6a035269bcdf5b44eef30b4550"
DEFAULTS = dict(spike_weight=.275, tau_membrane=20., tau_synapse=5.,
                graded_gain=.0001, graded_tau_membrane=20., graded_tau_synapse=5.)
BOUNDS = dict(spike_weight=[.1375, .55], tau_membrane=[10., 40.], tau_synapse=[2.5, 10.],
              graded_gain=[.00003, .0003], graded_tau_membrane=[10., 40.], graded_tau_synapse=[2.5, 10.])
MODELS = {"banc": ["banc-888", "60d220182e6f65b98a78b008c764bb13b802d1dc5b85a798cc9028a6557665de"],
          "paralimbo": ["paralimbo-visual-graded-v1", "229f9970e0b67cfa14658142dbc3adae8614d49887cd131521bf02e4d86cd884"]}
TRACE_NAMES = {"observation_time_ms", "observation_values_mv", "refined_observation_values_mv"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(value, historical=False):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     allow_nan=False, ensure_ascii=not historical).encode()
    return sha(raw + (b"\n" if historical else b""))


def sealed(document, field, historical=False):
    require(document.get(field) == identity({k: v for k, v in document.items() if k != field}, historical),
            f"Invalid {field}")


def safe_file(folder, relative):
    p = Path(relative)
    require(not p.is_absolute() and ".." not in p.parts, f"Unsafe relative path: {relative}")
    full = folder / p
    require(full.is_file() and not full.is_symlink() and full.resolve().is_relative_to(folder.resolve()),
            f"Missing or unsafe artifact: {relative}")
    return full


def read_json(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, f"Duplicate JSON key: {k}")
            result[k] = v
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Nonfinite JSON: {value}")))


def same(actual, expected, label):
    """Strict inventory comparison with a tiny cross-platform float allowance."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), f"{label}: fields differ")
        for key in expected:
            same(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), f"{label}: length differs")
        for index, (a, b) in enumerate(zip(actual, expected)):
            same(a, b, f"{label}[{index}]")
    elif isinstance(expected, float):
        require(type(actual) in (int, float) and math.isfinite(actual)
                and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), f"{label}: numeric mismatch")
    else:
        require(type(actual) is type(expected) and actual == expected, f"{label}: value differs")


def load_arrays(path):
    with np.load(path, allow_pickle=False) as z:
        require(len(z.files) == len(set(z.files)), "Duplicate NPZ members")
        arrays = {k: z[k].copy() for k in z.files}
    require(all(a.dtype.kind in "fiu" and np.isfinite(a).all() for a in arrays.values()), "Nonfinite/nonnumeric trace")
    return arrays


def valid_grid(time):
    require(time.ndim == 1 and time.size > 0 and np.all(np.diff(time) > 0)
            and np.isfinite(time).all(), "Invalid physical time grid")


def verify_inventory(folder):
    provenance = read_json(safe_file(folder, "public-provenance.json"))
    require(provenance["campaign_source_identity"] == SOURCE_ID, "Publication source identity changed")
    rows = provenance["files"]
    entries = {}
    for row in rows:
        relative = row["path"]
        require(relative not in entries, "Duplicate public inventory path")
        entries[relative] = row
        full = safe_file(folder, relative)
        require(sha(full.read_bytes()) == row["public_sha256"], f"Public artifact hash mismatch: {relative}")
        require(full.stat().st_size == row["bytes"], f"Public artifact size mismatch: {relative}")
        if row["original_path"] is None:
            require(row["original_sha256"] is None and row["transformation"] in {"new publication document", "new publication documentation"}
                    and not relative.startswith(("evidence/", "source/")), "Evidence cannot be a new publication document")
            continue
        original = row["original_path"]
        require(isinstance(original, str) and not Path(original).is_absolute() and ".." not in Path(original).parts,
                "Original provenance must use relative names")
        require(isinstance(row["changed_fields"], list), "Missing transformation fields")
        require(len(row["original_sha256"]) == 64, "Missing original identity")
        if row["original_sha256"] == row["public_sha256"]:
            require(not row["changed_fields"], "Unchanged bytes have changed fields")
        else:
            require(bool(row["transformation"]) and bool(row["changed_fields"]), "Undocumented derivative")
    excluded = provenance.get("excluded_files", [])
    require(len(excluded) == len(set(excluded)) and all(not p.startswith(("evidence/", "source/"))
            and not Path(p).is_absolute() and ".." not in Path(p).parts for p in excluded), "Invalid inventory exclusions")
    actual_files = {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()}
    require(actual_files == set(entries) | set(excluded), "Uninventoried publication file or missing exclusion")
    evidence = {str(p.relative_to(folder)) for p in (folder / "evidence").rglob("*") if p.is_file()}
    require(evidence <= set(entries), "Uninventoried evidence file")
    source = read_json(safe_file(folder, "source-inventory.json"))
    require(source["campaign_source_identity"] == SOURCE_ID, "Source inventory identity changed")
    source_paths = set()
    for row in source["files"]:
        relative = row["path"]
        require(relative.startswith("source/") and relative not in source_paths, "Invalid source inventory")
        source_paths.add(relative)
        require(relative in entries, "Source missing from public provenance")
        for field in ("original_sha256", "public_sha256", "transformation", "changed_fields"):
            require(row[field] == entries[relative][field], "Source inventories disagree")
    actual_source = {str(p.relative_to(folder)) for p in (folder / "source").rglob("*") if p.is_file()}
    require(actual_source == source_paths and source_paths, "Source file inventory differs")
    return entries


def verify_traces(folder, provenance=None):
    inventory = read_json(safe_file(folder, "trace-inventory.json"))
    traces = {}
    for row in inventory["files"]:
        original = row["original_sha256"]
        require(original not in traces and len(original) == 64, "Duplicate native trace identity")
        arrays = load_arrays(safe_file(folder, row["path"]))
        require(set(arrays) == set(row["arrays"]) == TRACE_NAMES, "Unexpected projected native arrays")
        for name, a in arrays.items():
            receipt = row["arrays"][name]
            require(sha(a.tobytes(order="C")) == receipt["sha256"], "Projected array hash mismatch")
            require(str(a.dtype) == receipt["dtype"] and list(a.shape) == receipt["shape"], "Projected array shape/dtype mismatch")
        valid_grid(arrays["observation_time_ms"])
        require(all(a.shape == arrays["observation_time_ms"].shape for a in arrays.values()), "Projected trace length mismatch")
        require(type(row["original_bytes"]) is int and row["original_bytes"] > 0, "Missing original trace size")
        if provenance is not None:
            require(provenance[row["path"]]["original_sha256"] == original, "Trace source provenance differs")
        traces[original] = {"arrays": arrays, "original_bytes": row["original_bytes"]}
    require(bool(traces), "Missing projected native traces")
    return traces


def observations(folder, protocol):
    native = protocol["native_contract"]
    cases = {c["case_id"]: c for c in native["cases"]}
    require(len(cases) == 9 and len(native["cases"]) == 9, "Nine unique cases required")
    dev, evaluation = protocol["development_case_ids"], protocol["evaluation_case_ids"]
    require(len(dev) == len(set(dev)) == 5 and len(evaluation) == len(set(evaluation)) == 4,
            "Frozen five/four split changed")
    require(set(dev).isdisjoint(evaluation) and set(dev + evaluation) == set(cases), "Development/evaluation overlap")
    require(all(cases[c]["family"] == "flash" for c in dev)
            and all(cases[c]["family"] == "moving" for c in evaluation), "Case families cross split")
    require(native["scoring_observation"]["trial_policy"] == "first_eligible_single_trial", "Trial policy changed")
    result = {}
    input_ids = set()
    for split, ids in (("development", dev), ("evaluation", evaluation)):
        manifest = read_json(safe_file(folder, f"evidence/observations/{split}/manifest.json"))
        sealed(manifest, "retention_sha256")
        require(manifest["protocol_sha256"] == protocol["protocol_sha256"] and manifest["split"] == split,
                "Observation protocol/split mismatch")
        require(set(manifest["cases"]) == set(ids), "Observation split inventory differs")
        if split == "evaluation":
            primary = read_json(safe_file(folder, "evidence/predictions/prediction-seal.json"))
            require(manifest["access_gate_sha256"] == primary["prediction_seal_sha256"], "Evaluation access gate differs")
        for cid in ids:
            c = cases[cid]
            meta_path = safe_file(folder, f"evidence/observations/{split}/{cid}.json")
            response_path = safe_file(folder, f"evidence/observations/{split}/{cid}.npz")
            meta = read_json(meta_path)
            sealed(meta, "observation_identity", historical=True)
            frozen = protocol["observation_sources"][cid]
            for kind, path, digest_key in (("metadata", meta_path, "metadata_sha256"), ("response", response_path, "response_sha256")):
                receipt = manifest["cases"][cid][kind]
                require(receipt["sha256"] == frozen[digest_key] == sha(path.read_bytes()), "Observation source identity mismatch")
                require(receipt["bytes"] == path.stat().st_size, "Observation byte length mismatch")
            require(meta["case_id"] == cid and meta["source_trace_sha256"] == c["source_trace_sha256"]
                    and meta["observation_identity"] == frozen["observation_identity"]
                    and meta["sha256"] == frozen["response_sha256"], "Historical observation identity mismatch")
            input_ids.add(meta["input_identity"])
            a = load_arrays(response_path)
            verify_observation_arrays(a, c)
            selected = min(c["eligible_trial_indices"])
            expected = [f"trial_{selected}"]
            require(native["scoring_observation"]["selected_trial_ids_by_case"][cid] == expected
                    and native["trial_ids_by_case"][cid] == expected, "Selected trial is not the frozen minimum eligible trial")
            require(meta["eligible_trial_indices"] == c["eligible_trial_indices"], "Metadata trials differ")
            row = int(np.flatnonzero(a["eligible_trial_indices"] == selected)[0])
            result[cid] = (a["time_ms"], a["eligible_trials_mv"][row])
    require(len(input_ids) == 1, "Observation inputs disagree")
    return cases, result


def verify_observation_arrays(a, case):
    require(set(a) == {"time_ms", "observed_mv", "repeat_sd_mv", "eligible_trials_mv", "eligible_trial_indices"}, "Observation array inventory differs")
    t = a["time_ms"]
    valid_grid(t)
    indices = a["eligible_trial_indices"]
    require(np.array_equal(indices, case["eligible_trial_indices"]) and len(indices) == len(set(indices.tolist())), "Observation eligible trials differ")
    repeats = a["eligible_trials_mv"]
    require(repeats.shape == (case["eligible_repeats"], len(t)) and len(indices) == case["eligible_repeats"], "Observation repeat shape differs")
    require(np.array_equal(a["observed_mv"], repeats.mean(axis=0)), "Observation mean differs from repeats")
    require(np.array_equal(a["repeat_sd_mv"], repeats.std(axis=0, ddof=1)), "Observation SD differs from repeats")
    mask = (t >= -200) & (t < -20)
    require(mask.any() and np.max(np.abs(repeats[:, mask].mean(axis=1))) <= 1e-8, "Observation baseline differs")


def native_trace(receipt, traces):
    require(receipt["status"] == "PASS" and receipt["population"] == 175401, "Native receipt not full-population PASS")
    n = receipt["numerics"]
    require(n["pass"] is True and n["endpoint_finite"] is True and n["simulated_population"] == 175401
            and n["first_failure_step"] is None, "Native numerical receipt failed")
    require(all(n[k] == 0 for k in ("clamps", "invalid_delayed_spikes", "nonfinite_release_updates",
                                   "nonfinite_synaptic_updates", "nonfinite_voltage_updates")), "Nonzero numerical guard")
    key = receipt["arrays"]["sha256"]
    require(key in traces, "Missing native trace projection")
    require(receipt["arrays"]["bytes"] == traces[key]["original_bytes"], "Original native trace size differs")
    a = traces[key]["arrays"]
    measured = float(np.max(np.abs(a["observation_values_mv"] - a["refined_observation_values_mv"])))
    same(receipt["observation_refinement_max_abs_mv"], measured, "Observation refinement")
    return a


def verify_training_row(row, dev, obs, traces):
    require(row["split"] == "development" and row["case_ids"] == dev, "Calibration crosses development split")
    require(set(row["predictions"]) == set(dev), "Incomplete development prediction inventory")
    errors = []
    failures = []
    for cid in dev:
        receipt = row["predictions"][cid]
        if receipt["status"] != "PASS":
            failures.append(cid)
            continue
        a = native_trace(receipt, traces)
        t, y = obs[cid]
        require(np.array_equal(a["observation_time_ms"], t), "Development grid differs")
        errors.append(float(np.mean((a["observation_values_mv"][t >= 0] - y[t >= 0]) ** 2)))
    if failures:
        require(row["status"] == "FAILED" and row["balanced_training_mse"] is None, "Failed candidate promoted")
    else:
        require(row["status"] == "PASS", "Complete training result changed")
        same(row["balanced_training_mse"], math.fsum(errors) / len(errors), "Development objective")


def verify_selection(selection, dev, *, projected=False):
    if projected:
        # Public projection changes only host paths; the original identity is provenance.
        require(selection["selection_sha256"] == "a4a2c64b783a5e37737fce1e5517d08f03330ea386c83a79c71f58b2408fafc1", "Original input selection identity changed")
    else:
        sealed(selection, "selection_sha256")
    rows = selection["attempts"]
    indices = [r["proposal_index"] for r in rows]
    require(len(indices) == len(set(indices)), "Duplicate proposals")
    valid = []
    for r in rows:
        require(r["split"] == "development" and r["case_ids"] == dev, "Selection crosses development split")
        if r["status"] == "PASS":
            require(type(r["balanced_training_mse"]) in (float, int) and math.isfinite(r["balanced_training_mse"])
                    and r["balanced_training_mse"] >= 0, "Invalid selection objective")
            valid.append(r)
    winner = min(valid, key=lambda r: (r["balanced_training_mse"], r["proposal_index"])) if valid else None
    same(selection["selected"], winner, "First minimum development selection")
    require(selection["status"] == ("SELECTED" if winner else "NO_VALID_CANDIDATE")
            and selection["selection_uses"] == "development_only" and selection["tie_break"] == "first_proposal_index", "Selection policy changed")
    require(selection["failed_proposal_indices"] == [r["proposal_index"] for r in rows if r not in valid], "Hidden failed proposals")


def verify_calibration(folder, protocol, obs, traces):
    dev = protocol["development_case_ids"]
    schedules = read_json(safe_file(folder, "evidence/calibration-schedules.json"))
    selections = read_json(safe_file(folder, "evidence/selected-candidates.json"))
    require(set(schedules) == set(selections) == set(ARMS), "Unequal arm inventory")
    for arm in ARMS:
        s = schedules[arm]
        sealed(s, "schedule_sha256")
        require(s["arm"] == arm and s["proposal_count"] == s["requested_proposal_count"] == len(s["proposals"]) == 8,
                "Equal eight-proposal opportunity changed")
        require(s["proposals"][0] == DEFAULTS and s["bounds"] == BOUNDS and s["fixed"] == {"graded_cap": .8}, "Defaults, bounds or cap changed")
        require(s["active_parameters"] == sorted(DEFAULTS) and s["inactive_parameters"] == [], "Active parameters changed")
        require(s["algorithm"] == "default_then_scipy_sobol_v1" and s["scramble"] is False
                and s["seed"] == 0 and s["additional_searches"] == 0, "Search protocol changed")
        # First seven points of the fixed six-dimensional unscrambled Sobol block.
        # Keeping this finite coefficient table makes verification NumPy-only.
        points = [(0.,)*6, (.5,)*6, (.75,.25,.25,.25,.75,.75), (.25,.75,.75,.75,.25,.25),
                  (.375,.375,.625,.875,.375,.125), (.875,.875,.125,.375,.875,.625),
                  (.625,.125,.875,.625,.625,.875)]
        expected_proposals = [dict(DEFAULTS)] + [
            {k: BOUNDS[k][0] + (BOUNDS[k][1] - BOUNDS[k][0]) * point[i]
             for i, k in enumerate(sorted(BOUNDS))} for point in points]
        same(s["proposals"], expected_proposals, "Frozen Sobol proposals")
        for proposal in s["proposals"]:
            require(set(proposal) == set(DEFAULTS), "Parameter inventory changed")
            require(all(BOUNDS[k][0] <= v <= BOUNDS[k][1] for k, v in proposal.items()), "Out of bounds proposal")
        selection = selections[arm]
        verify_selection(selection, dev)
        require(len(selection["attempts"]) == 8 and [r["proposal_index"] for r in selection["attempts"]] == list(range(8)), "Missing or reordered proposals")
        require(read_json(safe_file(folder, f"evidence/calibration/{arm}.json"))["attempts"] == selection["attempts"], "Calibration ledger differs")
        for row in selection["attempts"]:
            require(row["parameters"] == s["proposals"][row["proposal_index"]], "Candidate parameters differ from frozen proposal")
            verify_training_row(row, dev, obs, traces)
    require(schedules["banc"]["proposals"] == schedules["paralimbo"]["proposals"], "Arms received different proposals")
    inputs = read_json(safe_file(folder, "evidence/input-selection.json"))
    verify_selection(inputs, dev, projected=True)
    rows = inputs["arm_results"]
    require(len(rows) == 6, "Incomplete shared input comparison")
    keys = [(r["arm"], r["multiplier"]) for r in rows]
    require(len(keys) == len(set(keys)) and set(keys) == {(a, m) for a in ARMS for m in (1., .5, 2.)}, "Shared input arm inventory differs")
    require([r["multiplier"] for r in inputs["attempts"]] == [1., .5, 2.], "Input proposal order differs")
    for row in rows:
        verify_training_row(row, dev, obs, traces)
        require(row["proposal_index"] == [1., .5, 2.].index(row["multiplier"]), "Input proposal index changed")
    for attempt in inputs["attempts"]:
        paired = [r for r in rows if r["multiplier"] == attempt["multiplier"]]
        if all(r["status"] == "PASS" for r in paired):
            same(attempt["balanced_training_mse"], math.fsum(r["balanced_training_mse"] for r in paired) / 2., "Equal-arm input error")
            require(attempt["status"] == "PASS", "Input candidate status changed")
        else:
            require(attempt["status"] == "FAILED" and attempt["balanced_training_mse"] is None, "Failed input candidate promoted")
    require(inputs["shared_multiplier"] == inputs["selected"]["multiplier"], "Shared multiplier changed")
    for arm in ARMS:
        default_input = next(r for r in rows if r["arm"] == arm and r["multiplier"] == inputs["shared_multiplier"])
        require(default_input["predictions"] == selections[arm]["attempts"][0]["predictions"], "Input choice did not reuse intrinsic defaults")
    return selections, inputs["shared_multiplier"]


def verify_prediction_seal(folder, directory, protocol, selections, multiplier, traces):
    seal = read_json(safe_file(folder, f"evidence/{directory}/prediction-seal.json"))
    sealed(seal, "prediction_seal_sha256")
    require(seal["protocol_sha256"] == PROTOCOL_ID and seal["evaluation_outcomes_read"] is False, "Prediction seal protocol/gate changed")
    ids = protocol["development_case_ids"] + protocol["evaluation_case_ids"]
    expected = {a + ":" + c for a in ARMS for c in ids}
    records = seal["records"]
    keys = [r["key"] for r in records]
    require(len(keys) == len(set(keys)) == len(expected) and set(keys) == expected, "Missing or duplicate prediction rows, including failures")
    require(len(seal["expected_keys"]) == len(expected) and set(seal["expected_keys"]) == expected, "Expected prediction inventory changed")
    predictions = {}
    for r in records:
        arm, cid = r["arm"], r["case_id"]
        require(r["key"] == arm + ":" + cid and arm in ARMS and cid in ids, "Prediction key differs")
        require(r["parameters"] == selections[arm]["selected"]["parameters"]
                and r["selection_sha256"] == selections[arm]["selection_sha256"]
                and r["model"] == MODELS[arm] and r["input_multiplier"] == multiplier, "Prediction parameters/model/input selection changed")
        require(r["sensitivity_id"] == ("primary" if directory == "predictions" else "alternate_vertical_subtype"), "Correspondence changed")
        require(len(r["results"]) == 3, "Missing numerical refinement receipts")
        require([x["dt_ms"] for x in r["results"]] == [.1, .05, .1], "Refinement timesteps changed")
        coarse, fine, optical = [native_trace(x, traces) for x in r["results"]]
        require(np.array_equal(coarse["observation_time_ms"], fine["observation_time_ms"])
                and np.array_equal(coarse["observation_time_ms"], optical["observation_time_ms"]), "Refinement grids differ")
        qualification = dict(timestep_max_abs_mv=float(np.max(np.abs(coarse["observation_values_mv"] - fine["observation_values_mv"]))),
                             optical_max_abs_mv=float(np.max(np.abs(coarse["observation_values_mv"] - optical["observation_values_mv"]))),
                             observation_max_abs_mv=float(np.max(np.abs(coarse["observation_values_mv"] - coarse["refined_observation_values_mv"]))))
        same(r["qualification"], qualification, "Numerical qualification")
        passed = max(qualification.values()) <= .001
        require(r["status"] == ("PREDICTED" if passed else "FAILED"), "Qualification failure promoted or successful prediction removed")
        if not passed:
            require(r["reason"] == "Numerical refinement exceeded 0.001mV" and "path" not in r, "Failure reason/artifact changed")
            continue
        path = safe_file(folder, f"evidence/{directory}/{r['path']}")
        require(sha(path.read_bytes()) == r["sha256"], "Prediction trace changed")
        a = load_arrays(path)
        require(set(a) == {"time_ms", "values_mv"}, "Unexpected prediction members")
        require(np.array_equal(a["time_ms"], coarse["observation_time_ms"])
                and np.array_equal(a["values_mv"], coarse["observation_values_mv"])
                and len(a["time_ms"]) == r["samples"], "Sealed prediction differs from qualified trace")
        predictions[(arm, cid)] = (a["time_ms"], a["values_mv"])
    failed = any(r["status"] == "FAILED" for r in records)
    require(seal["status"] == ("COMPLETE_WITH_FAILURES" if failed else "COMPLETE"), "Prediction completion status changed")
    return seal, predictions


def endpoints(cases, stats):
    flash = [c for c in cases if c["family"] == "flash"]
    motion = [c for c in cases if c["family"] == "moving"]
    groups = {"flash_spatial_peak_rmse": [c for c in flash if c["duration_ms"] == 80.],
              "flash_duration_peak_rmse": [c for c in flash if c["position"] == 0.],
              "motion_waveform_rmse": motion, "direction_contrast_rmse": motion, "speed_contrast_rmse": motion}
    output = {}
    for name, required in groups.items():
        missing = [c["case_id"] for c in required if c["case_id"] not in stats]
        item = dict(metric=name, unit="mV", direction="lower", case_ids=[c["case_id"] for c in required],
                    missing_case_ids=missing, score=None, status="INCOMPLETE" if missing else "SCORED",
                    phase="CALIBRATION" if name.startswith("flash_") else "EVALUATION")
        if not missing:
            if name == "motion_waveform_rmse":
                item["score"] = float(np.mean([stats[c["case_id"]]["waveform_rmse_mv"] for c in required]))
            elif name.startswith("flash_"):
                errors = [stats[c["case_id"]]["predicted_peak_mv"] - stats[c["case_id"]]["observed_peak_mv"] for c in required]
                item["score"] = float(np.sqrt(np.mean(np.square(errors))))
            else:
                contrasts = []
                conditions = [("duration_ms", dwell, "primary_axis_sign", 1) for dwell in (20., 80.)] if name == "direction_contrast_rmse" else [("primary_axis_sign", sign, "duration_ms", 20.) for sign in (-1, 1)]
                for key, value, positive_key, positive_value in conditions:
                    pair = [c for c in required if c[key] == value]
                    require(len(pair) == 2, "Incomplete contrast pair")
                    first = next(c for c in pair if c[positive_key] == positive_value)
                    second = next(c for c in pair if c[positive_key] != positive_value)
                    a, b = stats[first["case_id"]], stats[second["case_id"]]
                    predicted = a["predicted_peak_mv"] - b["predicted_peak_mv"]
                    observed = a["observed_peak_mv"] - b["observed_peak_mv"]
                    contrasts.append(dict(first_case=first["case_id"], second_case=second["case_id"],
                                          predicted_contrast_mv=predicted, observed_contrast_mv=observed, error_mv=predicted-observed))
                item["contrasts"] = contrasts
                item["score"] = float(np.sqrt(np.mean(np.square([r["error_mv"] for r in contrasts]))))
        output[name] = item
    return output


def difference(baseline, candidate, tolerance):
    delta = None if baseline is None or candidate is None else baseline - candidate
    verdict = "INCOMPLETE" if delta is None else "CANDIDATE_LOWER_ERROR" if delta > tolerance else "BASELINE_LOWER_ERROR" if delta < -tolerance else "NUMERICAL_TIE"
    return dict(verdict=verdict, baseline_minus_candidate_mv=delta, tolerance_mv=tolerance)


def recompute_scores(seal, predictions, obs, cases, protocol):
    ordered_cases = [cases[c] for c in protocol["development_case_ids"] + protocol["evaluation_case_ids"]]
    scores, metrics = {}, {}
    for arm in ARMS:
        rows, stats, groups, failed = [], {}, defaultdict(list), []
        for record in seal["records"]:
            if record["arm"] != arm:
                continue
            cid = record["case_id"]
            animal = str(cases[cid]["cell_id"])
            row = dict(case_id=cid, animal_id=animal, status="FAILED")
            if record["status"] == "FAILED":
                row["reason"] = record["reason"]
                failed.append(cid)
            else:
                time, prediction = predictions[(arm, cid)]
                grid, target = obs[cid]
                require(np.array_equal(time, grid) and prediction.shape == target.shape, "Prediction and observation grids differ")
                use = time >= 0
                require(use.any(), "Empty post-onset window")
                mse = float(np.mean(np.square(prediction[use] - target[use])))
                row.update(status="PASS", mse=mse, waveform_rmse_mv=math.sqrt(mse),
                           predicted_peak_mv=float(np.max(prediction[use])), observed_peak_mv=float(np.max(target[use])))
                stats[cid] = row
                groups[animal].append(mse)
            rows.append(row)
        mse = None if failed else math.fsum(math.fsum(v)/len(v) for v in groups.values())/len(groups)
        scores[arm] = dict(status="INCOMPLETE" if failed else "SCORED", balanced_mse=mse,
                           balanced_rmse_mv=None if mse is None else math.sqrt(mse), animal_count=len(groups),
                           condition_count=len(rows), missing_case_ids=[], failed_case_ids=sorted(failed),
                           weighting="equal animals then equal conditions, sample MSE within condition", case_errors=rows)
        metrics[arm] = endpoints(ordered_cases, stats)
    comparisons = []
    for name, metric in metrics["paralimbo"].items():
        tolerance = .004 if name in ("direction_contrast_rmse", "speed_contrast_rmse") else .002
        comparisons.append(dict(baseline_arm="banc", candidate_arm="paralimbo", metric=name, phase=metric["phase"],
                                **difference(metrics["banc"][name]["score"], metric["score"], tolerance)))
    conditions = []
    baseline = {r["case_id"]: r for r in scores["banc"]["case_errors"]}
    for row in scores["paralimbo"]["case_errors"]:
        cid = row["case_id"]
        conditions.append(dict(baseline_arm="banc", candidate_arm="paralimbo", case_id=cid,
                               phase="CALIBRATION" if cases[cid]["family"] == "flash" else "EVALUATION",
                               **difference(baseline[cid].get("waveform_rmse_mv"), row.get("waveform_rmse_mv"), .002)))
    return dict(schema="transmission-scores-v1", prediction_seal_sha256=seal["prediction_seal_sha256"],
                protocol_sha256=seal["protocol_sha256"], scores=scores, numerical_tolerance_mv=.001,
                endpoints=metrics, comparisons=comparisons, condition_comparisons=conditions,
                scope="retrospective_native_conditional_prediction", biological_superiority="NOT_ESTABLISHED")


def verify(folder):
    folder = Path(folder).resolve()
    inventory = verify_inventory(folder)
    traces = verify_traces(folder, inventory)
    benchmark = read_json(safe_file(folder, "evidence/benchmark.json"))
    require(benchmark["benchmark_id"] == "native_t4", "Not the approved T4 fallback")
    protocol = benchmark["t4_protocol"]
    require(protocol["protocol_sha256"] == PROTOCOL_ID and protocol["biological_superiority"] == "NOT_ESTABLISHED"
            and protocol["historical_outcome_exposure"] is True, "Protocol/evidence scope changed")
    cases, obs = observations(folder, protocol)
    selections, multiplier = verify_calibration(folder, protocol, obs, traces)
    reports = {}
    for directory, name in (("predictions", "scores.json"), ("predictions-t4d", "scores-t4d.json")):
        seal, predictions = verify_prediction_seal(folder, directory, protocol, selections, multiplier, traces)
        saved = read_json(safe_file(folder, "evidence/" + name))
        sealed(saved, "scores_sha256")
        calculated = recompute_scores(seal, predictions, obs, cases, protocol)
        same({k: v for k, v in saved.items() if k != "scores_sha256"}, calculated, name)
        reports[directory] = {"qualified_conditions": {a: len([r for r in seal["records"] if r["arm"] == a and r["status"] == "PREDICTED"]) for a in ARMS},
                              "scores_sha256": saved["scores_sha256"], "endpoint_scores": {a: {k: v["score"] for k, v in saved["endpoints"][a].items()} for a in ARMS}}
    model = read_json(safe_file(folder, "evidence/experimental-model.json"))
    sealed(model, "model_identity")
    require(model["source_identity"] == SOURCE_ID and model["base_model"] == MODELS["paralimbo"]
            and model["selection"] == selections["paralimbo"] and model["input_multiplier"] == multiplier
            and model["default_changed"] is False and model["published_claims_changed"] is False
            and model["status"] == "EXPERIMENTAL", "Experimental candidate identity changed")
    require(model["evidence"] == read_json(safe_file(folder, "evidence/scores.json")), "Experimental evidence differs")
    return dict(status="PASS", verified_files=len(inventory), native_trace_projections=len(traces),
                comparison="INCONCLUSIVE", biological_superiority="NOT_ESTABLISHED", reports=reports,
                scope="Offline arithmetic, retained trace qualification, development selection and inventory consistency; no native simulation or hidden-state/checkpoint replay.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path(__file__).resolve().parents[1] / "docs" / "paralimbo-transmission-v1")
    args = parser.parse_args(argv)
    try:
        result = verify(args.folder)
    except (ValueError, KeyError, TypeError, OSError, EOFError, ArithmeticError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
