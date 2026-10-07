"""Small source-backed atlas fixtures; these tests never start a simulation."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather
import pytest

from flybrain.visual_assets import prepare_anatomy
from flybrain.visual_server import VisualState


BASE = 720575940606000000


def atlas_fixture(root, monkeypatch):
    (root / 'build').mkdir()
    # Adjacent IDs beyond float64 precision, in the released model order.
    neurons = pd.DataFrame({
        'root_id': np.array([BASE + 1, BASE, BASE + 2], np.int64),
        'super_class': ['optic', 'central', 'central'],
        'pos_x': [0., 100., np.nan], 'pos_y': [0., 0., np.nan],
        'pos_z': [0., 100., np.nan],
    })
    neurons.to_parquet(root / 'build/neurons.parquet')
    mapping = SimpleNamespace(
        model_root_ids=neurons.root_id.to_numpy(),
        names=['ME_L', 'g1', 'g2', 'hemolymph'],
        # The real compartment loader returns a dense boolean ndarray.
        membership=np.array([[0, 1, 0], [1, 1, 1], [0, 0, 1], [1, 1, 1]], bool),
    )
    np.savez(root / 'build/compartments.npz', membership=mapping.membership)
    (root / 'build/compartments_metadata.json').write_text('{}')
    monkeypatch.setattr('flybrain.neuromod.compartments.load_compartments', lambda _: mapping)
    return neurons, mapping


def region_state(root, metadata, neurons):
    # Avoid the production constructor's asset setup and executor creation.
    state = VisualState.__new__(VisualState)
    state.root, state.anatomy, state.neurons = root, metadata, neurons
    return state


def test_compartment_centroids_share_rendered_coordinates_and_preserve_unknowns(tmp_path, monkeypatch):
    neurons, _ = atlas_fixture(tmp_path, monkeypatch)
    metadata = prepare_anatomy(tmp_path)
    regions = {item['key']: item for item in metadata['regions']}
    points = np.fromfile(tmp_path / 'build/visual/anatomy/positions.bin', '<f4').reshape(3, 3)
    # Physical z has ten times the x extent because annotation voxels are anisotropic.
    assert points[1, 2] - points[0, 2] == pytest.approx(10 * (points[1, 0] - points[0, 0]))
    np.testing.assert_allclose(regions['ME_L']['position'], points[1])
    np.testing.assert_allclose(regions['g1']['position'], points[:2].mean(axis=0), atol=1e-8)
    assert regions['g1']['neuron_count'] == 3
    assert regions['g1']['located_neuron_count'] == 2
    assert regions['g2']['position'] is None
    assert regions['hemolymph']['position'] is None  # A symbolic pool has no brain location.
    state = region_state(tmp_path, metadata, neurons)
    assert state.region_neurons('g1')['indices'] == [0, 1, 2]
    assert state.region_neurons('g2')['indices'] == [2]
    with pytest.raises(ValueError, match='Unknown brain'):
        state.region_neurons('invented')


def test_real_endpoint_atlas_overrides_duplicate_compartment_and_selection_agrees(tmp_path, monkeypatch):
    neurons, _ = atlas_fixture(tmp_path, monkeypatch)
    raw = tmp_path / 'data/raw'
    raw.mkdir(parents=True)
    for part, ids, labels, counts in [
        ('pre', [BASE + 1, BASE + 1, BASE, BASE + 20], ['ME_L', 'AL_L', 'ME_L', 'ME_L'], [3, 1, 1, 999]),
        ('post', [BASE, BASE + 2], ['AL_L', 'None'], [1, 1]),
    ]:
        feather.write_feather(pa.table({
            f'{part}_pt_root_id': pa.array(ids, pa.int64()),
            'neuropil': labels, 'count': pa.array(counts, pa.int64()),
        }), raw / f'per_neuron_neuropil_count_{part}_783.feather')
    metadata = prepare_anatomy(tmp_path)
    regions = {item['key']: item for item in metadata['regions']}
    assert len(metadata['regions']) == len(regions)
    assert set(regions) == {'ME_L', 'AL_L', 'g1', 'g2', 'hemolymph'}
    assert regions['ME_L']['kind'] == 'neuropil'
    points = np.fromfile(tmp_path / 'build/visual/anatomy/positions.bin', '<f4').reshape(3, 3)
    # Weight each anchor by that neuron's measured endpoint fraction in ME_L.
    expected = (.75 * points[0] + .5 * points[1]) / 1.25
    np.testing.assert_allclose(regions['ME_L']['position'], expected, rtol=1e-6)
    assert regions['ME_L']['neuron_count'] == 2
    state = region_state(tmp_path, metadata, neurons)
    assert state.region_neurons('ME_L')['indices'] == [0, 1]
    assert state.region_neurons('AL_L')['indices'] == [0, 1]
    assert state.region_neurons('g1')['indices'] == [0, 1, 2]


def test_atlas_and_selection_reject_reordered_compartment_identity(tmp_path, monkeypatch):
    neurons, mapping = atlas_fixture(tmp_path, monkeypatch)
    mapping.model_root_ids = mapping.model_root_ids[::-1].copy()
    with pytest.raises(ValueError, match='released neuron order'):
        prepare_anatomy(tmp_path)
    with pytest.raises(ValueError, match='model neuron order'):
        region_state(tmp_path, {'regions': []}, neurons).region_neurons('g1')
