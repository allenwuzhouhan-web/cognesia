"""Identity-preserving circuit extraction and typed recorded surroundings.

A reduced circuit is a scientific boundary condition, not a visibility filter.
Recorded arrivals retain synaptic units and refractory semantics in the engine.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
import json
from pathlib import Path

import numpy as np
from scipy import sparse

from .model_registry import stable_hash
from .inspect_data import atomic_write_json


def normalize_selection(request=None):
    value = dict(request or {})
    allowed = {"mode", "entity_ids", "root_ids", "regions", "cell_types", "classes", "modules", "boundary", "reference_id"}
    if set(value)-allowed: raise ValueError("Unknown research selection field: "+", ".join(sorted(set(value)-allowed)))
    mode = value.get("mode", "selected" if any(value.get(k) for k in allowed-{"mode","boundary","reference_id"}) else "full")
    if mode not in {"full", "selected"}: raise ValueError("Research mode must be full or selected")
    boundary = value.get("boundary", "recorded")
    if boundary not in {"recorded", "isolated", "full_context"}: raise ValueError("Unknown circuit boundary policy")
    result = {"mode": mode, "boundary": boundary, "reference_id": value.get("reference_id")}
    for name in ("entity_ids", "root_ids", "regions", "cell_types", "classes", "modules"):
        items = value.get(name, [])
        if not isinstance(items, list) or any(isinstance(x, bool) or not isinstance(x, (str, int)) for x in items):
            raise ValueError(name+" must be a list of identities")
        result[name] = sorted(set(str(x) for x in items))
    if mode == "selected" and not any(result[k] for k in ("entity_ids","root_ids","regions","cell_types","classes","modules")):
        raise ValueError("Selected simulation requires at least one target")
    if result["reference_id"] is not None and (not isinstance(result["reference_id"], str) or not result["reference_id"] or "/" in result["reference_id"] or ".." in result["reference_id"]):
        raise ValueError("reference_id must be an artifact identifier, not a path")
    return result


def resolve_selection_indices(neurons, request=None):
    """Resolve identity/annotation selectors without slicing or loading a graph."""
    selection = normalize_selection(request); n = len(neurons)
    mask = np.ones(n, bool) if selection["mode"] == "full" else np.zeros(n, bool)
    for key, field in (("entity_ids", "entity_id"), ("root_ids", "root_id"), ("cell_types", "cell_type"), ("classes", "cell_class")):
        if selection[key]:
            if field not in neurons: raise ValueError("Model lacks selection annotation "+field)
            values = neurons[field].fillna("").astype(str)
            missing = set(selection[key])-set(values)
            if missing: raise ValueError("Unknown "+key+": "+", ".join(sorted(missing)[:8]))
            mask |= values.isin(selection[key]).to_numpy()
    if selection["regions"]:
        available = [k for k in ("region", "root_region", "super_class", "neuromere") if k in neurons]
        matched = set()
        for field in available:
            values = neurons[field].fillna("").astype(str)
            mask |= values.isin(selection["regions"]).to_numpy()
            matched.update(set(values)&set(selection["regions"]))
        if matched != set(selection["regions"]): raise ValueError("Some requested regions have no source annotation")
    if selection["modules"]:
        from .peripheral import catalog
        modules = {m["id"]: m for m in catalog(neurons)}
        for module in selection["modules"]:
            if module not in modules: raise ValueError("Unknown peripheral module: "+module)
            ids = modules[module]["neuron_indices"]
            if not ids: raise ValueError("Peripheral module has no neural interface in this model: "+module)
            mask[ids] = True
    selected = np.flatnonzero(mask).astype(np.int32)
    if not len(selected): raise ValueError("Research selection resolves to no neurons")
    return selected


def compile_selection(network, request=None):
    selection = normalize_selection(request); neurons = network["neurons"]; n = len(neurons)
    selected = resolve_selection_indices(neurons,selection)
    active = np.arange(n, dtype=np.int32) if selection["boundary"] == "full_context" else selected
    outside = np.flatnonzero(~np.isin(np.arange(n), active)).astype(np.int32)
    result = dict(network)
    result["neurons"] = neurons.iloc[active].copy().reset_index(drop=True)
    for name in ("graded", "spiking", "reference"):
        if name in network:
            result[name] = network[name][active][:, active].tocsr()
    incoming = sum(network[name][active][:, outside].nnz for name in ("graded", "spiking"))
    outgoing = sum(network[name][outside][:, active].nnz for name in ("graded", "spiking"))
    manifest = {**selection, "model_hash": network.get("manifest", {}).get("model_hash"),
                "parent_indices": active.tolist(), "research_indices": selected.tolist(),
                "parent_neurons": n, "simulated_neurons": len(active), "research_neurons": len(selected),
                "incoming_cut_edges": int(incoming), "outgoing_cut_edges": int(outgoing),
                "reference_required": bool(len(outside) and selection["boundary"] == "recorded"),
                "units": "native signed synapse counts; no compensating normalization",
                "one_way_surroundings": selection["boundary"] == "recorded"}
    manifest["selection_hash"] = stable_hash({k: v for k,v in manifest.items() if k != "reference_id"})
    result["selection"] = manifest
    result["parent_neuron_indices"] = active
    result["parent_source_neurons"] = neurons
    return result


def remap_eye_mapping(mapping, parent_indices):
    parent = np.asarray(parent_indices, dtype=np.int64)
    local = {int(index): i for i, index in enumerate(parent)}
    keep = np.array([int(i) in local for i in mapping.photoreceptor_indices])
    photos = np.asarray([local[int(i)] for i in mapping.photoreceptor_indices[keep]], dtype=np.int32)
    assignments = mapping.assignments.iloc[parent].copy().reset_index(drop=True) if len(mapping.assignments) >= (parent.max(initial=-1)+1) else mapping.assignments.copy()
    return replace(mapping, assignments=assignments, photoreceptor_indices=photos,
                   photoreceptor_columns=mapping.photoreceptor_columns[keep].copy(),
                   audit=dict(mapping.audit, circuit_selection=True, selected_photoreceptors=len(photos)))


def slice_source_projection(projection, parent_indices):
    """Keep native denominators; absent source activity is supplied by boundary."""
    return replace(projection, mean_rate_matrix=projection.mean_rate_matrix[:, np.asarray(parent_indices)].tocsr(),
                   metadata=dict(projection.metadata, normalization="Full source population denominators retained after circuit selection"))


@dataclass
class BoundaryRecording:
    metadata: dict
    graded_release: np.ndarray
    spike_delta: np.ndarray
    chemical_sources: np.ndarray | None = None
    chemical_fields: np.ndarray | None = None
    initial_state: dict | None = None
    component_data: dict | None = None

    def __post_init__(self):
        self.graded_release = np.asarray(self.graded_release, np.float64)
        self.spike_delta = np.asarray(self.spike_delta, np.float64)
        if self.graded_release.ndim != 2 or self.spike_delta.shape != self.graded_release.shape:
            raise ValueError("Boundary arrivals require matching [fine_step, local_neuron] arrays")
        if not np.isfinite(self.graded_release).all() or not np.isfinite(self.spike_delta).all():
            raise ValueError("Boundary contains nonfinite neural arrivals")
        dt = float(self.metadata.get("dt_ms",0))
        if not np.isfinite(dt) or dt <= 0: raise ValueError("Boundary requires positive fine timestep")
        if self.metadata.get("n_neurons", self.graded_release.shape[1]) != self.graded_release.shape[1]:
            raise ValueError("Boundary local identity count differs from arrays")
        components = self.component_data or {}
        if self.chemical_sources is not None or self.chemical_fields is not None or components:
            if not np.isclose(1./dt,round(1./dt),rtol=0,atol=1e-8) or len(self.graded_release)%round(1./dt):
                raise ValueError("Component reference must cover complete 1-ms ticks")
            count=len(self.graded_release)//round(1./dt)
            if (self.chemical_sources is None) != (self.chemical_fields is None):
                raise ValueError("Chemical reference must include source and field traces")
            if self.chemical_sources is not None:
                self.chemical_sources=np.asarray(self.chemical_sources,np.float64)
                self.chemical_fields=np.asarray(self.chemical_fields,np.float64)
                if self.chemical_sources.ndim!=3 or self.chemical_sources.shape[0]!=count or self.chemical_fields.shape!=self.chemical_sources.shape:
                    raise ValueError("Chemical traces must match [1-ms tick,species,compartment]")
                for values in (self.chemical_sources,self.chemical_fields):
                    if not np.isfinite(values).all() or np.any(values<0): raise ValueError("Invalid chemical boundary values")
            for name in ("endocrine_rates","organ_motor_sum_hz"):
                if name in components:
                    values=np.asarray(components[name])
                    if values.ndim!=2 or len(values)!=count or not np.isfinite(values).all() or np.any(values<0):
                        raise ValueError("Invalid component boundary trace: "+name)
            if "endocrine_rates" in components and components["endocrine_rates"].shape[1]!=len(components.get("endocrine_indices",[])):
                raise ValueError("Endocrine trace source identities differ")

    def validate_reference(self, *, model_hash, selection_hash, dt_ms, protocol_hash=None, parameter_hash=None, chemistry=False):
        expected = {"model_hash": model_hash, "selection_hash": selection_hash, "dt_ms": dt_ms}
        if protocol_hash is not None: expected["protocol_hash"] = protocol_hash
        if parameter_hash is not None: expected["parameter_hash"] = parameter_hash
        for key, value in expected.items():
            if self.metadata.get(key) != value: raise ValueError("Recorded surroundings mismatch: "+key)
        if chemistry and (self.chemical_sources is None or self.chemical_fields is None):
            raise ValueError("Reduced chemistry requires recorded external source rates and compartment field boundaries")

    def component_tick(self, end_step):
        tick = int(round(1. / float(self.metadata["dt_ms"])))
        offset = int(end_step)-int(self.metadata.get("start_step",0))
        if offset <= 0 or offset % tick: raise ValueError("Component surroundings require exact 1-ms clock alignment")
        row = offset//tick-1
        if row >= self.graded_release.shape[0]//tick: raise ValueError("Component recording does not cover this tick")
        return row

    def chemical_tick(self, end_step):
        row = self.component_tick(end_step)
        if self.chemical_sources is None: raise ValueError("Reference lacks chemical source surroundings")
        data = self.component_data or {}
        return {"source_drive":self.chemical_sources[row],
                "endocrine_indices":np.asarray(data.get("endocrine_indices",[]),np.int64),
                "endocrine_rates":data.get("endocrine_rates",np.empty((len(self.chemical_sources),0)))[row]}

    def organ_tick(self, end_time_ms):
        row = self.component_tick(round(float(end_time_ms)/float(self.metadata["dt_ms"])))
        if not self.component_data or "organ_motor_sum_hz" not in self.component_data:
            raise ValueError("Reference lacks peripheral source surroundings")
        return self.component_data["organ_motor_sum_hz"][row]

    def slice(self, start_step, n_steps):
        first = int(start_step)-int(self.metadata.get("start_step", 0)); last = first+int(n_steps)
        if first < 0 or last > len(self.graded_release): raise ValueError("Recorded surroundings do not cover requested simulation interval")
        return {"boundary_graded_release": self.graded_release[first:last], "boundary_spike_delta": self.spike_delta[first:last]}

    def save(self, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        arrays = {"graded_release": self.graded_release, "spike_delta": self.spike_delta}
        for name in ("chemical_sources", "chemical_fields"):
            if getattr(self, name) is not None: arrays[name] = getattr(self, name)
        metadata = dict(self.metadata)
        if self.initial_state is not None:
            from .experiment_session import _pack
            metadata["initial_state"] = _pack(self.initial_state,arrays)
        if self.component_data is not None:
            from .experiment_session import _pack
            metadata["component_data"] = _pack(self.component_data,arrays)
        np.savez_compressed(folder/"arrivals.npz", **arrays)
        from .fetch import checksum
        atomic_write_json(folder/"manifest.json", dict(metadata, arrivals_sha256=checksum(folder/"arrivals.npz")))
        return str(folder)

    @classmethod
    def load(cls, folder):
        from .fetch import checksum
        folder = Path(folder); meta = json.loads((folder/"manifest.json").read_text())
        if checksum(folder/"arrivals.npz") != meta["arrivals_sha256"]: raise ValueError("Boundary recording checksum failed")
        with np.load(folder/"arrivals.npz", allow_pickle=False) as data:
            from .experiment_session import _unpack
            initial = _unpack(meta.pop("initial_state"),data) if "initial_state" in meta else None
            components = _unpack(meta.pop("component_data"),data) if "component_data" in meta else None
            return cls(meta, **{name: data[name].copy() for name in ("graded_release", "spike_delta", "chemical_sources", "chemical_fields") if name in data},initial_state=initial,component_data=components)

    def apply_initial_state(self,engine):
        if self.initial_state is None:
            raise ValueError("Recorded surroundings lack the exact selected initial neural state")
        if float(self.metadata["dt_ms"]) != engine.dt:
            raise ValueError("Reference timestep differs from selected circuit")
        if self.metadata.get("parameter_hash") and self.metadata["parameter_hash"] != stable_hash(engine.parameters):
            raise ValueError("Reference neural parameters differ from selected circuit")
        from .experiment_session import restore_state
        restore_state(engine,self.initial_state)
        self.bind_components(engine)

    def bind_components(self, engine):
        for name in ("chemistry","organs"):
            component = getattr(engine,name,None)
            if component is not None:
                if name=="chemistry":
                    if self.chemical_sources is None or self.chemical_sources.shape[1:]!=component.field.C.shape:
                        raise ValueError("Reference chemical compartments differ from selected model")
                    if self.metadata.get("chemical_compartments") != list(component.mapping.names):
                        raise ValueError("Reference chemical compartment identities differ")
                elif self.metadata.get("organ_modules") != [m["id"] for m in component.modules]:
                    raise ValueError("Reference peripheral module identities differ")
                component.boundary = self

    @classmethod
    def from_reference(cls, network, selection, *, voltages, spike_indices, spike_steps, dt_ms,
                       delay_steps, graded_release_threshold, spike_weight, protocol_hash,
                       start_step=0, release_factors=None):
        """Convert fine-step source records into native, delayed crossing arrivals.

        Voltages must include the preceding delay interval: row zero represents
        start_step-delay_steps. No interpolation from display frames is allowed.
        """
        active = np.asarray(selection["parent_indices"], dtype=np.int64)
        n = len(network["neurons"]); outside = np.setdiff1d(np.arange(n), active)
        voltage = np.asarray(voltages, np.float64)
        if voltage.ndim != 2 or voltage.shape[1] != n or len(voltage) <= delay_steps:
            raise ValueError("Reference requires full fine-step voltage history including delay prefix")
        count = len(voltage)-delay_steps
        release = np.maximum(0., voltage[:count, outside]-graded_release_threshold)
        graded = (network["graded"][active][:, outside] @ release.T).T
        arrivals = np.zeros((count, len(active)), np.float64)
        weights = network["spiking"][active].tocsc()
        factors = np.ones(weights.nnz) if release_factors is None else np.asarray(release_factors)
        if factors.shape != (weights.nnz,): raise ValueError("Boundary release factors do not match crossing edge order")
        outside_mask = np.zeros(n, bool); outside_mask[outside] = True
        for neuron, step in zip(spike_indices, spike_steps, strict=True):
            if not 0 <= int(neuron) < n: raise ValueError("Reference spike identity is outside model")
            row = int(step)+delay_steps-start_step
            if outside_mask[int(neuron)] and 0 <= row < count:
                lo, hi = weights.indptr[int(neuron):int(neuron)+2]
                arrivals[row, weights.indices[lo:hi]] += weights.data[lo:hi]*spike_weight*factors[lo:hi]
        meta = {"schema_version": 1, "model_hash": selection["model_hash"], "selection_hash": selection["selection_hash"],
                "protocol_hash": protocol_hash, "dt_ms": float(dt_ms), "start_step": int(start_step),
                "n_neurons": len(active), "parent_indices": active.tolist(), "boundary": "recorded",
                "warning": "External responses remain recorded after internal interventions; excluded feedback is not recomputed.",
                "channels": {"graded_release": "signed synapse count times positive graded release (mV)", "spike_delta": "synaptic g arrival including spike weight"}}
        return cls(meta, graded, arrivals)


def capture_initial_state(full_engine,parent_indices):
    """Project full native delay queues/state into selected neural identity order."""
    from .experiment_session import STATE_ARRAYS
    active = np.asarray(parent_indices,np.int64)
    n = full_engine.n_neurons
    local = np.full(n,-1,np.int32); local[active] = np.arange(len(active),dtype=np.int32)
    state = {"step":int(full_engine.step),"clamp_count":int(full_engine.per_neuron_clamp_counts[active].sum())}
    for name in STATE_ARRAYS:
        value = getattr(full_engine,name)
        if name == "release_history": state[name] = value[:,active].copy()
        elif name == "ring":
            ring = np.zeros((value.shape[0],len(active)),dtype=value.dtype)
            counts = np.zeros_like(full_engine.ring_counts)
            for i,count in enumerate(full_engine.ring_counts):
                selected = local[value[i,:count]]; selected = selected[selected >= 0]
                ring[i,:len(selected)] = selected; counts[i] = len(selected)
            state[name] = ring; state["ring_counts"] = counts
        elif name == "ring_counts": continue
        else: state[name] = value[active].copy()
    spiking = sparse.csc_matrix((full_engine.csc_counts,full_engine.csc_indices,full_engine.csc_indptr),shape=(n,n))
    graded = sparse.csr_matrix((full_engine.graded_counts,full_engine.graded_indices,full_engine.graded_indptr),shape=(n,n))
    state["csc_counts"] = spiking[active][:,active].tocsc().data.copy()
    state["graded_counts"] = graded[active][:,active].tocsr().data.copy()
    chemistry = getattr(full_engine,"chemistry",None)
    if chemistry is not None:
        saved = copy.deepcopy(chemistry.snapshot())
        saved["rates_hz"] = saved["rates_hz"][active].copy()
        if hasattr(chemistry,"plasticity"):
            keep_kc = np.isin(chemistry.kc_indices,active)
            saved["e_pre"] = saved["e_pre"][keep_kc].copy() if keep_kc.any() else np.zeros(1,np.float32)
            pre = chemistry.receptors.edge_pre[chemistry.plastic_csc]
            post = chemistry.receptors.edge_post[chemistry.plastic_csc]
            keep_edge = np.isin(pre,active)&np.isin(post,active)
            saved["weights"] = saved["weights"][keep_edge].copy()
        state["chemistry"] = saved
    organs = getattr(full_engine,"organs",None)
    if organs is not None:
        saved = copy.deepcopy(organs.snapshot()); saved["rates_hz"] = saved["rates_hz"][active].copy()
        state["organs"] = saved
    if getattr(full_engine,"rng",None) is not None:
        state["rng_state"] = copy.deepcopy(full_engine.rng.bit_generator.state)
    return state


class BoundaryRecorder:
    """Collect reference arrivals in bounded chunks from a full-context run.

    Temporarily set the reference engine record_stride=1 and record only
    `record_indices`. Pass each completed result to add_chunk. Existing engine
    voltage outputs must retain float64 integration precision. Components are
    sampled every 1 ms after their own update, using full source denominators.
    """
    def __init__(self,full_engine,network,selection,protocol_hash,duration_ms,*,max_bytes=3_000_000_000):
        self.engine = full_engine; self.selection = selection
        self.active = np.asarray(selection["parent_indices"],np.int64)
        self.start_step = int(full_engine.step); self.steps = full_engine._steps(duration_ms,"reference duration")
        needed = self.steps*len(self.active)*16
        if needed > max_bytes: raise ValueError(f"Boundary recordings require {needed/1e9:.2f} GB; shorten duration or select fewer neurons")
        self.initial_state = capture_initial_state(full_engine,self.active)
        self.graded = np.zeros((self.steps,len(self.active)),np.float64)
        self.spike = np.zeros_like(self.graded)
        n = full_engine.n_neurons
        inside = np.zeros(n,bool); inside[self.active] = True
        g = network["graded"][self.active].tocsr()
        self.record_indices = np.unique(g.indices[~inside[g.indices]]).astype(np.int32)
        self.g_weights = g[:,self.record_indices].tocsr()
        self.s_weights = network["spiking"][self.active].tocsc()
        local = np.full(n,-1,np.int32); local[self.active] = np.arange(len(self.active))
        # Preserve original sparse data positions so each reference tick reads
        # only crossing edges, rather than copying the full graph per tick.
        self.s_positions = np.flatnonzero(inside[full_engine.csc_indices])
        pres = np.searchsorted(full_engine.csc_indptr,self.s_positions,side="right")-1
        chosen = ~inside[pres]; self.s_positions = self.s_positions[chosen]; pres = pres[chosen]
        self.s_weights = sparse.csc_matrix((full_engine.csc_counts[self.s_positions].astype(np.float64),
            local[full_engine.csc_indices[self.s_positions]],np.r_[0,np.bincount(pres,minlength=n).cumsum()]),shape=(len(self.active),n))
        g_positions=[]; g_rows=[];g_columns=[]
        for row,parent in enumerate(self.active):
            positions=np.arange(full_engine.graded_indptr[parent],full_engine.graded_indptr[parent+1])
            columns=full_engine.graded_indices[positions];keep=~inside[columns]
            g_positions.extend(positions[keep]);g_rows.extend([row]*int(keep.sum()));g_columns.extend(np.searchsorted(self.record_indices,columns[keep]))
        self.g_positions=np.asarray(g_positions,np.int64)
        self.g_weights=sparse.csr_matrix((full_engine.graded_counts[self.g_positions].copy(),(g_rows,g_columns)),shape=(len(self.active),len(self.record_indices)))
        self.inside = inside; self.delay = full_engine.delay_steps
        self.prefix = np.asarray([full_engine.release_history[(self.start_step-self.delay+i)%len(full_engine.release_history),self.record_indices] for i in range(self.delay)],np.float64).reshape(self.delay,len(self.record_indices))
        self.written = 0
        self.pending_spikes = {}
        chemistry = getattr(full_engine,"chemistry",None)
        organs = getattr(full_engine,"organs",None)
        self.chemical_sources=[]; self.chemical_fields=[]; self.component_data={}
        if chemistry is not None:
            self.component_data["endocrine_indices"] = np.flatnonzero(chemistry.state.endocrine_mask & ~inside) if hasattr(chemistry,"state") else np.empty(0,np.int64)
            self.component_data["endocrine_rates"] = []
        if organs is not None: self.component_data["organ_motor_sum_hz"] = []
        self.metadata = {"schema_version":1,"model_hash":selection["model_hash"],"selection_hash":selection["selection_hash"],
                         "protocol_hash":protocol_hash,"dt_ms":full_engine.dt,"start_step":self.start_step,"n_neurons":len(self.active),
                         "parent_indices":self.active.tolist(),"parameter_hash":stable_hash(full_engine.parameters),
                         "boundary":"recorded","graded_voltage_precision":"fine-step records; no temporal interpolation",
                         "warning":"One-way recorded surroundings; changed circuit output does not alter excluded neurons."}
        if chemistry is not None: self.metadata["chemical_compartments"] = list(chemistry.mapping.names)
        if organs is not None: self.metadata["organ_modules"] = [m["id"] for m in organs.modules]
        # Keep pending external spikes that were already scheduled before the
        # reference interval begins, not only spikes emitted during the interval.
        for offset in range(self.delay+1):
            slot = (self.start_step+offset)%len(full_engine.ring_counts)
            for pre in full_engine.ring[slot,:full_engine.ring_counts[slot]]:
                if not self.inside[int(pre)]: self.pending_spikes.setdefault(offset,[]).append(int(pre))

    def _spike(self,pre,row):
        if not self.inside[pre] and 0 <= row < self.steps:
            lo,hi = self.s_weights.indptr[pre:pre+2]
            self.spike[row,self.s_weights.indices[lo:hi]] += self.s_weights.data[lo:hi]*self.engine.parameters["spike_weight"]

    def prepare_chunk(self):
        # Crossing weights are evaluated on delivery, preserving in-flight
        # events across source silencing and timed connection interventions.
        self.g_weights.data[:] = self.engine.graded_counts[self.g_positions]
        self.s_weights.data[:] = self.engine.csc_counts[self.s_positions]
        chemistry = getattr(self.engine,"chemistry",None)
        if chemistry is not None:
            group = chemistry.effects.release_group[self.s_positions]
            self.s_weights.data *= chemistry.effects.release[group]

    def add_chunk(self,result):
        precision = str(np.asarray(result["voltages"]).dtype)
        previous_precision = self.metadata.get("voltage_dtype")
        if previous_precision is not None and previous_precision != precision:
            raise ValueError("Reference voltage precision changed during recording")
        self.metadata["voltage_dtype"] = precision
        volts = np.asarray(result["voltages"],np.float64)
        if not np.array_equal(result["record_indices"],self.record_indices): raise ValueError("Reference records wrong boundary sources")
        expected = (self.start_step+self.written+np.arange(len(volts)))*self.engine.dt
        if not np.allclose(result["voltage_times"],expected,rtol=0,atol=2e-4): raise ValueError("Reference voltages must cover every fine integration step")
        if self.written+len(volts)>self.steps: raise ValueError("Reference exceeds promised duration")
        releases = np.maximum(0.,volts-self.engine.parameters["graded_release"])
        releases *= self.engine.output_enabled[self.record_indices]
        history = np.vstack([self.prefix,releases])
        delayed = history[:len(volts)]
        self.graded[self.written:self.written+len(volts)] = (self.g_weights @ delayed.T).T
        self.prefix = history[-self.delay:].copy() if self.delay else history[:0].copy()
        for pre,time_ms in zip(result["spike_indices"],result["spike_times"],strict=True):
            step = int(round(float(time_ms)/self.engine.dt))
            row = step+self.delay-self.start_step
            if not self.inside[int(pre)] and self.engine.output_enabled[int(pre)]:
                self.pending_spikes.setdefault(row,[]).append(int(pre))
        for row in range(self.written,self.written+len(volts)):
            for pre in self.pending_spikes.pop(row,[]): self._spike(pre,row)
        chemistry = getattr(self.engine,"chemistry",None)
        organs = getattr(self.engine,"organs",None)
        if chemistry is not None or organs is not None:
            if len(volts) != self.engine._steps(1.,"component reference tick"):
                raise ValueError("Chemical and organ reference observer must run every 1 ms")
        if chemistry is not None:
            outside_rates = chemistry.last_source_rates.copy(); outside_rates[self.active] = 0.
            self.chemical_sources.append(chemistry.field.projection.mean_rates_hz(outside_rates)/chemistry.field.parameters.max_source_rate_hz[:,None])
            self.chemical_fields.append(chemistry.field.C.copy())
            ids = self.component_data["endocrine_indices"]
            self.component_data["endocrine_rates"].append(chemistry.rates_hz[ids].copy())
        if organs is not None:
            self.component_data["organ_motor_sum_hz"].append(np.asarray([organs.rates_hz[np.asarray(m["output_indices"],int)[~self.inside[np.asarray(m["output_indices"],int)]]].sum() for m in organs.modules]))
        self.written += len(volts)

    def finish(self):
        if self.written != self.steps: raise ValueError("Incomplete full-context reference")
        components = {k:np.asarray(v) for k,v in self.component_data.items()}
        return BoundaryRecording(self.metadata,self.graded,self.spike,
            chemical_sources=np.asarray(self.chemical_sources) if self.chemical_sources else None,
            chemical_fields=np.asarray(self.chemical_fields) if self.chemical_fields else None,
            initial_state=self.initial_state,component_data=components or None)
