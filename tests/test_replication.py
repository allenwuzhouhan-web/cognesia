import pytest
from flybrain.replication import plan_replicates


def test_repeatable_independent_seed_schedule_and_original_preserved():
    request = {'master_seed':20, 'replicates':8, 'options':{'duration_ms':300,'neural_overrides':{'seed':7}}}
    first = plan_replicates(request)
    assert first == plan_replicates(request)
    assert len({run['seed'] for run in first['replicates']}) == 8
    assert request['options']['neural_overrides']['seed'] == 7
    assert first['replicates'][0]['options']['neural_overrides']['seed'] != 7
    assert 'optical ray sampling' in first['interpretation']
    assert first['status'] == 'draft'
    assert len(first['options_sha256']) == 64


@pytest.mark.parametrize('payload', [{'master_seed':True},{'replicates':51},{'replicates':0},{'options':[]},{'options':{'from_checkpoint':'a'}},{'options':{'duration_ms':50000}}, {'master_seed':-1}])
def test_invalid_or_unbounded_plans_rejected(payload):
    with pytest.raises(ValueError): plan_replicates(payload)
