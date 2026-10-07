"""Durable, explicit gate status; missing evidence is never a pass."""
from pathlib import Path
from datetime import datetime
import json
import yaml
from .inspect_data import atomic_write_json, stat_signature
from .fetch import checksum

GATES = {
    "V-A": "Data integrity", "V-B": "Photoreceptor sign response",
    "V-C": "Numerics and equilibration", "V-D": "Five-second dark control",
    "V-E": "Brian2 reference cross-check", "V-F": "ON/OFF split",
    "V-G": "Direction selectivity", "V-H": "Wide-field responses", "V-I": "Looming selectivity",
}


def _compact(value):
    """Keep the report readable; complete machine evidence stays on disk."""
    if isinstance(value, dict):
        omitted = {"source_hashes", "source_stats", "config_hashes", "implementation_hashes", "code_hashes"}
        return {k: _compact(v) for k, v in value.items() if k not in omitted}
    if isinstance(value, list):
        if len(value) > 12:
            return {"total_items": len(value), "first_12": [_compact(v) for v in value[:12]], "note": "Full list in the linked JSON evidence."}
        return [_compact(v) for v in value]
    return value


def _read_evidence(path, default, issues):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        issues.append(f"Cannot read {path.name}: {error}")
        return default


def _time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError):
        return float("-inf")


def _current_result(entry, root, manifest, failures, errors, evidence_issues):
    """A historical measured result requires unchanged inputs to remain current.

    Reports use file identity/stat signatures, never reread multi-GB datasets.
    Fetch and validation compute actual hashes and detect in-place changes.
    """
    result = dict(entry)
    if result.get("status") not in {"PASS", "FAIL"}:
        return result
    issues = list(evidence_issues)
    hashes = entry.get("source_hashes", {})
    signatures = entry.get("source_stats", {})
    if not hashes:
        issues.append("Validation has no recorded input hashes; rerun the gate.")
    for name, digest in hashes.items():
        if name in failures:
            issues.append(f"Fetch integrity failure for {name}: {failures[name].get('error', 'unverified')}")
        cached = manifest.get(name)
        if cached is not None and cached.get("sha256") != digest:
            issues.append(f"Input hash no longer matches the verified manifest: {name}")
        if name not in signatures:
            issues.append(f"Validation has no file signature for {name}")
            continue
        try:
            if stat_signature(root / "data/raw" / name) != signatures[name]:
                issues.append(f"Input changed since validation: {name}")
        except OSError as error:
            issues.append(f"Input unavailable: {name}: {error}")
    for error in errors:
        if (error.get("stage") in {"fetch", "validate"}
                and _time(error.get("time")) >= _time(entry.get("created_at"))):
            issues.append(f"A later {error['stage']} attempt stopped: {error.get('error', 'unknown error')}")
    for key, base in (("config_hashes", root / "config"), ("implementation_hashes", root)):
        for name, digest in entry.get(key, {}).items():
            path = base / name
            if not path.exists() or checksum(path) != digest:
                issues.append(f"Implementation or configuration changed since validation: {name}")
    if issues:
        result["previous_status"] = entry["status"]
        result["status"] = "NOT-RUN"
        result["stale_evidence_reasons"] = issues
    return result


