"""Validated runtime lab controls and virtual additive membrane electrodes.

Electrode amplitudes are model input in mV-equivalent units, not physical device
voltages or a tissue electric-field solution. Body aliases identify explicit
annotation subsets and never add a body/VNC/muscle model to the brain connectome.
"""
from __future__ import annotations
from dataclasses import dataclass
import os
import numpy as np
import numba as nb

MAX_RECORDING_BYTES = 3_000_000_000
MAX_ELECTRODES = 16
NEURAL_OVERRIDE_LIMITS = {
    'dt': {'choices':[.025,.05,.1,.2]}, 'dt_graded': {'min':.025,'max':1.},
    'v_rest':{'min':-90.,'max':0.}, 'v_reset':{'min':-100.,'max':0.},
    'v_threshold':{'min':-80.,'max':20.}, 'tau_membrane':{'min':1.,'max':200.},
    'tau_synapse':{'min':.5,'max':100.}, 'refractory':{'min':0.,'max':50.},
    'synaptic_delay':{'min':0.,'max':20.}, 'spike_weight':{'min':0.,'max':5.},
    'graded_tau_membrane':{'min':1.,'max':200.}, 'graded_tau_synapse':{'min':.5,'max':100.},
    'graded_rest':{'min':-100.,'max':20.}, 'graded_release':{'min':-110.,'max':20.},
    'graded_gain':{'min':0.,'max':.01}, 'voltage_min':{'min':-150.,'max':-30.},
    'voltage_max':{'min':-30.,'max':80.}, 'pre_equilibration':{'min':100.,'max':5000.},
    'stationary_tolerance':{'min':.000001,'max':1.}, 'seed':{'min':0,'max':4294967295,'integer':True},
}
VISUAL_OVERRIDE_LIMITS = {
    'frame_rate':{'choices':[60.,120.,240.,480.]}, 'eye_spacing':{'min':1.,'max':10.},
    'eye_fwhm':{'min':.5,'max':15.}, 'optics_samples':{'choices':[4096,8192,16384]},
    'optics_convergence_tolerance':{'min':.001,'max':.02},
    'adaptation_tau_ms':{'min':1.,'max':2000.},'phototransduction_tau_ms':{'min':1.,'max':200.},
    'half_saturation':{'min':.001,'max':5.},'adaptation_strength':{'min':0.,'max':5.},
    'maximum_drive_mv':{'min':0.,'max':100.},'eye_center_azimuth_deg':{'min':0.,'max':90.},
    'apparent_point_radius_columns':{'min':.05,'max':3.},'apparent_onset_ms':{'min':0.,'max':9000.},
    'display_sample_ms':{'min':2.,'max':50.},
}
LAB_OPTION_KEYS = {'neural_overrides','visual_overrides','record_dt_ms','electrodes'}
GROUP_FIELDS = ('cell_type','super_class','cell_class','cell_sub_class','side','mode','nerve')
REGION_NAMES = ('left_optic','right_optic','optic','central','descending','motor','sensory',
                'ascending','olfactory','mechanosensory','kenyon_cells','central_complex','all_brain')
BODY_ZONE_NAMES = ('left_eye','right_eye','antennae','legs','wings','body')


def available_threads():
    return max(1,min(os.cpu_count() or 1,int(nb.config.NUMBA_NUM_THREADS)))


def _number(value, label):
    if isinstance(value,(bool,np.bool_)):
        raise ValueError(label+' must be a finite number')
    try:
        number=float(value)
    except (ValueError,TypeError):
        raise ValueError(label+' must be a finite number') from None
    if not np.isfinite(number):
        raise ValueError(label+' must be a finite number')
    return number


def _overrides(given, limits, name):
    if given is None:
        return {}
    if not isinstance(given,dict):
        raise ValueError(name+' must be an object')
    unknown=set(given)-set(limits)
    if unknown:
        raise ValueError('Unsupported '+name+': '+', '.join(sorted(unknown)))
    values={}
    for key,value in given.items():
        value=_number(value,name+'.'+key);bound=limits[key]
        if 'choices' in bound and value not in bound['choices']:
            raise ValueError(f'{name}.{key} must be one of {bound["choices"]}')
        if 'min' in bound and not bound['min']<=value<=bound['max']:
            raise ValueError(f'{name}.{key} must be in [{bound["min"]},{bound["max"]}]')
        if bound.get('integer') and value%1:
            raise ValueError(name+'.'+key+' must be an integer')
        values[key]=int(value) if bound.get('integer') or key=='optics_samples' else value
    return values


