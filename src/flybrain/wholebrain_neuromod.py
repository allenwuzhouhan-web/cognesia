"""Experimental chemical/state coupling for the complete original visual network.

This does not modify or certify the original HybridEngine. Disabled runs delegate
unchanged. Active runs retain every released graded/spiking edge and its delay,
while chemical fields change named receptor parameters and KC->MBON weights.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import time
from pathlib import Path

import numba as nb
from numba.typed import List
import numpy as np
from scipy import sparse
import yaml

from .engine import _integer_array
from .hybrid_engine import HybridEngine
from .memguard import check_memory
from .neuromod.compartments import load_compartments
from .neuromod.field import FieldEngine, FieldParameters, FIELD_SPECIES, build_source_projection
from .neuromod.receptors import ReceptorModel, read_receptors, receptor_bounds
from .neuromod.plasticity import NormalizedPlasticity, parameters_from_root, load_compartment_rules, normalize_kc_rates
from .neuromod.state import EndocrineState, STATE_NAMES, HORMONES, INITIAL_STATE
from .rt.engine_rt import FastReceptors
from .enzymes import EnzymeSystem, normalize_enzyme_options

SCENARIOS = {
    'baseline': {}, 'fed': {}, 'starved': {'energy': 0.},
    'dehydrated': {'hydration': 0.}, 'stressed': {'stress': 1.},
}
CHEMICAL_INPUT_FILES = (
    'config/neuromod.yaml', 'config/receptors.csv', 'config/compartment_rules.csv',
    'config/endocrine_sources.csv', 'build/compartments.npz',
    'build/compartments_metadata.json', 'build/validation_neuromod_sources.json',
    'build/validation_neuromod_compartments.json',
    'src/flybrain/wholebrain_neuromod.py', 'src/flybrain/neuromod/field.py',
    'src/flybrain/neuromod/receptors.py', 'src/flybrain/neuromod/plasticity.py',
    'src/flybrain/neuromod/state.py', 'src/flybrain/neuromod/sources.py',
    'src/flybrain/neuromod/compartments.py', 'src/flybrain/rt/engine_rt.py',
    'src/flybrain/enzymes.py',
)
ASSUMPTIONS = [
    'EXPERIMENTAL_UNVALIDATED: original whole-brain voltage clamps and failed base stability remain; core validation does not certify this new coupling.',
    'Fields are spatially coarse compartment concentrations in arbitrary units, not measured molecular concentrations or simulated particle trajectories.',
    'Neuron exposure is the equal weighted mean over its assigned compartments; unassigned neurons have unknown exposure, not measured zero.',
    'Source release sites inherit coarse anatomical membership; compartment spillover uses the saved adjacency, not anatomical diffusion.',
    'Spiking source rates use the configured exponential rate estimator. Graded source rate-equivalent drive is clipped positive voltage above graded_release divided by 10 mV, times state_source_max_rate_hz; this conversion is an explicit new assumption.',
    'Receptor expressions, gains, time constants and release magnitudes retain their cited or assumed table provenance. Chemicals are never injected as additive membrane current.',
    'Named hormone secretion and state coupling reuse EndocrineState. Starvation/dehydration/stress presets change normalized initial boundary state; time constants remain model assumptions.',
    'Plasticity uses actual full-network KC-to-MBON synapses and empirical MBON compartments; no core-only edge deletion or canonical anatomical remapping is applied.',
    'Chemical state at each voltage frame is its start-slot value; new field/receptor effects apply to the next 1-ms neural interval.',
    'Optional chemical controls impose a uniform model concentration in every compartment, including normally unoccupied volumes. They are experimental interventions, not measured secretion or hormone levels. Missing species remain endogenous.',
]


def normalize_neuromod_options(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('neuromod must be an object')
    allowed = {'enabled','scenario','plasticity_enabled','initial_state','feeding','drinking','locomotion','aversive',
               'chemical_levels','chemical_control_mode','enzymes'}
    if set(value) - allowed:
        raise ValueError('Unknown neuromod option: '+', '.join(sorted(set(value)-allowed)))
    enabled, plastic = value.get('enabled',False), value.get('plasticity_enabled',True)
    if not isinstance(enabled,bool) or not isinstance(plastic,bool):
        raise ValueError('neuromod enabled and plasticity_enabled must be booleans')
    scenario = value.get('scenario','fed')
    if not isinstance(scenario,str) or scenario not in SCENARIOS:
        raise ValueError('Unknown neuromod scenario')
    override = value.get('initial_state',{})
    if not isinstance(override,dict) or set(override)-set(STATE_NAMES):
        raise ValueError('initial_state must contain only recognized normalized state variables')
    initial = dict(INITIAL_STATE) | SCENARIOS[scenario] | override
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not np.isfinite(x) for x in initial.values()):
        raise ValueError('Initial state must contain finite numeric values')
    EndocrineState._validate_state(initial)
    mode = value.get('chemical_control_mode','initial')
    if not isinstance(mode,str) or mode not in {'initial','clamped'}:
        raise ValueError('chemical_control_mode must be initial or clamped')
    levels = value.get('chemical_levels',{})
    if not isinstance(levels,dict) or any(name not in FIELD_SPECIES for name in levels):
        raise ValueError('chemical_levels must map recognized chemical species to model concentrations')
    normalized_levels = {}
    for name,level in levels.items():
        if isinstance(level,bool) or not isinstance(level,(int,float)):
            raise ValueError('chemical_levels.'+name+' must be a finite number on [0,2] a.u.')
        try:
            number = float(level)
        except (OverflowError,ValueError):
            raise ValueError('chemical_levels.'+name+' must be a finite number on [0,2] a.u.') from None
        if not np.isfinite(number) or not 0 <= number <= 2:
            raise ValueError('chemical_levels.'+name+' must be a finite number on [0,2] a.u.')
        normalized_levels[name] = number
    result = {'enabled':enabled,'scenario':scenario,'plasticity_enabled':plastic,
              'initial_state':{k:float(v) for k,v in initial.items()},
              'chemical_levels':normalized_levels,'chemical_control_mode':mode}
    result['enzymes'] = normalize_enzyme_options(value.get('enzymes'))
    if result['enzymes']['enabled'] and not enabled:
        raise ValueError('Enable the chemical layer to use enzyme reactions')
    for name in ('feeding','drinking','locomotion','aversive'):
        v=value.get(name,0.)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) or not 0<=v<=1:
            raise ValueError(name+' must be a finite number on [0,1]')
        result[name]=float(v)
    return result


class WholeBrainChemistry:
    """Stateful coupling, bound to exact full-network IDs and sorted spike edges."""
    def __init__(self, engine, neurons, mapping, options, field_parameters, receptor_rows,
                 state, nm, plastic_parameters, signs, scales, *, bounds=None, source_neurons=None, model_indices=None):
        self.engine, self.neurons, self.mapping = engine, neurons, mapping
        self.options = normalize_neuromod_options(options)
        self.nm = dict(nm)
        source_neurons = neurons if source_neurons is None else source_neurons
        self.source_population_size = len(source_neurons)
        self.model_indices = np.arange(len(neurons)) if model_indices is None else np.asarray(model_indices,np.int64)
        self.boundary = None
        if not np.array_equal(neurons.root_id.to_numpy(np.int64),mapping.model_root_ids[self.model_indices]):
            raise ValueError('Full-brain chemical mapping differs from model neuron order')
        self.tick_steps = engine._steps(field_parameters.dt_mod_ms,'chemical_tick_ms')
        if field_parameters.dt_mod_ms != 1 or not self.tick_steps or self.nm['dt_plast_ms'] != 1:
            raise ValueError('Whole-brain chemistry currently requires 1-ms field and plasticity ticks')
        if not np.isclose(self.tick_steps*engine.dt,1.,rtol=0,atol=1e-10):
            raise ValueError('Neural timestep must divide the 1-ms chemical tick exactly')
        projection = build_source_projection(source_neurons,mapping)
        if self.source_population_size != len(neurons):
            from .selection import slice_source_projection
            projection = slice_source_projection(projection,self.model_indices)
        self.field = FieldEngine(field_parameters,mapping.names,mapping.adjacency,projection)
        self.enzymes = EnzymeSystem(self.options['enzymes'], mapping.names)
        self.enzymes.configure_field(self.field)
        if any(v > field_parameters.concentration_max_au for v in self.options['chemical_levels'].values()):
            raise ValueError('Chemical control exceeds the configured concentration bound')
        self.apply_chemical_levels()
        weights = sparse.csc_matrix((engine.csc_counts,engine.csc_indices,engine.csc_indptr),shape=(engine.n_neurons,engine.n_neurons))
        self.receptors = ReceptorModel(receptor_rows,neurons,mapping,weights,model_indices=self.model_indices,bounds=bounds)
        if not np.array_equal(self.receptors.edge_post,engine.csc_indices):
            raise ValueError('Receptor edge order differs from the original engine CSC order')
        # Every currently enabled all-out release row targets spiking DANs. Reject
        # an unsupported future graded release row instead of silently ignoring it.
        for row,(target,edges) in zip(self.receptors.rows,self.receptors.targets,strict=True):
            if row['enabled'] and row['effect']=='release_prob' and np.any(target & engine.graded_mask):
                raise ValueError('Graded edge-scoped release receptor rows need a graded-edge adapter')
        self.effects = FastReceptors(self.receptors)
        self.membership = self.receptors.membership.tocsr()
        if self.source_population_size != len(neurons):
            self.mapping = replace(mapping, membership=mapping.membership[:,self.model_indices],
                mb_assignment=mapping.mb_assignment[self.model_indices],model_root_ids=mapping.model_root_ids[self.model_indices])
        self.state = state
        self.state.reset(self.options['initial_state'])
        self.state_output = self.state.outputs()
        self.rates_hz = np.zeros(engine.n_neurons)
        self.kc_indices = np.flatnonzero(neurons.cell_type.fillna('').str.startswith('KC').to_numpy()).astype(np.int32)
        self.plastic_csc = np.flatnonzero(self.receptors.plastic_edges).astype(np.int32)
        compartment = self.receptors.edge_compartment[self.plastic_csc]
        if np.any(compartment<0) or np.any(compartment>=15) :
            raise ValueError('KC-to-MBON plasticity requires empirical MB compartments and KCs')
        position = np.full(engine.n_neurons,-1,np.int32)
        position[self.kc_indices] = np.arange(len(self.kc_indices))
        baseline = engine.csc_counts[self.plastic_csc]
        if np.any(baseline < 0):
            raise ValueError('KC-to-MBON baseline weights must be nonnegative')
        self.plasticity = NormalizedPlasticity(max(1,len(self.kc_indices)),15,
            position[self.receptors.edge_pre[self.plastic_csc]],compartment,baseline,
            plastic_parameters,compartment_sign=signs,compartment_scale=scales)
        self.saturation_count=0
        self.last_source_rates = np.zeros(engine.n_neurons)
        self.update_effects()

    @classmethod
    def from_root(cls, root, engine, neurons, options, *, source_neurons=None, model_indices=None):
        root=Path(root)
        source_neurons = neurons if source_neurons is None else source_neurons
        mapping=load_compartments(root)
        nm={k:v['value'] for k,v in yaml.safe_load((root/'config/neuromod.yaml').read_text())['parameters'].items()}
        signs,scales,_=load_compartment_rules(root,mapping.names[:15])
        return cls(engine,neurons,mapping,options,FieldParameters.from_root(root),
            read_receptors(root/'config/receptors.csv'),EndocrineState.from_root(root,source_neurons),nm,
            parameters_from_root(root),signs,scales,bounds=receptor_bounds(root),source_neurons=source_neurons,model_indices=model_indices)

    def update_effects(self):
        self.effects.evaluate(self.field.C,self.state_output['gain_factor'][self.model_indices])
        self.engine.decay_v_each[:] = np.exp(-self.engine.dt/(self.engine.tau_membrane*self.effects.tau_factor))

    def apply_chemical_levels(self):
        """Apply only explicitly controlled species; a requested zero is active."""
        for name,level in self.options['chemical_levels'].items():
            self.field.C[FIELD_SPECIES.index(name),:] = level

    def advance(self, spike_indices):
        counts=np.bincount(spike_indices,minlength=self.engine.n_neurons)
        target=counts*1000.
        graded=self.engine.graded_mask
        target[graded]=np.clip((self.engine.v[graded]-self.engine.parameters['graded_release'])/10.,0.,1.)*self.nm['state_source_max_rate_hz']
        self.rates_hz += -np.expm1(-1/self.nm['runtime_rate_tau_ms'])*(target-self.rates_hz)
        boundary_tick = self.boundary.chemical_tick(self.engine.step) if self.boundary is not None else None
        if self.engine.step % self.engine._steps(self.nm['state_dt_ms'],'state_dt_ms')==0:
            full_rates = np.zeros(self.source_population_size)
            if boundary_tick is not None:
                full_rates[boundary_tick['endocrine_indices']] = boundary_tick['endocrine_rates']
            full_rates[self.model_indices] = self.rates_hz
            self.state.step(self.nm['state_dt_ms'],full_rates,**{k:self.options[k] for k in ('feeding','drinking','locomotion','aversive')})
            self.state_output=self.state.outputs()
        source_rates=self.rates_hz*self.state_output['source_rate_scale'][self.model_indices]
        mask=self.state_output['endocrine_mask'][self.model_indices]
        source_rates[mask]=self.state_output['endocrine_drive'][self.model_indices][mask]*self.state_output['source_max_rate_hz']
        source_rates[~self.engine.output_enabled] = 0.
        # Multiplication above allocated this tick's snapshot; never aliases rates_hz.
        self.last_source_rates = source_rates
        drive = self.field.projection.mean_rates_hz(source_rates)/self.field.parameters.max_source_rate_hz[:,None]
        if boundary_tick is not None: drive += boundary_tick['source_drive']
        if self.enzymes.enabled: self.enzymes.step(self.field, drive, 1.)
        else: self.field.advance_drive(drive)
        if self.options['chemical_control_mode'] == 'clamped':
            # Field release/clearance/spillover advances first. The controlled
            # boundary then replaces selected species so both plasticity and
            # next-tick receptor effects consume the same imposed concentration.
            self.apply_chemical_levels()
        if self.options['plasticity_enabled']:
            drive,saturated=normalize_kc_rates(self.rates_hz[self.kc_indices] if len(self.kc_indices) else np.zeros(1),self.nm['max_kc_rate_hz'])
            self.saturation_count+=saturated
            self.plasticity.step(drive,self.field.C[FIELD_SPECIES.index('DA'),:15],1.)
            self.engine.csc_counts[self.plastic_csc]=self.plasticity.weights
        self.update_effects()
        if not np.isfinite(self.engine.v).all() or not np.isfinite(self.engine.g).all():
            raise FloatingPointError('Nonfinite full-brain neural state during chemical coupling')

    def empty_recording(self, count):
        result = {'concentrations_au':np.empty((count,len(FIELD_SPECIES),len(self.mapping.names)),np.float32),
                'state_values':np.empty((count,len(STATE_NAMES)),np.float32),
                'hormones_au':np.empty((count,len(HORMONES)),np.float32),
                'plasticity_change_l1':np.empty(count,np.float64)}
        if self.enzymes.enabled:
            result['enzyme_pools_au'] = np.empty((count,*self.enzymes.pools.shape),np.float64)
            result['enzyme_flux_au_per_ms'] = np.empty((count,*self.enzymes.flux.shape),np.float64)
        return result

    def capture(self, output, first, last):
        output['concentrations_au'][first:last]=self.field.C
        output['state_values'][first:last]=[self.state.state[n] for n in STATE_NAMES]
        output['hormones_au'][first:last]=[self.state.hormones[n] for n in HORMONES]
        output['plasticity_change_l1'][first:last]=float(np.abs(self.plasticity.weights-self.plasticity.w0).sum())
        if self.enzymes.enabled:
            output['enzyme_pools_au'][first:last] = self.enzymes.pools
            output['enzyme_flux_au_per_ms'][first:last] = self.enzymes.flux

    def diagnostics(self):
        return {'field_clamps':int(self.field.clamp_count),'receptor_guards':int(self.effects.guard_events),
                'weight_clamps':int(self.plasticity.weight_clamp_events),'kc_rate_saturations':int(self.saturation_count),
                'plastic_edges':int(len(self.plastic_csc)),
                'weight_change_l1':float(np.abs(self.plasticity.weights-self.plasticity.w0).sum()),
                'enzymes_enabled':self.enzymes.enabled, 'substrate_limited_reactions':self.enzymes.limited_reactions}

    def snapshot(self):
        return {'field_C':self.field.C.copy(),'field_steps':self.field.steps,'field_clamps':self.field.clamp_count,
                'state':self.state.snapshot(),'rates_hz':self.rates_hz.copy(),
                'weights':self.plasticity.weights.copy(),'e_pre':self.plasticity.e_pre.copy(),'e_da':self.plasticity.e_da.copy(),
                'weight_clamps':self.plasticity.weight_clamp_events,'movement':self.plasticity.total_absolute_weight_change,
                'receptor_guards':self.effects.guard_events,'saturations':self.saturation_count,
                'enzymes':self.enzymes.snapshot()}

    def restore(self, saved):
        self.field.C[:]=saved['field_C'];self.field.steps=saved['field_steps'];self.field.clamp_count=saved['field_clamps']
        self.state.restore(copy.deepcopy(saved['state']));self.state_output=self.state.outputs()
        self.rates_hz[:]=saved['rates_hz']
        for name in ('weights','e_pre','e_da'): getattr(self.plasticity,name)[:]=saved[name]
        self.plasticity.weight_clamp_events=saved['weight_clamps'];self.plasticity.total_absolute_weight_change=saved['movement']
        self.saturation_count=saved['saturations']
        if 'enzymes' in saved: self.enzymes.restore(saved['enzymes'])
        elif self.enzymes.enabled: raise ValueError('Snapshot lacks active enzyme state')
        self.engine.csc_counts[self.plastic_csc]=self.plasticity.weights
        self.update_effects();self.effects.guard_events=saved['receptor_guards']

    def reset(self):
        self.field.reset(); self.state.reset(self.options['initial_state'])
        self.enzymes.reset(); self.enzymes.configure_field(self.field)
        self.apply_chemical_levels()
        self.state_output=self.state.outputs(); self.rates_hz.fill(0)
        self.plasticity.weights[:]=self.plasticity.w0
        self.plasticity.e_pre.fill(0); self.plasticity.e_da.fill(0)
        self.plasticity.weight_clamp_events=0
        self.plasticity.total_absolute_weight_change=0.
        self.engine.csc_counts[self.plastic_csc]=self.plasticity.w0
        self.saturation_count=0; self.effects.guard_events=0
        self.update_effects()

    def metadata(self):
        return {'schema_version':1,'enabled':True,'scenario':self.options['scenario'],
                'options':copy.deepcopy(self.options),'species':list(FIELD_SPECIES),'compartments':list(self.mapping.names),
                'state_names':list(STATE_NAMES),'hormone_names':list(HORMONES),'units':'a.u.',
                'neurons':self.engine.n_neurons,'neuron_order':'Global released model row order',
                'assumptions':ASSUMPTIONS,'source_projection':self.field.projection.metadata,
                'receptor_coverage':self.receptors.coverage,'chemical_tick_ms':1.,
                'enzymes':self.enzymes.metadata(),
                'state_tick_ms':self.nm['state_dt_ms'],'graded_release_scale_mV':10.,
                'chemical_intervention':{
                    'active':bool(self.options['chemical_levels']),
                    'mode':self.options['chemical_control_mode'],
                    'levels_au':dict(self.options['chemical_levels']),
                    'scope':'Uniform concentration in all model compartments; missing species remain endogenous',
                    'initialization':'Applied before the first receptor evaluation and before preequilibration; reset reapplies it, paired snapshot restore preserves the evolved concentration',
                    'ordering':'Clamped mode reapplies levels after each 1-ms field update, before plasticity and next-interval receptor evaluation',
                    'interpretation':'ASSUMPTION: imposed field boundary, including normally unoccupied volumes; not additive membrane current, physical dose, or measured endocrine secretion',
                    'storage_dtype':'float32'},
                'membership_policy':'Equal normalized compartment weights; missing membership means anatomically unassigned exposure'}


@nb.njit(cache=True, parallel=True, fastmath=False)
def _advance_modulated_hybrid(v, g, graded, last_spike, refractory_steps, active, firing,
                    spike_ring, spike_ring_counts, release_history, clamp_counts,
                    graded_indptr, graded_indices, graded_counts,
                    spike_indptr, spike_indices, spike_counts,
                    start, stop, run_start, delay_steps, decay_v, decay_g,
                    synaptic_forcing_scale, rest, release_threshold, gain,
                    reset, threshold, spike_weight, minimum, maximum,
                    photo_map, photo_drive, drive_mode, records, record_stride,
                    record_start, voltages, receptor_gain, receptor_threshold, release_group, receptor_release,
                    boundary_graded_release, boundary_spike_delta, output_enabled):
    output_indices = List.empty_list(nb.int32)
    output_steps = List.empty_list(nb.int64)
    n = len(v)
    for step in range(start, stop):
        if step % record_stride == 0:
            row = step // record_stride - record_start
            for j in range(len(records)):
                voltages[row, j] = v[records[j]]

        # Snapshot release before ANY neuron is advanced, including delay=0.
        history_now = step % len(release_history)
        for neuron in nb.prange(n):
            release_history[history_now, neuron] = max(0.0, v[neuron] - release_threshold) if graded[neuron] and output_enabled[neuron] else 0.0
        history_delayed = (step - delay_steps) % len(release_history)

        for neuron in nb.prange(n):
            eligible = graded[neuron] or step - last_spike[neuron] >= refractory_steps[neuron]
            active[neuron] = eligible
            firing[neuron] = False
            if eligible:
                # Row ownership and fixed edge order keep sums deterministic.
                release_sum = 0.0
                for edge in range(graded_indptr[neuron], graded_indptr[neuron + 1]):
                    pre = graded_indices[edge]
                    release_sum += graded_counts[edge] * release_history[history_delayed, pre]
                if len(boundary_graded_release):
                    release_sum += boundary_graded_release[step-run_start,neuron]
                current = 0.0
                photo = photo_map[neuron]
                if photo >= 0:
                    if drive_mode == 0:
                        current = photo_drive[0, 0]
                    elif drive_mode == 1:
                        current = photo_drive[step - run_start, 0]
                    else:
                        current = photo_drive[step - run_start, photo]
                old_g = g[neuron]
                updated = (rest[neuron] + (v[neuron] - rest[neuron]) * decay_v[neuron]
                           + (old_g + current) * receptor_gain[neuron] * (1.0 - decay_v[neuron]))
                g[neuron] = old_g * decay_g[neuron] + synaptic_forcing_scale[neuron] * gain * release_sum
                if updated < minimum:
                    updated = minimum
                    clamp_counts[neuron] += 1
                elif updated > maximum:
                    updated = maximum
                    clamp_counts[neuron] += 1
                v[neuron] = updated
                if not graded[neuron] and updated > rest[neuron] + (threshold - rest[neuron]) * receptor_threshold[neuron]:
                    firing[neuron] = True
                    active[neuron] = False
                    last_spike[neuron] = step

        future = (step + delay_steps) % len(spike_ring_counts)
        count = 0
        for neuron in range(n):
            if firing[neuron]:
                if output_enabled[neuron]:
                    spike_ring[future, count] = neuron
                    count += 1
                output_indices.append(np.int32(neuron))
                output_steps.append(np.int64(step))
        spike_ring_counts[future] = count
        current = step % len(spike_ring_counts)
        for j in range(spike_ring_counts[current]):
            pre = spike_ring[current, j]
            for edge in range(spike_indptr[pre], spike_indptr[pre + 1]):
                post = spike_indices[edge]
                if active[post]:
                    g[post] += spike_counts[edge] * spike_weight * receptor_release[release_group[edge]]
        spike_ring_counts[current] = 0
        if len(boundary_spike_delta):
            for neuron in range(n):
                if active[neuron]: g[neuron] += boundary_spike_delta[step-run_start,neuron]
        for neuron in nb.prange(n):
            if firing[neuron]:
                v[neuron] = reset
                g[neuron] = 0.0
    return np.asarray(output_indices), np.asarray(output_steps)


class WholeBrainNeuromodEngine(HybridEngine):
    """Original hybrid network with opt-in, causal 1-ms chemical feedback."""
    def __init__(self, graded_counts, spiking_counts, graded_mask, parameters, dt=None,
                 threads=16, *, root=None, neurons=None, neuromod=None, chemistry_factory=None):
        self.chemistry=None
        super().__init__(graded_counts,spiking_counts,graded_mask,parameters,dt,threads)
        self.neuromod_options=normalize_neuromod_options(neuromod)
        if self.neuromod_options['enabled']:
            if chemistry_factory is not None:
                self.chemistry=chemistry_factory(self)
            else:
                if root is None or neurons is None:
                    raise ValueError('Enabled full-brain chemistry requires source root and neurons')
                self.chemistry=WholeBrainChemistry.from_root(root,self,neurons,self.neuromod_options)

    def reset(self):
        super().reset()
        if self.chemistry is not None:
            self.chemistry.reset()

    def run(self, duration_ms, record_indices=None, photoreceptor_indices=None,
            photoreceptor_drive=None, chunk_ms=100, *, membrane_input_indices=None,
            membrane_input_drive=None, boundary_graded_release=None, boundary_spike_delta=None, record_dtype=np.float32):
        if self.chemistry is None:
            return super().run(duration_ms, record_indices, photoreceptor_indices, photoreceptor_drive,
                               chunk_ms, membrane_input_indices=membrane_input_indices,
                               membrane_input_drive=membrane_input_drive,
                               boundary_graded_release=boundary_graded_release,boundary_spike_delta=boundary_spike_delta,record_dtype=record_dtype)
        n_steps = self._steps(duration_ms, "duration_ms")
        boundary_arrays = []
        for name,values in (("boundary_graded_release",boundary_graded_release),("boundary_spike_delta",boundary_spike_delta)):
            array = np.empty((0,0),np.float64) if values is None else np.asarray(values,np.float64)
            if values is not None and (array.shape != (n_steps,self.n_neurons) or not np.isfinite(array).all()):
                raise ValueError(name+' must match fine steps and local neuron order')
            boundary_arrays.append(array)
        if n_steps % self.chemistry.tick_steps or self.step % self.chemistry.tick_steps:
            raise ValueError('Enabled chemistry requires whole 1-ms duration increments')
        chunk_steps = self._steps(chunk_ms, "chunk_ms")
        if chunk_steps < 1:
            raise ValueError("chunk_ms must be at least dt")
        general_input = membrane_input_indices is not None or membrane_input_drive is not None
        if general_input:
            if photoreceptor_indices is not None or photoreceptor_drive is not None:
                raise ValueError('Use either photoreceptor input or combined membrane input, not both')
            photoreceptor_indices, photoreceptor_drive = membrane_input_indices, membrane_input_drive
        photos = _integer_array([] if photoreceptor_indices is None else photoreceptor_indices, "photoreceptor_indices")
        if (np.any(photos < 0) or np.any(photos >= self.n_neurons)
                or len(np.unique(photos)) != len(photos)):
            raise ValueError("photoreceptor_indices must be unique valid indices")
        if not general_input and np.any(~self.graded_mask[photos]):
            raise ValueError("Photoreceptor input must target graded neurons")
        photo_map = np.full(self.n_neurons, -1, dtype=np.int32)
        photo_map[photos] = np.arange(len(photos), dtype=np.int32)
        drive = np.asarray(0. if photoreceptor_drive is None else photoreceptor_drive, dtype=np.float64)
        if not np.all(np.isfinite(drive)):
            raise ValueError("photoreceptor_drive contains non-finite input")
        if not len(photos) and np.any(drive):
            raise ValueError("Nonzero photoreceptor_drive requires photoreceptor_indices")
        if drive.ndim == 0:
            drive_mode, drive = 0, drive.reshape(1, 1)
        elif drive.shape == (n_steps,):
            drive_mode, drive = 1, drive.reshape(n_steps, 1)
        elif drive.shape == (n_steps, len(photos)):
            drive_mode = 2
        else:
            raise ValueError("photoreceptor_drive must be scalar, [n_steps], or [n_steps,n_photoreceptors]")
        records = _integer_array([] if record_indices is None else record_indices, "record_indices")
        if np.any(records < 0) or np.any(records >= self.n_neurons):
            raise ValueError("record_indices contains an invalid neuron")
        records = records.astype(np.int32)
        start, end = self.step, self.step + n_steps
        record_start = (start + self.record_stride - 1) // self.record_stride
        record_steps = np.arange(record_start * self.record_stride, end, self.record_stride, dtype=np.int64)
        if np.dtype(record_dtype) not in (np.dtype('float32'), np.dtype('float64')):
            raise ValueError('record_dtype must be float32 or float64')
        voltages = np.empty((len(record_steps), len(records)), dtype=record_dtype)
        spike_arrays, time_arrays, chunk_timings = [], [], []
        initial_clamps = self.per_neuron_clamp_counts.copy()
        chemical_samples = self.chemistry.empty_recording(len(record_steps))
        wall_start = time.perf_counter()
        old_threads = nb.get_num_threads()
        nb.set_num_threads(self.threads)
        self.partial_result = None

        def snapshot(complete):
            captured = np.searchsorted(record_steps, self.step, side="left")
            per_neuron_clamps = self.per_neuron_clamp_counts - initial_clamps
            external = np.zeros(self.n_neurons, dtype=np.float64)
            if len(photos) and self.step > start:
                row = 0 if drive_mode == 0 else self.step - start - 1
                external[photos] = drive[row, 0] if drive_mode < 2 else drive[row]
            derivative = (self.rest - self.v + (self.g + external)*self.chemistry.effects.gain) / (self.tau_membrane*self.chemistry.effects.tau_factor)
            eligible = self.graded_mask | (self.step - self.last_spike >= self.refractory_steps)
            derivative[~eligible] = 0.
            return {"spike_indices": np.concatenate(spike_arrays) if spike_arrays else np.empty(0, np.int32),
                    "spike_times": np.concatenate(time_arrays) if time_arrays else np.empty(0, np.float32),
                    "voltages": voltages[:captured], "voltage_times": (record_steps[:captured] * self.dt).astype(np.float32),
                    "record_indices": records, "per_neuron_clamp_counts": per_neuron_clamps,
                    "clamp_count": int(per_neuron_clamps.sum()), "final_dvdt": derivative,
                    "max_abs_dvdt": float(np.max(np.abs(derivative))) if len(derivative) else 0.,
                    "final_v": self.v.copy(), "final_g": self.g.copy(),
                    "wall_seconds": time.perf_counter() - wall_start, "completed": complete,
                    "simulated_ms": (self.step - start) * self.dt, "integrator": "exponential_euler",
                    "dt_ms": self.dt, "actual_dt_graded_ms": self.dt,
                    "requested_dt_graded_ms": self.parameters["dt_graded"],
                    "graded_timestep_note": "Shared fine timestep exactly represents the configured synaptic delay; dt_graded is an upper bound.",
                    "threads": self.threads, "chunk_timings": chunk_timings,
                    "chemistry": {k: values[:captured].copy() for k, values in chemical_samples.items()},
                    "chemistry_diagnostics": self.chemistry.diagnostics(),
                    "input_units": "mV additive normalized membrane current; never voltage clamping",
                    "input_kind": "combined optical/electrode input" if general_input else "graded photoreceptor input"}

        try:
            check_memory()
            # A chemical tick is fixed at 1 ms; caller chunk sizes never move its clock.
            for chunk_start in range(start, end, self.chemistry.tick_steps):
                chunk_end = min(chunk_start + self.chemistry.tick_steps, end)
                if chunk_end - chunk_start != self.chemistry.tick_steps:
                    raise ValueError('Enabled chemistry requires whole 1-ms duration increments')
                first = int(np.searchsorted(record_steps, chunk_start))
                last = int(np.searchsorted(record_steps, chunk_end))
                self.chemistry.capture(chemical_samples, first, last)
                chunk_wall = time.perf_counter()
                indices, steps = _advance_modulated_hybrid(
                    self.v, self.g, self.graded_mask, self.last_spike, self.refractory_steps,
                    self.active, self.firing, self.ring, self.ring_counts, self.release_history,
                    self.per_neuron_clamp_counts, self.graded_indptr, self.graded_indices,
                    self.graded_counts, self.csc_indptr, self.csc_indices, self.csc_counts,
                    chunk_start, chunk_end, start, self.delay_steps, self.decay_v_each,
                    self.decay_g_each, self.forcing_scale, self.rest, self.parameters["graded_release"],
                    self.parameters["graded_gain"], self.parameters["v_reset"], self.parameters["v_threshold"],
                    self.parameters["spike_weight"], self.parameters["voltage_min"], self.parameters["voltage_max"],
                    photo_map, drive, drive_mode, records, self.record_stride, record_start, voltages,
                    self.chemistry.effects.gain, self.chemistry.effects.threshold_factor,
                    self.chemistry.effects.release_group, self.chemistry.effects.release,*boundary_arrays,self.output_enabled)
                self.step = chunk_end
                self.chemistry.advance(indices)
                self.clamp_count = int(self.per_neuron_clamp_counts.sum())
                spike_arrays.append(indices)
                time_arrays.append((steps * self.dt).astype(np.float32))
                elapsed = time.perf_counter() - chunk_wall
                chunk_timings.append({"simulated_ms": (chunk_end - chunk_start) * self.dt,
                                      "wall_seconds": elapsed, "first_chunk_may_include_compilation": chunk_start == start})
                check_memory()
            self.last_result = snapshot(True)
            return self.last_result
        except BaseException:
            self.last_result = snapshot(False)
            self.partial_result = self.last_result | {
                "checkpoint_v": self.v, "checkpoint_g": self.g,
                "checkpoint_last_spike": self.last_spike,
                "checkpoint_ring": self.ring, "checkpoint_ring_counts": self.ring_counts,
                "checkpoint_release_history": self.release_history,
                "checkpoint_per_neuron_clamp_counts": self.per_neuron_clamp_counts,
                "checkpoint_step": self.step}
            raise
        finally:
            nb.set_num_threads(old_threads)
