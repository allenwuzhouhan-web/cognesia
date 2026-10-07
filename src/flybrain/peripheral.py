"""Anatomical peripheral ports and explicitly modeled organ dynamics.

Annotations identify neural interfaces. The transfer equations below are model
assumptions, never a claim that the EM reconstruction contains organ physiology.
"""
from __future__ import annotations

import copy
import hashlib
import re

import numpy as np

SOURCE = "https://www.nature.com/articles/s41586-026-10735-w"
SENSORY_CLASSES = {"sensory", "sensory_ascending", "sensory_descending"}
EFFECTOR_CLASSES = {"motor", "endocrine", "visceral_circulatory", "ascending_visceral_circulatory"}


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def _module(identifier, label, kind, inputs, outputs, **extra):
    return {"id": identifier, "label": label, "kind": kind,
            "neuron_indices": sorted(set(inputs)|set(outputs)), "input_indices": list(inputs),
            "output_indices": list(outputs), "status": "annotated_neural_interface" if inputs or outputs else "modeled_physiology_only",
            "ports": [{"id": "stimulus", "direction": "input", "unit": "normalized model stimulus"},
                      {"id": "activation", "direction": "state", "unit": "a.u."},
                      {"id": "output", "direction": "output", "unit": "a.u."}],
            "source": SOURCE, "assumptions": ["Neural identity/target annotation is source data; organ state and feedback kinetics are explicit model assumptions."], **extra}


def catalog(neurons=None):
    if neurons is None:
        return []
    def values(field):
        return neurons[field].fillna("").astype(str) if field in neurons else np.full(len(neurons), "")
    classes = np.asarray(values("super_class")); cells = np.asarray(values("cell_class")); sub = np.asarray(values("cell_sub_class"))
    types = np.asarray(values("cell_type")); side = np.asarray(values("side"))
    sensory = np.isin(classes, list(SENSORY_CLASSES)); effector = np.isin(classes, list(EFFECTOR_CLASSES))
    result = []
    definitions = [
        ("vision", "Compound eyes", "sensory", (cells == "visual") | (np.asarray(values("native_cell_class")) == "photoreceptor_neuron") | np.isin(types, ["R1-6","R7","R8"])),
        ("ocelli", "Ocelli", "sensory", sub == "ocellar"),
        ("hearing", "Johnston’s organ · hearing", "sensory", (sub == "auditory") | np.array([bool(re.match(r"JO-[AB]", x)) for x in types])),
        ("wind-gravity", "Johnston’s organ · wind and gravity", "sensory", sub == "wind_gravity"),
        ("smell", "Olfactory sensilla", "sensory", cells == "olfactory"),
        ("taste", "Gustatory sensilla", "sensory", (cells == "gustatory") | np.array(["gustatory" in x or "taste" in x for x in cells])),
        ("touch", "Touch and bristles", "sensory", (cells == "mechanosensory") | np.array(["bristle" in x for x in cells])),
        ("temperature", "Temperature sensilla", "sensory", (cells == "thermosensory") | np.array(["thermo" in x for x in cells])),
        ("humidity", "Humidity sensilla", "sensory", (cells == "hygrosensory") | np.array(["hygro" in x for x in cells])),
    ]
    for name, label, kind, mask in definitions:
        for laterality in ("left", "right", "center"):
            ids = np.flatnonzero(mask & sensory & (side == laterality)).tolist()
            if ids: result.append(_module(name+"-"+laterality, label+" · "+laterality, kind, ids, [], system=name, side=laterality, parent_id=name))
    # BANC supplies per-neuron nerve, organ and muscle target names. Preserve
    # those subdivisions; don't collapse six legs into a generic body proxy.
    grouped = {}
    target_values = np.asarray(values("peripheral_target_type"))
    nerve_values = np.asarray(values("nerve"))
    for role,column,mask in (("input_indices","body_part_sensory",sensory),("output_indices","body_part_effector",effector)):
        if column not in neurons: continue
        bodies = np.asarray(values(column))
        for i in np.flatnonzero(mask & (bodies != "")):
            key = (bodies[i], target_values[i] or "unspecified target", side[i] or "unassigned", nerve_values[i] or "unassigned")
            grouped.setdefault(key,{"input_indices":[],"output_indices":[]})[role].append(int(i))
    for key,ports in sorted(grouped.items()):
        body,target,laterality,nerve = key
        inputs,outputs = ports["input_indices"],ports["output_indices"]
        name = "anatomy-"+_slug(body+" "+target+" "+laterality)
        name += "-"+hashlib.sha256("|".join(key).encode()).hexdigest()[:8]
        kind = "muscle" if "muscle" in target else "sensory" if not outputs else "organ"
        result.append(_module(name," · ".join([body.replace("_"," "),target.replace("_"," "),laterality]),kind,inputs,outputs,
                              system=body,parent_id=_slug(body),side=laterality,nerve=nerve,subdivision=target))
    return result