def _multiple(value, step, label):
    if not np.isclose(round(value/step)*step,value,rtol=0,atol=1e-7):
        raise ValueError(label+f' must be an exact multiple of {step:g} ms')


def normalize_electrodes(electrodes,duration_ms,dt_ms):
    if electrodes is None:
        return []
    if not isinstance(electrodes,list) or len(electrodes)>MAX_ELECTRODES:
        raise ValueError(f'electrodes must be a list of at most {MAX_ELECTRODES} electrodes')
    normalized=[];ids=set()
    allowed={'id','label','target','voltage_mv','frequency_hz','duty_percent','start_ms','end_ms','phase_deg'}
    for i,item in enumerate(electrodes):
        if not isinstance(item,dict) or set(item)-allowed:
            raise ValueError('Electrode contains unsupported fields')
        e={'id':str(item.get('id',f'electrode_{i+1}')),'label':str(item.get('label',f'Electrode {i+1}')),
           'target':item.get('target'),'voltage_mv':0.,'frequency_hz':0.,'duty_percent':50.,
           'start_ms':0.,'end_ms':float(duration_ms),'phase_deg':0.}
        if not e['id'] or len(e['id'])>80 or e['id'] in ids or len(e['label'])>120:
            raise ValueError('Electrode IDs must be unique short strings; labels must be at most 120 characters')
        ids.add(e['id'])
        if not isinstance(e['target'],dict):
            raise ValueError('Each electrode requires a target object')
        for key in ('voltage_mv','frequency_hz','duty_percent','start_ms','end_ms','phase_deg'):
            e[key]=_number(item.get(key,e[key]),'electrode.'+key)
        if not -100<=e['voltage_mv']<=100:
            raise ValueError('electrode.voltage_mv must be in [-100,100] model-input mV')
        if not 0<=e['frequency_hz']<=500 or not 0<=e['duty_percent']<=100:
            raise ValueError('Electrode frequency must be 0-500 Hz and duty must be 0-100 percent')
        if not 0<=e['start_ms']<e['end_ms']<=duration_ms:
            raise ValueError('Electrode window must satisfy 0 <= start_ms < end_ms <= duration_ms')
        if e['frequency_hz']>0 and 0<e['duty_percent']<100:
            period=1000/e['frequency_hz']
            if min(e['duty_percent'],100-e['duty_percent'])/100*period < dt_ms-1e-9:
                raise ValueError('Electrode on/off pulse width is shorter than the integration timestep')
        e['phase_deg']%=360
        e['timing_resolution_ms']=float(dt_ms)
        e['effective_start_ms']=float(np.ceil(e['start_ms']/dt_ms-1e-9)*dt_ms)
        e['effective_end_ms']=float(np.ceil(e['end_ms']/dt_ms-1e-9)*dt_ms)
        e['units']='mV-equivalent additive membrane input; not physical electrode voltage'
        e['waveform']='constant during window' if e['frequency_hz']==0 else 'monophasic square pulse'
        normalized.append(e)
    return normalized


