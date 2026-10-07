"""Capacity worker ordering/protocol parity without loading the real network."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from flybrain.rt import capacity


@pytest.mark.parametrize('full,requested,expected',[(False,None,1),(True,None,4),(True,1,1),(False,4,4)])
def test_capacity_worker_defaults_and_override(full,requested,expected):
    assert capacity._worker_count(full,requested)==expected


@pytest.mark.parametrize('workers',[0,5,-1,True,2.0,'4'])
def test_capacity_refuses_invalid_worker_count(workers):
    with pytest.raises(ValueError,match='1 to 4'):capacity._worker_count(True,workers)


def test_worker_aggregation_matches_serial_seeded_protocol(monkeypatch,tmp_path):
    runtimes=[]
    class FixtureRuntime:
        def __init__(self,root=None,record=False):
            self.root=tmp_path;self.config_hash='fixture';self.session_dir=tmp_path/'session-fixture'
            self.plasticity=SimpleNamespace(w0=np.array([1.,2.]),weights=np.array([1.,2.]))
            self.training_calls=[];self.test_calls=[];self.closed=False;self.warmups=0
            runtimes.append(self)
        def warmup(self):self.warmups+=1
        def close(self):self.closed=True
    def training(runtime,events,duration_ms,*,seed):
        assert duration_ms==3000 and seed==7
        events=sorted(events,key=lambda item:item['t_sim_ms'])
        assert [item['t_sim_ms'] for item in events]==[0,500,1000,1000]
        assert events[-1]['value']['drive']==0
        handle=events[1]['value']['cell_type'];odor=events[0]['value']
        runtime.training_calls.append((handle,odor,seed))
        code=sum(map(ord,handle))%7
        runtime.plasticity.weights[:]=[1+code/10,1.5 if odor=='OCT' else 2.5]
    def test(runtime,odor,*,seed,weights,duration_ms):
        assert duration_ms==500 and seed in (101,102)
        runtime.test_calls.append((odor,seed))
        digest=capacity.array_hash(weights)
        valence=float(weights[1]-2+(.1 if odor=='OCT' else -.1))
        return {'valence':valence,'spikes':seed+int(weights[0]*10),
                'weights_sha256_before':digest,'weights_sha256_after':digest}
    def statistics(table,*,randomizations,seed):
        assert randomizations==1000
        # The statistics implementation is tested separately; this records the
        # exact scheduling-independent seed, readout and clustered protocol set.
        return {'statistical_seed':seed,'empirical_p':float(np.random.default_rng(seed).uniform()),
                'mutual_information_bits':capacity.mutual_information(table.intended,table.decision),
                'protocols':list(table.protocol.unique())}
    monkeypatch.setattr(capacity,'CoreRuntime',FixtureRuntime)
    monkeypatch.setattr(capacity,'execute_events',training)
    monkeypatch.setattr(capacity,'odor_test',test)
    monkeypatch.setattr(capacity,'information_statistics',statistics)
    selected=['PPL101','PAM01','OA-AL2b2','IPC']
    seeds=(101,102)
    baselines={(odor,seed):{'valence':-1. if odor=='OCT' else 1.} for odor in ('OCT','MCH') for seed in seeds}
    serial_runtime=FixtureRuntime()
    serial=[capacity._measure_handle(serial_runtime,i,handle,baselines,seeds,1000) for i,handle in enumerate(selected)]
    completed=[]
    # Strided batches finish in reverse worker order, as imap_unordered permits.
    for worker in (1,0):
        job={'root':str(tmp_path),'worker':worker,'assigned':list(enumerate(selected))[worker::2],
             'progress_path':str(tmp_path/f'worker-{worker}.json'),'runtime_hash':'fixture',
             'capacity_hash':capacity.checksum(Path(capacity.__file__)),'baselines':baselines,'seeds':seeds,'randomizations':1000}
        completed.extend(capacity._capacity_worker(job))
        progress=json.loads(Path(job['progress_path']).read_text())
        assert progress['status']=='PASS' and progress['completed_handles']==2
    serial_trials,serial_statistics=capacity._ordered_results(selected,serial)
    worker_trials,worker_statistics=capacity._ordered_results(selected,completed)
    assert serial_trials==worker_trials and serial_statistics==worker_statistics
    np.testing.assert_array_equal(capacity.benjamini_hochberg([x['empirical_p'] for x in serial_statistics]),
                                  capacity.benjamini_hochberg([x['empirical_p'] for x in worker_statistics]))
    assert [x['statistical_seed'] for x in worker_statistics]==[700,701,702,703]
    assert len(worker_trials)==32 and len(serial_runtime.training_calls)==8
    assert all(len(runtime.training_calls)==4 and len(runtime.test_calls)==16
               and runtime.warmups==1 and runtime.closed for runtime in runtimes[1:])
    assert not (tmp_path/'build/validation_neuromod_capacity.json').exists()
    assert not list(tmp_path.glob('*.csv'))


def test_worker_result_merge_rejects_duplicate_or_relabelled_handles():
    row={'index':0,'handle':'PPL101','statistics':{'handle':'PPL101'},'observations':[{'handle':'PPL101'}]}
    with pytest.raises(ValueError,match='duplicate'):capacity._ordered_results(['PPL101'],[row,row])
    bad=copy.deepcopy(row);bad['observations'][0]['handle']='PAM01'
    with pytest.raises(ValueError,match='identity'):capacity._ordered_results(['PPL101'],[bad])


def test_worker_rejects_changed_runtime_and_retains_failure_progress(monkeypatch,tmp_path):
    runtime=SimpleNamespace(config_hash='changed',close=lambda:None)
    monkeypatch.setattr(capacity,'CoreRuntime',lambda *args,**kwargs:runtime)
    path=tmp_path/'worker.json'
    job={'root':str(tmp_path),'progress_path':str(path),'worker':0,'assigned':[(0,'PPL101')],
         'runtime_hash':'original','capacity_hash':capacity.checksum(Path(capacity.__file__))}
    with pytest.raises(ValueError,match='differs from parent'):capacity._capacity_worker(job)
    progress=json.loads(path.read_text())
    assert progress['status']=='FAIL' and progress['completed_handles']==0
