"""Six finite, explicit model assumptions; never edits a frozen provider."""
from __future__ import annotations
import copy
import math
from flybrain.paralimbo_upgrade.interfaces import identity

DEFAULTS = {'spike_weight': .275, 'tau_membrane': 20., 'tau_synapse': 5.,
            'graded_gain': .0001, 'graded_tau_membrane': 20., 'graded_tau_synapse': 5.}
BOUNDS = {'spike_weight': (.1375, .55), 'tau_membrane': (10., 40.), 'tau_synapse': (2.5, 10.),
          'graded_gain': (.00003, .0003), 'graded_tau_membrane': (10., 40.), 'graded_tau_synapse': (2.5, 10.)}
NATIVE_POPULATION = 175401
SCHEMA = 'transmission-six-parameter-dynamics-v1'


def validate_parameters(values=None):
    values = dict(values or {})
    if set(values) - set(DEFAULTS):
        raise ValueError('Unregistered intrinsic parameter')
    result = dict(DEFAULTS)
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Intrinsic parameter must be finite scalar')
        lo, hi = BOUNDS[name]
        if not lo <= value <= hi:
            raise ValueError('Intrinsic parameter outside frozen bounds: ' + name)
        result[name] = float(value)
    return result


def configured_parameters(inherited, manifest, values=None, *, dt_ms=.1, record_dt_ms=1.):
    result = copy.deepcopy(dict(inherited))
    result.update(validate_parameters(values))
    cap = manifest.get('runtime_profile', {}).get('graded_input_cap')
    if cap is not None and cap != .8:
        raise ValueError('Only the frozen 0.8 graded cap is supported')
    if 'graded_input_cap' in result and result['graded_input_cap'] != cap:
        raise ValueError('Foreign inherited gain cap')
    if cap is not None:
        result['graded_input_cap'] = cap
    for key, value in (('dt', dt_ms), ('record_dt_ms', record_dt_ms)):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError('Positive finite physical time required')
        result[key] = float(value)
    if result['dt'] > min(result['dt_graded'], result['graded_tau_membrane'], result['graded_tau_synapse'], result['tau_membrane'], result['tau_synapse']):
        raise ValueError('Timestep exceeds inherited integration bound')
    for name in ('record_dt_ms', 'synaptic_delay'):
        steps = round(result[name] / result['dt'])
        if steps < (1 if name == 'record_dt_ms' else 0) or not math.isclose(steps * result['dt'], result[name], abs_tol=1e-9, rel_tol=0):
            raise ValueError(name + ' must align with integration timestep')
    return result


def parameter_manifest(values=None):
    body = {'schema': SCHEMA, 'parameters': validate_parameters(values), 'bounds': BOUNDS,
            'evidence_class': 'assumed', 'gain_cap': 'inherit pinned provider; graded candidate 0.8',
            'anatomy_changed': False, 'electrical_modes_changed': False,
            'gain_caution': 'Graded gain cancels on cap-saturated rows; assess input-only sensitivity before search.'}
    return body | {'identity': identity(body)}
