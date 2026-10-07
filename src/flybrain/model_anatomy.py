"""Model-qualified and recording-local anatomical assets in explicit row order."""
from pathlib import Path
import numpy as np
import pandas as pd
from .fetch import checksum
from .inspect_data import atomic_write_json
from .visual_assets import GROUPS


def write_anatomy(neurons, directory, prefix, *, model_id, model_hash=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    xyz = neurons[['pos_x', 'pos_y', 'pos_z']].to_numpy(float) * [.004, .004, .04]
    valid = np.isfinite(xyz).all(axis=1)
    low = xyz[valid].min(axis=0) if valid.any() else np.zeros(3)
    high = xyz[valid].max(axis=0) if valid.any() else np.zeros(3)
    center = (low + high) / 2
    scale = max(float((high - low).max() / 2), .001)
    points = np.zeros_like(xyz, dtype=np.float32)
    points[valid] = (xyz[valid] - center) / scale
    points.astype('<f4').tofile(directory / 'positions.bin')
    np.flatnonzero(valid).astype('<u4').tofile(directory / 'visible_indices.bin')
    classes = neurons.super_class.fillna('missing').astype(str).to_numpy()
    group_ids = np.full(len(neurons), len(GROUPS)-1, dtype=np.uint8)
    groups = []
    for index, (key, label, color) in enumerate(GROUPS):
        selected = classes == key
        group_ids[selected] = index
        groups.append({'id': index, 'key': key, 'name': label, 'color': color, 'count': int(selected.sum())})
    group_ids.tofile(directory / 'groups.bin')
    regions = []; membership = {}
    for column in ('root_region', 'region', 'neuromere'):
        if column not in neurons:continue
        for label, entries in neurons.groupby(column, dropna=True).indices.items():
            label = str(label)
            if not label or label in ('None', 'nan', 'unknown'):continue
            key = f'{column}:{label}'
            selected = np.asarray(entries, dtype=int)
            located = selected[valid[selected]]
            membership[key] = selected.tolist()
            regions.append({'key': key, 'name': label.replace('_', ' '), 'kind': 'source_annotation',
                            'neuron_count': len(selected), 'located_neuron_count': len(located),
                            'position': points[located].mean(axis=0).tolist() if len(located) else None})
    atomic_write_json(directory / 'regions.json', membership)
    identity = [{'index': i, 'root_id': str(row.root_id),
                 'entity_id': str(row.get('entity_id', f'flywire:783:{row.root_id}')),
                 'cell_type': str(row.get('cell_type', '')), 'side': str(row.get('side', ''))}
                for i, (_, row) in enumerate(neurons.iterrows())]
    atomic_write_json(directory / 'identities.json', identity)
    metadata = {'model_id': model_id, 'model_hash': model_hash, 'neuron_count': len(neurons),
                'visible_neuron_count': int(valid.sum()), 'missing_positions': int((~valid).sum()),
                'groups': groups, 'regions': regions, 'center_um': center.tolist(), 'scale_um': scale,
                'extents_um': (high-low).tolist(), 'position_units': 'isotropically normalized micrometers',
                'source_coordinate_units': 'provider-normalized 4 x 4 x 40 nm coordinates',
                'representation': 'Source annotation anchors; missing positions are omitted',
                'coordinate_orientation': 'native source XYZ; no automatic whole-fly registration',
                'positions_url': prefix+'/positions.bin', 'groups_url': prefix+'/groups.bin',
                'visible_indices_url': prefix+'/visible_indices.bin', 'metadata_url': prefix+'/metadata.json',
                'identities_url': prefix+'/identities.json', 'regions_url': prefix+'/regions.json',
                'analysis': {'version': 1, 'receptors': [], 'orientation': {'positions': {}}}}
    atomic_write_json(directory / 'metadata.json', metadata)
    return metadata


def model_anatomy_directory(root, model_id, model_hash=None):
    """Validate the requested version before resolving its display-only cache."""
    from .model_registry import get_model_manifest
    manifest = get_model_manifest(root, model_id, model_hash)
    return Path(root)/'build/model-versions'/manifest['model_hash']/'anatomy'


def prepare_model_anatomy(root, model_id, model_hash=None):
    import json
    import shutil
    from .model_registry import get_model_manifest
    manifest = get_model_manifest(root, model_id, model_hash)
    digest = manifest['model_hash']
    directory = model_anatomy_directory(root, model_id, digest)
    path = directory/'metadata.json'
    names = ('positions.bin', 'groups.bin', 'visible_indices.bin', 'identities.json')
    if path.exists() and all((directory/name).exists() for name in names):
        previous = json.loads(path.read_text())
        if previous.get('model_hash') == digest:
            return previous
    legacy = model_id == 'flywire-783'
    neuron_path = (Path(root)/'build/neurons.parquet' if legacy else
                   Path(root)/'build/model-versions'/digest/'neurons.parquet')
    expected = manifest.get('source_hashes' if legacy else 'output_hashes', {}).get('neurons.parquet')
    if not expected:
        raise ValueError('Anatomy source has no pinned neuron-table checksum')
    if checksum(neuron_path) != expected:
        raise ValueError('Anatomy source neuron-table checksum changed; cannot reuse its model identity')
    prefix = f'/api/model-anatomy/{model_id}'
    if legacy:
        from .visual_assets import prepare_anatomy
        metadata = dict(prepare_anatomy(root))
        directory.mkdir(parents=True, exist_ok=True)
        for name in names[:3]:
            shutil.copyfile(Path(root)/'build/visual/anatomy'/name, directory/name)
        neurons = pd.read_parquet(neuron_path)
        identities = [{'index': i, 'root_id': str(row['root_id']),
                       'entity_id': f"flywire:783:{row['root_id']}",
                       'cell_type': str(row.get('cell_type', '')), 'side': str(row.get('side', ''))}
                      for i, row in enumerate(neurons.to_dict('records'))]
        atomic_write_json(directory/'identities.json', identities)
        metadata.update(model_id=model_id, model_hash=digest)
    else:
        neurons = pd.read_parquet(neuron_path)
        metadata = write_anatomy(neurons, directory, prefix, model_id=model_id, model_hash=digest)
    for key, name in [('positions_url','positions.bin'), ('groups_url','groups.bin'),
                      ('visible_indices_url','visible_indices.bin'), ('metadata_url','metadata.json'),
                      ('identities_url','identities.json')]:
        metadata[key] = f'{prefix}/{name}?model_hash={digest}'
    if (directory/'regions.json').exists():
        metadata['regions_url'] = f'{prefix}/regions.json?model_hash={digest}'
    atomic_write_json(path, metadata)
    return metadata