def normalize_lab_options(options,params,visual,n_neurons=138639):
    """Return normalized options, effective copies of parameters, and memory estimate."""
    from .stimuli import normalize_options
    given=dict(options or {})
    neural=_overrides(given.pop('neural_overrides',{}),NEURAL_OVERRIDE_LIMITS,'neural_overrides')
    optics=_overrides(given.pop('visual_overrides',{}),VISUAL_OVERRIDE_LIMITS,'visual_overrides')
    p=dict(params)|neural;v=dict(visual)
    for key,value in optics.items():
        (p if key in ('frame_rate','eye_spacing','eye_fwhm') else v)[key]=value
    record=_number(given.pop('record_dt_ms',v['display_sample_ms']),'record_dt_ms')
    if not 2<=record<=50:
        raise ValueError('record_dt_ms must be in [2,50] ms')
    if 'display_sample_ms' in optics and not np.isclose(record,optics['display_sample_ms']):
        raise ValueError('record_dt_ms conflicts with visual_overrides.display_sample_ms')
    v['display_sample_ms']=record
    electrodes=given.pop('electrodes',[])
    given.setdefault('threads',available_threads())
    if p['dt']>p['dt_graded']:
        raise ValueError('dt cannot exceed dt_graded')
    if p['voltage_min']>=p['voltage_max']:
        raise ValueError('Voltage limits must be ordered')
    for key in ('v_rest','v_reset','v_threshold','graded_rest'):
        if not p['voltage_min']<=p[key]<=p['voltage_max']:
            raise ValueError(key+' must lie inside the configured voltage bounds')
    if p['v_reset']>=p['v_threshold']:
        raise ValueError('v_reset must be below v_threshold')
    _multiple(p['synaptic_delay'],p['dt'],'synaptic_delay')
    _multiple(p['pre_equilibration'],p['dt'],'pre_equilibration')
    _multiple(p['pre_equilibration'],1000/p['frame_rate'],'pre_equilibration')
    _multiple(record,p['dt'],'record_dt_ms')
    normalized=normalize_options(given,p['frame_rate'],eye_spacing_deg=p['eye_spacing'],
                                 point_radius_columns=v['apparent_point_radius_columns'],flash_onset_ms=v['apparent_onset_ms'])
    _multiple(normalized['duration_ms'],p['dt'],'duration_ms')
    normalized['neural_overrides']=neural;normalized['visual_overrides']=optics;normalized['record_dt_ms']=record
    normalized['electrodes']=normalize_electrodes(electrodes,normalized['duration_ms'],p['dt'])
    count=int(np.ceil(normalized['duration_ms']/record))
    recording_bytes=count*int(n_neurons)*4*3
    if recording_bytes>MAX_RECORDING_BYTES:
        raise ValueError(f'Raw + baseline + delta recordings need {recording_bytes/1e9:.2f} GB; limit is {MAX_RECORDING_BYTES/1e9:g} GB. Increase record_dt_ms or shorten duration.')
    estimate={'recorded_neurons':int(n_neurons),'voltage_samples_per_neuron':count,
              'recording_float32_bytes':recording_bytes,'recording_budget_bytes':MAX_RECORDING_BYTES,
              'neural_steps_per_branch':int(round(normalized['duration_ms']/p['dt'])),
              'preequilibration_steps':int(round(p['pre_equilibration']/p['dt'])),
              'total_neural_steps':int(round((p['pre_equilibration']+2*normalized['duration_ms'])/p['dt'])),
              'threads':normalized['threads'],'available_threads':available_threads(),
              'note':'Recording estimate covers three full-brain voltage matrices; network, optical inputs, spikes, rendering and compression need additional memory.'}
    return normalized,p,v,estimate


@dataclass
class ResolvedElectrode:
    definition: dict
    indices: np.ndarray


