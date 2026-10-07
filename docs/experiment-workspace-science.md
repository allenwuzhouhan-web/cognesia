# Research workspace: meanings of controls and recordings

## Selected circuits and their surroundings

A simulated selection changes the computed neural graph. A visible or recorded
selection changes what is displayed or saved. These choices must not be treated
as interchangeable. Selections are bound to source-qualified neuron identity,
model hashes, and stable parent-to-local index maps.

Selected simulations default to recorded surroundings. A matching full-context
reference supplies incoming delayed graded release and spike synaptic-state
arrivals at the neural integration timestep. The selected circuit starts with
the reference's own membrane voltage, synaptic state, refractory state and
pending delay queues. Display-rate recordings are not interpolated into a
physiological boundary signal.

Recorded surroundings are **one-way inputs**: an internal intervention cannot
change the excluded circuit's prerecorded response. Full-context verification
is necessary to investigate that feedback. Baseline and experimental branches
need their own compatible reference inputs; a stimulated external network is
not an unstimulated baseline. Manifests bind references to model, selection,
parameters, time step and protocol.

Isolated mode explicitly removes crossing edges. It records the number of
incoming/outgoing edges cut and does not renormalize remaining connections.
Full-context mode retains all neural computation while focusing analysis on the
chosen circuit. It does not promise reduced neural compute cost.

Source-population denominators must remain the full model's denominators when a
chemical source projection is sliced. Otherwise a small circuit can silently
receive exaggerated chemical influence. Automatic references also save typed
chemical and peripheral sources every 1 ms. Selected neural runs keep the full
compact compartment field and enzyme pools, the historical endocrine state
where that provider supports it, and the selected organ states. They recompute
these shared states from live local rates plus recorded outside source drive.
Full-population chemical and motor denominators are retained. Excluded neural
activity is not recomputed, and changing a shared chemical field does not cause
excluded neurons to respond differently from their reference history.

Chemical sources are recorded after the reference state normalization and
source-output gates. Separate outside endocrine rates preserve the historical
slow endocrine update clock. Outside organ motor sums preserve original module
membership and mean-rate normalization. Reference field concentrations are
saved for provenance and comparison; they do not overwrite the live field.
Precursor pools, organ states, local source filters and native delay queues
start from the same projected checkpoint. Restoring a paired branch also
rebinds that branch's distinct source recording.

Reference arrival weights and receptor release factors are captured before
each neural tick. Source silencing suppresses future releases while preserving
already queued arrivals. Numerical equivalence is tested with explicit floating
point tolerances; rearranging sparse sums is not a bitwise-equivalence claim.

## Peripheral states

Each selected source-annotated organ, muscle or sensory subdivision has its own
state and input/output ports. Motor/visceral firing drives its normalized
activation. Explicit external stimuli drive selected afferents through declared
normalized membrane-input gains. Repeated aliases do not multiply the same
sensory current. Optional modeled links must name existing neural entities and
are stored separately from source-annotated interfaces.

The current organ dynamics use a first-order activation/output response and
integrate cumulative normalized effort. These states are useful for explicit
controlled model experiments. They are not physical force, muscle strain,
heart rate, oxygen supply, metabolic flux, sound pressure or measured behavior.
Named anatomical subdivisions do not change that distinction. No missing
physiological calibration is concealed behind a physical-looking unit.

## Enzymes

The opt-in system contains [ChAT](https://flybase.org/reports/FBgn0000303),
[AChE/Ace](https://www.ncbi.nlm.nih.gov/gene/41625), and
[Tbh](https://flybase.org/reports/FBgn0010329). Their reaction identities are
sourced. Their activity multipliers, kinetic constants, precursor pools,
expression coverage and release transport in Cognesia are normalized model
assumptions.

- ChAT consumes intracellular choline and acetyl-CoA pools and produces an ACh
  release pool.
- Tbh consumes intracellular tyramine and produces an OA release pool. It does
  not convert the extracellular tyramine field into octopamine.
- AChE removes ACh from the selected chemical field compartments and records
  separate choline and acetate products. Unsupported uptake/recycling is not
  silently added.

Saturating reactions use normalized Michaelis–Menten kinetics, bounded by
available substrate. Source activity releases available product pools. The
activity value is a relative model multiplier, not measured enzyme expression
or administered dosage. Substrate-limited steps and fluxes are recorded.

In selected compartments, AChE **replaces** the old unspecified ACh field
clearance so the same removal is not counted twice. AChE inhibition therefore
does not secretly restore the old clearance. This acts on the modeled
modulatory field; the fast synaptic-current model is unchanged. Held chemical
concentrations are reapplied after reactions and remain imposed boundary
conditions. Enzyme-off operation preserves the original chemical path.

Snapshots save precursor/product pools, activity changes, instantaneous and
cumulative fluxes, field state, and clock. Experimental branches can therefore
compare enzyme interventions from the same history rather than only matching
the displayed concentration.

## New-provider chemistry

For the BANC/fused model, chemical compartments use native region-anchor
annotations, with no invented diffusion geometry. Receptor relationships from
the existing model are transferred as explicit cell-type hypotheses; they do
not establish expression magnitudes in the new specimen. The old FlyWire
15-cluster mushroom-body plasticity map and 76-cell endocrine census are not
fabricated in BANC. New-provider chemical runs require that unsupported
plasticity be off, and record that limitation. Neuron-scoped effects and
source-scoped `all_out` release effects retain their explicit receptor model
assumptions; the latter do not require an invented mushroom-body compartment.

Tests establish software properties such as enzyme-off numerical compatibility,
positive reaction pools, deterministic checkpoints, causal organ-to-neural
input, delayed boundary handling, and reduced/reference agreement in a small
fixture. They do not constitute a biological validation pass.

## Saved full-versus-selected benchmark

[`build/runtime_paired_benchmark.json`](../build/runtime_paired_benchmark.json)
records a completed 300-ms dark experiment on the actual fused graph, with
chemistry, enzymes, and a modeled left antennal chordotonal input of 0.8 a.u.
The full run integrated **175,401 neurons** and recorded eight; the reduced run
integrated the same **eight selected neurons** with recorded surroundings.
The saved raw, baseline, delta, compartment-field, enzyme-pool, and organ-state recordings
have maximum absolute differences of **zero** in this experiment.

The full run was `20261001T080416Z_visual_dark_de403c`; the selected run was
`20261001T080433Z_visual_dark_a09299`. Both used immutable model
`14a57b223bf7f1694fd84650a22a7e891a587056761ee3e763f443968cbaf8b1`
and remain `EXPERIMENTAL_UNVALIDATED`. Run manifests retain their precise
implementation fingerprints; these recorded results are not retroactively
attributed to later source changes.

Observed wall times were 15.63 s for the full paired experiment and 16.85 s for
automatic reference generation plus the selected paired experiment. These
measurements do not show a first-run speedup: producing fresh surroundings
requires a full reference run. Later selected runs can reuse compatible saved
surroundings. Preparation reads full source annotations and graph indices;
after compilation it releases the full graph and retains selected neural
matrices plus the required compact shared fields and source normalization.

The original core prerequisites were rerun on 2026-10-01 without weakening their
expected counts or tolerances: field numerics V-NM-D, receptor software V-NM-A,
plasticity software V-NM-E, and source-backed odour mapping V-NM-ODOUR passed.
The separate V-NM-CORE validation attempt failed before measuring equilibrium
because its required historical `build/validation_hybrid.json` input is absent.
That failure remains saved as `stationarity_execution`; the missing comparison
was not replaced with synthetic evidence. These software gates do not alter
the historical failed biological or performance gates.