def write_report(root: Path):
    root = Path(root)
    build = root / "build"
    build.mkdir(parents=True, exist_ok=True)
    evidence_issues = []
    manifest = _read_evidence(build / "downloads.json", {}, evidence_issues).get("files", {})
    failures = _read_evidence(build / "integrity_failures.json", {}, evidence_issues)
    errors = _read_evidence(build / "stage_errors.json", [], evidence_issues)
    results = {}
    for path in sorted(build.glob("validation*.json")):
        data = _read_evidence(path, {}, evidence_issues)
        entries = data if isinstance(data, list) else data.get("gates", [data])
        for entry in entries:
            if entry.get("gate") in GATES:
                prior = results.get(entry["gate"])
                if prior is None or _time(entry.get("created_at")) >= _time(prior.get("created_at")):
                    results[entry["gate"]] = entry
    results = {gate: _current_result(entry, root, manifest, failures, errors, evidence_issues)
               for gate, entry in results.items()}
    lines = ["# Flybrain execution report", ""]
    runtime_path = build / "validation_neuromod_runtime.json"
    if runtime_path.exists():
        runtime = _read_evidence(runtime_path, {}, evidence_issues)
        recorded = {row.get("gate"): _current_result(row, root, manifest, failures, errors, evidence_issues)
                    for row in runtime.get("gates", [])}
        replay = recorded.get("V-NM-B", {})
        timing = recorded.get("V-NM-F'", {})
        speed = timing.get("real_time_factor")
        speed_text = f"{speed:.3f}× real time" if isinstance(speed, (int, float)) else "not measured"
        lines += ["## Current neuromodulation implementation", "",
                  "The corrected normalized plasticity, coupled 13,300-neuron core, endocrine state, "
                  "protocol runner, session recording/replay and browser console are implemented. "
                  "The default `./Open\\ Cognesia.command` launcher opens the unified whole-brain viewer, idle, at http://127.0.0.1:8794. "
                  "Use `.venv/bin/flybrain rt serve --core` explicitly for the smaller diagnostic console at http://127.0.0.1:8795. "
                  "[Whole-brain chemical integration](docs/wholebrain_chemistry.md) is an experimental extension; the core checks below do not validate that coupling.", "",
                  f"The 60-second exact-replay gate is **{replay.get('status', 'NOT-RUN')}**. "
                  f"Measured throughput is **{speed_text}**; the performance gate is **{timing.get('status', 'NOT-RUN')}** "
                  "against the 1.2× target. No integration steps are skipped to improve the displayed speed.", "",
                  "The driven core's voltage bounds and biological validation remain failures where measured. "
                  "The separate normalized whole-brain variant has its own resting-stability evidence below; "
                  "it does not replace the original base model or validate visual/motor behaviour.", "",
                  "[Console and controls](docs/live_console.md) · [Measurement methods](docs/runtime_measurements.md) · "
                  "[Evidence figures](build/neuromod_figures/index.json)", ""]
    hybrid = results.get("V-C", {})
    eq = hybrid.get("equilibration", {})
    visual_runs = sorted((root / "runs").glob("*/visual_summary.json"))
    if hybrid.get("status") == "FAIL" and eq:
        derivative = eq.get("max_abs_dvdt_mV_per_ms")
        derivative_text = f"{derivative:.6f}" if isinstance(derivative, (int, float)) else "non-finite"
        headline = "**The original validation pipeline stopped at stage 4: the uniform hybrid model failed equilibration.**" if visual_runs else "**Stopped at stage 4: the uniform hybrid model failed equilibration. The requested end-to-end eye-driven simulator is not complete.**"
        lines += [headline, "",
                  f"With zero external input for 1,000 ms, the maximum voltage derivative was **{derivative_text} mV/ms** against a **0.001 mV/ms** limit. **{eq['unstable_neurons']:,} neurons** remained nonstationary, and **{eq['clamp_events']:,} voltage-clamp events** occurred across **{eq['clamped_neurons']:,} neurons**.", "",
                  "No parameters were changed to force a pass. The brief's stop rule was applied before the separate five-second dark control, eye construction, stimulus battery, lamina/flyvis comparisons, and sensitivity sweeps. Preparatory source downloads are not completed eye-model validation.", ""]
    if visual_runs:
        lines += ["## Experimental visual simulator", "",
                  "The subsequent request to build a visual simulator is implemented as a separate exploratory continuation. The unchanged neural core runs actual eye-driven input and a matched constant-luminance control, then displays recorded raw, baseline and difference voltages. The original failed gate remains unchanged; these recordings do not complete the biological validation battery.", "",
                  f"{len(visual_runs)} saved visual recordings are available through `flybrain view --open`. See [VISUAL_SIMULATOR.md](VISUAL_SIMULATOR.md) for launch instructions, assumptions, provenance, and measurement definitions.", ""]
    lines += ["This report records executed checks. NOT-RUN is not a pass. A historical PASS with changed or unverified inputs is shown as NOT-RUN until validation is repeated.", "", "| Gate | Check | Status |", "|---|---|---|"]
    for gate, label in GATES.items():
        lines.append(f"| {gate} | {label} | {results.get(gate, {}).get('status', 'NOT-RUN')} |")
    if hybrid.get("status") == "FAIL":
        from .figures import hybrid_failure_figure
        figure = hybrid_failure_figure(root)
        if figure:
            lines += ["", "## Why execution stopped", "", "![Observed hybrid equilibration diagnostics](build/figures/hybrid_equilibration.png)", "", "These measurements are from the one-second equilibration phase. They are not the separate five-second dark-control test. The logarithmic derivative histogram omits exact zero values."]
    runs = []
    for path in sorted((root / "runs").glob("*/run_manifest.json"))[-12:]:
        try:
            run = json.loads(path.read_text())
            runs.append((path.parent.relative_to(root), run))
        except (OSError, ValueError):
            pass
    if runs:
        lines += ["", "## Recorded runs", "", "These are recorded experiments, not substitutes for the validation gates.", "", "| Experiment | Spikes | Clamps | Wall seconds | Peak RSS GB | Evidence |", "|---|---:|---:|---:|---:|---|"]
        for path, run in runs:
            rss = run.get("peak_rss_bytes")
            rss_text = f"{rss / 1e9:.3f}" if isinstance(rss, (int, float)) else "not recorded"
            wall = run.get("wall_seconds")
            wall_text = f"{wall:.3f}" if isinstance(wall, (int, float)) else "not recorded"
            experiment = run.get('experiment', 'visual ' + run['options']['stimulus'] if 'options' in run else 'unspecified')
            lines.append(f"| {experiment} | {run.get('spike_count', run.get('stimulus_spike_count', 'not recorded'))} | {run.get('clamp_count', run.get('stimulus_clamp_count', 'not recorded'))} | {wall_text} | {rss_text} | [{path.name}]({path}/run_manifest.json) |")
    if results.get("V-E", {}).get("status") == "PASS":
        from .figures import reference_figure
        figure = reference_figure(root)
        if figure:
            reference = results["V-E"]
            lines += ["", "## Reference comparison", "", "![Mean firing rates against Brian2](build/figures/reference_comparison.png)", "", f"Firing-rate agreement passed (r = {reference['metrics']['mean_rate_correlation']:.7f}), with **{reference.get('clamp_count', 0):,} voltage-clamp events**. This is not a zero-clamp or biological-validation pass; it checks the specified firing-rate statistic under the explicit Poisson comparison protocol."]
    for gate, data in results.items():
        evidence_name = "validation_data.json" if gate == "V-A" else "validation_engine.json" if gate == "V-E" else "validation_hybrid.json"
        lines += ["", f"## {gate}: {GATES[gate]}", "", f"[Complete measurements and provenance](build/{evidence_name})", "", "```json", json.dumps(_compact(data), indent=2), "```"]
    if errors:
        lines += ["", "## Stopped stages", "", "```json", json.dumps(errors, indent=2), "```"]
    if failures:
        lines += ["", "## Unresolved source verification failures", "", "```json", json.dumps(failures, indent=2), "```"]
    if evidence_issues:
        lines += ["", "## Unreadable evidence", ""] + [f"- {issue}" for issue in evidence_issues]
    for name, label in [("build_summary.json", "Network build"), ("execution_summary.json", "Execution summary")]:
        p = build / name
        if p.exists():
            lines += ["", f"## {label}", "", "```json", p.read_text().strip(), "```"]
    lines += ["", "## Evidence files", ""]
    for filename, description in {
        "build/schema_inspection.json": "observed schemas and three source rows",
        "build/downloads.json": "URLs, byte counts, SHA-256, file signatures and publisher checksums where supplied",
        "BUILD_BRIEF.md": "unmodified input brief",
    }.items():
        suffix = description if (root / filename).exists() else "not yet recorded"
        lines.append(f"- `{filename}`: {suffix}.")
    lines += ["", "## Scope and scientific limitations", "", "See [LIMITATIONS.md](LIMITATIONS.md). Biological validation, parameter sweeps and figures are pending unless accompanied by run evidence above.", ""]
    if hybrid.get("status") == "FAIL":
        eye_status = "Implemented for exploratory visual runs; coverage and optical assumptions are recorded. No formal eye-validation pass is claimed." if visual_runs else "NOT-RUN; stopped before stage 5. Official source table is downloaded and audited."
        map_status = "Exploratory apparent-motion playback and source-weighted brain-area traces are available. The full apparent-motion response map and validation sweeps remain NOT-RUN." if visual_runs else "NOT-RUN; no measurements exist to plot."
        lines += ["## Requested outputs and remaining validation", "", "| Output | Status and reason |", "|---|---|",
                  f"| Eye column map and optical projection | {eye_status} |",
                  "| Lamina repair and connectome/cartridge comparison | NOT-RUN; no synthetic edges were added. |",
                  "| T4/T5 polar tuning and ON/OFF split | NOT-RUN; no visual stimulus battery ran. |",
                  "| HS/VS and LPLC2 looming responses | NOT-RUN; no visual stimulus battery ran. |",
                  f"| Apparent-motion map and neuropil activation maps | {map_status} |",
                  "| Flyvis comparison and assumption sensitivity sweeps | NOT-RUN; candidate sweep values are listed in PARAMETERS.md, without claiming results. |", ""]
    if (root / "NEUROMOD_BUILD_BRIEF.md").exists():
        from .neuromod.report import report_lines
        lines += report_lines(root, lambda entry: _current_result(
            entry, root, manifest, failures, errors, evidence_issues))
    (root / "REPORT.md").write_text("\n".join(lines))
    parameter_file = root / "config/parameters.yaml"
    if parameter_file.exists():
        data = yaml.safe_load(parameter_file.read_text())
        rows = ["# Parameter provenance", "", "Sweep values are predeclared candidates. Only runs with saved evidence in REPORT.md were executed; a listed candidate is not a completed experiment.", "", "| Parameter | Value | Unit | Source | Planned sensitivity values |", "|---|---|---|---|---|"]
        for name, p in data.get("parameters", data).items():
            if isinstance(p, dict) and "value" in p:
                rows.append(f"| {name} | {p['value']} | {p.get('unit', '')} | {p.get('source', 'MISSING')} | {p.get('sweep', '—')} |")
        from .neuromod.report import parameter_lines
        rows += parameter_lines(root)
        (root / "PARAMETERS.md").write_text("\n".join(rows) + "\n")
    return root / "REPORT.md"


def record_error(root, stage, error):
    path = Path(root) / "build/stage_errors.json"
    path.parent.mkdir(exist_ok=True, parents=True)
    entries = json.loads(path.read_text()) if path.exists() else []
    from datetime import datetime, timezone
    entries.append({"stage": stage, "error": str(error), "type": type(error).__name__, "time": datetime.now(timezone.utc).isoformat()})
    atomic_write_json(path, entries)
    write_report(root)
