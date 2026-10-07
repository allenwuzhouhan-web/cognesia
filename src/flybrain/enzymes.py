"""Opt-in normalized ChAT/AChE/Tbh synthesis and degradation kinetics.

Reaction identity is biological; all rate magnitudes, transport and pools here
are declared model assumptions in a.u. No molar concentration is inferred.
"""
from __future__ import annotations

import copy
import numpy as np

ENZYME_IDS = ("ChAT", "AChE", "Tbh")
POOL_NAMES = ("choline", "acetyl_coa", "ach_vesicle", "tyramine", "oa_vesicle", "choline_product", "acetate_product")
DEFAULT_POOLS = {"choline": 1., "acetyl_coa": 1., "ach_vesicle": .5, "tyramine": 1., "oa_vesicle": .5, "choline_product": 0., "acetate_product": 0.}
DEFAULT_KINETICS = {"ChAT": {"vmax_au_per_ms": .002, "km_au": .5},
                    "AChE": {"vmax_au_per_ms": .01, "km_au": .5},
                    "Tbh": {"vmax_au_per_ms": .002, "km_au": .5}}
SOURCES = {
    "ChAT": "https://flybase.org/reports/FBgn0000303",
    "AChE": "https://www.ncbi.nlm.nih.gov/gene/41625",
    "Tbh": "https://flybase.org/reports/FBgn0010329",
}


def _number(value, label, minimum=0., maximum=100.):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(label+f" must be a finite number in [{minimum:g},{maximum:g}]")
    return float(value)


def normalize_enzyme_options(value=None):
    value = dict(value or {})
    allowed = {"enabled", "activities", "compartments", "kinetics", "initial_pools", "release_rate_per_ms"}
    if set(value)-allowed: raise ValueError("Unknown enzyme option")
    enabled = value.get("enabled",False)
    if not isinstance(enabled,bool): raise ValueError("enzymes.enabled must be boolean")
    activities = value.get("activities",{})
    if not isinstance(activities,dict) or set(activities)-set(ENZYME_IDS): raise ValueError("Unknown enzyme activity")
    compartments = value.get("compartments",[])
    if not isinstance(compartments,list) or any(not isinstance(x,str) for x in compartments): raise ValueError("Enzyme compartments must be source compartment names")
    initial = value.get("initial_pools",{})
    if not isinstance(initial,dict) or set(initial)-set(POOL_NAMES): raise ValueError("Unknown synthesis precursor pool")
    kinetics = copy.deepcopy(DEFAULT_KINETICS)
    supplied = value.get("kinetics",{})
    if not isinstance(supplied,dict) or set(supplied)-set(ENZYME_IDS): raise ValueError("Unknown enzyme kinetics")
    for name, parameters in supplied.items():
        if not isinstance(parameters,dict) or set(parameters)-{"vmax_au_per_ms","km_au"}: raise ValueError("Unknown kinetic parameter")
        for key,val in parameters.items():
            kinetics[name][key] = _number(val,name+"."+key,1e-9,100.)
    return {"enabled": enabled, "activities": {name:_number(activities.get(name,1.),name,0.,10.) for name in ENZYME_IDS},
            "compartments": sorted(set(compartments)), "kinetics": kinetics,
            "initial_pools": {name:_number(initial.get(name,DEFAULT_POOLS[name]),name,0.,100.) for name in POOL_NAMES},
            "release_rate_per_ms": _number(value.get("release_rate_per_ms",.01),"release_rate_per_ms",0.,1.)}


