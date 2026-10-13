"""Versioned visual electrical candidate and complete quiescent initialization.

Physiological recordings support a graded visual-pathway model; the exact
cell-type assignment, shared kinetics and incoming gain cap remain assumptions.
The candidate changes electrical partitions and effective gains, not anatomy.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from scipy import sparse

from .fetch import checksum
from .inspect_data import atomic_write_json
from .memguard import check_memory
from .model_registry import load_model_network, stable_hash, _freeze_model

BASE_MODEL = 'paralimbo-v0-1-0'
BASE_HASH = '251615940b84dad843d0cf85138c936e118b0890274231bb8e5720b5b381bb5c'
CANDIDATE_ID = 'paralimbo-visual-graded-v1'
HISTORICAL_RUN = '20261008T142805Z_visual_edge_feef0d'
VISUAL_GRADED_TYPES = ('L1','L2','L3','L4','L5','Mi1','Mi4','Mi9',
    'Tm1','Tm2','Tm3','Tm4','Tm9','C3','T4a','T4b','T4c','T4d','T5a','T5b','T5c','T5d')
SOURCES = {
    'voltage_and_passive_T4': 'https://doi.org/10.1038/s41586-022-04428-3',
    'voltage_imaging_lamina_medulla': 'https://doi.org/10.1016/j.cell.2016.05.031',
    'graded_L1_pathway': 'https://doi.org/10.7554/eLife.49373',
    'visual_network_modeling_precedent': 'https://doi.org/10.1038/s41586-024-07939-3',
}


def partition_counts(counts, mask):
    """Partition by presynaptic column without changing signed anatomy."""
    graded = counts.multiply(mask).tocsr()
    spiking = counts.multiply(~mask).tocsr()
    for matrix in (graded, spiking):
        matrix.eliminate_zeros(); matrix.sort_indices()
    if (graded + spiking != counts).nnz:
        raise ValueError('Electrical repartition changed anatomical signed counts')
    return graded, spiking


def build_candidate(root, base_hash=BASE_HASH):
    root = Path(root)
    original = load_model_network(root, BASE_MODEL, base_hash)
    if base_hash != BASE_HASH:
        reference = json.loads((root/'config/reference-visual-map/base-model.json').read_text())
        # Source-code identities may change as startup/export code is repaired.
        # Every data artifact must still be byte-identical to the audited graph.
        expected = {k:v for k,v in reference['output_hashes'].items() if k not in ('compiler.py','compiler_hashes.json')}
        actual = {k:v for k,v in original['manifest']['output_hashes'].items() if k not in ('compiler.py','compiler_hashes.json')}
        if reference['model_hash'] != BASE_HASH or expected != actual:
            raise ValueError('Rebuilt ParaLimbo data differ from the frozen reference graph')
    table = original['neurons'].copy()
    old = table.is_graded.to_numpy(bool)
    mask = old | table.cell_type.isin(VISUAL_GRADED_TYPES).to_numpy()
    ledger = table[['entity_id','cell_type','side']].copy()
    ledger['original_mode'] = np.where(old, 'graded','spiking')
    ledger['candidate_mode'] = np.where(mask,'graded','spiking')
    ledger['evidence_status'] = np.where(mask & ~old,
        'ASSUMPTION: type-level graded visual model supported by voltage physiology; not per-cell measured',
        'inherited original electrical assumption')
    table['is_graded'] = mask; table['mode'] = np.where(mask,'graded','spiking')
    graded, spiking = partition_counts(original['reference'], mask)
    runtime = {'schema_version':1, 'initialization':'constant_background_equilibrium_v1',
               'graded_input_cap':0.8, 'chemistry_supported':False,
               'assumption':'Cap absolute incoming graded DC gain at 0.8 per target; weak rows remain unchanged.'}
    parent = root/'build/neural-baseline'; parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='candidate-',dir=parent) as tmp:
        folder = Path(tmp)
        table.to_parquet(folder/'neurons.parquet',index=False)
        ledger.to_parquet(folder/'electrical_modes.parquet',index=False)
        historical = root/'runs'/HISTORICAL_RUN
        mapping = historical/'visual-workspace-mapping'
        if (historical/'run_manifest.json').is_file():
            eye_audit = json.loads((historical/'run_manifest.json').read_text())['eye_audit']
        else:
            # A source installation has no developer recordings. Ship only the
            # frozen mapping inputs, with the original provenance and hashes.
            mapping = root/'config/reference-visual-map'
            reference = json.loads((mapping/'manifest.json').read_text())
            if reference['historical_run'] != HISTORICAL_RUN or reference['original_model_hash'] != BASE_HASH:
                raise ValueError('Reference optical map belongs to another baseline')
            for name, digest in reference['sha256'].items():
                if name not in ('columns.parquet', 'assignments.parquet') or checksum(mapping/name) != digest:
                    raise ValueError('Reference optical map checksum mismatch')
            if set(reference['sha256']) != {'columns.parquet', 'assignments.parquet'}:
                raise ValueError('Reference optical map is incomplete')
            eye_audit = reference['audit']
        for source,dest in [('columns.parquet','eye_columns.parquet'),('assignments.parquet','eye_assignments.parquet')]:
            shutil.copyfile(mapping/source,folder/dest)
        eye_snapshot = {'historical_run':HISTORICAL_RUN,'original_model_hash':BASE_HASH,
            'columns_sha256':checksum(folder/'eye_columns.parquet'),
            'assignments_sha256':checksum(folder/'eye_assignments.parquet'),'audit':eye_audit}
        eye_snapshot['mapping_hash'] = stable_hash(eye_snapshot)
        for name,matrix in [('graded',graded),('spiking',spiking)]:
            for field in ('data','indices','indptr'):
                np.save(folder/f'{name}_{field}.npy',getattr(matrix,field),allow_pickle=False)
        files = sorted(p.name for p in folder.iterdir())
        manifest = {'schema_version':1,'id':CANDIDATE_ID,'source':'BANC with declared visual electrical assumptions',
            'materialization':888,'identity_namespace':'banc:888','species':'Drosophila melanogaster',
            'sex':'female','stage':'adult','base_model':BASE_MODEL,'base_model_hash':base_hash,
            'neurons':len(table),'edges':int(graded.nnz+spiking.nnz),'anatomical_edges_changed':0,
            'graded_neurons':int(mask.sum()),'reclassified_neurons':int(np.sum(mask & ~old)),
            'graded_types':list(VISUAL_GRADED_TYPES),'runtime_profile':runtime,'sources':SOURCES,
            'eye_snapshot':eye_snapshot,
            'implementation_hash':checksum(Path(__file__)),
            'output_hashes':{name:checksum(folder/name) for name in files},
            'optical_mapping_supported':False,'status':'EXPERIMENTAL_NUMERICAL_CANDIDATE',
            'warnings':['Electrical modes and gain normalization are model assumptions.',
                        'Historical optical mapping is incomplete; biological accuracy remains unvalidated.']}
        manifest['model_hash'] = stable_hash(manifest)
        _freeze_model(root,folder,manifest)
    alias = root/'build/models'/CANDIDATE_ID; alias.mkdir(parents=True,exist_ok=True)
    atomic_write_json(alias/'manifest.json',manifest)
    return manifest


def candidate_eye_mapping(root, network):
    """Read a frozen historical map, checking qualified model row identities."""
    import pandas as pd
    from .eye import EyeMapping
    manifest = network['manifest']; saved = manifest['eye_snapshot']
    folder = Path(root)/'build/model-versions'/manifest['model_hash']
    for name,key in [('eye_columns.parquet','columns_sha256'),('eye_assignments.parquet','assignments_sha256')]:
        if checksum(folder/name)!=saved[key]:raise ValueError('Frozen eye map checksum mismatch')
    columns = pd.read_parquet(folder/'eye_columns.parquet')
    assignments = pd.read_parquet(folder/'eye_assignments.parquet')
    neurons = network['neurons']
    if not np.array_equal(assignments.root_id.to_numpy(),neurons.root_id.to_numpy()):
        raise ValueError('Frozen eye map neuron identity or order mismatch')
    mapped = np.flatnonzero(assignments.column_index.ge(0).to_numpy() & neurons.is_graded.to_numpy(bool)).astype(np.int32)
    return EyeMapping(columns,assignments,mapped,assignments.column_index.to_numpy(np.int32)[mapped],
        saved['audit']|{'mapping_hash':saved['mapping_hash'],'historical_run':saved['historical_run'],
                       'source_model_hash':manifest['model_hash'],'original_model_hash':saved['original_model_hash']})


def graded_operator(engine):
    return sparse.csr_matrix((engine.graded_counts,engine.graded_indices,engine.graded_indptr),
                            shape=(engine.n_neurons,engine.n_neurons),copy=False)


def equilibrium_state(engine, external, *, tolerance=1e-10, max_iterations=10000):
    """Solve the actual two-state DC equations; reject invalid quiescent states.

    No threshold resets, voltage clamps, subtraction of tonic release or changed
    effective weights occur in the solver. Delays affect stability, not this DC
    equation, and must still receive an independent dynamic test.
    """
    external = np.asarray(external,dtype=np.float64)
    if external.shape != (engine.n_neurons,) or not np.isfinite(external).all():
        raise ValueError('Equilibrium input must be finite and cover every neuron')
    w = graded_operator(engine)
    scale = engine.tau_synapse * engine.parameters['graded_gain'] * engine.graded_row_scale
    v = engine.rest + external
    residual = float('inf')
    for iteration in range(1,max_iterations+1):
        release = np.maximum(0.,v-engine.parameters['graded_release'])*engine.graded_mask
        g = scale * w.dot(release)
        target = engine.rest + external + g
        residual = float(np.max(np.abs(target-v)))
        if not np.isfinite(target).all() or np.max(np.abs(target))>1e6:
            raise ValueError('Fixed-point iteration diverged')
        if residual <= tolerance:
            break
        v = .5*(v+target)
        if iteration % 20 == 0: check_memory()
    else:
        raise ValueError(f'No equilibrium within {max_iterations} iterations; residual {residual:g} mV')
    invalid = ((~engine.graded_mask) & (v > engine.parameters['v_threshold']))
    if invalid.any():
        raise ValueError(f'Continuous fixed point has {int(invalid.sum())} suprathreshold spiking cells')
    if np.any(v<engine.parameters['voltage_min']) or np.any(v>engine.parameters['voltage_max']):
        raise ValueError('Fixed point outside voltage bounds')
    return v,g,{'iterations':iteration,'max_fixed_point_residual_mv':residual,
                'tolerance_mv':tolerance,'spiking_threshold_margin_mv':float(np.min(
                    engine.parameters['v_threshold']-v[~engine.graded_mask])) if (~engine.graded_mask).any() else None}


def initialize_equilibrium(engine, indices, drive):
    if getattr(engine,'chemistry',None) is not None or getattr(engine,'organs',None) is not None:
        raise ValueError('Quiescent baseline profile does not yet validate chemical or organ coupling')
    indices = np.asarray(indices,dtype=np.int64)
    if indices.ndim!=1 or np.any(indices<0) or np.any(indices>=engine.n_neurons) or len(np.unique(indices))!=len(indices):
        raise ValueError('Equilibrium input indices must be unique valid neurons')
    external = np.zeros(engine.n_neurons)
    external[indices] = np.broadcast_to(np.asarray(drive,dtype=float),(len(indices),))
    v,g,summary = equilibrium_state(engine,external)
    engine.reset()
    engine.v[:] = v; engine.g[:] = g
    release = np.maximum(0.,v-engine.parameters['graded_release'])*engine.graded_mask
    engine.release_history[:] = release
    engine.ring.fill(0); engine.ring_counts.fill(0)
    engine.output_enabled[:] = True
    return summary


def complete_residual(engine, indices, drive):
    external = np.zeros(engine.n_neurons)
    external[np.asarray(indices,dtype=int)] = drive
    release = np.maximum(0.,engine.v-engine.parameters['graded_release'])*engine.graded_mask*engine.output_enabled
    forcing = engine.parameters['graded_gain']*engine.graded_row_scale*graded_operator(engine).dot(release)
    dv = (engine.rest-engine.v+engine.g+external)/engine.tau_membrane
    dg = -engine.g/engine.tau_synapse+forcing
    finite = bool(np.isfinite(engine.v).all() and np.isfinite(engine.g).all()
                  and np.isfinite(engine.release_history).all() and np.isfinite(dv).all() and np.isfinite(dg).all())
    return {'finite':finite,'max_abs_dvdt_mv_per_ms':float(np.max(abs(dv))) if finite else None,
            'max_abs_dgdt_mv_per_ms':float(np.max(abs(dg))) if finite else None,
            'max_delay_history_residual_mv':float(np.max(abs(engine.release_history-release))) if finite else None,
            'queued_spikes':int(engine.ring_counts.sum()),'clamp_count':int(engine.per_neuron_clamp_counts.sum())}
