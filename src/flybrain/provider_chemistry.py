"""Source-aware chemistry for new connectome providers and reduced circuits.

No FlyWire neuron-count or empirical MB compartment requirement is transferred
to another specimen. Region anchor membership is explicitly a coarse model.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import numpy as np
from scipy import sparse

from .enzymes import EnzymeSystem
from .neuromod.compartments import CompartmentMap
from .neuromod.field import FieldEngine, FieldParameters, FIELD_SPECIES, build_source_projection
from .neuromod.receptors import ReceptorModel, read_receptors, receptor_bounds
from .neuromod.state import STATE_NAMES
from .rt.engine_rt import FastReceptors
from .wholebrain_neuromod import normalize_neuromod_options


def provider_compartments(neurons):
    field = "root_region" if "root_region" in neurons else "super_class"
    regions = neurons[field].fillna("unassigned").replace("", "unassigned")
    names = tuple(sorted(set(regions)-{"hemolymph"}))+ ("hemolymph",)
    membership = np.vstack([(regions == name).to_numpy() for name in names])
    membership[-1] = neurons.super_class.eq("endocrine").to_numpy()
    return CompartmentMap(names, membership, np.zeros((len(names),len(names))),
                          np.full(len(neurons),-1,np.int16),neurons.root_id.to_numpy(np.int64),
                          {"method":"source region anchor; no invented spatial diffusion or MB cluster recovery", "source_field":field})


class ProviderChemistry:
    def __init__(self, root, engine, network, options):
        self.engine = engine; self.neurons = network["neurons"]
        source_neurons = network.get("parent_source_neurons", self.neurons)
        self.source_population_size = len(source_neurons)
        self.model_indices = np.asarray(network.get("parent_neuron_indices", np.arange(len(self.neurons))), np.int64)
        self.boundary = None
        self.options = normalize_neuromod_options(options)
        if self.options["plasticity_enabled"]:
            raise ValueError("This provider lacks a verified MB plasticity-compartment transfer; set plasticity_enabled=false")
        self.mapping = provider_compartments(source_neurons)
        self.tick_steps = engine._steps(1., "chemical_tick_ms")
        parameters = FieldParameters.from_root(root)
        projection = build_source_projection(source_neurons,self.mapping)
        # Provider annotations can include evidence transferred between specimens.
        # A successful source projection does not turn that inference into a measurement.
        projection.metadata.update({
            "units": "Hz mean over compiled positive chemical annotations",
            "identity": "compiled positive known_nt; native and inferred evidence remain in the model provenance",
            "model_id": network.get("model_id"),
            "model_hash": network.get("manifest", {}).get("model_hash"),
        })
        if self.source_population_size != len(self.neurons):
            from .selection import slice_source_projection
            projection = slice_source_projection(projection, self.model_indices)
        self.field = FieldEngine(parameters,self.mapping.names,self.mapping.adjacency,projection)
        self.enzymes = EnzymeSystem(self.options["enzymes"],self.mapping.names)
        self.enzymes.configure_field(self.field)
        self.rates_hz = np.zeros(len(self.neurons))
        # Source-scoped release modulation uses source membership and does not
        # require the unimported empirical KC-to-MBON compartment assignment.
        rows = [r for r in read_receptors(root/"config/receptors.csv") if r["edge_scope"] in {"none","all_out"}]
        weights = sparse.csc_matrix((engine.csc_counts,engine.csc_indices,engine.csc_indptr),shape=(engine.n_neurons,engine.n_neurons))
        self.receptors = ReceptorModel(rows,self.neurons,self.mapping,weights,model_indices=self.model_indices,bounds=receptor_bounds(root))
        for row,(target,_) in zip(self.receptors.rows,self.receptors.targets,strict=True):
            if row["enabled"] and row["effect"]=="release_prob" and np.any(target & engine.graded_mask):
                raise ValueError("Provider graded release receptors require an explicit graded-edge adapter")
        self.effects = FastReceptors(self.receptors)
        self.membership = self.receptors.membership.tocsr()
        if self.source_population_size != len(self.neurons):
            self.mapping = replace(self.mapping, membership=self.mapping.membership[:,self.model_indices],
                mb_assignment=self.mapping.mb_assignment[self.model_indices],model_root_ids=self.mapping.model_root_ids[self.model_indices])
        self.state_values = dict(self.options["initial_state"])
        self.time_ms = 0.
        self.reset()

    def apply_chemical_levels(self):
        for name,level in self.options["chemical_levels"].items(): self.field.C[FIELD_SPECIES.index(name),:] = level

    def update_effects(self):
        self.effects.evaluate(self.field.C,1.)
        self.engine.decay_v_each[:] = np.exp(-self.engine.dt/(self.engine.tau_membrane*self.effects.tau_factor))

    def advance(self,spike_indices):
        targets = np.bincount(spike_indices,minlength=self.engine.n_neurons)*1000.
        graded = self.engine.graded_mask
        targets[graded] = np.clip((self.engine.v[graded]-self.engine.parameters["graded_release"])/10.,0.,1.)*50.
        self.rates_hz += -np.expm1(-1/20.)*(targets-self.rates_hz)
        source_rates = self.rates_hz.copy()
        source_rates[~self.engine.output_enabled] = 0.
        # Already a private, freshly allocated tick snapshot; projection is read-only.
        self.last_source_rates = source_rates
        drive = self.field.projection.mean_rates_hz(source_rates)/self.field.parameters.max_source_rate_hz[:,None]
        if self.boundary is not None: drive += self.boundary.chemical_tick(self.engine.step)["source_drive"]
        if self.enzymes.enabled: self.enzymes.step(self.field,drive,1.)
        else: self.field.advance_drive(drive)
        if self.options["chemical_control_mode"] == "clamped": self.apply_chemical_levels()
        # Explicit normalized boundary state, not an inferred animal condition.
        for name,target,tau in (("energy",self.options["feeding"],300000.),("hydration",self.options["drinking"],60000.),("arousal",self.options["locomotion"],5000.),("stress",self.options["aversive"],60000.)):
            self.state_values[name] += -np.expm1(-1/tau)*(target-self.state_values[name])
        self.state_values["circadian_phase"] = (self.state_values["circadian_phase"]+1/86400000.)%1.
        self.time_ms += 1.
        self.update_effects()

    def empty_recording(self,count):
        result = {"concentrations_au":np.empty((count,len(FIELD_SPECIES),len(self.mapping.names)),np.float32),
                  "state_values":np.empty((count,len(STATE_NAMES)),np.float32),"hormones_au":np.empty((count,0),np.float32),
                  "plasticity_change_l1":np.zeros(count,np.float64)}
        if self.enzymes.enabled:
            result["enzyme_pools_au"] = np.empty((count,*self.enzymes.pools.shape),np.float64)
            result["enzyme_flux_au_per_ms"] = np.empty((count,*self.enzymes.flux.shape),np.float64)
        return result

    def capture(self,output,first,last):
        output["concentrations_au"][first:last] = self.field.C
        output["state_values"][first:last] = [self.state_values[k] for k in STATE_NAMES]
        if self.enzymes.enabled:
            output["enzyme_pools_au"][first:last] = self.enzymes.pools
            output["enzyme_flux_au_per_ms"][first:last] = self.enzymes.flux

    def reset(self):
        self.field.reset(); self.enzymes.reset(); self.enzymes.configure_field(self.field)
        self.last_source_rates = np.zeros(len(self.neurons))
        self.rates_hz.fill(0.); self.state_values = dict(self.options["initial_state"]); self.time_ms = 0.
        self.apply_chemical_levels(); self.update_effects()

    def snapshot(self):
        return {"field_C":self.field.C.copy(),"field_steps":self.field.steps,"field_clamps":self.field.clamp_count,
                "rates_hz":self.rates_hz.copy(),"enzymes":self.enzymes.snapshot(),"state_values":dict(self.state_values),
                "time_ms":self.time_ms,"receptor_guards":self.effects.guard_events}

    def restore(self,saved):
        if np.asarray(saved["field_C"]).shape != self.field.C.shape: raise ValueError("Provider chemical snapshot has different anatomy")
        self.field.C[:] = saved["field_C"]; self.field.steps = saved["field_steps"]; self.field.clamp_count = saved["field_clamps"]
        self.rates_hz[:] = saved["rates_hz"]; self.enzymes.restore(saved["enzymes"])
        self.state_values = dict(saved["state_values"]); self.time_ms = saved["time_ms"]
        self.update_effects(); self.effects.guard_events = saved["receptor_guards"]

    def diagnostics(self):
        return {"field_clamps":self.field.clamp_count,"receptor_guards":self.effects.guard_events,
                "enzymes_enabled":self.enzymes.enabled,"substrate_limited_reactions":self.enzymes.limited_reactions,
                "plastic_edges":0,"weight_change_l1":0.,"plasticity_status":"unavailable for this provider"}

    def metadata(self):
        return {"schema_version":1,"enabled":True,"scenario":self.options["scenario"],"options":copy.deepcopy(self.options),
                "species":list(FIELD_SPECIES),"compartments":list(self.mapping.names),"state_names":list(STATE_NAMES),"hormone_names":[],
                "units":"a.u.","neurons":self.engine.n_neurons,"neuron_order":"provider entity order",
                "source_projection":self.field.projection.metadata,"receptor_coverage":self.receptors.coverage,
                "enzymes":self.enzymes.metadata(),"chemical_tick_ms":1.,
                "assumptions":["Source-region anchors are coarse chemical volumes, not release-site measurements.",
                               "Existing receptor identities and signs are transferred as explicit cell-type model hypotheses; expression levels remain unknown.",
                               "No FlyWire-specific MB plasticity compartments or 76-cell endocrine inventory are fabricated in this provider.",
                               "State relaxation, source-rate filter and graded-release scaling are normalized model assumptions."]}


def build_model_chemistry(root,engine,network,options):
    from pathlib import Path
    if network.get("model_id","flywire-783") == "flywire-783":
        from .wholebrain_neuromod import WholeBrainChemistry
        return WholeBrainChemistry.from_root(Path(root),engine,network["neurons"],options,
            source_neurons=network.get("parent_source_neurons"), model_indices=network.get("parent_neuron_indices"))
    return ProviderChemistry(Path(root),engine,network,options)
