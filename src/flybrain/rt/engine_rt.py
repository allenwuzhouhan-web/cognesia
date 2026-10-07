"""Causal one-ms coupling around the unchanged Brian-compatible LIF schedule.

The immutable released counts, retained recurrence, source projection and plastic
edge identities are all real connectome data. Only source afferents are Poisson
events; fields and endocrine release are never additive membrane currents.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
import zipfile

import numba as nb
import numpy as np
import pandas as pd
import psutil
from scipy import sparse
import yaml

from ..config import parameters
from ..engine import LIFEngine
from ..fetch import checksum
from ..neuromod.compartments import load_compartments
from ..neuromod.core import load_core
from ..neuromod.field import FieldEngine, FieldParameters, SourceProjection, build_source_projection, FIELD_SPECIES
from ..neuromod.odour import OdourLibrary, OdourTransduction, read_odour_parameters
from ..neuromod.plasticity import build_core_plasticity, normalize_kc_rates, require_receptor_gate
from ..neuromod.receptor_engine import _advance_receptors
from ..neuromod.receptors import ReceptorModel, read_receptors, receptor_bounds, kernel_response, parse_kernel
from ..neuromod.sources import source_masks
from ..neuromod.state import EndocrineState, MBONValence
from .kernel import advance_compact


def native_document(document):
    """Losslessly convert supported numerical recording types for safe YAML."""
    def convert(value):
        if isinstance(value,np.generic): return value.item()
        if isinstance(value,np.ndarray): return value.tolist()
        raise TypeError(f'Unsupported recording value: {type(value).__name__}')
    return json.loads(json.dumps(document,allow_nan=False,default=convert))

@nb.njit(cache=True, fastmath=False)
def _response(c, kind, n, k):
    if kind == 0: return c
    if kind == 1: return c*(2-c)
    cn = c**n
    kn = k**n
    return (1+kn)*cn/(cn+kn)


@nb.njit(cache=True, fastmath=False)
def _receptor_tick(c, membership_ptr, membership_indices, membership_data,
                   row_ptr, selections, row_species, row_effect, row_scope,
                   row_magnitude, row_kind, row_n, row_k,
                   edge_pre, edge_compartment, release_indices, bounds,
                   gain, threshold, tau, release, enabled):
    gain[:] = 1.; threshold[:] = 1.; tau[:] = 1.
    for edge in release_indices: release[edge] = 1.
    guards = 0
    if enabled:
        for row in range(len(row_species)):
            si, effect, scope = row_species[row], row_effect[row], row_scope[row]
            compartment_response = np.empty(c.shape[1],np.float64)
            if scope == 2:
                for k in range(c.shape[1]):
                    compartment_response[k] = _response(c[si,k],row_kind[row],row_n[row],row_k[row])
            for j in range(row_ptr[row],row_ptr[row+1]):
                selected = selections[j]
                if scope == 2:
                    value = compartment_response[edge_compartment[selected]]
                elif scope == 1:
                    neuron = edge_pre[selected]
                    value = 0.
                    for k in range(membership_ptr[neuron], membership_ptr[neuron+1]):
                        value += membership_data[k]*c[si,membership_indices[k]]
                    value = _response(value,row_kind[row],row_n[row],row_k[row])
                else:
                    value = 0.
                    for k in range(membership_ptr[selected],membership_ptr[selected+1]):
                        value += membership_data[k]*c[si,membership_indices[k]]
                    value = _response(value,row_kind[row],row_n[row],row_k[row])
                signal = value*row_magnitude[row]
                if abs(signal)>bounds[8]: guards += 1
                signal = min(bounds[8],max(-bounds[8],signal))
                if effect == 0: gain[selected] += signal
                elif effect == 1: threshold[selected] += signal
                elif effect == 2: tau[selected] += signal
                else: release[selected] += signal
    for i in range(len(gain)):
        if gain[i]<bounds[0] or gain[i]>bounds[1]: guards+=1
        if threshold[i]<bounds[2] or threshold[i]>bounds[3]: guards+=1
        if tau[i]<bounds[4] or tau[i]>bounds[5]: guards+=1
        gain[i]=min(bounds[1],max(bounds[0],gain[i]))
        threshold[i]=min(bounds[3],max(bounds[2],threshold[i]))
        tau[i]=min(bounds[5],max(bounds[4],tau[i]))
    for edge in release_indices:
        if release[edge]<bounds[6] or release[edge]>bounds[7]: guards+=1
        release[edge]=min(bounds[7],max(bounds[6],release[edge]))
    return guards


class FastReceptors:
    """Cache target identities, never cache evolving concentrations or effects."""
    def __init__(self, model):
        self.model = model
        n = len(model.neurons)
        self.gain = np.ones(n)
        self.threshold_factor = np.ones(n)
        self.tau_factor = np.ones(n)
        self.rows = []
        for row, (target, edges) in zip(model.rows, model.targets, strict=True):
            if not row['enabled'] or row['effect'].startswith('plasticity_'):
                continue
            selected = np.flatnonzero(target if row['edge_scope'] == 'none' else edges)
            if row['edge_scope'] == 'KC->MBON':
                selected = selected[model.edge_compartment[selected] >= 0]
            if len(selected):
                self.rows.append((row, selected))
        # Group edges only when every enabled release row and its source of
        # concentration are identical. This is exact algebraic sharing, not an
        # anatomical merge: all 927,567 retained edges remain in the engine.
        signature = np.zeros(len(model.edge_pre),np.int64)
        pres = np.full(len(signature),-1,np.int64)
        compartments = np.full(len(signature),-1,np.int64)
        for bit,(row,selected) in enumerate(self.rows):
            if row['effect'] != 'release_prob': continue
            if bit>=62: raise ValueError('Too many release receptor rows for exact group signature')
            signature[selected] |= 1<<bit
            if row['edge_scope']=='all_out': pres[selected] = model.edge_pre[selected]
            else: compartments[selected] = model.edge_compartment[selected]
        keys, self.release_group = np.unique(np.stack((signature,pres,compartments),axis=1),axis=0,return_inverse=True)
        self.release_group = self.release_group.astype(np.int32)
        self.group_pre, self.group_compartment = keys[:,1].astype(np.int32), keys[:,2].astype(np.int32)
        self.release = np.ones(len(keys))
        self.rows = [(row,np.unique(self.release_group[selected]) if row['effect']=='release_prob' else selected)
                     for row,selected in self.rows]
        selected_release = [i for r,i in self.rows if r['effect']=='release_prob']
        self.release_indices = np.unique(np.concatenate(selected_release)).astype(np.int32) if selected_release else np.empty(0,np.int32)
        self.row_ptr = np.array([0]+list(np.cumsum([len(i) for r,i in self.rows])),np.int32)
        self.selections = np.concatenate([i for r,i in self.rows]).astype(np.int32) if self.rows else np.empty(0,np.int32)
        self.row_species = np.array([model.species.index(r['modulator']) for r,i in self.rows],np.int32)
        self.row_effect = np.array([{'gain':0,'v_th':1,'tau_m':2,'release_prob':3}[r['effect']] for r,i in self.rows],np.int32)
        self.row_scope = np.array([{'none':0,'all_out':1,'KC->MBON':2}[r['edge_scope']] for r,i in self.rows],np.int32)
        self.row_magnitude = np.array([r['magnitude'] for r,i in self.rows])
        kernels = [parse_kernel(r['kernel']) for r,i in self.rows]
        self.row_kind = np.array([{'linear':0,'biphasic':1,'hill':2}[k] for k,args in kernels],np.int32)
        self.row_n = np.array([args[0] if args else 1. for k,args in kernels])
        self.row_k = np.array([args[1] if args else 1. for k,args in kernels])
        self.bounds = np.array([model.bounds[k] for k in ('gain_min','gain_max','threshold_factor_min','threshold_factor_max','tau_factor_min','tau_factor_max','release_min','release_max','signal_abs_max')])
        self.guard_events = 0

    def evaluate(self, c, state_gain=None, enabled=True):
        membership = self.model.membership
        self.guard_events += _receptor_tick(c,membership.indptr,membership.indices,membership.data,
            self.row_ptr,self.selections,self.row_species,self.row_effect,self.row_scope,
            self.row_magnitude,self.row_kind,self.row_n,self.row_k,self.group_pre,
            self.group_compartment,self.release_indices,self.bounds,
            self.gain,self.threshold_factor,self.tau_factor,self.release,enabled)
        if state_gain is not None:
            self.gain *= state_gain
            np.clip(self.gain, self.model.bounds['gain_min'], self.model.bounds['gain_max'], out=self.gain)
        return self


def runtime_fingerprint(root):
    root = Path(root)
    paths = sorted((root/'config').glob('*.yaml')) + sorted((root/'config').glob('*.csv'))
    # Bind dynamics/event semantics. Presentation-only edits cannot change a
    # recorded experiment; validators bind their own analysis code separately.
    modules = {
        'neuromod': ('core','compartments','field','odour','plasticity','receptors','receptor_engine','sources','state'),
        'rt': ('engine_rt','kernel','protocol','replay'),
    }
    paths += [root/f'src/flybrain/{folder}/{name}.py' for folder,names in modules.items() for name in names]
    paths += [root/'src/flybrain/engine.py', root/'build/compartments.npz', root/'build/neuromod_core_diagnostic.parquet']
    hashes = {str(p.relative_to(root)): checksum(p) for p in paths}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(), hashes


def require_plasticity_gate(root):
    """Reject incomplete, failed or stale V-NM-E evidence before constructing a run."""
    root = Path(root)
    gate = json.loads((root/'build/validation_neuromod_plasticity.json').read_text())
    checks = gate.get('checks')
    if (gate.get('gate') != 'V-NM-E' or gate.get('status') != 'PASS'
            or not isinstance(checks, list) or not checks
            or any(not isinstance(check, dict) or check.get('status') != 'PASS' for check in checks)):
        raise ValueError('Coupled runtime requires complete V-NM-E PASS evidence')
    for field, prefix in [('config_hashes', root/'config'), ('implementation_hashes', root),
                          ('dependency_hashes', root), ('artifact_hashes', root/'build')]:
        hashes = gate.get(field)
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError(f'Plasticity prerequisite lacks provenance: {field}')
        for name, digest in hashes.items():
            if checksum(prefix/name) != digest:
                raise ValueError(f'Stale plasticity prerequisite: {name}')
    return gate


class CoreRuntime:
    """One owner thread, bounded display history, complete on-disk spike stream.

    Controls are applied only between integer-ms ticks. Warm compilation occurs
    before measured runs. No wall-clock value ever enters simulation dynamics.
    """
    def __init__(self, root, seed=7, *, require_gates=True, record=True):
        self.root = Path(root).resolve()
        if require_gates:
            require_receptor_gate(self.root)
            require_plasticity_gate(self.root)
        self.core = load_core(self.root)
        self.neurons = self.core.neurons
        self.mapping = load_compartments(self.root)
        full_neurons = pd.read_parquet(self.root/'build/neurons.parquet')
        full_projection = build_source_projection(full_neurons, self.mapping)
        projection = SourceProjection(FIELD_SPECIES, self.mapping.names,
            full_projection.mean_rate_matrix[:, self.core.model_indices].tocsr(), full_projection.source_counts,
            full_projection.metadata | {'core_policy': 'Full-model denominators; omitted neurons contribute zero, not rescaled substitutes.'})
        self.field = FieldEngine(FieldParameters.from_root(self.root), self.mapping.names, self.mapping.adjacency, projection)
        self.p = parameters(self.root)
        self.nm = {k: v['value'] for k,v in yaml.safe_load((self.root/'config/neuromod.yaml').read_text())['parameters'].items()}
        if self.nm['dt_mod_ms'] != 1 or self.nm['dt_plast_ms'] != 1 or self.nm['dt_base_ms'] != .1:
            raise ValueError('Runtime contract requires dt_base=0.1 ms, dt_mod=dt_plast=1 ms; no silent timestep changes')
        self.engine = LIFEngine(self.core.counts, self.p, dt=.1, threads=1, clamp=False)
        model = ReceptorModel(read_receptors(self.root/'config/receptors.csv'), self.neurons,
            self.mapping, self.core.counts, model_indices=self.core.model_indices, bounds=receptor_bounds(self.root))
        self.receptor_model = model
        self.effects = FastReceptors(model)
        plastic = build_core_plasticity(self.root, self.core)
        self.plasticity = plastic.kernel
        self.kc_indices = plastic.kc_indices
        self.plastic_metadata = plastic.metadata
        # Transfer the CSR plasticity identity into the engine's sorted CSC order.
        csr = self.core.counts
        posts = np.repeat(np.arange(len(self.neurons)), np.diff(csr.indptr))[plastic.edge_data_indices]
        pres = csr.indices[plastic.edge_data_indices]
        self.plastic_csc = np.array([self.engine.csc_indptr[pre] + np.searchsorted(
            self.engine.csc_indices[self.engine.csc_indptr[pre]:self.engine.csc_indptr[pre+1]], post)
            for pre,post in zip(pres,posts,strict=True)], np.int32)
        if not np.array_equal(self.engine.csc_counts[self.plastic_csc], self.plasticity.w0):
            raise ValueError('Plastic edge CSC identities differ from released baseline')
        self.library = OdourLibrary.from_root(self.root, download=False)
        self.odour_parameters = read_odour_parameters(self.root)
        lookup = np.full(len(full_neurons), -1, np.int32)
        lookup[self.core.model_indices] = np.arange(len(self.neurons))
        self.orn_indices = lookup[self.library.neuron_indices]
        if np.any(self.orn_indices < 0):
            raise ValueError('ORN missing from normative core')
        self.sources = source_masks(self.neurons)
        self.cells = self.neurons.cell_type.fillna('').to_numpy(str)
        self.state = EndocrineState.from_root(self.root, self.neurons)
        self.valence = MBONValence(self.neurons, self.root/'config/mbon_valence.csv')
        self.kc_types = sorted(set(self.cells[self.kc_indices]))
        self.mbon_types = sorted(set(self.cells[np.char.startswith(self.cells, 'MBON')]))
        self.kc_groups = [np.flatnonzero(self.cells==name) for name in self.kc_types]
        self.mbon_groups = [np.flatnonzero(self.cells==name) for name in self.mbon_types]
        assignment = self.mapping.mb_assignment[self.core.model_indices]
        self.dan_groups = [np.flatnonzero(self.sources['DA'] & (assignment==i)) for i in range(15)]
        self.weight_groups = [np.flatnonzero(self.plasticity.compartment_index==i) for i in range(15)]
        kc_type_code = np.array([self.kc_types.index(self.cells[x]) for x in self.kc_indices])
        self.weight_bins = self.plasticity.compartment_index*len(self.kc_types) + kc_type_code[self.plasticity.pre_index]
        self.weight_bin_counts = np.bincount(self.weight_bins, minlength=15*len(self.kc_types))
        self.config_hash, self.manifest_hashes = runtime_fingerprint(self.root)
        self.record = bool(record)
        self.reset(seed)

    @property
    def t_sim_ms(self):
        return self.engine.step*self.engine.dt

    def reset(self, seed=None):
        if hasattr(self, '_spike_files'):
            for handle in self._spike_files: handle.close()
            self._frame_file.close()
        self.seed = int(seed if seed is not None else self.seed)
        self.rng = np.random.default_rng(self.seed)
        self.engine.reset(); self.field.reset(); self.state.reset()
        self.plasticity.weights[:] = self.plasticity.w0
        self.plasticity.e_pre.fill(0); self.plasticity.e_da.fill(0)
        self.plasticity.weight_clamp_events = 0
        self.plasticity.total_absolute_weight_change = 0.
        self.engine.csc_counts[self.plastic_csc] = self.plasticity.w0
        self.effects.guard_events = 0
        self.odour = OdourTransduction(self.library, self.odour_parameters)
        self.controls = {'odour': 'air', 'intensity': 1., 'dan_type': 'PPL101', 'dan_drive': 0.,
            'oa_tone': 0., 'serotonin_tone': 0., 'plasticity.enabled': True, 'receptors.enabled': True,
            'fields.enabled': True, 'state.enabled': True, 'field.clamp': None,
            'feeding': 0., 'drinking': 0., 'aversive': 0.}
        self.events = []; self.frames = deque(maxlen=3000)
        self.rates_hz = np.zeros(len(self.neurons))
        self.spike_totals = np.zeros(len(self.neurons), np.int64)
        self.saturation_count = 0; self.voltage_out_of_bounds = 0
        self.voltage_min = float(self.p['v_rest']); self.voltage_max = self.voltage_min
        self._voltage_diagnostics = np.array([self.voltage_min, self.voltage_max, 0.], dtype=np.float64)
        self.wall_seconds = 0.; self.frame_counter = 0
        self.tick_wall_seconds = []; self.spike_count = 0
        self._spike_hashes = [hashlib.sha256(), hashlib.sha256()]
        self.session_dir = self.root/'runs/neuromod'/('session-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._spike_files = [open(self.session_dir/name, 'wb') for name in ('spike_indices.i32', 'spike_steps.i64')]
        self._frame_file = open(self.session_dir/'frames.jsonl','w')
        self._state_output = self.state.outputs()
        self._update_effects()
        self._last_snapshot = self.snapshot()
        return self._last_snapshot

    def control(self, control_id, value):
        aliases = {'odor':'odour', 'odor_intensity':'intensity', 'odour_intensity':'intensity', '5ht_tone':'serotonin_tone'}
        key = aliases.get(control_id, control_id)
        if key == 'odour':
            if value not in ('air','OCT','MCH'):
                self.library.responses(str(value))  # allow other actual DoOR entries only
            value = str(value)
        elif key == 'dan_type':
            if value not in set(self.cells[self.sources['DA']]):
                raise ValueError('DAN handle must be a positive-known-DA type in this core')
        elif key.startswith('state.') or key == 'nutritional_state':
            self.state.apply_control(key.removeprefix('state.'), value)
            self._state_output = self.state.outputs()
        elif key == 'field.clamp':
            if value is not None:
                if not isinstance(value,dict) or value.get('species') not in FIELD_SPECIES or value.get('compartment') not in self.mapping.names:
                    raise ValueError('Field clamp requires known species and compartment')
                concentration = float(value['value'])
                if not np.isfinite(concentration) or not 0 <= concentration <= 5:
                    raise ValueError('Field clamp must be in [0,5] a.u.')
                value = dict(value, value=concentration, access='SIMULATION ONLY: direct concentration clamp')
        elif key.endswith('.enabled'):
            if key not in self.controls or not isinstance(value, bool):
                raise ValueError('Layer toggle must be a known boolean control')
        elif key in ('intensity','dan_drive','oa_tone','serotonin_tone','feeding','drinking','aversive'):
            value = float(value)
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Drive/intensity must be finite in [0,1]')
        elif key == 'source_drive':
            if not isinstance(value,dict) or value.get('cell_type') not in set(self.cells):
                raise ValueError('Source drive requires an existing cell type')
            selected = self.cells == value['cell_type']
            allowed = self.sources['DA']|self.sources['OA']|self.sources['TA']|self.sources['5HT']|self.neurons.super_class.eq('endocrine').to_numpy()
            if not np.all(allowed[selected]):
                raise ValueError('Handle must consist of known modulator or endocrine sources')
            drive = float(value['drive'])
            if not np.isfinite(drive) or not 0<=drive<=1:
                raise ValueError('Source drive must be in [0,1]')
            value = {'cell_type':value['cell_type'],'drive':drive}
        elif key in ('pause','step','reset'):
            # Transport commands are replayable no-ops. The bridge alone owns
            # wall-clock pausing; reset starts a new seeded recording first.
            if key == 'pause' and not isinstance(value,bool):
                raise ValueError('Pause control must be boolean')
            if key == 'step' and value != 1:
                raise ValueError('A single step is 1 ms')
        else:
            raise ValueError(f'Unknown runtime control: {control_id}')
        self.controls[key] = value
        event = {'t_sim_ms': self.t_sim_ms, 'control_id': key, 'value': value}
        self.events.append(event)
        with open(self.session_dir/'events.jsonl','a') as stream: stream.write(json.dumps(event)+'\n')
        self._update_effects()
        return event

    def _update_effects(self):
        effect = self.effects.evaluate(self.field.C,
            self._state_output['gain_factor'] if self.controls['state.enabled'] else None,
            self.controls['receptors.enabled'])
        tau = self.p['tau_membrane']*effect.tau_factor
        self._decay_v = np.exp(-self.engine.dt/tau)
        self._coupling = 1-self._decay_v
        self._threshold = self.p['v_rest'] + (self.p['v_threshold']-self.p['v_rest'])*effect.threshold_factor

    def _neural_tick(self, rates):
        engine = self.engine
        active_inputs = rates > 0
        active_inputs[self.orn_indices] = True
        inputs = np.flatnonzero(active_inputs).astype(np.int32)
        # Poisson splitting: draw the count in this 1-ms constant-rate interval,
        # then independently assign each event to one of ten 0.1-ms bins. This
        # is exactly independent Poisson counts per bin, with no Bernoulli cap.
        counts = self.rng.poisson(rates[inputs]/1000)
        event_inputs = np.repeat(np.arange(len(inputs),dtype=np.int32),counts)
        bins = self.rng.integers(0,10,size=len(event_inputs),dtype=np.int64)
        order = np.lexsort((event_inputs,bins))
        event_steps = bins[order]+engine.step
        event_inputs = event_inputs[order]
        engine.refractory_steps.fill(engine.default_refractory_steps)
        engine.refractory_steps[inputs] = 0
        indices, steps, _, _ = advance_compact(engine.v, engine.g, engine.last_spike,
            engine.refractory_steps, engine.active, engine.firing, engine.ring, engine.ring_counts,
            engine.csc_indptr, engine.csc_indices, engine.csc_counts, engine.step, engine.step+10,
            engine.dt, engine.delay_steps, self._decay_v, engine.decay_g, self._coupling,
            self.p['v_rest'],self.p['v_reset'],self._threshold,self.p['spike_weight'],
            self.p['spike_weight']*self.p['poisson_factor'],inputs,event_steps,event_inputs,0,
            False,self.p['voltage_min'],self.p['voltage_max'],np.empty(0,np.int32),10,
            engine.step//10,np.empty((1,0),np.float32),self.effects.gain,self.effects.release,self.effects.release_group,
            self._voltage_diagnostics)
        engine.step += 10
        return indices, steps

    def advance(self, duration_ms):
        if not np.isfinite(duration_ms) or duration_ms < 0 or float(duration_ms) != round(duration_ms):
            raise ValueError('Duration must be a nonnegative integer number of 1-ms coupling ticks')
        start_wall = time.perf_counter()
        chunks_i, chunks_t = [], []
        for _ in range(int(duration_ms)):
            tick = time.perf_counter()
            rates = np.zeros(len(self.neurons))
            rates[self.orn_indices] = self.odour.step(None if self.controls['odour']=='air' else self.controls['odour'], self.controls['intensity'], 1.)
            maximum = self.nm['max_source_rate_hz_DA']
            rates[(self.cells==self.controls['dan_type']) & self.sources['DA']] += maximum*self.controls['dan_drive']
            rates[self.sources['OA']] += self.nm['max_source_rate_hz_OA']*self.controls['oa_tone']
            rates[self.sources['5HT']] += self.nm['max_source_rate_hz_5HT']*self.controls['serotonin_tone']
            if self.controls.get('source_drive'):
                drive = self.controls['source_drive']
                rates[self.cells==drive['cell_type']] += self.nm['state_source_max_rate_hz']*drive['drive']
            indices, steps = self._neural_tick(rates)
            chunks_i.append(indices); chunks_t.append(steps)
            counts = np.bincount(indices,minlength=len(self.neurons))
            self.spike_totals += counts
            self.rates_hz += -np.expm1(-1/self.nm['runtime_rate_tau_ms'])*(counts*1000-self.rates_hz)
            if self.controls['state.enabled'] and int(self.t_sim_ms)%int(self.nm['state_dt_ms'])==0:
                self.state.step(self.nm['state_dt_ms'], self.rates_hz,
                    feeding=self.controls['feeding'], drinking=self.controls['drinking'], aversive=self.controls['aversive'])
                self._state_output = self.state.outputs()
            if self.controls['fields.enabled']:
                source_rates = self.rates_hz.copy()
                if self.controls['state.enabled']:
                    source_rates *= self._state_output['source_rate_scale']
                    mask = self._state_output['endocrine_mask']
                    source_rates[mask] = self._state_output['endocrine_drive'][mask]*self._state_output['source_max_rate_hz']
                self.field.step(source_rates)
                clamp = self.controls['field.clamp']
                if clamp is not None:
                    self.field.C[FIELD_SPECIES.index(clamp['species']),self.mapping.names.index(clamp['compartment'])] = clamp['value']
            else:
                self.field.C.fill(0)
            if self.controls['plasticity.enabled']:
                drive,saturations = normalize_kc_rates(self.rates_hz[self.kc_indices],self.nm['max_kc_rate_hz'])
                self.saturation_count += saturations
                self.plasticity.step(drive,self.field.C[0,:15],1.)
                self.engine.csc_counts[self.plastic_csc] = self.plasticity.weights
            self._update_effects()
            if not np.isfinite(self.engine.v).all() or not np.isfinite(self.engine.g).all():
                raise FloatingPointError('Nonfinite network state; simulation stopped with evidence retained')
            self.voltage_min, self.voltage_max = map(float, self._voltage_diagnostics[:2])
            self.voltage_out_of_bounds = int(self._voltage_diagnostics[2])
            elapsed = time.perf_counter()-tick
            self.tick_wall_seconds.append(elapsed)
            if len(self.tick_wall_seconds)>60000: del self.tick_wall_seconds[:1000]
            if int(self.t_sim_ms)%20 == 0:
                frame = self.snapshot(wall_seconds=self.wall_seconds+time.perf_counter()-start_wall)
                self.frames.append(frame)
                if self.record: self._frame_file.write(json.dumps(frame,allow_nan=False)+'\n')
                self.frame_counter += 1
        for array_list, handle, digest in zip((chunks_i,chunks_t),self._spike_files,self._spike_hashes,strict=True):
            if array_list:
                array = np.concatenate(array_list)
                raw = array.tobytes(); handle.write(raw); digest.update(raw)
        self.spike_count += sum(map(len,chunks_i))
        self.wall_seconds += time.perf_counter()-start_wall
        self._last_snapshot = self.snapshot()
        return self._last_snapshot

    def warmup(self):
        """Compile actual sizes, then restore a clean seed and empty recording."""
        self.advance(1)
        self.reset(self.seed)

    @property
    def all_spike_indices(self):
        self._spike_files[0].flush()
        return np.fromfile(self.session_dir/'spike_indices.i32',np.int32)

    @property
    def all_spike_steps(self):
        self._spike_files[1].flush()
        return np.fromfile(self.session_dir/'spike_steps.i64',np.int64)

    def digests(self):
        return {'spike_indices':self._spike_hashes[0].hexdigest(),'spike_steps':self._spike_hashes[1].hexdigest(),
                'weights':hashlib.sha256(self.plasticity.weights.tobytes()).hexdigest()}

    def weight_heatmap(self):
        relative = self.plasticity.weights/self.plasticity.w0
        sums = np.bincount(self.weight_bins,weights=relative,minlength=len(self.weight_bin_counts))
        return np.divide(sums,self.weight_bin_counts,out=np.full(len(sums),np.nan),where=self.weight_bin_counts>0).reshape(15,-1)

    def snapshot(self, *, wall_seconds=None):
        elapsed = self.wall_seconds if wall_seconds is None else wall_seconds
        mean = lambda groups: [float(np.mean(self.rates_hz[i])) if len(i) else 0. for i in groups]
        weights = [float(np.mean(self.plasticity.weights[i]/self.plasticity.w0[i])) if len(i) else None for i in self.weight_groups]
        heat = self.weight_heatmap()
        return {'schema_version':1,'t_sim_ms':self.t_sim_ms,'dt_ms':self.engine.dt,
            'rtf':self.t_sim_ms/1000/elapsed if elapsed else 0.,
            'rss_gb':psutil.Process().memory_info().rss/1e9,'frame_counter':self.frame_counter,
            'config_hash':self.config_hash,'seed':self.seed,'controls':dict(self.controls),
            'kc_rates_hz':mean(self.kc_groups),'dan_rates_hz':mean(self.dan_groups),'mbon_rates_hz':mean(self.mbon_groups),
            'concentrations_au':self.field.C.tolist(),'weights_relative':weights,
            'weight_heatmap':[[float(x) if np.isfinite(x) else None for x in row] for row in heat],
            'valence':self.valence.evaluate(self.rates_hz),'valence_label':'INFERRED_SIGN MBON readout; not decoded motor behaviour',
            'state':dict(self.state.state),'hormones_au':dict(self.state.hormones),
            'spikes':int(self.spike_totals.sum()),'kc_active_fraction':float(np.mean(self.spike_totals[self.kc_indices]>0)),
            'voltage_min_mV':self.voltage_min,'voltage_max_mV':self.voltage_max,
            'voltage_out_of_bounds':self.voltage_out_of_bounds,'voltage_clamps':0,
            'voltage_diagnostic_scope':'Every eligible integration and external input update at 0.1 ms, before spike reset; count is violating updates',
            'field_clamps':self.field.clamp_count,'weight_clamps':self.plasticity.weight_clamp_events,
            'receptor_guards':self.effects.guard_events,'kc_rate_saturations':self.saturation_count,
            'body_status':'NOT-RUN: no validated body/descending motor decoder is available',
            'visual_status':'NOT-RUN: core omits the unvalidated visual pathway',
            'recording':self.record,'session_dir':str(self.session_dir),'recent_events':self.events[-30:]}

    def metadata(self):
        positions = self.neurons[['soma_x','soma_y','soma_z']].to_numpy(float)
        valid = np.isfinite(positions).all(axis=1)
        coords = [[float(v) for v in row] if ok else None for row,ok in zip(positions,valid,strict=True)]
        return {'schema_version':1,'neurons':len(self.neurons),'edges':self.core.counts.nnz,
            'released_edges':self.core.metadata['released_edges'],'plastic_edges':len(self.plasticity.weights),
            'kc_kc_mode':self.core.metadata['kc_kc_mode'],'species':list(FIELD_SPECIES),
            'compartments':list(self.mapping.names),'kc_types':self.kc_types,'mbon_types':self.mbon_types,
            'dan_types':sorted(set(self.cells[self.sources['DA']])),'valence_coverage':self.valence.coverage,
            'plasticity':self.plastic_metadata,'source_projection':self.field.projection.metadata,
            'atlas':{'root_ids':[str(x) for x in self.neurons.root_id], 'cell_types':self.cells.tolist(),
                'xyz':coords,'coordinate_source':'Released soma coordinates; missing soma coordinates omitted',
                'known_nt':self.neurons.known_nt.fillna('').tolist(),'predicted_nt':self.neurons.top_nt.fillna('').tolist(),
                'compartment':self.mapping.mb_assignment[self.core.model_indices].tolist()},
            'warnings':['Empirical PPL101 assignment is g4; published anatomy says g1. No remapping is applied.',
                'Odour-driven KC sparseness and voltage bounds previously failed; current measurements remain visible.',
                'All field concentrations and receptor/plasticity coefficients are model assumptions.',
                'Cell-type addressability does not establish a published genetic driver line.']}

    def export(self, path=None):
        for handle in self._spike_files: handle.flush()
        self._frame_file.flush()
        np.savez_compressed(self.session_dir/'endpoint.npz',root_ids=self.neurons.root_id.to_numpy(),v=self.engine.v,
            g=self.engine.g,rates_hz=self.rates_hz,weights=self.plasticity.weights,e_pre=self.plasticity.e_pre,
            e_da=self.plasticity.e_da,C=self.field.C)
        manifest = {'schema_version':1,'seed':self.seed,'duration_ms':self.t_sim_ms,'config_hash':self.config_hash,
            'hashes':self.manifest_hashes,'digests':self.digests(),'snapshot':self.snapshot(),
            'event_clock':'Integer simulation milliseconds; equal-time events retain file order',
            'spike_format':'little-endian int32 core indices and int64 base-step times; dt=0.1 ms'}
        # NumPy state scalars are valid numerical measurements but PyYAML's safe
        # dumper only accepts native scalar types. Canonicalize through JSON;
        # this changes the recording envelope, never the underlying dynamics.
        manifest = native_document(manifest)
        (self.session_dir/'session.yaml').write_text(yaml.safe_dump(manifest,sort_keys=False))
        (self.session_dir/'metadata.json').write_text(json.dumps(self.metadata(),allow_nan=False))
        if not (self.session_dir/'events.jsonl').exists(): (self.session_dir/'events.jsonl').touch()
        path = Path(path) if path else self.session_dir.with_suffix('.zip')
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
            for file in self.session_dir.iterdir(): archive.write(file,file.name)
            for file in (self.root/'config').glob('*'):
                if file.is_file(): archive.write(file,'config/'+file.name)
        return path

    def close(self):
        for handle in self._spike_files: handle.close()
        self._frame_file.close()