class EnzymeSystem:
    def __init__(self, options=None, compartment_names=()):
        self.options = normalize_enzyme_options(options)
        self.compartments = tuple(compartment_names)
        if not self.compartments: raise ValueError("Enzymes require named chemical compartments")
        if set(self.options["compartments"])-set(self.compartments): raise ValueError("Enzyme targets an unknown compartment")
        self.selected = np.array([not self.options["compartments"] or name in self.options["compartments"] for name in self.compartments],bool)
        self.activities = dict(self.options["activities"])
        self.reset()

    @property
    def enabled(self):
        return self.options["enabled"]

    def reset(self):
        self.activities = dict(self.options["activities"])
        self.pools = np.array([[self.options["initial_pools"][name]]*len(self.compartments) for name in POOL_NAMES],np.float64)
        self.flux = np.zeros((5,len(self.compartments)),np.float64) # ChAT, AChE, Tbh, ACh release, OA release
        self.total_flux = np.zeros_like(self.flux)
        self.time_ms = 0.
        self.limited_reactions = 0

    def set_activity(self, enzyme_id, activity):
        if enzyme_id not in ENZYME_IDS: raise ValueError("Unknown enzyme")
        self.activities[enzyme_id] = _number(activity,enzyme_id,0.,10.)

    def get_activity(self, enzyme_id):
        if enzyme_id not in ENZYME_IDS: raise ValueError("Unknown enzyme")
        return self.activities[enzyme_id]

    def configure_field(self, field):
        if self.enabled:
            if tuple(field.compartment_names) != self.compartments: raise ValueError("Enzyme/field compartment ordering differs")
            if "ACh" not in field.species or "OA" not in field.species: raise ValueError("Enzyme pathways require ACh and OA field species")
            # AChE replaces the historical unspecified ACh clearance; inhibiting
            # AChE does not silently restore that extra removal term.
            field.clearance_disabled[field.species.index("ACh"), self.selected] = True

    def _amount(self, name, substrate, dt):
        p = self.options["kinetics"][name]
        desired = dt*p["vmax_au_per_ms"]*self.activities[name]*substrate/(p["km_au"]+substrate)
        desired *= self.selected
        self.limited_reactions += int(np.count_nonzero(desired > substrate))
        return np.minimum(desired,substrate)

    def prepare_source_drive(self, normalized_drive, field, dt_ms=1.):
        """Synthesize intracellular transmitter and release available vesicle pools.

        Only selected compartments replace ACh/OA source release. Other fields
        and compartments retain the original normalized source-driven equations.
        """
        drive = np.asarray(normalized_drive,np.float64)
        if not self.enabled: return drive
        dt = _number(dt_ms,"reaction timestep",1e-9,1000.)
        if drive.shape != field.C.shape or not np.isfinite(drive).all() or np.any(drive < 0): raise ValueError("Enzyme release drive is invalid")
        self.flux.fill(0.)
        choline, acetyl, ach, tyramine, oa = [self.pools[POOL_NAMES.index(x)] for x in POOL_NAMES[:5]]
        substrate = np.minimum(choline,acetyl)
        made_ach = self._amount("ChAT",substrate,dt)
        choline -= made_ach; acetyl -= made_ach; ach += made_ach
        made_oa = self._amount("Tbh",tyramine,dt)
        tyramine -= made_oa; oa += made_oa
        self.flux[0] = made_ach/dt; self.flux[2] = made_oa/dt
        result = drive.copy()
        for species,pool,row in (("ACh",ach,3),("OA",oa,4)):
            i = field.species.index(species)
            # Exact exponential pool release avoids negative states at high drive.
            amount = pool*(-np.expm1(-self.options["release_rate_per_ms"]*drive[i]*dt))*self.selected
            pool -= amount; self.flux[row] = amount/dt
            scale = field.drive_scale[i]*field.parameters.source_gain[i]
            if scale <= 0 and np.any(amount): raise ValueError("Cannot release enzyme product into a zero-gain chemical field")
            result[i,self.selected] = amount[self.selected]/scale if scale > 0 else 0.
        self.total_flux += self.flux*dt
        self.time_ms += dt
        return result

    def degrade(self, concentrations, species, dt_ms=1.):
        if not self.enabled: return
        dt = float(dt_ms); ach = concentrations[tuple(species).index("ACh")]
        amount = self._amount("AChE",ach.astype(np.float64),dt)
        ach[:] = np.maximum(0.,ach-amount)
        # Products are retained separately. No unsupported uptake/recycling into
        # intracellular synthesis pools is smuggled into this reaction.
        self.pools[POOL_NAMES.index("choline_product")] += amount
        self.pools[POOL_NAMES.index("acetate_product")] += amount
        self.flux[1] = amount/dt; self.total_flux[1] += amount

    def step(self, field, source_drive, dt_ms=1.):
        drive = self.prepare_source_drive(source_drive,field,dt_ms)
        field.advance_drive(drive)
        self.degrade(field.C,field.species,dt_ms)
        return field.C

    def snapshot(self):
        return {"compartments":list(self.compartments),"options":copy.deepcopy(self.options),"activities":dict(self.activities),
                "pools":self.pools.copy(),"flux":self.flux.copy(),"total_flux":self.total_flux.copy(),
                "time_ms":self.time_ms,"limited_reactions":self.limited_reactions}

    def restore(self,saved):
        if tuple(saved["compartments"]) != self.compartments or saved["options"] != self.options: raise ValueError("Enzyme snapshot belongs to another reaction system")
        for key in ("pools","flux","total_flux"):
            values = np.asarray(saved[key],np.float64)
            if values.shape != getattr(self,key).shape or not np.isfinite(values).all() or np.any(values < 0): raise ValueError("Invalid enzyme snapshot "+key)
            getattr(self,key)[:] = values
        for name,value in saved["activities"].items(): self.set_activity(name,value)
        self.time_ms = float(saved["time_ms"]); self.limited_reactions = int(saved["limited_reactions"])

    def metadata(self):
        return {"enabled":self.enabled,"enzymes":list(ENZYME_IDS),"pool_names":list(POOL_NAMES),"compartments":list(self.compartments),
                "options":copy.deepcopy(self.options),"sources":SOURCES,"units":"normalized arbitrary model units and ms",
                "assumptions":["Reaction identities are sourced; kinetic magnitudes, enzyme expression coverage and precursor availability are assumptions.",
                               "Intracellular synthesis pools are distinct from extracellular/modulatory fields.",
                               "AChE replaces selected ACh field clearance; fast cholinergic synapse kinetics are unchanged.",
                               "ChAT and Tbh products release according to actual source activity; no extracellular TA-to-OA conversion.",
                               "No molecular concentration, gene-expression magnitude or physiological dose is inferred."]}
