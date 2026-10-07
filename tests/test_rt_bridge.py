"""Transport fixtures do not stand in for the real core's numerical gates."""
import asyncio
import json
from pathlib import Path
import time
import zipfile
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from flybrain.rt.bridge import binary_frame, create_app, EngineWorker, _evidence


class FixtureRuntime:
    def __init__(self, root, seed=7):
        self.root, self.seed, self.t_sim_ms = Path(root), seed, 0
        self.events=[]
        self.closed=False
    def warmup(self): pass
    def reset(self, seed=None):
        self.t_sim_ms=0
        self.seed=self.seed if seed is None else seed
    def control(self, key, value):
        if key=='bad': raise ValueError('Rejected fixture control')
        if key=='pause' and not isinstance(value,bool): raise ValueError('pause requires boolean')
        event={'control_id':key,'value':value,'t_sim_ms':self.t_sim_ms}
        self.events.append(event)
        return event
    def advance(self, duration_ms): self.t_sim_ms+=duration_ms
    def snapshot(self):
        return {'t_sim_ms':self.t_sim_ms,'dt_ms':.1,'rtf':1.,'seed':self.seed,'valence':.25,
                'kc_rates_hz':[1.,2.], 'dan_rates_hz':[3.], 'mbon_rates_hz':[4.],
                'weights_relative':[1.,None], 'weight_heatmap':[[1.,None]],
                'concentrations_au':[[.2,.3]],'recent_events':list(self.events)}
    def metadata(self): return {'neurons':2,'test_fixture':True}
    def export(self, path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('frames.jsonl',json.dumps(self.snapshot())+'\n')
            z.writestr('metadata.json',json.dumps(self.metadata()))
        return path
    def close(self): self.closed=True


def test_binary_layout_preserves_values_and_missing_measurements():
    sample=FixtureRuntime('/tmp').snapshot()
    data,layout=binary_frame(sample,123)
    words=np.frombuffer(data,dtype='<f4')
    assert list(words[:3])==[1.,0.,np.float32(.1)]
    assert words[4]==123 and len(words)==int(words[5])+6
    weights=next(x for x in layout if x['name']=='weights_relative')
    assert words[6+weights['offset']]==1 and np.isnan(words[7+weights['offset']])
    assert np.isnan(words[7])  # missing KC fraction is a gap, not zero


def test_worker_pause_step_and_pulse_use_simulation_time(tmp_path):
    worker=EngineWorker(tmp_path,runtime_factory=FixtureRuntime,autostart=False).start()
    try:
        worker.submit('control','step',1).result(timeout=5)
        assert worker.submit('control','pause',True).result(timeout=5)['t_sim_ms']==1
        time.sleep(.03)
        assert worker.snapshot()['t_sim_ms']==1
        event=worker.submit('control','dan.pulse',{'duration_ms':30,'drive':1}).result(timeout=5)
        assert event['ends_at_ms']==31
        worker.submit('control','pause',False).result(timeout=5)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            events=worker.snapshot().get('recent_events',[])
            if any(e['control_id']=='dan_drive' and e['value']==0 for e in events): break
            time.sleep(.01)
        end=[e for e in events if e['control_id']=='dan_drive' and e['value']==0]
        assert end and end[0]['t_sim_ms']==31
    finally: worker.close()
    assert not worker.thread.is_alive()


def test_http_commands_ws_export_and_origin_guard(tmp_path):
    async def run():
        client=TestClient(TestServer(create_app(tmp_path,runtime_factory=FixtureRuntime,autostart=False)))
        await client.start_server()
        try:
            for _ in range(100):
                response=await client.get('/api/metadata')
                if (await response.json()).get('neurons')==2: break
                await asyncio.sleep(.01)
            response=await client.post('/api/control',json={'control_id':'step','value':1})
            assert response.status==200 and (await response.json())['ok']
            response=await client.post('/api/control',json={'control_id':'bad','value':1})
            assert response.status==400 and 'Rejected' in (await response.json())['error']
            response=await client.post('/api/control',json={'control_id':'step','value':1},headers={'Origin':'https://example.com'})
            assert response.status==403
            response=await client.get('/api/session')
            assert response.status==200 and response.content_type=='application/zip'
            assert (await response.read())[:2]==b'PK'
            ws=await client.ws_connect('/ws')
            found_binary=False
            for _ in range(5):
                message=await asyncio.wait_for(ws.receive(),timeout=3)
                if message.type==WSMsgType.BINARY:
                    assert np.frombuffer(message.data,dtype='<f4')[0]==1
                    found_binary=True;break
            assert found_binary
            await ws.close()
        finally: await client.close()
    asyncio.run(run())


def test_stability_variant_display_rejects_changed_nested_artifact(tmp_path):
    from flybrain.fetch import checksum, stat_signature
    build=tmp_path/'build';build.mkdir()
    source=tmp_path/'data/raw/input.csv';source.parent.mkdir(parents=True);source.write_text('release')
    artifact=build/'variant.npz';artifact.write_bytes(b'original numerical evidence')
    record={'gate':'V-C-VARIANT','status':'PASS',
            'source_hashes':{'input.csv':checksum(source)},'source_stats':{'input.csv':stat_signature(source)},
            'defaults':[{'label':'current','artifact_hashes':{'variant.npz':checksum(artifact)},
                         'gates':[{'gate':'V-C1','status':'PASS'}]}]}
    (build/'validation_hybrid_variant.json').write_text(json.dumps(record))
    assert _evidence(tmp_path)['stability_variant']['status']=='PASS'
    artifact.write_bytes(b'changed numerical evidence')
    result=_evidence(tmp_path)['stability_variant']
    assert result['status']=='NOT-RUN'
    assert any('Variant run artifact changed' in issue for issue in result['stale_evidence_reasons'])


def test_raster_is_bounded_actual_spike_data_with_explicit_omissions(tmp_path):
    indices=np.array([0,1,2,0,2,1,0],np.int32)
    steps=np.array([0,5,10,15,20,25,30],np.int64)
    indices.tofile(tmp_path/'spike_indices.i32')
    steps.tofile(tmp_path/'spike_steps.i64')
    runtime=SimpleNamespace(t_sim_ms=4.,kc_types=['KCa','KCb'],kc_indices=np.array([0,2]),
        cells=np.array(['KCa','MBON01','KCb']),session_dir=tmp_path,_spike_files=[],
        neurons=pd.DataFrame({'root_id':[10,11,12]}),engine=SimpleNamespace(dt=.1),config_hash='fixture')
    worker=EngineWorker(tmp_path)
    result=worker._raster(runtime,{'cell_type':'all','duration_ms':4,'max_points':2})
    assert result['matching_spikes']==5 and result['retained_spikes']==2 and result['omitted_spikes']==3
    assert result['spike_indices']==[2,0] and result['spike_times_ms']==[2.,3.]
    assert result['neuron_indices']==[0,2] and result['root_ids']==['10','12']
    subtype=worker._raster(runtime,{'cell_type':'KCb','duration_ms':4})
    assert subtype['spike_indices']==[2,2] and subtype['spike_times_ms']==[1.,2.]
    with pytest.raises(ValueError): worker._raster(runtime,{'duration_ms':5001})
    with pytest.raises(ValueError): worker._raster(runtime,{'cell_type':'MBON01'})


def test_manual_steps_honor_pulse_end_and_protocol_boundaries(tmp_path):
    runtime=FixtureRuntime(tmp_path)
    scheduled=[(2,'dan_drive',0)]
    class Runner:
        done=False
        def advance(self,n):
            runtime.advance(min(n,3-runtime.t_sim_ms))
            self.done=runtime.t_sim_ms>=3
    runner=Runner()
    EngineWorker._advance(runtime,runner,scheduled,5)
    assert runtime.t_sim_ms==5 and runner.done
    assert runtime.events==[{'control_id':'dan_drive','value':0,'t_sim_ms':2}]
    assert not scheduled


def test_weight_query_returns_actual_indexed_edges_with_bounds(tmp_path):
    kernel=SimpleNamespace(pre_index=np.array([0,1,0]),compartment_index=np.array([0,1,1]),
        w0=np.array([2.,3.,0.]),weights=np.array([1.5,3.3,0.]))
    runtime=SimpleNamespace(t_sim_ms=9,config_hash='sample',mapping=SimpleNamespace(names=['g1','g2']),
        kc_types=['KCa','KCb'],kc_indices=np.array([0,1]),cells=np.array(['KCa','KCb','MBON01']),
        neurons=pd.DataFrame({'root_id':[2**60,2**60+1,2**60+2]}),plasticity=kernel,
        engine=SimpleNamespace(csc_indices=np.array([2,2,2])),plastic_csc=np.array([0,1,2]))
    worker=EngineWorker(tmp_path)
    result=worker._weights(runtime,{'compartment':'g2','kc_type':'KCa','limit':1})
    assert result['matching_edges']==1 and result['returned_edges']==1
    assert result['rows'][0]['edge_index']==2 and result['rows'][0]['relative'] is None
    assert result['rows'][0]['pre_root_id']==str(2**60)
    assert result['rows'][0]['post_root_id']==str(2**60+2)
    with pytest.raises(ValueError):worker._weights(runtime,{'limit':2001})
    with pytest.raises(ValueError):worker._weights(runtime,{'compartment':'invented'})


def test_session_seal_preserves_events_exact_endpoint_and_unique_archives(tmp_path):
    import yaml
    from flybrain.rt.protocol import compile_protocol
    worker=EngineWorker(tmp_path)
    runtime=FixtureRuntime(tmp_path,seed=23)
    runtime.session_dir=tmp_path/'runs/neuromod/session-test'
    runtime.session_dir.mkdir(parents=True)
    runtime.config_hash='fixture'
    runtime.control('odour','OCT');runtime.advance(3);runtime.control('odour','air')
    runtime.control('pause',True)
    (runtime.session_dir/'protocol.yaml').write_text('name: requested\nblocks: []\n')
    archive=worker._export_session(runtime,tmp_path/'runs/shared-download.zip')
    doc=yaml.safe_load((runtime.session_dir/'protocol.yaml').read_text())
    compiled=compile_protocol(doc)
    assert compiled['duration_ms']==3
    assert [(e['t_sim_ms'],e['control_id'],e['value']) for e in compiled['events']]==[(0,'odour','OCT'),(3,'odour','air')]
    assert archive==runtime.session_dir.with_suffix('.zip') and archive.exists()
    assert 'requested' in (runtime.session_dir/'requested_protocol.yaml').read_text()
    records=json.loads((tmp_path/'runs/neuromod/session_index.json').read_text())
    assert records[0]['duration_ms']==3 and records[0]['seed']==23
    assert records[0]['archive']=='runs/neuromod/session-test.zip'
    worker._export_session(runtime)
    assert len(json.loads((tmp_path/'runs/neuromod/session_index.json').read_text()))==1


def test_retriggered_pulse_replaces_old_turnoff_and_rejects_fractional_time(tmp_path):
    worker=EngineWorker(tmp_path,runtime_factory=FixtureRuntime,autostart=False).start()
    try:
        worker.submit('control','dan.pulse',{'duration_ms':3}).result(5)
        worker.submit('control','step',1).result(5)
        worker.submit('control','dan.pulse',{'duration_ms':4}).result(5)
        for _ in range(4): worker.submit('control','step',1).result(5)
        events=worker.submit('control','pause',True).result(5)
        deadline=time.monotonic()+2
        while worker.snapshot()['t_sim_ms']<5 and time.monotonic()<deadline:time.sleep(.001)
        stops=[e for e in worker.snapshot()['recent_events'] if e['control_id']=='dan_drive' and e['value']==0]
        assert [e['t_sim_ms'] for e in stops]==[5]
        for bad in (1.5,True,float('nan')):
            with pytest.raises(ValueError):worker.submit('control','dan.pulse',{'duration_ms':bad}).result(5)
    finally:worker.close()


def test_atlas_samples_and_hulls_come_from_actual_membership(tmp_path):
    positions=np.array([[0.,0.],[2.,0.],[0.,2.],[9.,9.]])
    runtime=SimpleNamespace(rates_hz=np.array([1.,2.,3.,4.]),
        neurons=pd.DataFrame({'soma_x':positions[:,0],'soma_y':positions[:,1]}),
        metadata=lambda:{'atlas':{'xyz':positions.tolist()}},
        mapping=SimpleNamespace(names=['g1','g2'],membership=np.array([[1,1,1,0],[0,0,0,1]],bool)),
        core=SimpleNamespace(model_indices=np.arange(4)),
        plasticity=SimpleNamespace(parameters=SimpleNamespace(tau_forget_ms=600000,beta=1)))
    worker=EngineWorker(tmp_path)
    metadata=worker._metadata(runtime)
    assert metadata['atlas']['sample_indices']==[0,1,2,3]
    hulls=metadata['atlas']['schematic_hulls']
    assert len(hulls)==1 and hulls[0]['compartment']=='g1'
    assert set(map(tuple,hulls[0]['xy']))==set(map(tuple,positions[:3]))
    assert 'not anatomical' in metadata['atlas']['hull_scope']


def test_presentation_exports_are_persistent_same_origin_files(tmp_path):
    import base64
    async def run():
        client=TestClient(TestServer(create_app(tmp_path,runtime_factory=FixtureRuntime,autostart=False)))
        await client.start_server()
        try:
            csv='root_id,weight\n1152921504606846976,1.25\n'
            response=await client.post('/api/exports',json={'filename':'cognesia-edges.csv','content_type':'text/csv','text':csv,'context':{'seed':7,'recorded':False}})
            assert response.status==200
            saved=await response.json()
            assert Path(saved['path']).read_text()==csv
            assert Path(saved['path']).is_relative_to(tmp_path/'runs/exports')
            response=await client.get(saved['url'])
            assert response.status==200 and await response.text()==csv
            assert 'attachment' in response.headers['Content-Disposition']
            assert json.loads(Path(saved['path']+'.json').read_text())['context']['seed']==7
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
            response=await client.post('/api/exports',json={'filename':'figure.png','content_type':'image/png','base64':base64.b64encode(png).decode()})
            assert response.status==200
            saved_png=await response.json()
            assert Path(saved_png['path']).read_bytes()==png
            response=await client.get(saved_png['url'])
            assert response.status==200 and await response.read()==png
            for name in ('../escape.csv','/absolute.csv','image.svg'):
                response=await client.post('/api/exports',json={'filename':name,'content_type':'text/csv','text':'bad'})
                assert response.status==400
            response=await client.post('/api/exports',json={'filename':'valid.csv','content_type':'text/csv','text':'bad'},headers={'Origin':'https://example.com'})
            assert response.status==403
            response=await client.post('/api/exports',json={'filename':'invalid.png','content_type':'image/png','base64':base64.b64encode(b'not png').decode()})
            assert response.status==400
        finally:await client.close()
    asyncio.run(run())
