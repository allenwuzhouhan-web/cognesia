"""Render the extension's actual evidence without upgrading absent gates."""
from __future__ import annotations

import json
from pathlib import Path


GATES = {
    "V-NM-A": ("software", "Disabled-layer equivalence"),
    "V-NM-B": ("software", "60 s event-log replay determinism"),
    "V-NM-C": ("software", "Sources, overrides and released connectivity census"),
    "V-NM-COMP": ("software", "Empirical compartment construction and assignment audit"),
    "V-NM-CORE": ("software", "Core zero-input resting equilibrium (Patch 1)"),
    "V-NM-ODOUR": ("software", "Source-backed ORN response mapping and transduction"),
    "V-NM-ODSP": ("biology", "Odour-driven core dynamics and Kenyon-cell sparseness"),
    "V-NM-D": ("software", "Compartment field numerics"),
    "V-NM-E": ("software", "Plasticity bounds and twelve-point reference curve"),
    "V-NM-F'": ("software", "60 s real-time budget and resident memory"),
    "V-NM-F": ("biology", "Pairing asymmetry against Handler 2019, PMID:31230716"),
    "V-NM-G": ("biology", "Compartment specificity, PMID:26687359"),
    "V-NM-H": ("biology", "Behavioural sign, PMID:25535794; PMID:25864636"),
    "V-NM-I": ("biology", "Octopamine visual gain, PMID:23142045"),
    "V-NM-J": ("biology", "Fed/starved state dependence"),
    "V-NM-K": ("biology", "Extinction through recurrence, PMID:30245010; PMID:32203499"),
}

DEPENDENCIES = {
    "V-NM-COMP": ("V-NM-C",),
    "V-NM-CORE": ("V-NM-C",),
    "V-NM-ODOUR": ("V-NM-C",),
    "V-NM-D": ("V-NM-COMP",),
    "V-NM-A": ("V-NM-D",),
    "V-NM-ODSP": ("V-NM-CORE", "V-NM-ODOUR"),
    "V-NM-E": ("V-NM-A",),
}


def _propagate_dependency_status(results):
    """Do not retain a downstream PASS when an upstream gate is stale or absent."""
    for gate, dependencies in DEPENDENCIES.items():
        entry, path = results.get(gate, ({}, None))
        if entry.get("status") != "PASS":
            continue
        missing = [name for name in dependencies if results.get(name, ({}, None))[0].get("status") != "PASS"]
        if missing:
            results[gate] = (dict(entry, status="NOT-RUN", previous_status="PASS",
                                 stale_evidence_reasons=entry.get("stale_evidence_reasons", []) +
                                 ["Current prerequisite gates are not PASS: " + ", ".join(missing)]), path)


def _cell(value):
    if value is None:
        return "not measured"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return str(value).replace("|", "\\|").replace("\n", " ")


def _verify_artifacts(entry: dict, root: Path) -> dict:
    """A measured extension gate also depends on its derived/base artifacts."""
    if entry.get("status") not in {"PASS", "FAIL"}:
        return entry
    from ..fetch import checksum
    issues = []
    for field in ("artifact_hashes", "base_artifact_hashes"):
        hashes = entry.get(field, {})
        if entry.get("gate") == "V-NM-C" and not hashes:
            issues.append(f"Source gate has no recorded {field}")
        for name, digest in hashes.items():
            path = root / "build" / name
            try:
                if checksum(path) != digest:
                    issues.append(f"Derived artifact changed: {name}")
            except OSError as error:
                issues.append(f"Derived artifact unavailable: {name}: {error}")
    for name, digest in entry.get("base_config_hashes", {}).items():
        try:
            if checksum(root / "config" / name) != digest:
                issues.append(f"Base configuration changed: {name}")
        except OSError as error:
            issues.append(f"Base configuration unavailable: {name}: {error}")
    for field in ("dependency_hashes", "neuropil_source_hashes"):
        for name, digest in entry.get(field, {}).items():
            try:
                if checksum(root / name) != digest:
                    issues.append(f"Upstream evidence changed: {name}")
            except OSError as error:
                issues.append(f"Upstream evidence unavailable: {name}: {error}")
    if issues:
        entry = dict(entry, previous_status=entry["status"], status="NOT-RUN",
                     stale_evidence_reasons=entry.get("stale_evidence_reasons", []) + issues)
    return entry