def normalize_peripheral_options(value=None):
    value = dict(value or {})
    allowed = {"enabled", "modules", "external_inputs", "feedback_gain_mv", "motor_scale_hz", "time_constant_ms", "modeled_links"}
    if set(value)-allowed: raise ValueError("Unknown peripheral option")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool): raise ValueError("peripheral.enabled must be boolean")
    modules = value.get("modules", [])
    if not isinstance(modules, list) or any(not isinstance(x,str) for x in modules): raise ValueError("Peripheral modules must be IDs")
    external = value.get("external_inputs", {})
    if not isinstance(external, dict): raise ValueError("Peripheral stimuli must be keyed model values")
    result = {"enabled": enabled, "modules": sorted(set(modules)), "external_inputs": {}, "modeled_links": copy.deepcopy(value.get("modeled_links", []))}
    for key, val in external.items():
        if isinstance(val,bool) or not isinstance(val,(int,float)) or not np.isfinite(val) or not 0 <= val <= 1: raise ValueError("Organ stimulus must be on [0,1]")
        result["external_inputs"][str(key)] = float(val)
    for key, default, bound in (("feedback_gain_mv",5.,100.),("motor_scale_hz",50.,1000.),("time_constant_ms",100.,100000.)):
        val = value.get(key,default)
        if isinstance(val,bool) or not isinstance(val,(int,float)) or not np.isfinite(val) or val <= 0 or val > bound: raise ValueError("Invalid peripheral "+key)
        result[key] = float(val)
    if not isinstance(result["modeled_links"], list): raise ValueError("modeled_links must be a list")
    return result


