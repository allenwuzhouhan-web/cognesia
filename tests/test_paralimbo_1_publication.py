"""Public evidence must reproduce and reject internally rehashed altered traces."""
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_benchmark_verifier',ROOT/'scripts/verify_paralimbo_1_publication.py')
verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)


def test_all_public_scores_recalculate():
    report=verifier.verify(ROOT/'docs/paralimbo-1')
    assert report['native_endpoint_scores']==15 and report['paralimbo_1_wins']==4


def test_rehashed_altered_native_trace_is_rejected(tmp_path):
    source=ROOT/'docs/paralimbo-1'
    (tmp_path/'evidence').mkdir()
    for name in ('protocol.json','prediction-seal.json'):
        (tmp_path/'evidence'/name).write_bytes((source/'evidence'/name).read_bytes())
    result=json.loads((source/'results.json').read_text())
    trace=next(value for key,value in result['traces'].items() if key.startswith('paralimbo-visual-graded-v1/'))
    index=next(i for i,t in enumerate(trace['time_ms']) if t>=0)
    trace['prediction_mv'][index]+=1
    result['public_results_sha256']=verifier.identity({k:v for k,v in result.items() if k!='public_results_sha256'})
    (tmp_path/'results.json').write_text(json.dumps(result))
    with pytest.raises(ValueError,match='predicted_peak_mv|waveform_rmse_mv'):
        verifier.verify(tmp_path)