def report_lines(root: Path, current_result) -> list[str]:
    """Use the base report's provenance verifier for historical measured results."""
    root = Path(root)
    if not (root / "NEUROMOD_BUILD_BRIEF.md").exists():
        return []
    results = {}
    issues = []
    for path in sorted((root / "build").glob("validation_neuromod*.json")):
        try:
            data = json.loads(path.read_text())
            entries = data if isinstance(data, list) else data.get("gates", [data])
            for entry in entries:
                if entry.get("gate") in GATES:
                    results[entry["gate"]] = (_verify_artifacts(current_result(entry), root), path.name)
        except (OSError, ValueError) as error:
            issues.append(f"Cannot read {path.name}: {error}")
    _propagate_dependency_status(results)
    lines = ["", "## Neuromodulation extension", "",
             "Requested specification: [NEUROMOD_BUILD_BRIEF.md](NEUROMOD_BUILD_BRIEF.md). "
             "[Final corrections](NEUROMOD_FINAL.md) supersede the original plasticity equation; Patch 1 corrects source policies. "
             "Primary-data/software failures stop dependent stages; population-definition discrepancies are reported while normative selectors remain authoritative. No absent measurement is a pass.", "",
             "[Accepted findings from the initial audit](docs/neuromod_specification_findings.md).", "",
             "| Gate | Kind | Check / source | Status | Measurement |", "|---|---|---|---|---|"]
    for gate, (kind, label) in GATES.items():
        entry = results.get(gate, ({}, None))[0]
        checks = entry.get("checks", [])
        measurement = entry.get("metrics")
        if measurement is None:
            selected = {k:entry[k] for k in ('real_time_factor','duration_ms','over_budget_fraction','rss_sampled_max_bytes',
                'forward_sum','backward_sum','paired_mean_absolute_change','ratio','valence_change',
                'appetitive_valence_change','relative_reversal',
                'valence_difference_starved_minus_fed','decoded_decisions') if k in entry}
            if selected: measurement = selected
        if measurement is None and gate == "V-NM-ODSP" and entry.get("runs"):
            measurement = "; ".join(
                f"{row['odour']}: KC active {100 * row['kc_active_fraction']:.2f}% ({row['status']})"
                if row.get("kc_active_fraction") is not None else f"{row['odour']}: incomplete"
                for row in entry["runs"])
        if measurement is None:
            measurement = (f"{sum(c.get('status') == 'PASS' for c in checks)}/{len(checks)} exact checks passed"
                           if checks else "not measured")
        lines.append(f"| {gate} | {kind} | {label} | {entry.get('status', 'NOT-RUN')} | {_cell(measurement)} |")
    for gate, (entry, evidence_name) in results.items():
        lines += ["", f"### {gate} evidence", "", f"[Complete recorded evidence](build/{evidence_name})", ""]
        if entry.get("stop_reason"):
            lines += [_cell(entry["stop_reason"]), ""]
        if entry.get("scope"):
            lines += [_cell(entry["scope"]), ""]
        if gate == "V-NM-E" and entry.get("reference_assertion"):
            lines += ["**" + _cell(entry["reference_assertion"]) + "**", "",
                      "[All twelve residuals](build/plasticity_reference_curve.csv); "
                      "[normalized implementation and assumptions](docs/plasticity.md). "
                      "The historical literal-equation mismatch is superseded by the explicit Part III correction.", ""]
        if entry.get("stale_evidence_reasons"):
            lines += [f"Historical {entry.get('previous_status', 'measured')} evidence is stale: " + _cell(entry["stale_evidence_reasons"]), ""]
        checks = entry.get("checks", [])
        if checks:
            lines += ["| Assertion | Expected | Observed | Status |", "|---|---|---|---|"]
            for check in checks:
                lines.append(f"| {_cell(check.get('name'))} | {_cell(check.get('expected'))} | {_cell(check.get('observed'))} | {check.get('status', 'NOT-RUN')} |")
        if entry.get("audit"):
            lines += ["", "**Transmitter-prediction audit (full annotation table)**", "",
                      "| Transmitter | Positive known_nt | Predicted top_nt | Agree | Ground truth recovered |",
                      "|---|---:|---:|---:|---:|"]
            for row in entry["audit"]:
                recovered = row.get("ground_truth_recovered_pct")
                recovery_text = f"{recovered:.1f}%" if recovered is not None else "not measured"
                lines.append(f"| {_cell(row['transmitter'])} | {row['positive_known_nt']:,} | "
                             f"{row['predicted_top_nt']:,} | {row['agree']:,} | {recovery_text} |")
        if entry.get("clustering"):
            clustering = entry["clustering"]
            lines += ["", "**Empirical clustering versus published anatomy**", "",
                      "| Comparison | Types |", "|---|---:|"]
            for label, count in clustering["comparison_counts"].items():
                lines.append(f"| {label.replace('_', ' ')} | {count} |")
            lines += ["", "[Every type and its disagreement](build/mb_compartment_comparison.csv); "
                      "[15-compartment inventory](build/mb_compartments.csv); [method and anatomical sources](docs/compartments.md). "
                      "The connectivity-derived label for PPL101 is g4; the published anatomical assignment is g1. "
                      "This disagreement is retained, so a command targeting an empirical cluster cannot be presented as anatomically verified γ1 stimulation."]
        if "sensitivity_runs" in entry and gate == "V-NM-J":
            lines += ["", f"Executed **{entry['sensitivity_runs']}** endocrine-state sensitivity fixtures. "
                      "[All measured state runs](build/neuromod_state_sensitivity.csv). "
                      "These software fixtures do not establish a biological decision change."]
        elif "sensitivity_runs" in entry and gate == "V-NM-D":
            lines += ["", f"Executed **{entry['sensitivity_runs']}** field sensitivity fixtures. "
                      f"Stress fixtures produced **{entry.get('sensitivity_clamp_events', 0)}** clamps in "
                      f"**{entry.get('sensitivity_runs_with_clamps', 0)}** runs; these are separate from the default-drive clamp assertion above. "
                      "[All measured runs](build/neuromod_field_sensitivity.csv). Candidate sweeps for other layers are not completed measurements."]
        for key in ("inventory", "motifs", "core", "coverage", "MB_DAN_nitric_oxide_counts", "wholebrain_comparison", "specification_conflicts", "notes", "warnings", "limitations", "results", "runs", "corrections", "disabled_equivalence", "active_fixtures", "5HT_AL_scope", "core_target_coverage", "fixture"):
            if key in entry:
                from ..report import _compact
                lines += ["", f"**{key.replace('_', ' ').capitalize()}**", "", "```json",
                          json.dumps(_compact(entry[key]), indent=2, ensure_ascii=False), "```"]
    if issues:
        lines += ["", "Evidence read errors: " + _cell(issues)]
    reference_path = root / "build/neuromod_reference_audit.json"
    if reference_path.exists():
        try:
            reference = json.loads(reference_path.read_text())
            literal = reference["literal"]["max_absolute_reference_error"]
            alternative = reference["normalized_alternative"]["max_absolute_reference_error"]
            lines += ["", "### Historical equation preflight", "",
                      "This audit records the original specification. The final brief explicitly supersedes its equation with the normalized rule validated by current V-NM-E. "
                      "Using the explicit diagnostic assumptions (10 Hz KC activity, no forgetting, 30 s horizon), "
                      f"the written trace equations differ from the supplied table by up to **{literal:.9f}** "
                      f"against its **0.001** tolerance. Normalizing both trace equations reduces the error to **{alternative:.9f}**, "
                      "but changes the specified equations and eta units. No alternative was silently adopted.", "",
                      "[Method, all twelve values, convergence and history/forgetting conflicts](docs/neuromod_reference_findings.md)."]
        except (OSError, ValueError, KeyError, TypeError) as error:
            lines += ["", f"Reference diagnostic unavailable: {_cell(error)}"]
    timing = results.get("V-NM-F'", ({},None))[0]
    biology = results.get('V-NM-F', ({},None))[0]
    measured_speed = timing.get('real_time_factor')
    speed_text = f"{measured_speed:.3f} model s / wall s ({timing.get('status')})" if measured_speed is not None else 'not yet measured by the 60-second gate'
    crossings = biology.get('observed_crossings')
    crossing_text = _cell(crossings) if crossings else ('no sign crossing observed' if 'observed_crossings' in biology else 'not yet measured in the network')
    lines += ['', f"Measured real-time factor: **{speed_text}**. Network pairing-curve crossover: **{crossing_text}**.",
              '[Coupled runtime, console, recording and interpretation](docs/live_console.md). '
              'Executed software and biological measurements have separate gates; absent measurements remain NOT-RUN. '
              'V-NM-I remains NOT-RUN pending base V-G/V-H. Body readout remains NOT-RUN without a validated motor decoder.', '']
    variant_path = root/'build/validation_hybrid_variant.json'
    if variant_path.exists():
        variant = _verify_artifacts(current_result(json.loads(variant_path.read_text())),root)
        lines += ['', '### Separate normalized whole-brain stability variant', '',
            f"Overall current status: **{variant.get('status','NOT-RUN')}**. Original base V-C evidence remains unchanged.", '',
            '| Synaptic model | Gate | Status | Measurement |', '|---|---|---|---|']
        for gate in variant.get('gates',[]):
            measured={k:gate[k] for k in ('relative_residual','slope_per_ms','tau_net_ms','clamp_count','max_perturbed_endpoint_difference_mV') if k in gate}
            status=gate.get('status') if variant.get('status')=='PASS' else 'NOT-RUN'
            lines.append(f"| {gate.get('syn_model')} | {gate.get('gate')} | {status} | {_cell(measured)} |")
        lines += ['', '[Methods and limits](docs/hybrid_stability_variant.md); [complete evidence](build/validation_hybrid_variant.json). '
                  'Additional normalization and kappa sweeps have fixed-point/spectral evidence only; dynamic sweeps are NOT-RUN.']
    capacity_path=root/'build/validation_neuromod_capacity.json'
    if capacity_path.exists():
        capacity=_verify_artifacts(current_result(json.loads(capacity_path.read_text())),root)
        lines += ['', '### Measured write-handle capacity', '',
                  f"Current result: **{capacity.get('status','NOT-RUN')}**. "
                  '[Complete trial, null and confidence-interval evidence](build/validation_neuromod_capacity.json). '
                  'Inferred MBON readout, short-protocol power, unknown driver-line access and saturation limits remain explicit.']
        handles = capacity.get('per_handle', [])
        if handles:
            values = [row['mutual_information_bits'] for row in handles]
            significant = sum(row.get('significant_q_lt_05', False) for row in handles)
            trials = next((c.get('observed') for c in capacity.get('checks', [])
                           if c.get('name') == 'actual_held_out_trials'), 'not recorded')
            lines += ['', f"Measured **{len(handles)} handles** and **{trials} held-out trials**. "
                      f"Per-handle information ranged from **{min(values):.6g} to {max(values):.6g} bits per observation**; "
                      f"**{significant}** survived BH correction at q < 0.05. "
                      'PASS here certifies execution and provenance, not successful biological writing.', '',
                      _cell(capacity.get('saturation_status'))]
    figures = root/'build/neuromod_figures'
    available = [(name, title) for name, title in (
        ('plasticity_reference.png', 'Normalized isolated reference fixture'),
        ('network_pairing.png', 'Measured closed-loop pairing curve'),
        ('wholebrain_stability.png', 'Separate whole-brain perturbation recovery'),
        ('capacity_curve.png', 'Measured bounded-task information curve'),
        ('capacity_per_handle.png', 'Per-handle information with uncertainty')) if (figures/name).exists()]
    if available:
        lines += ['', '### Measured figures', '']
        for name, title in available:
            lines += [f'![{title}](build/neuromod_figures/{name})', '']
    return lines