class PeripheralRuntime:
    """Independent subdivision states driven by identified motor/visceral cells.

    Input currents are normalized model currents. Physical force, sound level,
    organ flow and metabolic dose are deliberately not inferred from these.
    """
    def __init__(self, modules=None, dt_ms=1., options=None, *, neurons=None, source_neurons=None, parent_indices=None):
        if neurons is None and hasattr(modules, "columns"):
            neurons, modules = modules, None
        if neurons is None: raise ValueError("Peripheral runtime requires neural identity table")
        self.options = normalize_peripheral_options(options)
        self.dt_ms = float(dt_ms); self.neurons = neurons
        source_neurons = neurons if source_neurons is None else source_neurons
        parent_indices = np.arange(len(neurons)) if parent_indices is None else np.asarray(parent_indices)
        self.boundary = None
        available = {m["id"]: m for m in (catalog(source_neurons) if modules is None else modules)}
        selected = self.options["modules"]
        if self.options["enabled"] and not selected: raise ValueError("Select at least one anatomical peripheral module")
        if set(selected)-set(available): raise ValueError("Selected peripheral module is absent from this model")
        self.modules = [copy.deepcopy(available[key]) for key in selected]
        ids = {str(x): i for i,x in enumerate(source_neurons.get("entity_id", source_neurons.root_id.astype(str)))}
        for link in self.options["modeled_links"]:
            if not isinstance(link,dict) or set(link)-{"module_id","direction","entity_ids"}: raise ValueError("Invalid modeled organ link")
            if link.get("direction") not in {"afferent","efferent"} or link.get("module_id") not in selected: raise ValueError("Modeled link has unknown module/direction")
            targets = link.get("entity_ids", [])
            if not targets or any(x not in ids for x in targets): raise ValueError("Modeled organ link requires existing neuron identities")
            module = next(m for m in self.modules if m["id"] == link["module_id"])
            field = "input_indices" if link["direction"] == "afferent" else "output_indices"
            module[field] = sorted(set(module[field]) | {ids[x] for x in targets})
            module.setdefault("modeled_links", []).append(copy.deepcopy(link))
            module["status"] = "annotated_and_explicitly_modeled_links"
        local = {int(parent):index for index,parent in enumerate(parent_indices)}
        for module in self.modules:
            module["source_output_count"] = len(module["output_indices"])
            for name in ("neuron_indices","input_indices","output_indices"):
                module[name] = [local[i] for i in module[name] if i in local]
        if set(self.options["external_inputs"])-set(selected): raise ValueError("Stimulus targets an unloaded organ module")
        self.state = np.zeros((len(self.modules),3),np.float64)  # activation, output, cumulative effort
        self.t_ms = 0.
        self.rates_hz = np.zeros(len(neurons),np.float64)

    def advance(self, neuron_rates_hz=None, dt_ms=None):
        if not self.options["enabled"]: return self.readout()
        dt = self.dt_ms if dt_ms is None else float(dt_ms)
        if not np.isfinite(dt) or dt <= 0: raise ValueError("Peripheral step must be positive")
        if neuron_rates_hz is not None:
            rates = np.asarray(neuron_rates_hz,np.float64)
            if rates.shape != self.rates_hz.shape or not np.isfinite(rates).all() or np.any(rates < 0): raise ValueError("Peripheral source rates differ from neural identity")
            self.rates_hz[:] = rates
        a = -np.expm1(-dt/self.options["time_constant_ms"])
        external = self.boundary.organ_tick(self.t_ms+dt) if self.boundary is not None else np.zeros(len(self.modules))
        for i,module in enumerate(self.modules):
            output = module["output_indices"]
            denominator = module["source_output_count"]
            motor = (float(self.rates_hz[output].sum())+external[i])/denominator/self.options["motor_scale_hz"] if denominator else 0.
            stimulus = self.options["external_inputs"].get(module["id"],0.)
            target = min(1., max(0., motor+stimulus))
            self.state[i,0] += a*(target-self.state[i,0])
            self.state[i,1] += a*(self.state[i,0]-self.state[i,1])
            self.state[i,2] += self.state[i,1]*dt/1000.
        self.t_ms += dt
        return self.readout()

    def membrane_drive(self):
        drive = np.zeros(len(self.neurons),np.float64)
        if self.options["enabled"]:
            for i,module in enumerate(self.modules):
                targets = module["input_indices"]
                # Overlapping atlas/module aliases don't multiply the same stimulus.
                drive[targets] = np.maximum(drive[targets],self.state[i,0]*self.options["feedback_gain_mv"])
        indices = np.flatnonzero(drive).astype(np.int32)
        return indices, drive[indices]

    def set_input(self, module_id, value):
        if module_id not in self.options["modules"] or not np.isfinite(value) or not 0 <= value <= 1: raise ValueError("Invalid organ stimulus")
        self.options["external_inputs"][module_id] = float(value)

    def readout(self):
        return {"time_ms":self.t_ms,"units":"a.u.; modeled transfer dynamics", "modules":[{"id":m["id"],"label":m["label"],"activation":float(self.state[i,0]),"output":float(self.state[i,1]),"cumulative_effort_au_s":float(self.state[i,2]),"status":m["status"]} for i,m in enumerate(self.modules)]}

    def snapshot(self):
        return {"state":self.state.copy(),"rates_hz":self.rates_hz.copy(),"time_ms":self.t_ms,"options":copy.deepcopy(self.options),"module_ids":[m["id"] for m in self.modules]}

    def restore(self, saved):
        if saved["module_ids"] != [m["id"] for m in self.modules] or np.asarray(saved["state"]).shape != self.state.shape: raise ValueError("Peripheral snapshot has different anatomy")
        self.state[:] = saved["state"]; self.rates_hz[:] = saved["rates_hz"]; self.t_ms = saved["time_ms"]
        self.options = normalize_peripheral_options(saved["options"])


def build_model_peripheral(network, options):
    return PeripheralRuntime(neurons=network["neurons"], options=options,
        source_neurons=network.get("parent_source_neurons"), parent_indices=network.get("parent_neuron_indices"))
