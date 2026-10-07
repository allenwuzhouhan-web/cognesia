# Explicit interpretation decisions

These decisions are declared before simulation results are observed. They are not parameter changes made to pass biological tests.

## Graded equations and units

The brief writes a capacitance equation whose terms do not share physical units. The implementable uniform model uses a normalized passive voltage state:

```
dV/dt = (V_rest - V + g) / tau_membrane
dg/dt = -g / tau_synapse + graded_gain * sum(signed_synapse_count * max(0, V_pre_delayed - V_release))
```

Both V and g are in mV. `graded_gain` is in 1/(ms*synapse). Spike arrivals add `signed_synapse_count * spike_weight` mV to g. This convention supports both graded and spiking postsynaptic neurons without mixing current and voltage. Physical capacitance is absorbed into the normalization and is not claimed to have been measured. This is an explicit correction of the brief's dimensional inconsistency, not literal implementation of that equation.

The uniform gain is predeclared as 0.0001/(ms*synapse), with a tenfold sweep (0.00003–0.0003). No simulation output informed this choice. No silent gain normalization by in-degree is allowed. Every other uniform graded parameter is an assumption listed in `config/parameters.yaml`.

For the first hybrid implementation, all states use the common fine timestep of 0.1 ms. The permitted 0.5 ms graded step is an upper bound, not a coarser clock forced onto the 1.8 ms synaptic delay. Actual and requested timestep values are recorded explicitly. This prioritizes delay correctness; multirate acceleration is deferred.

## Reference compatibility

Shiu's actual code freezes V and g during refractory periods, clears g on reset, uses a strict threshold, and blocks synaptic writes during refractory periods. Its external Poisson input changes V directly and sets driven-neuron refractory time to zero. The reference comparison must preserve these details and share exact event times across engines. Raw signed connectome counts are used for both sides of the reference comparison; corrected photoreceptor signs belong to the biological hybrid model.

The source uses exact coupled linear integration. A reference-compatible exact update and an exponential-Euler production update must be distinguished in run metadata. Passing the exact update against Brian2 alone is not evidence that a different integrator has passed.

## Eye and fitted parameters

Cell coordinates in the annotation table are not a replacement for Mi1 medulla synapse centroids. A missing retinotopy export must trigger the specified real-synapse fallback, never an invented ordering by root ID.

Flyvis voltages are in arbitrary units. Import requires an explicit affine conversion, fit ID, and calibration provenance; until implemented and verified, that mode must fail clearly rather than quietly use uniform parameters.

## Gates

V-A checks the immutable release facts. The HS/VS row in the brief is a formatting ambiguity: the measured families are HS=3 per side and VS=16 per side, and the V-A evidence enumerates their members. V-B through V-E must be reported on executed configurations. Hardware/source errors and absent prerequisites produce FAIL or NOT-RUN, not PASS. A scientific model may fail a requested stationarity or zero-spike criterion even when its numerical implementation is correct; the stage must still stop and record that result.
