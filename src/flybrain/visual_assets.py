"""Anatomical display assets from real annotation anchors, never invented morphology."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

from .fetch import checksum
from .inspect_data import atomic_write_json
from .visual_neuropils import neuropil_traces

GROUPS = [
    ("optic", "Optic lobe", "#43cbd6"),
    ("central", "Central brain", "#8894ef"),
    ("sensory", "Sensory", "#ead190"),
    ("visual_projection", "Visual projection", "#58b58d"),
    ("ascending", "Ascending", "#c28cec"),
    ("descending", "Descending", "#f29072"),
    ("sensory_ascending", "Sensory ascending", "#c7be83"),
    ("visual_centrifugal", "Visual centrifugal", "#7897c5"),
    ("motor", "Motor", "#d79b91"),
    ("endocrine", "Endocrine", "#b6a3ab"),
    ("missing", "Unclassified", "#747f91"),
]


def _with_analysis_annotations(root, metadata, neurons=None):
    from .visual_analysis import analysis_annotations
    assignment_path = root / "build/visual/eye_assignments.parquet"
    digest = checksum(assignment_path) if assignment_path.exists() else None
    if metadata.get("analysis", {}).get("version") == 1 and metadata.get("eye_assignments_sha256") == digest:
        return metadata
    neurons = pd.read_parquet(root / "build/neurons.parquet") if neurons is None else neurons
    assignments = pd.read_parquet(assignment_path) if assignment_path.exists() else None
    metadata["analysis"] = analysis_annotations(neurons, assignments, metadata["center_um"], metadata["scale_um"])
    metadata["eye_assignments_sha256"] = digest
    atomic_write_json(root / "build/visual/anatomy/metadata.json", metadata)
    return metadata


def _with_region_annotations(root, metadata, neurons=None):
    """Label actual assigned neuron centroids, without inventing region surfaces."""
    path = root / 'build/compartments.npz'
    mapping_meta = root / 'build/compartments_metadata.json'
    if not path.exists() or not mapping_meta.exists():
        metadata['regions'] = []
        return metadata
    neuropil_paths = [root / f'data/raw/per_neuron_neuropil_count_{part}_783.feather' for part in ('pre', 'post')]
    has_neuropils = all(p.exists() for p in neuropil_paths)
    digest = checksum(path) + ':' + checksum(mapping_meta) + ':atlas-v2'
    if has_neuropils:
        digest += ':' + ':'.join(checksum(p) for p in neuropil_paths)
    if metadata.get('region_source_sha256') == digest and 'regions' in metadata:
        return metadata
    from .neuromod.compartments import load_compartments
    from scipy import sparse
    mapping = load_compartments(root)
    neurons = pd.read_parquet(root / 'build/neurons.parquet') if neurons is None else neurons
    if not np.array_equal(mapping.model_root_ids, neurons.root_id.to_numpy()):
        raise ValueError('Region atlas differs from the released neuron order')
    xyz = neurons[['pos_x', 'pos_y', 'pos_z']].to_numpy(float)
    valid = np.isfinite(xyz).all(axis=1)
    points = (xyz * [.004, .004, .040] - metadata['center_um']) / metadata['scale_um']
    rows = sparse.csr_matrix(mapping.membership)
    groups = []
    if has_neuropils:
        from .visual_neuropils import load_neuropil_weights
        neuropils = load_neuropil_weights(root)
        groups.extend((name, neuropils['weights'].getrow(i), 'neuropil') for i, name in enumerate(neuropils['names']) if name != 'None')
    existing = {name for name, _, _ in groups}
    groups.extend((name, rows.getrow(i), 'chemical_compartment') for i, name in enumerate(mapping.names) if name not in existing)
    regions = []
    for name, row, kind in groups:
        indices = row.indices[valid[row.indices]]
        weights = row.data[valid[row.indices]]
        center = np.average(points[indices], weights=weights, axis=0).tolist() if len(indices) and name != 'hemolymph' else None
        regions.append({'key': name, 'position': center, 'neuron_count': int(row.nnz),
                        'located_neuron_count': len(indices), 'kind': kind})
    metadata.update(regions=regions, region_source_sha256=digest,
                    region_label_definition='Weighted centers of assigned neuron annotation anchors, not neuropil boundaries. Mushroom body labels retain empirical assignments.')
    atomic_write_json(root / 'build/visual/anatomy/metadata.json', metadata)
    return metadata


def prepare_anatomy(root):
    root = Path(root)
    source = root / "build/neurons.parquet"
    out = root / "build/visual/anatomy"
    out.mkdir(parents=True, exist_ok=True)
    digest = checksum(source)
    meta_path = out / "metadata.json"
    if meta_path.exists():
        previous = json.loads(meta_path.read_text())
        if previous.get("source_sha256") == digest and all((out / name).exists() for name in ("positions.bin", "groups.bin", "visible_indices.bin")):
            return _with_region_annotations(root, _with_analysis_annotations(root, previous))
    neurons = pd.read_parquet(source)
    xyz = neurons[["pos_x", "pos_y", "pos_z"]].to_numpy(dtype=np.float64)
    valid = np.all(np.isfinite(xyz), axis=1)
    physical = xyz * np.array([0.004, 0.004, 0.040])
    low, high = physical[valid].min(axis=0), physical[valid].max(axis=0)
    center = (low + high) / 2
    scale = float((high - low).max() / 2)
    normalized = np.zeros_like(physical, dtype=np.float32)
    normalized[valid] = (physical[valid] - center) / scale
    normalized.astype("<f4").tofile(out / "positions.bin")
    np.flatnonzero(valid).astype("<u4").tofile(out / "visible_indices.bin")
    classes = neurons.super_class.fillna("missing").to_numpy()
    group_ids = np.full(len(neurons), len(GROUPS) - 1, dtype=np.uint8)
    groups = []
    for i, (key, label, color) in enumerate(GROUPS):
        mask = classes == key
        group_ids[mask] = i
        groups.append({"id": i, "key": key, "name": label, "color": color, "count": int(mask.sum())})
    group_ids.tofile(out / "groups.bin")
    metadata = {
        "neuron_count": len(neurons), "visible_neuron_count": int(valid.sum()),
        "missing_positions": int((~valid).sum()), "groups": groups,
        "representation": "Neuron annotation anchors; not cell morphology or synapse locations",
        "position_units": "isotropically normalized micrometers", "source_coordinate_units": "4 x 4 x 40 nm voxels",
        "source_fields": ["pos_x", "pos_y", "pos_z"], "center_um": center.tolist(),
        "scale_um": scale, "extents_um": (high - low).tolist(), "coordinate_orientation": "original dataset XYZ",
        "source_url": "https://raw.githubusercontent.com/flyconnectome/flywire_annotations/main/supplemental_files/README.md",
        "source_sha256": digest, "missing_positions_policy": "Retain in simulation; omit from indexed point rendering",
        "positions_url": "/api/anatomy/positions.bin", "groups_url": "/api/anatomy/groups.bin",
        "visible_indices_url": "/api/anatomy/visible_indices.bin", "metadata_url": "/api/anatomy/metadata.json",
    }
    return _with_region_annotations(root, _with_analysis_annotations(root, metadata, neurons), neurons)


def export_visual_run(root, result):
    """Adapt scientifically complete experiment outputs to the browser protocol."""
    root = Path(root).resolve()
    directory = Path(result["run_dir"]).resolve()
    if not directory.is_relative_to(root / "runs"):
        raise ValueError("Visual result directory is outside project runs")
    run_id = directory.name
    model_id=result.get('model_id',result.get('metadata',{}).get('model_id','flywire-783'))
    model_hash=result.get('model_hash',result.get('metadata',{}).get('model_hash'))
    neuron_path=directory/'neurons.parquet'
    if neuron_path.exists():
        neurons=pd.read_parquet(neuron_path)
    elif model_id!='flywire-783':
        neurons=pd.read_parquet(root/'build/models'/model_id/'neurons.parquet')
    else:
        neurons = pd.read_parquet(root / "build/neurons.parquet")
    n = len(neurons)
    with np.load(result["activity_path"]) as activity:
        indices = activity["node_indices"].astype(np.int64)
        recorded_indices=indices.copy()
        if not np.array_equal(indices, np.arange(n)):
            if not neuron_path.exists() and model_id=='flywire-783' and not result.get('selection'):
                raise ValueError('Historical recording must retain the released order')
            if np.any(indices<0) or np.any(indices>=n) or len(np.unique(indices))!=len(indices):
                raise ValueError("Recording neuron indices do not match its model")
            neurons=neurons.iloc[indices].reset_index(drop=True)
            n=len(neurons)
        time_ms = activity["time_ms"].astype(float).tolist()
        frames = len(time_ms)
        shapes = []
        color_range = 0.05
        for key, name in (("delta_mv", "delta.bin"), ("raw_mv", "raw.bin"), ("baseline_mv", "baseline.bin")):
            array = activity[key]
            if array.shape != (frames, n) or not np.all(np.isfinite(array)):
                raise ValueError(f"Invalid browser activity shape or values for {key}")
            array.astype("<f4").tofile(directory / name)
            shapes.append(list(array.shape))
            if key == "delta_mv":
                color_range = max(0.05, float(np.quantile(np.abs(array), .995)))
        historical_full=model_id=='flywire-783' and np.array_equal(neurons.root_id.to_numpy(),pd.read_parquet(root/'build/neurons.parquet',columns=['root_id']).root_id.to_numpy())
        region_traces = neuropil_traces(root, activity["raw_mv"], activity["baseline_mv"]) if historical_full else []
    metadata = result.get("metadata", {})
    options = metadata.get("options", metadata.get("stimulus", {}))
    if not isinstance(options, dict):
        options = {}
    stimulus = dict(options)
    stimulus["type"] = options.get("stimulus", options.get("type", result.get("stimulus", "grating")))
    if "duration_ms" not in stimulus:
        stimulus["duration_ms"] = metadata.get("duration_ms", frames * 20)
    colors = ["#4dd4df", "#8e9fec", "#f0b47b", "#d699c7", "#80c6a1", "#d3ce88"]
    traces = []
    for i, trace in enumerate(result.get("traces", [])):
        traces.append({**trace, "values": trace.get("delta_mv", trace.get("values", [])),
                       "raw": trace.get("raw_mv", trace.get("raw", [])),
                       "baseline": trace.get("baseline_mv", trace.get("baseline", [])),
                       "color": colors[i % len(colors)]})
    for i, trace in enumerate(region_traces):
        trace.update(values=trace["delta_mv"], raw=trace["raw_mv"], baseline=trace["baseline_mv"], color=colors[i % len(colors)])
    prefix = f"/api/runs/{run_id}"
    stats = dict(result.get("stats", {}))
    stats.update(clamps=stats.get("clamp_count", 0), baseline_clamps=stats.get("baseline_clamp_count", 0),
                 spikes=stats.get("spike_count", 0), baseline_spikes=stats.get("baseline_spike_count", 0),
                 wall_seconds=metadata.get("wall_seconds"),
                 preequilibration_clamps=metadata.get("preequilibration", {}).get("clamp_events"),
                 mapped_photoreceptors=metadata.get("eye_audit", {}).get("photoreceptors_mapped"),
                 unassigned_photoreceptors=metadata.get("eye_audit", {}).get("photoreceptors_unassigned"))
    warnings = list(result.get("warnings", []))
    if not metadata.get("optics"):
        warnings.append("Legacy recording: optical smoothing used coarse 5 × 5 Gaussian quadrature. Sharp-pattern responses may differ from new recordings with refined optics.")
    summary = {
        "id": run_id, "label": f"{stimulus['type'].replace('_', ' ').title()} · {stimulus['duration_ms']:g} ms",
        "stimulus": stimulus, "frames": {"count": frames, "dt_ms": float(time_ms[1] - time_ms[0]) if frames > 1 else float(metadata.get("sample_interval_ms", 20)), "time_ms": time_ms},
        "activity": {"delta_url": prefix + "/delta.bin", "raw_url": prefix + "/raw.bin", "baseline_url": prefix + "/baseline.bin",
                     "shape": shapes[0], "dtype": "float32", "unit": "mV", "raw_unit": "mV", "color_range_mv": color_range},
        "traces": traces, "region_traces": region_traces, "stats": stats, "warnings": warnings,
        "eyes": result.get("eye", {}), "metadata": metadata,
        "stimulation": result.get("stimulation", {}),
        "interpretation": "Paired membrane-voltage difference from a matched constant-luminance control; experimental unstable model, not validated fly behavior",
        "neuron_count":n,"simulation_scope":"complete released whole-brain model" if historical_full else 'model-qualified recorded selection',
        "model_id":model_id,"model_hash":model_hash,
    }
    if not historical_full:
        from .model_anatomy import write_anatomy
        summary['anatomy']=write_anatomy(neurons,directory/'anatomy',prefix+'/anatomy',model_id=model_id,model_hash=model_hash)
        neurons.to_parquet(directory/'recorded_neurons.parquet',index=False)
    summary['spikes']={}
    spike_source=directory/'spikes.npz'
    if not spike_source.exists():spike_source=Path(result['activity_path'])
    if spike_source.exists():
        with np.load(spike_source,allow_pickle=False) as spikes:
            for prefix_key in ('','baseline_'):
                ik,tk=prefix_key+'spike_indices',prefix_key+'spike_times_ms'
                if ik not in spikes or tk not in spikes:continue
                indices=np.asarray(spikes[ik]);spike_times=np.asarray(spikes[tk])
                if indices.shape!=spike_times.shape:raise ValueError('Recorded spike axes disagree')
                lookup={int(value):i for i,value in enumerate(recorded_indices)}
                keep=np.fromiter((int(value) in lookup for value in indices),dtype=bool,count=len(indices))
                indices=np.fromiter((lookup[int(value)] for value in indices[keep]),dtype=np.int64,count=int(keep.sum()))
                spike_times=spike_times[keep]
                summary['spikes'][ik]=indices[-200000:].tolist()
                summary['spikes'][tk]=spike_times[-200000:].tolist()
                summary['spikes'][prefix_key+'total_count']=len(indices)
                summary['spikes'][prefix_key+'truncated']=len(indices)>200000
    if result.get('chemistry_path'):
        summary['chemistry']=export_chemistry(directory,result,neurons.root_id.to_numpy(),time_ms)
    else:
        summary['chemistry']={'available':False,'status':'NOT-RECORDED',
                              'reason':'This recording contains no neuromodulator/state data; concentrations are not synthesized.'}
    if result.get('peripheral',{}).get('enabled'):
        organ=dict(result['peripheral'])
        if organ.get('time_ms')!=time_ms:raise ValueError('Peripheral and neural samples disagree')
        for name in ('state_values','baseline_state_values'):
            values=np.asarray(organ[name],dtype=float)
            if values.shape!=(frames,len(organ['modules']),len(organ['state_names'])) or not np.isfinite(values).all():
                raise ValueError('Invalid peripheral state recording')
        summary['peripheral']=organ
    eye_source = directory / "eye_input.npz"
    if eye_source.exists():
        with np.load(eye_source) as eye:
            light, eye_times = eye["luminance"], eye["frame_times_ms"]
            light.astype("<f4").tofile(directory / "eye_luminance.bin")
            summary["eyes"] = {**summary["eyes"], "luminance_url": prefix + "/eye_luminance.bin",
                               "shape": list(light.shape), "time_ms": eye_times.tolist(),
                               "dt_ms": float(eye_times[1] - eye_times[0]) if len(eye_times) > 1 else 20}
    frame_source = result.get("stimulus_full_frames_path", result.get("stimulus_frames_path"))
    if frame_source:
        image_frames = np.load(frame_source)
        image_frames.astype(np.uint8).tofile(directory / "stimulus.bin")
        source_times = result.get("stimulus_frame_times_ms", time_ms)
        summary["stimulus_frames"] = {"url": prefix + "/stimulus.bin", "shape": list(image_frames.shape), "dtype": "uint8", "time_ms": source_times,
                                     "dt_ms": float(source_times[1] - source_times[0]) if len(source_times) > 1 else 20}
    atomic_write_json(directory / "visual_summary.json", summary)
    return summary


def export_chemistry(directory,result,root_ids,frame_times):
    """Export recorded fields and sparse neuron exposure without fabricating rows."""
    directory=Path(directory).resolve()
    source=Path(result['chemistry_path']).resolve()
    if not source.is_relative_to(directory):
        raise ValueError('Chemistry recording must belong to the recorded run')
    metadata=result.get('chemistry',{})
    if not isinstance(metadata,dict):raise ValueError('Chemistry metadata must be a mapping')
    metadata=dict(metadata)
    if 'compartment_names' not in metadata:metadata['compartment_names']=metadata.get('compartments')
    def labels(key):
        values=metadata.get(key)
        if not isinstance(values,list) or not all(isinstance(x,str) and x for x in values) or len(set(values))!=len(values):
            raise ValueError('Missing or invalid chemistry labels: '+key)
        return values
    species,compartments=labels('species'),labels('compartment_names')
    states,hormones=labels('state_names'),labels('hormone_names')
    if not species or not compartments or not states:raise ValueError('Empty recorded chemistry axes')
    n,t,k=len(root_ids),len(frame_times),len(compartments)
    arrays={}
    with np.load(source,allow_pickle=False) as data:
        if not np.array_equal(data['time_ms'],np.asarray(frame_times)):
            raise ValueError('Chemistry times must align exactly with recorded voltage frames')
        if data['node_root_ids'].dtype.kind not in 'iu' or not np.array_equal(data['node_root_ids'],root_ids):
            raise ValueError('Chemistry neurons differ from full released root order')
        shapes={'concentrations_au':(t,len(species),k),'baseline_concentrations_au':(t,len(species),k),
                'state_values':(t,len(states)),'hormones_au':(t,len(hormones))}
        optional={'baseline_state_values':(t,len(states)),'baseline_hormones_au':(t,len(hormones)),
                  'plasticity_change_l1':(t,),'baseline_plasticity_change_l1':(t,)}
        enzyme_meta=dict(metadata.get('enzymes') or {})
        if enzyme_meta.get('enabled'):
            pool_names=enzyme_meta.get('pool_names',[])
            flux_names=enzyme_meta.get('flux_names',['ChAT','AChE','Tbh','ACh release','OA release'])
            if not pool_names or len(set(pool_names))!=len(pool_names):raise ValueError('Invalid enzyme pool axis')
            enzyme_meta['flux_names']=flux_names
            for axis,names in [('pools_au',pool_names),('flux_au_per_ms',flux_names)]:
                for prefix_key in ('','baseline_'):
                    key=prefix_key+'enzyme_'+axis
                    if key not in data:raise ValueError('Missing enabled enzyme recording: '+key)
                    optional[key]=(t,len(names),k)
        shapes.update({key:shape for key,shape in optional.items() if key in data})
        for key,shape in shapes.items():
            value=np.asarray(data[key])
            if value.shape!=shape or not np.isfinite(value).all():raise ValueError('Invalid chemistry array: '+key)
            if np.any(value<0):raise ValueError('Negative chemistry/state value: '+key)
            arrays[key]=value.astype('<f4')
            if not np.isfinite(arrays[key]).all():raise ValueError('Chemistry values overflow float32: '+key)
        indptr=np.asarray(data['membership_indptr']);indices=np.asarray(data['membership_indices']);weights=np.asarray(data['membership_weights'])
        if (indptr.dtype.kind not in 'iu' or indices.dtype.kind not in 'iu' or indptr.shape!=(n+1,)
                or indices.ndim!=1 or weights.shape!=indices.shape or indptr[0]!=0 or indptr[-1]!=len(indices)
                or np.any(indptr[1:]<indptr[:-1]) or np.any(indices<0) or np.any(indices>=k)
                or not np.isfinite(weights).all() or np.any(weights<0)):
            raise ValueError('Invalid neuron-compartment membership CSR')
        rows=np.repeat(np.arange(n),np.diff(indptr).astype(np.int64))
        sums=np.bincount(rows,weights=weights,minlength=n)
        assigned=np.diff(indptr)>0
        if not np.allclose(sums[assigned],1.,rtol=0,atol=1e-5):
            raise ValueError('Assigned neuron-compartment memberships must sum to one')
        if len(indices)>np.iinfo(np.uint32).max:raise ValueError('Membership CSR exceeds browser uint32 range')
        arrays.update(membership_indptr=indptr.astype('<u4'),membership_indices=indices.astype('<u4'),membership_weights=weights.astype('<f4'))
    filenames={'concentrations_au':'chemistry.bin','baseline_concentrations_au':'chemistry_baseline.bin',
               'state_values':'chemistry_state.bin','hormones_au':'chemistry_hormones.bin',
               'membership_indptr':'chemistry_membership_indptr.bin','membership_indices':'chemistry_membership_indices.bin',
               'membership_weights':'chemistry_membership_weights.bin',
               'baseline_state_values':'chemistry_baseline_state.bin','baseline_hormones_au':'chemistry_baseline_hormones.bin',
               'plasticity_change_l1':'chemistry_plasticity.bin','baseline_plasticity_change_l1':'chemistry_baseline_plasticity.bin',
               'enzyme_pools_au':'enzyme_pools.bin','baseline_enzyme_pools_au':'enzyme_baseline_pools.bin',
               'enzyme_flux_au_per_ms':'enzyme_flux.bin','baseline_enzyme_flux_au_per_ms':'enzyme_baseline_flux.bin'}
    for name,array in arrays.items():array.tofile(directory/filenames[name])
    prefix=f'/api/runs/{directory.name}/'
    result_meta={key:metadata[key] for key in ('scenario','enabled','plasticity_enabled','assumptions','warnings',
        'interpretation','field_units','state_units','hormone_units','source_provenance','parameters','status',
        'options','diagnostics','baseline_diagnostics','paired_initialization','source_projection','receptor_coverage',
        'chemical_tick_ms','state_tick_ms','membership_policy','chemical_intervention') if key in metadata}
    optional_urls={key+'_url':prefix+filenames[key] for key in optional if key in arrays}
    return {**result_meta,'enzymes':enzyme_meta,'available':True,'neuron_count':n,'species':species,'compartment_names':compartments,
            'state_names':states,'hormone_names':hormones,'time_ms':list(frame_times),
            'dtype':'float32','unit':'a.u.','shape':list(arrays['concentrations_au'].shape),
            'concentrations_url':prefix+filenames['concentrations_au'],
            'baseline_concentrations_url':prefix+filenames['baseline_concentrations_au'],
            'state_values_url':prefix+filenames['state_values'],'state_shape':list(arrays['state_values'].shape),
            'hormones_url':prefix+filenames['hormones_au'],'hormone_shape':list(arrays['hormones_au'].shape),
            'membership':{'indptr_url':prefix+filenames['membership_indptr'],
                'indices_url':prefix+filenames['membership_indices'],'weights_url':prefix+filenames['membership_weights'],
                'shape':[n,k],'nnz':len(indices),'index_dtype':'uint32','weight_dtype':'float32',
                'assigned_neuron_count':int(assigned.sum()),'unassigned_neuron_count':int((~assigned).sum()),
                'order':'Full released neuron order; sparse weighted compartment exposure',
                'unassigned_policy':'No assigned compartment; no concentration is inferred for an empty row'},
            **optional_urls,
            'recording_sha256':checksum(source),'asset_sha256':{filenames[key]:checksum(directory/filenames[key]) for key in arrays}}
