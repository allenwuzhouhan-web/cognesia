"""Safe YAML protocols share exactly the live console's simulation-time controls."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
import yaml


def _time(value, name, *, signed=False):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not np.isfinite(value) or (not signed and value<0) or value!=round(value):
        raise ValueError(f'{name} must be an {"integer" if signed else "unsigned integer"} number of ms')
    return int(value)


def compile_protocol(document, *, pairing_interval_ms=None):
    if isinstance(document,str): document = yaml.safe_load(document)
    if not isinstance(document,dict) or not isinstance(document.get('blocks'),list):
        raise ValueError('Protocol requires a mapping with a blocks list')
    document = copy.deepcopy(document)
    events, intervals, test_windows, training_windows = [], [], [], []
    duration = 0
    blocks = document['blocks']
    if pairing_interval_ms is not None:
        odours = [b for b in blocks if b.get('kind')=='odour']
        pulses = [b for b in blocks if b.get('kind')=='dan_pulse']
        if len(odours)!=1 or len(pulses)!=1:
            raise ValueError('Pairing sweep requires exactly one training odour and one DAN pulse')
        pulses[0]['t_ms'] = _time(odours[0].get('t_ms',0),'t_ms') + _time(pairing_interval_ms,'pairing_interval_ms',signed=True)
    def add(t,key,value,order=1,**metadata):
        events.append({'t_sim_ms':t,'control_id':key,'value':value,'_order':order,**metadata})
    for block in blocks:
        if not isinstance(block,dict): raise ValueError('Each protocol block must be a mapping')
        t = _time(block.get('t_ms',0),'t_ms')
        d = _time(block.get('dur_ms',0),'dur_ms')
        kind = block.get('kind')
        if d==0 and kind!='control': raise ValueError('Protocol block duration must be positive except instantaneous control events')
        end = t+d
        if kind in ('rest','iti'):
            pass
        elif kind=='odour':
            intensity = float(block.get('intensity',1))
            if not np.isfinite(intensity) or not 0<=intensity<=1: raise ValueError('Odour intensity must be in [0,1]')
            add(t,'odour',block['id']); add(t,'intensity',intensity)
            add(end,'odour','air',0)
            intervals.append(('odour',t,end))
            training_windows.append((t,end))
        elif kind=='dan_pulse':
            drive = float(block.get('drive',1))
            if not np.isfinite(drive) or not 0<=drive<=1: raise ValueError('DAN drive must be in [0,1]')
            add(t,'dan_type',block['source']); add(t,'dan_drive',drive)
            add(end,'dan_drive',0.,0)
            intervals.append(('dan',t,end))
            training_windows.append((t,end))
        elif kind=='test':
            odors = block.get('odours',[])
            if not isinstance(odors,list) or not odors: raise ValueError('Test requires nonempty odours')
            gap = _time(block.get('iti_ms',1000),'iti_ms')
            intensity = float(block.get('intensity',1))
            if not np.isfinite(intensity) or not 0<=intensity<=1: raise ValueError('Test intensity must be in [0,1]')
            for i,odor in enumerate(odors):
                on = t+i*(d+gap)
                add(on,'odour',odor); add(on,'intensity',intensity)
                add(on+d,'odour','air',0)
                intervals.append(('odour',on,on+d))
            end = t+len(odors)*d+(len(odors)-1)*gap
            test_windows.append((t,end))
            # Boundaries resolve to ordinary, replayable boolean controls in
            # ProtocolRunner. Restore the state observed at the test's start,
            # including an already disabled user setting. Freeze ITIs as well.
            add(t,'plasticity.enabled',False,.5,_test_boundary='start')
            add(end,'plasticity.enabled',None,.25,_test_boundary='end')
        elif kind=='control':
            add(t,block['control_id'],block['value'])
        else:
            raise ValueError(f'Unknown protocol block kind: {kind}')
        duration = max(duration,end)
    # Concurrent odour or DAN blocks would silently overwrite each other.
    for kind in ('odour','dan'):
        selected = sorted((a,b) for k,a,b in intervals if k==kind)
        if any(b>c for (a,b),(c,d) in zip(selected,selected[1:])):
            raise ValueError(f'Overlapping {kind} blocks are ambiguous')
    ordered_tests=sorted(test_windows)
    if any(b>c for (a,b),(c,d) in zip(ordered_tests,ordered_tests[1:])):
        raise ValueError('Overlapping test windows are ambiguous')
    for start,end in test_windows:
        if any(start<b and a<end for a,b in training_windows):
            raise ValueError('Training blocks cannot overlap a frozen test window, including its ITIs')
        if any(block.get('kind')=='control' and block.get('control_id')=='plasticity.enabled'
               and start<=block.get('t_ms',0)<end for block in blocks):
            raise ValueError('Plasticity controls cannot override a frozen test window')
    events.sort(key=lambda e:(e['t_sim_ms'],e['_order']))
    for event in events: event.pop('_order')
    return {'name':str(document.get('name','untitled')),'seed':int(document.get('seed',7)),
            'duration_ms':duration,'events':events,'document':document}


class ProtocolRunner:
    def __init__(self, runtime, document, *, pairing_interval_ms=None, reset=True):
        self.protocol = compile_protocol(document,pairing_interval_ms=pairing_interval_ms)
        self.runtime = runtime
        if reset: runtime.reset(self.protocol['seed'])
        self.start_ms = runtime.t_sim_ms
        self.position = 0
        self.done = False
        self.warnings = []
        self.test_readouts = []
        self._active_test = None
        for block in self.protocol['document']['blocks']:
            if block['kind']=='dan_pulse' and block.get('compartment'):
                selected = runtime.cells == block['source']
                empirical = runtime.mapping.mb_assignment[runtime.core.model_indices[selected]]
                actual = sorted({runtime.mapping.names[i] for i in empirical if i>=0})
                if actual != [block['compartment']]:
                    self.warnings.append(f"{block['source']}: requested nominal {block['compartment']}; actual empirical compartments {actual}. Source identities are preserved.")
        (runtime.session_dir/'protocol.yaml').write_text(yaml.safe_dump(self.protocol['document'],sort_keys=False))

    def advance(self, duration_ms):
        duration_ms = _time(duration_ms,'advance duration')
        end = min(self.runtime.t_sim_ms+duration_ms,self.start_ms+self.protocol['duration_ms'])
        events = self.protocol['events']
        while self.position<len(events) and self.start_ms+events[self.position]['t_sim_ms']<=end:
            event = events[self.position]
            t = self.start_ms+event['t_sim_ms']
            self._advance_runtime(int(t-self.runtime.t_sim_ms))
            boundary=event.get('_test_boundary')
            if boundary=='start':
                self._active_test={'start_ms':self.runtime.t_sim_ms,
                    'prior_plasticity_enabled':self.runtime.controls['plasticity.enabled'],
                    'weights_sha256_before':self._weight_hash()}
                self.runtime.control('plasticity.enabled',False)
            elif boundary=='end':
                test=self._active_test
                if test is None:raise RuntimeError('Test end has no matching start')
                test['end_ms']=self.runtime.t_sim_ms
                test['weights_sha256_after']=self._weight_hash()
                test['weights_unchanged']=test['weights_sha256_before']==test['weights_sha256_after']
                if not test['weights_unchanged']:raise RuntimeError('Protocol test changed trained weights')
                self.runtime.control('plasticity.enabled',test['prior_plasticity_enabled'])
                self.test_readouts.append(test)
                self._active_test=None
            else:
                self.runtime.control(event['control_id'],event['value'])
            self.position += 1
        self._advance_runtime(int(end-self.runtime.t_sim_ms))
        self.done = self.runtime.t_sim_ms >= self.start_ms+self.protocol['duration_ms']
        return self.runtime.snapshot()

    def _weight_hash(self):
        return hashlib.sha256(np.ascontiguousarray(self.runtime.plasticity.weights).tobytes()).hexdigest()

    def _advance_runtime(self,duration_ms):
        if self._active_test is not None and self.runtime.controls['plasticity.enabled']:
            raise RuntimeError('Plasticity was enabled during a frozen protocol test')
        self.runtime.advance(duration_ms)


def train(root, protocol_path):
    from .engine_rt import CoreRuntime
    document = yaml.safe_load(Path(protocol_path).read_text())
    runtime = CoreRuntime(root,seed=document.get('seed',7))
    try:
        runtime.warmup()
        runner = ProtocolRunner(runtime,document)
        while not runner.done:
            runner.advance(100)
        archive = runtime.export()
        result = {'status':'PASS','scope':'Protocol software execution; biological gates reported separately',
            'protocol':runner.protocol['name'],'warnings':runner.warnings,'archive':str(archive),
            'metrics':runtime.snapshot(),'digests':runtime.digests(),'frozen_test_readouts':runner.test_readouts}
        Path(root,'build/training_latest.json').write_text(json.dumps(result,indent=2))
        return result
    finally:
        runtime.close()