def resolve_electrodes(neurons,electrodes):
    n=len(neurons);resolved=[]
    def values(field):
        if field not in neurons:
            raise ValueError('Neuron annotations do not contain '+field)
        return neurons[field].fillna('').to_numpy()
    for e in electrodes:
        target=e['target'];kind=target.get('kind');assumption=None
        if kind=='indices':
            if set(target)-{'kind','indices'}:
                raise ValueError('Unsupported indices target field')
            raw=np.asarray(target.get('indices',[]))
            if raw.ndim!=1 or raw.dtype.kind not in 'iu' or np.any(raw<0) or np.any(raw>=n):
                raise ValueError('Electrode indices must be a nonempty list of valid integer neuron indices')
            indices=np.unique(raw).astype(np.int32)
            mask=np.zeros(n,dtype=bool);mask[indices]=True
        elif kind in ('root_ids','entity_ids'):
            field='root_id' if kind=='root_ids' else 'entity_id'
            identities=target.get(kind,[])
            if set(target)-{'kind',kind} or not isinstance(identities,list) or not identities or any(isinstance(x,bool) or not isinstance(x,(str,int)) for x in identities):
                raise ValueError('Identity target requires a nonempty list of source identities')
            known=values(field).astype(str)
            requested={str(x) for x in identities}
            missing=requested-set(known)
            if missing: raise ValueError('Unknown target identities: '+', '.join(sorted(missing)[:8]))
            mask=np.isin(known,list(requested))
        elif kind=='group':
            if set(target)-{'kind','field','values','side'}:
                raise ValueError('Unsupported group target field')
            field=target.get('field');selection=target.get('values')
            if field not in GROUP_FIELDS or not isinstance(selection,list) or not selection or not all(isinstance(x,str) for x in selection):
                raise ValueError('Group target requires an allowed annotation field and nonempty string values')
            mask=np.isin(values(field),selection)
            if 'side' in target:
                if target['side'] not in ('left','right','center'):
                    raise ValueError('Invalid electrode target side')
                mask &= values('side')==target['side']
        elif kind=='region':
            if set(target)-{'kind','name'} or target.get('name') not in REGION_NAMES:
                raise ValueError('Unknown electrode brain region')
            name=target['name'];classes=values('super_class')
            if name in ('left_optic','right_optic','optic'):
                mask=np.isin(classes,['optic','visual_projection','visual_centrifugal'])
                if name!='optic':mask &= values('side')==name.split('_')[0]
            elif name in ('olfactory','mechanosensory'):
                mask=values('cell_class')==name
            elif name in ('kenyon_cells','central_complex'):
                mask=values('cell_class')=={'kenyon_cells':'Kenyon_Cell','central_complex':'CX'}[name]
            elif name=='all_brain':mask=np.ones(n,dtype=bool)
            else:mask=classes==name
        elif kind=='body_zone':
            if set(target)-{'kind','name'} or target.get('name') not in BODY_ZONE_NAMES:
                raise ValueError('Unknown electrode body zone')
            name=target['name']
            if name in ('left_eye','right_eye'):
                mask=np.isin(values('cell_type'),['R1-6','R7','R8']) & (values('side')==name.split('_')[0])
                assumption='Virtual electrode targets annotated eye photoreceptors; no tissue electric-field model.'
            elif name=='antennae':
                mask=(values('super_class')=='sensory') & (values('nerve')=='AN')
                assumption='Antenna proxy uses sensory neurons annotated with nerve AN; no physical antenna or field model.'
            else:
                mask=np.isin(values('super_class'),['ascending','sensory_ascending'])
                assumption='ASSUMPTION: legs, wings and body share the same generic ascending/body-afferent proxy. This brain release has no body-part-specific VNC, muscle or limb simulation.'
        elif kind=='sphere':
            if set(target)-{'kind','center_um','radius_um'}:
                raise ValueError('Unsupported sphere target field')
            center=np.asarray(target.get('center_um'),dtype=float);radius=_number(target.get('radius_um'),'sphere.radius_um')
            if center.shape!=(3,) or not np.isfinite(center).all() or not 1<=radius<=500:
                raise ValueError('Sphere requires a finite XYZ center_um and radius_um in [1,500]')
            points=neurons[['pos_x','pos_y','pos_z']].to_numpy(dtype=float)*[.004,.004,.04]
            mask=np.isfinite(points).all(axis=1)&(np.linalg.norm(points-center,axis=1)<=radius)
            assumption='Targets annotation anchor positions inside a sphere; not neurite geometry or an electric-field solution.'
        else:
            raise ValueError('Unknown electrode target kind')
        indices=np.flatnonzero(mask).astype(np.int32)
        if not len(indices):
            raise ValueError('Electrode '+e['id']+' resolves to no neurons')
        definition=dict(e)|{'n_targets':len(indices),'target_indices':indices.tolist(),'assumption':assumption,
                            'sampling_note':'Waveform sampled at the neural integration timestep; pulse boundaries have at most one timestep quantization.'}
        resolved.append(ResolvedElectrode(definition,indices))
    return resolved


def electrode_waveform(definition,times_ms):
    t=np.asarray(times_ms,dtype=float);e=definition
    active=(t>=e['start_ms']-1e-9)&(t<e['end_ms']-1e-9)
    if e['duty_percent']<=0:
        active &= False
    elif e['frequency_hz']>0 and e['duty_percent']<100:
        phase=np.mod((t-e['start_ms'])*e['frequency_hz']/1000.+e['phase_deg']/360.,1.)
        active &= phase < e['duty_percent']/100.-1e-12
    return active.astype(float)*e['voltage_mv']


def input_layout(photoreceptor_indices,electrodes):
    inputs=np.unique(np.concatenate([np.asarray(photoreceptor_indices,dtype=np.int32)]+[e.indices for e in electrodes])).astype(np.int32)
    photo_columns=np.searchsorted(inputs,photoreceptor_indices)
    electrode_columns=[np.searchsorted(inputs,e.indices) for e in electrodes]
    return inputs,photo_columns,electrode_columns


def combined_drive(times_ms,photo_drive,layout,electrodes):
    inputs,photo_columns,electrode_columns=layout
    drive=np.zeros((len(times_ms),len(inputs)),dtype=float)
    drive[:,photo_columns]+=photo_drive
    for e,columns in zip(electrodes,electrode_columns):
        drive[:,columns]+=electrode_waveform(e.definition,times_ms)[:,None]
    return drive
