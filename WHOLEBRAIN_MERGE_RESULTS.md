# Whole-brain chemistry integration

The original whole-brain viewer now includes the chemical and internal-state
model. Both launchers open http://127.0.0.1:8794 with simulation and playback
stopped. The previous small-core service on port 8795 was stopped.

## Implemented

- The original 138,639-neuron graded/spiking brain retains all 15,091,983 released
  connections. Receptors, endocrine state and KC-to-MBON plasticity affect this
  same network. The disabled path preserves the original experiment behavior.
- The existing 3D neurons and branches can show any of eight recorded chemical
  fields. Voltage, optical input, electrodes, paired baselines and comparison
  charts remain available.
- Fed, Starved, Dehydrated and Stressed presets initialize declared model state.
  Recorded state and concentration traces share the neural playback clock.
- Stop terminates active viewer jobs and freezes playback. Clear cache removes
  generated display assets and browser buffers while preserving saved experiments.

## Verification

The full Python suite passed **528 tests**. Subsequent focused server/assets tests
passed **39 tests**, and frontend numerical/interaction tests passed **17 tests**.
An independent review checked complete paired-state restoration, source and edge
identity, scoped receptor effects, causal sample times and source hashes.

Two real full-brain tests ran with the same full-field flash and parameters:
100 ms preequilibration followed by 1,000 ms stimulus and 1,000 ms matched baseline,
recorded every 20 ms. These are bounded integration checks, not biological gates.

| Measurement | Result |
|---|---:|
| Full neurons recorded per frame | 138,639 |
| Chemical array per scenario | 50 × 8 species × 96 compartments |
| Neurons with assigned compartment exposure | 112,670 |
| Neurons left explicitly unassigned | 25,969 |
| Fed/starved maximum voltage difference | 0.109158 mV |
| Fed/starved maximum field difference | 0.015356 model units |
| Fed test wall time | 56.517 s |
| Starved test wall time | 56.574 s |

Both scenarios produced finite exported neural and chemical arrays with matching
times and neuron order. Starved energy starts at 0; fed energy starts at 1. The
paired baseline restores the same complete neural, chemical and plastic state.

The initial cache cleanup removed **201,726,861 bytes** of regenerable viewer
assets. Raw sources, master morphology, recorded runs and validation evidence
were preserved. Cache files can be recreated when their view is reopened.

## Evidence and interpretation

[Measured integration results](build/wholebrain_merge_check.json) ·
[Run log](build/wholebrain_merge_check.log) ·
[Full test log](build/wholebrain_merge_tests.log) ·
[Cache cleanup](build/wholebrain_merge_cache_cleanup.json) ·
[Controls and model assumptions](docs/wholebrain_chemistry.md)

Chemical colours show compartment-level model concentrations projected onto
assigned anatomy. They do not show individual molecule trajectories. The
original whole-brain stability limitations remain; the previous small-core
validation does not certify this integration's biology.
