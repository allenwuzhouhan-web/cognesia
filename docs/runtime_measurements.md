# Coupled runtime measurements

`flybrain.rt.validation` runs the released core through the actual field,
receptor, plasticity, odor and endocrine implementations. It never fits a
coefficient to a biological outcome. F retains the PPL101 empirical/published
compartment discrepancy. Its zero-crossing bracket is measured, and a 500 ms
near-zero tolerance is explicitly an assumed one-pulse-width criterion.

G subtracts a same-seed, same-odor no-pulse control. Its concentration clamp is
marked simulation-only. H measures both PPL101 and PAM01 training directions
using frozen trained weights, fresh fast state, and window-mean MBON rates.
The signed rate is inferred valence, not a motor decoder. K compares repeated
unreinforced exposure with passive forgetting and a causal diagnostic that
temporarily zeros only MBON-to-DAN edges. The diagnostic restores every removed
value; it does not change the production connectome. J uses identical odor,
seed, parameters and fixed memory for fed/starved initial endocrine states.

B records a full 60-second session, reads its saved event log, then compares
every spike and final weight hash after replay. It also checks voltages,
conductances, fields, traces and the endocrine snapshot. F-prime measures the
same run after compilation. Its 50 Hz frame timing includes the complete
20 ms advance call, recording and snapshot overhead. Passing requires RTF at
least 1.2, at most 1% frame overruns and sampled RSS no more than 4 GB. Sampled
RSS is explicitly not an OS high-water mark. Per-tick timings remain diagnostic.

`flybrain capacity --full` measures every addressable positive-annotation or
endocrine cell-type handle in the core. The default is a two-handle pilot.
The bounded task has OCT/MCH and approach/avoid intended actions; exactly zero
inferred valence is a separate observed outcome. Each handle trains two opposite
odor assignments for three seconds each. Two independent held-out Poisson seeds
test both odors for 500 ms with memory frozen. These durations and the task
instructions are assumptions, not fitted biological effects. An untrained
same-seed baseline separates innate odor information from changes after writing.

The full inventory uses four isolated worker processes by default; the pilot
uses one. The Python `measure_capacity(..., workers=...)` API accepts an integer
from one to four. Each worker constructs one runtime and reuses it for its
assigned handles, with unique session directories and a separate progress JSON
under the UUID-named capacity run directory. The parent computes the shared
baseline, merges results into the original inventory order, and alone writes
the global validation JSON and CSVs. Training seeds, held-out seeds, event order,
weight checks and statistical seeds remain independent of worker scheduling.
The parent applies BH correction once across all measured handles. Worker
progress preserves completed trials if a batch fails, and an error terminates
the remaining pool. Launch parallel runs through the CLI or a Python script
with a guarded main entry point, as required by the `spawn` process method.
This execution strategy carries no measured speedup or real-time claim.

The empirical MI, 95% protocol-cluster bootstrap interval, at least 1,000
shuffled-protocol draws, empirical `(exceedances+1)/(B+1)` p value and BH q value
are saved for each handle. All test seeds sharing trained memory stay in the
same cluster. Two opposite trained assignments alone have very low null
resolution: increasing the Monte Carlo count cannot create independent training
replicates. A nonsignificant result remains nonsignificant.

The curve pools a fixed prefix of the enumerated handle inventory; it is not an
optimization over handle combinations. This finite two-odor task cannot establish
asymptotic capacity or a saturation point. No verified type-to-driver-line table
exists in this build. Its absence means unknown physical accessibility, not zero
available drivers. The physical interface gap remains unquantifiable and is
reported as such rather than converted into an invented bandwidth number.
