from pathlib import Path
import pytest
import yaml
from flybrain.rt.replay import replay_session


@pytest.mark.parametrize('change',[
    {'digests':{}}, {'digests':{'weights':'0'*64}}, {'duration_ms':float('nan')},
    {'duration_ms':.5}, {'seed':True}, {'seed':-1}, {'schema_version':2}, {'config_hash':None},
])
def test_bad_manifest_rejected_before_any_runtime_side_effect(tmp_path,change):
    record={'schema_version':1,'seed':7,'duration_ms':10,'config_hash':'0'*64,
            'digests':{k:'0'*64 for k in ('spike_indices','spike_steps','weights')}} | change
    (tmp_path/'session.yaml').write_text(yaml.safe_dump(record))
    (tmp_path/'events.jsonl').touch()
    with pytest.raises(ValueError):
        replay_session(tmp_path/'events.jsonl',tmp_path,runtime=object())


def test_recording_keeps_numpy_values_numeric_and_large_id_exact():
    import numpy as np
    from flybrain.rt.engine_rt import native_document
    record=native_document({'state':{'energy':np.float64(.9944598480048971)},
                            'identity':np.int64(720575940614074816),'field':np.array([.3],np.float32)})
    loaded=yaml.safe_load(yaml.safe_dump(record))
    assert loaded['state']['energy']==.9944598480048971
    assert loaded['identity']==720575940614074816
    assert isinstance(loaded['field'][0],float)
    with pytest.raises(TypeError): native_document({'unexpected':object()})
