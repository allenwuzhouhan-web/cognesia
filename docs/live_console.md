# Coupled core console

Start with `.venv/bin/flybrain rt serve --core`, then open
http://127.0.0.1:8795. The engine starts running after compilation. Pause, step,
reset, odour, named source and state controls use simulation milliseconds.
The separate visual observatory remains on port 8794.

The console runs the normative 13,300-neuron core. The released core has
1,161,917 edges; the explicitly configured thresholded KC recurrence policy
retains 927,567. All 62,261 KC→MBON plastic edges remain. Real released soma
coordinates supply the atlas; missing coordinates are omitted.

## Clock and coupling

Every 1 ms, the same ten 0.1-ms LIF steps execute in the validated base event
order. A deterministic seeded Poisson source provides ORN and externally driven
source afferents. Poisson splitting generates counts over the 1-ms interval,
then assigns individual events to ten bins; multiple events are preserved.
ORN transduction is held constant over that interval. Recurrent spikes are
actual network outputs, never prescribed rate traces.

The exponential rate estimate uses the configured 20-ms time constant. After
the neural interval, source rates update the field, the new DA concentration
updates normalized eligibility traces and weights, and receptor factors apply
to the next neural interval. State updates every 1,000 model ms. The full-model
source denominators are retained; sources outside the core contribute zero.

Plastic efficacy is in synapse-count equivalents, initialized to the actual
released count on each edge. The supplied eta therefore changes absolute counts
per edge; the display divides by that edge's baseline. No scalar fit is applied
to make network plasticity match the isolated unit-weight reference.

Release factors are shared only among edges with identical receptor row
membership and identical concentration exposure. This reduces repeated work,
without deleting connections or changing their counts. A compiled serial kernel
preserves the base delay, threshold, refractory, input and reset ordering.

The engine owns its state on one thread. HTTP and WebSocket clients read immutable
published snapshots. Binary Float32 frames carry a versioned layout, simulation
time, timestep, measured compute speed and sequence number. Rendering can drop
frames; it cannot advance model time. A speed below 1 means the model is running
slower than the wall clock, with the original integration timestep preserved.

## Experiments and recording

```
.venv/bin/flybrain neuromod build
.venv/bin/pytest -q
.venv/bin/flybrain train protocols/forward_pairing_gamma1.yaml
.venv/bin/flybrain capacity --full
.venv/bin/flybrain validate --gate neuromod-runtime
.venv/bin/flybrain replay runs/neuromod/<session>/events.jsonl
```

Each session saves ordered JSONL controls, complete int32 spike indices and int64
base-step timestamps, reduced display frames, seed, configuration/implementation
hashes and final weights. ZIP export includes metadata and the configuration
files. Replay rejects a changed implementation/configuration and compares every
spike index, spike timestep and final weight by digest. Chunk sizes and browser
frame dropping do not affect the dynamics.

Protocol YAML is parsed as data. Overlapping odours or source pulses are rejected.
At a shared boundary, an old stimulus ends before the new one starts. Test odours
run sequentially with the specified intertrial interval. A `test` block disables
plasticity across all its odours and intervening ITIs, then restores the exact
setting observed when that block began, including an already disabled setting.
The runner checks that the trained-weight hashes match before and after the
test. Overlapping training or explicit plasticity controls are rejected; manually
enabling plasticity during a test stops it before another interval executes.
The CLI training result includes these frozen-weight checks. Signed pairing
delays must be integer milliseconds. Generic `control` blocks may have zero
duration, so an exported control at the final timestamp adds no model time.
Other block durations must be positive. The nominal gamma1
protocol stimulates actual PPL101 cells: their empirical assignment is g4, so
the anatomical disagreement is exported instead of changing their identity.

## Interpretation

The corrected twelve-point plasticity reference validates software. It does not
validate the closed-loop network. Driven voltage bounds and KC sparseness have
failed in this model and remain explicit measurements. Voltage clamping is off.
The new normalized whole-brain stability variant is separate from the historical
base V-C failure, and passing its resting checks does not validate its visual
response. There is no validated body or motor decoder; the MBON valence display
uses published-sign inference and retains unknown types as unassigned.

Direct concentration clamps are simulation-only controls. Named cell types are
addressable in the model; this does not establish genetic driver-line access.
Field/receptor/state magnitudes, rate conversion and compartment generalization
are explicit assumptions. No parameter search was used to force biological gates
to pass. Detailed measurements and current provenance appear in REPORT.md.
