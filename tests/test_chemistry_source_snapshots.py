from types import SimpleNamespace
import numpy as np
import pytest

from flybrain.provider_chemistry import ProviderChemistry
from flybrain.wholebrain_neuromod import WholeBrainChemistry


@pytest.mark.parametrize('chemistry_type', [ProviderChemistry, WholeBrainChemistry])
def test_tick_source_snapshot_is_private_and_previous_tick_remains_unchanged(chemistry_type):
    chemistry = chemistry_type.__new__(chemistry_type)
    chemistry.engine = SimpleNamespace(n_neurons=3, graded_mask=np.array([False,True,False]),
        v=np.array([-52.,-49.,-52.]), g=np.zeros(3), parameters={'graded_release':-54.},
        output_enabled=np.array([True,True,False]), step=1, _steps=lambda *args:100)
    chemistry.rates_hz = np.zeros(3)
    chemistry.options = {'chemical_control_mode':'initial','plasticity_enabled':False,
                          'feeding':0.,'drinking':0.,'locomotion':0.,'aversive':0.}
    chemistry.boundary = None
    chemistry.enzymes = SimpleNamespace(enabled=False)
    projected = []
    def projection(rates):
        projected.append(rates)
        return np.zeros((8,1))
    chemistry.field = SimpleNamespace(projection=SimpleNamespace(mean_rates_hz=projection),
        parameters=SimpleNamespace(max_source_rate_hz=np.ones(8)), advance_drive=lambda _:None)
    chemistry.update_effects = lambda:None
    chemistry.state_values = dict(energy=0.,hydration=0.,arousal=0.,stress=0.,circadian_phase=0.)
    chemistry.time_ms = 0.
    chemistry.nm = {'state_source_max_rate_hz':50.,'runtime_rate_tau_ms':20.,'state_dt_ms':10.}
    chemistry.model_indices = np.arange(3)
    chemistry.state_output = {'source_rate_scale':np.ones(3),'endocrine_mask':np.zeros(3,bool),
        'endocrine_drive':np.zeros(3),'source_max_rate_hz':50.}
    chemistry.advance(np.array([0,2]))
    snapshot = chemistry.last_source_rates
    expected = -np.expm1(-1/20.) * np.array([1000.,25.,0.])
    np.testing.assert_array_equal(snapshot, expected)
    assert projected[-1] is snapshot
    assert not np.shares_memory(snapshot, chemistry.rates_hz)
    chemistry.advance(np.array([1]))
    assert chemistry.last_source_rates is not snapshot
    np.testing.assert_array_equal(snapshot, expected)