def parameter_lines(root: Path) -> list[str]:
    path = Path(root) / "config/neuromod.yaml"
    if not path.exists():
        return []
    import yaml
    document = yaml.safe_load(path.read_text())
    parameters = document.get("parameters", {})
    lines = ["", "## Neuromodulation parameters", "",
             "Generated from config/neuromod.yaml. Candidate sweeps are not completed sensitivity experiments. "
             "No eligibility parameters have been fitted to published data.", "",
             "| Parameter | Value | Unit | Source | Sweep candidates | Notes / fit data |",
             "|---|---|---|---|---|---|"]
    for name, entry in parameters.items():
        lines.append("| " + " | ".join(_cell(value) for value in (
            name, entry["value"], entry["unit"], entry["source"], entry.get("sweep", "—"),
            entry.get("fit_data", entry.get("note", "—")))) + " |")
    if not parameters:
        lines += ["", "No dynamical parameters have been introduced: implementation stopped at the source audit."]
    if document.get("source_policy"):
        lines += ["", "### Source-audit policies", "",
                  "These are descriptive selection and failure policies, not tunable simulation parameters or completed sensitivity sweeps.", "",
                  "| Policy | Value | Unit | Provenance | Interpretation |", "|---|---|---|---|---|"]
        for name, entry in document["source_policy"].items():
            lines.append("| " + " | ".join(_cell(value) for value in (
                name, entry["value"], entry["unit"], entry["source"], entry.get("note", "—"))) + " |")
    if document.get("compartment_policy"):
        lines += ["", "### Compartment construction assumptions", "", "```json",
                  json.dumps(document["compartment_policy"], indent=2, ensure_ascii=False), "```"]
    receptor_path = Path(root) / "config/receptors.csv"
    if receptor_path.exists():
        import csv
        lines += ["", "### Receptor coefficients", "",
                  "Generated from config/receptors.csv. Every numerical magnitude and expression coverage is ASSUMPTION. "
                  "Biological sign evidence does not calibrate the coefficient; the sweep column lists candidates, not executed sweeps.", "",
                  "| Row | Active | Magnitude at C=1 (dimensionless) | Kernel | History | Sign evidence | Candidate magnitudes |",
                  "|---|---|---:|---|---|---|---|"]
        with receptor_path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                lines.append("| " + " | ".join(_cell(row.get(key, "—")) for key in (
                    "id", "enabled", "magnitude", "kernel", "history", "sign_provenance", "magnitude_sweep")) + " |")
        lines += ["", "[Receptor identities, cited signs, assumed coverage and limitations](docs/receptors.md)."]
    if (Path(root) / "src/flybrain/neuromod/plasticity.py").exists():
        from .plasticity import REFERENCE_FIXTURE
        lines += ["", "### Stage-5 reference fixture", "",
                  "These immutable diagnostic assumptions are declared in plasticity.py; they are not calibrated model defaults. "
                  "The final brief supplies the normalized equation and all twelve reference targets. No coefficients were fitted to the table or to network biology.", "",
                  "```json", json.dumps(REFERENCE_FIXTURE, indent=2, ensure_ascii=False), "```"]
    return lines
